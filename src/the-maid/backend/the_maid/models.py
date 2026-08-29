"""
The Maid — Three-Tier Categorization Pipeline

Tier 1: Sub-agents (per folder) — LLM classifies files using few-shot prompting
        Model outputs "id: Category > Subcategory" lines, Python builds the tree
Tier 2: Programmatic merge — Python merges sub-trees by category name similarity
Tier 3: Review agent — LLM reviews merged tree, outputs corrections in simple format

The LLM is gemma4:e2b (Q4_K_M, 5.1B params, ~2.96GB GGUF) running via Ollama.
Uses /api/generate with think:false to bypass Gemma 4's thinking channel.
Benchmarked at 96% accuracy, 0.44s/file on 47-file test set.
Falls back to extension-based rules if no LLM available.

Features:
- Hierarchical categories: Category > Subcategory > Sub-subcategory (up to 3 levels)
- Persistent category registry (~/.the-maid/category_registry.json) remembers the
  hierarchy across scans and feeds it back to the LLM as context
"""

import json
import os
import re
import requests
from pathlib import Path
from difflib import SequenceMatcher
from typing import Optional, Dict, Any, List, Tuple

from .extractor import extract_text
from .exif_reader import format_exif_compact
from .sandbox import validate_path
from .registry import CategoryRegistry

# LLM server configuration — set by Rust sidecar via env vars
LLM_BASE_URL = os.environ.get("THE_MAID_LLM_BASE_URL", "http://127.0.0.1:11434")
LLM_MODEL = os.environ.get("THE_MAID_LLM_MODEL", "gemma4:e2b")

# Max files per sub-agent LLM call (context window limit)
MAX_FILES_PER_SUBAGENT = 40
# Max content preview chars per file (keeps prompt small)
CONTENT_PREVIEW_CHARS = 150
# Similarity threshold for merging categories (0-1)
CATEGORY_MERGE_THRESHOLD = 0.6
# Max hierarchy depth (Category > Sub > Sub-sub)
MAX_DEPTH = 3


class LLMManager:
    """Manages LLM inference for three-tier file categorization."""

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path
        self._loaded = False
        self._is_ollama = False
        self._registry = CategoryRegistry()

    @staticmethod
    def _server_url() -> str:
        return LLM_BASE_URL.rstrip("/")

    def _chat_complete(self, messages: list[dict], *, max_tokens: int = 256, temperature: float = 0.3) -> str:
        """Call the LLM server. Routes to Ollama /api/generate or OpenAI API based on detected server type."""
        if self._is_ollama:
            return self._ollama_generate(messages, max_tokens, temperature)
        else:
            return self._openai_chat(messages, max_tokens, temperature)

    def _ollama_generate(self, messages: list[dict], max_tokens: int, temperature: float) -> str:
        """Ollama /api/generate with think:false — raw prompt mode bypassing Gemma 4 thinking channel."""
        url = f"{self._server_url()}/api/generate"
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                parts.append(content)
            else:
                parts.append(content)
        full_prompt = "\n\n".join(parts)

        response = requests.post(url, json={
            "model": LLM_MODEL,
            "prompt": full_prompt,
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "top_p": 0.9,
                "num_predict": max_tokens,
            },
        }, timeout=300)
        response.raise_for_status()
        return response.json().get("response", "")

    def _openai_chat(self, messages: list[dict], max_tokens: int, temperature: float) -> str:
        url = f"{self._server_url()}/v1/chat/completions"
        response = requests.post(url, json={
            "model": LLM_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }, timeout=300)
        response.raise_for_status()
        data = response.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")

    def load_model(self) -> bool:
        """Probe the LLM server. Detects Ollama vs llama-server automatically."""
        try:
            r = requests.get(f"{self._server_url()}/api/tags", timeout=3)
            if r.status_code == 200:
                self._loaded = True
                self._is_ollama = True
                print(f"[LLM] Connected to Ollama at {self._server_url()}")
                return True
        except Exception:
            pass
        try:
            r = requests.get(f"{self._server_url()}/v1/models", timeout=3)
            if r.status_code == 200:
                self._loaded = True
                self._is_ollama = False
                print(f"[LLM] Connected to llama-server at {self._server_url()}")
                return True
        except Exception:
            pass
        print(f"[LLM] No LLM server at {self._server_url()}. Using extension fallback.")
        return False

    # --- Three-Tier Pipeline ---

    def categorize_all(
        self,
        files: List[Dict[str, Any]],
        sandbox_folders: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        """
        Three-tier categorization pipeline with hierarchical categories and persistent registry.

        Returns:
        {
            "tree": [
                {
                    "category": "Law",
                    "subbuckets": [
                        {"subcategory": "Contract", "files": [0, 1]},
                        {"subcategory": "Tort", "files": [5]},
                    ],
                    "rationale": "..."
                }
            ]
        }
        """
        if not files:
            return {"tree": []}

        if not self._loaded:
            return self._fallback_tree(files)

        # Assign global IDs to files
        indexed = [{"id": i, **f} for i, f in enumerate(files)]

        # Single LLM call for ALL files — avoids per-folder fragmentation
        # where each subfolder becomes its own top-level category.
        # The manifest includes folder context so the LLM sees the full hierarchy.
        if len(indexed) <= MAX_FILES_PER_SUBAGENT:
            tree = self._classify_batch(indexed)
        else:
            # Chunk by MAX_FILES_PER_SUBAGENT, then merge
            sub_trees = []
            total_chunks = (len(indexed) + MAX_FILES_PER_SUBAGENT - 1) // MAX_FILES_PER_SUBAGENT
            import time as _time
            _batch_start = _time.monotonic()
            for chunk_idx, chunk_start in enumerate(range(0, len(indexed), MAX_FILES_PER_SUBAGENT)):
                chunk = indexed[chunk_start:chunk_start + MAX_FILES_PER_SUBAGENT]
                tree = self._classify_batch(chunk)
                sub_trees.append(tree)
                import json as _json
                progress = (chunk_idx + 1) / total_chunks
                elapsed = _time.monotonic() - _batch_start
                done = chunk_idx + 1
                remaining = total_chunks - done
                eta = (elapsed / done * remaining) if done > 0 else 0
                processed = min((chunk_idx + 1) * MAX_FILES_PER_SUBAGENT, len(indexed))
                print(_json.dumps({
                    "event": "categorize_progress",
                    "progress": progress,
                    "batch": done,
                    "total_batches": total_chunks,
                    "files_done": processed,
                    "files_total": len(indexed),
                    "elapsed_seconds": round(elapsed, 1),
                    "eta_seconds": round(eta, 1),
                }), flush=True)
                print(f"[LLM] Batch {done}/{total_chunks} done ({len(chunk)} files)", flush=True)
            # Merge chunks
            if len(sub_trees) == 1:
                tree = sub_trees[0]
            else:
                merged = self._programmatic_merge(sub_trees)
                tree = merged.get("tree", [])

        # Review agent — LLM fixes fallback buckets
        reviewed_tree = self._review_agent(tree, indexed)

        # Save to registry
        self._registry.register_from_tree(reviewed_tree)
        self._registry.save()

        return {"tree": reviewed_tree}

    def _classify_batch(self, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Classify a batch of files in a single LLM call.
        The manifest includes folder context so the LLM sees the full directory hierarchy.
        Returns a tree: [{"category": ..., "subbuckets": [{"subcategory": ..., "files": [...]}], "rationale": ...}]
        """
        if not files:
            return []

        manifest = self._build_manifest(files)
        file_count = len(files)

        # Build registry hint from persistent memory
        registry_hint = self._registry.build_hint()
        if registry_hint:
            registry_hint = f"\n{registry_hint}\nReuse these categories when appropriate. Add new ones only if a file doesn't fit any existing category.\n"

        prompt = f"""For each file, assign a content-based category hierarchy based on what the file is ABOUT.
Use broad subjects as top-level categories and more specific topics as subcategories.
Think about how a person would organize their own files — practical, intuitive categories.

HIERARCHY RULES:
- Use BROAD subjects as top-level categories: Finance, Law, Work, Personal, Software, Travel, Recipes, Health, Education, Engineering, Game Development, etc.
- Use SPECIFIC topics as subcategories: Finance > Cryptocurrency, Finance > Taxes, Finance > Investments, Work > Projects, Work > Meeting Notes, etc.
- Cryptocurrency should be Finance > Cryptocurrency, NOT a top-level category.
- Software tools and installers go under Software (no subcategory needed).

FOLDER STRUCTURE RULES:
- The file path shown in the manifest is the user's EXISTING organization — respect it.
- Files that are in the same project folder SHOULD stay together in the same category/subcategory.
  e.g. files under 'the-maid/' should all be categorized under Game Development > The Maid or Software > The Maid.
- If a folder clearly represents a project or topic, use that as the subcategory.
  e.g. 'Crypto Projects/btc_analysis.xlsx' -> Finance > Cryptocurrency (NOT 'Crypto Projects').
- But if the folder IS the natural category (e.g. 'Recipes/', 'Travel/'), match it to the right top-level category.
- Do NOT copy folder names as categories. Instead, understand what the folder is ABOUT and use that subject.

NEVER use file types like "pdf", "document", "code" as categories — use what the file is ABOUT.
Only use "Screenshots" for image files with no meaningful content (just a screen grab).
Only use "Uncategorized" as a last resort when you truly cannot tell what the file is about.

Format: "id: Category > Subcategory" (or just "id: Category" if no subcategory fits).

Example (with content):
0: Contract Law Lecture 3.pdf | Consideration in contract law requires a bargained-for exchange
0: Law > Contract
1: btc_price.xlsx | BTC-USD price data, moving averages, RSI indicators
1: Finance > Cryptocurrency
2: chocolate_cake.pdf | Ingredients: 2 cups flour, 1 cup cocoa. Bake at 180C
2: Recipes > Desserts
3: vacation_itinerary.docx | Day 1: Tokyo, Day 2: Kyoto hotels and trains
3: Travel > Japan
4: meeting_notes_q2.docx | Q2 revenue review, action items for sales team
4: Work > Meeting Notes
5: proton-recovery-phrase.pdf | Recovery kit. Recovery phrase. Proton Account.
5: Finance > Cryptocurrency

Example (no content — use FILENAME and FOLDER as clues):
6: Cryocare Services/contract_law_lecture_3.pdf | (no text content, file type: .pdf)
6: Law > Contract
7: Crypto Projects/btc_analysis_2024.xlsx | (no text content, file type: .xlsx)
7: Finance > Cryptocurrency
8: Recipes/grandma_chocolate_cake.pdf | (no text content, file type: .pdf)
8: Recipes > Desserts
9: screenshot_2024_03_15.png | (no text content, file type: .png)
9: Screenshots
10: Cryocare Services/tort_lecture_1.pdf | (no text content, file type: .pdf)
10: Law > Tort
11: backup AI/calculus_homework.pdf | (no text content, file type: .pdf)
11: Education > Mathematics
12: Crypto Projects/eth_wallet_recovery.txt | (no text content, file type: .txt)
12: Finance > Cryptocurrency
13: backup AI/math_exam_prep.pdf | (no text content, file type: .pdf)
13: Education > Mathematics
14: Software/Obsidian-1.12.4.AppImage | (no text content, file type: .appimage)
14: Software
15: Crypto Projects/ledger-live-desktop-4.13.1.AppImage | (no text content, file type: .appimage)
15: Finance > Cryptocurrency
16: Software/BoseUpdaterInstaller_7.1.13.exe | (no text content, file type: .exe)
16: Software
17: Game Development/car_tutorial.rbxl | (no text content, file type: .rbxl)
17: Game Development > Roblox
18: Game Development/the-maid/main.rs | (no text content, file type: )
18: Game Development > The Maid
19: Gemini_Generated_Image.png | (no text content, file type: .png)
19: AI Art

Example (with EXIF and face data — use camera, GPS, and face info as categorization clues):
20: vacation_2024/img_001.jpg | [EXIF: Canon EOS R6, 2024-07-15, GPS: 35.68°N 139.69°E, 5472x3648] | (no text content, file type: .jpg)
20: Travel > Japan
21: family/birthday_party.jpg | [EXIF: Xiaomi Redmi K40, 2024-06-15, 4624x3472] [FACES: 3 (Sarah, Tom, Unknown_Person_2)] | (no text content, file type: .jpg)
21: Personal > Family Events
22: work_site/photo_2024.jpg | [EXIF: iPhone 15 Pro, 2024-03-10, GPS: -33.87°S 151.21°E, 4032x3024] [FACES: 2] | (no text content, file type: .jpg)
22: Work > Construction Site
23: Crypto Projects/wallet_screenshot.png | [EXIF: Samsung SM-G991B, 2024-08-01, 1080x2400] | (no text content, file type: .png)
23: Finance > Cryptocurrency

Note: Image files may include [EXIF: ...] with camera model, date taken, GPS coordinates, and resolution, and [FACES: N (labels)] with detected face count and cluster labels. Use these as categorization signals — GPS suggests travel locations, camera model + date can indicate events, face labels can indicate people and social context.
{registry_hint}
Now categorize these {file_count} files:
{manifest}

Output one line per file: "id: Category > Subcategory" (or "id: Category" if no subcategory)
"""

        try:
            text = self._chat_complete(
                [{"role": "user", "content": prompt}],
                max_tokens=max(512, file_count * 20),
                temperature=0.3,
            )
            assignments = self._parse_hierarchical_lines(text, files)
            if assignments:
                assignments = self._fix_folder_name_cats(assignments, files)
                return self._build_tree_from_assignments(assignments)
        except Exception as e:
            print(f"[LLM] Classification error: {e}")

        # Fallback to extension rules
        return self._fallback_tree(files).get("tree", [])

    def _fix_folder_name_cats(self, assignments: List[Tuple[int, str, str]], files: List[Dict[str, Any]]) -> List[Tuple[int, str, str]]:
        """Post-process: detect and fix categories that are actually folder names.
        Only fixes when the category IS a verbatim folder name AND there's a better
        subcategory to promote. With the new full-path manifest, the LLM has more
        context so this is a lighter-touch fixer."""
        # Collect all folder names from file paths (just the leaf folder)
        folder_names = set()
        for f in files:
            path = f.get("path", "")
            if path:
                parent = Path(path).parent.name
                if parent and parent != ".":
                    folder_names.add(parent.lower())
        
        fixed = []
        for fid, cat, subcat in assignments:
            cat_lower = cat.lower().strip()
            # Only fix if category is a folder name AND we have a subcategory to promote
            if cat_lower in folder_names and subcat:
                cat = subcat
                subcat = ""
            fixed.append((fid, cat, subcat))
        return fixed

    def _build_tree_from_assignments(self, assignments: List[Tuple[int, str, str]]) -> List[Dict[str, Any]]:
        """Build a hierarchical tree from (file_id, category, subcategory) assignments."""
        # Group by category → subcategory → file_ids
        by_cat: Dict[str, Dict[str, List[int]]] = {}
        for fid, cat, subcat in assignments:
            by_cat.setdefault(cat, {}).setdefault(subcat, []).append(fid)

        tree = []
        for cat, subs in by_cat.items():
            subbuckets = [
                {"subcategory": sub, "files": list(dict.fromkeys(ids))}
                for sub, ids in subs.items()
            ]
            subbuckets.sort(key=lambda s: (s["subcategory"] == "", s["subcategory"]))
            tree.append({
                "category": cat,
                "subbuckets": subbuckets,
                "rationale": "Classified by content analysis",
            })
        tree.sort(key=lambda n: sum(len(s.get("files", [])) for s in n.get("subbuckets", [])), reverse=True)
        return tree

    def _build_manifest(self, files: List[Dict[str, Any]]) -> str:
        """Build a compact text manifest of files for the LLM prompt.
        Includes the FULL relative path from scan root — folder structure is critical
        categorization signal. Files in the same project folder should stay together.
        Enriched with [EXIF: ...] and [FACES: ...] blocks when available.
        """
        lines = []
        for f in files:
            fid = f.get("id", 0)
            name = self._sanitize(f.get("filename", ""))
            path = f.get("path", "")
            # Use the full relative path (not just parent folder name)
            # so the LLM can see project groupings and existing organization
            rel_path = self._relative_path_hint(path)
            content = extract_text(path, max_chars=CONTENT_PREVIEW_CHARS) if path else ""

            # Build enrichment blocks for EXIF and faces
            exif_block = format_exif_compact(f.get("exif", {}))
            face_block = self._format_faces_compact(f)
            enrichment = " ".join(filter(None, [exif_block, face_block]))

            if content:
                content_preview = content[:CONTENT_PREVIEW_CHARS]
            else:
                ext = f.get("extension", "")
                content_preview = f"(no text content, file type: {ext})"

            # Build the manifest line: path | [EXIF: ...] [FACES: ...] | content
            path_part = f"{rel_path}/{name}" if rel_path and rel_path != "." else name
            if enrichment:
                lines.append(f"{fid}: {path_part} | {enrichment} | {content_preview}")
            else:
                lines.append(f"{fid}: {path_part} | {content_preview}")
        return "\n".join(lines)

    @staticmethod
    def _format_faces_compact(f: Dict[str, Any]) -> str:
        """Format face detection data as [FACES: N (labels)] for LLM manifest."""
        faces = f.get("faces_detected", [])
        if not faces:
            return ""
        labels = []
        for face in faces:
            label = face.get("cluster_label")
            if label:
                labels.append(label)
        count = len(faces)
        if labels:
            return f"[FACES: {count} ({', '.join(labels)})]"
        return f"[FACES: {count}]"

    def _relative_path_hint(self, path: str) -> str:
        """Extract a meaningful relative path from the full path.
        Trims the scan root prefix and common home dirs to show the folder hierarchy
        that the user created — this IS categorization signal.
        e.g. /home/user/Downloads/Crypto Projects/btc_analysis.xlsx -> 'Crypto Projects'
             /home/user/Documents/Work/Projects/the-maid/Cargo.toml -> 'Work/Projects/the-maid'
        """
        if not path:
            return ""
        p = Path(path)
        # Try to trim common prefixes: home dir, Downloads, Desktop, Documents, Pictures
        parts = p.parts
        # Find the first meaningful segment after home/root
        trim_prefixes = {"home", "Users", "root", "tmp"}
        start = 0
        for i, part in enumerate(parts):
            if part in trim_prefixes:
                start = i + 2  # skip /home/user
                break
        # Also trim common scan roots
        scan_roots = {"Downloads", "Desktop", "Documents", "Pictures", "Videos", "Music"}
        # If we see a scan root, start after it
        for i in range(start, len(parts) - 1):  # -1 to skip filename
            if parts[i] in scan_roots:
                start = i + 1
                break
        # Build relative path from meaningful segments (exclude filename)
        rel_parts = parts[start:-1] if start < len(parts) - 1 else []
        return "/".join(rel_parts) if rel_parts else ""

    def _parse_hierarchical_lines(self, text: str, files: List[Dict[str, Any]]) -> List[Tuple[int, str, str]]:
        """Parse 'id: Category > Subcategory' lines from LLM output.

        Returns list of (file_id, category, subcategory) tuples.
        Subcategory is "" if the model only output a top-level category.

        Handles pipe-delimited echoing where the model outputs:
            "0: filename | content | Category > Subcategory"
        by taking the last pipe-separated segment as the category hierarchy.
        """
        assignments = []
        valid_ids = {f.get("id", 0) for f in files}
        for line in text.strip().split("\n"):
            match = re.match(r'^(\d+)\s*:\s*(.+)', line.strip())
            if match:
                fid = int(match.group(1))
                rest = match.group(2).strip()
                # Model may echo manifest pipe format: "filename | content | Category > Sub"
                if '|' in rest:
                    rest = rest.split('|')[-1].strip()
                # Strip quotes, markdown
                rest = rest.strip('*`"\'')
                # Reject garbage: too long, looks like content, or contains path separators
                if len(rest) > 80:
                    continue
                if '/' in rest or '\\' in rest:
                    continue
                if 'no text content' in rest.lower() or 'file type:' in rest.lower():
                    continue

                # Split on ">" for hierarchy
                parts = [p.strip() for p in rest.split('>')]
                parts = [p for p in parts if p]  # remove empty

                if not parts:
                    continue
                if len(parts) == 1:
                    cat, subcat = parts[0], ""
                else:
                    cat = parts[0]
                    subcat = parts[1] if len(parts) >= 2 else ""
                    # Allow 3rd level: "Cat > Sub > Sub-sub" → store as cat="Cat", sub="Sub > Sub-sub"
                    if len(parts) > 2:
                        subcat = " > ".join(parts[1:MAX_DEPTH])

                if fid in valid_ids and cat:
                    assignments.append((fid, cat, subcat))
        # Ensure all files are assigned
        assigned_ids = {a[0] for a in assignments}
        for f in files:
            if f.get("id", 0) not in assigned_ids:
                assignments.append((f.get("id", 0), "Uncategorized", ""))
        return assignments

    def _parse_id_category_lines(self, text: str, files: List[Dict[str, Any]]) -> List[Tuple[int, str]]:
        """Parse flat 'id: category' lines — used by review agent."""
        assignments = []
        valid_ids = {f.get("id", 0) for f in files}
        for line in text.strip().split("\n"):
            match = re.match(r'^(\d+)\s*:\s*(.+)', line.strip())
            if match:
                fid = int(match.group(1))
                cat = match.group(2).strip()
                if '|' in cat:
                    cat = cat.split('|')[-1].strip()
                cat = cat.strip('*`"\'')
                if len(cat) > 50:
                    continue
                if 'no text content' in cat.lower() or 'file type:' in cat.lower():
                    continue
                # Also handle "Category > Sub" — take full hierarchy
                if fid in valid_ids and cat:
                    assignments.append((fid, cat))
        assigned_ids = {a[0] for a in assignments}
        for f in files:
            if f.get("id", 0) not in assigned_ids:
                assignments.append((f.get("id", 0), "Uncategorized"))
        return assignments

    def _programmatic_merge(self, sub_trees: List) -> Dict[str, Any]:
        """
        Merge multiple tree chunks by category+subcategory similarity.
        Pure Python — no LLM call. Used when files exceed MAX_FILES_PER_SUBAGENT.
        Input: list of tree node lists (each is [{"category": ..., "subbuckets": [...], ...}])
        """
        # Flatten all subbuckets from all trees into (category, subcategory, files) tuples
        all_buckets: List[Dict[str, Any]] = []
        for tree in sub_trees:
            nodes = tree if isinstance(tree, list) else tree.get("tree", [])
            for node in nodes:
                cat = node.get("category", "Uncategorized")
                for sub in node.get("subbuckets", []):
                    all_buckets.append({
                        "category": cat,
                        "subcategory": sub.get("subcategory", ""),
                        "files": list(sub.get("files", [])),
                    })

        # Merge similar categories
        merged: List[Dict[str, Any]] = []
        used = [False] * len(all_buckets)

        for i, b in enumerate(all_buckets):
            if used[i]:
                continue
            used[i] = True
            cat_name = b["category"]
            sub_name = b["subcategory"]
            files = list(b["files"])

            for j in range(i + 1, len(all_buckets)):
                if used[j]:
                    continue
                other = all_buckets[j]
                cat_sim = self._category_similarity(cat_name, other["category"])
                if cat_sim >= CATEGORY_MERGE_THRESHOLD:
                    if sub_name and other["subcategory"]:
                        if self._category_similarity(sub_name, other["subcategory"]) >= CATEGORY_MERGE_THRESHOLD:
                            used[j] = True
                            files.extend(other["files"])
                            if len(other["category"]) > len(cat_name):
                                cat_name = other["category"]
                            if len(other["subcategory"]) > len(sub_name):
                                sub_name = other["subcategory"]
                    elif not sub_name and not other["subcategory"]:
                        used[j] = True
                        files.extend(other["files"])
                        if len(other["category"]) > len(cat_name):
                            cat_name = other["category"]
                    elif not sub_name and other["subcategory"]:
                        used[j] = True
                        files.extend(other["files"])
                        sub_name = other["subcategory"]
                        if len(other["category"]) > len(cat_name):
                            cat_name = other["category"]

            files = list(dict.fromkeys(files))
            merged.append({"category": cat_name, "subcategory": sub_name, "files": files})

        # Group by category -> subcategory -> file_ids
        by_cat: Dict[str, Dict[str, List[int]]] = {}
        for b in merged:
            by_cat.setdefault(b["category"], {}).setdefault(b["subcategory"], []).extend(b["files"])

        tree = []
        for cat, subs in by_cat.items():
            subbuckets = [
                {"subcategory": sub, "files": list(dict.fromkeys(ids))}
                for sub, ids in subs.items()
            ]
            subbuckets.sort(key=lambda s: (s["subcategory"] == "", s["subcategory"]))
            tree.append({
                "category": cat,
                "subbuckets": subbuckets,
                "rationale": "Merged from multiple batches",
            })
        tree.sort(key=lambda n: sum(len(s.get("files", [])) for s in n.get("subbuckets", [])), reverse=True)
        return {"tree": tree}

    @staticmethod
    def _category_similarity(a: str, b: str) -> float:
        """Similarity score between two category names (0-1)."""
        a = a.lower().strip()
        b = b.lower().strip()
        if a == b:
            return 1.0
        if not a or not b:
            return 0.0
        # Substring match is a strong signal
        if a in b or b in a:
            return 0.9
        return SequenceMatcher(None, a, b).ratio()

    def _review_agent(self, tree: List[Dict[str, Any]], all_files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Tier 3: LLM reviews files in fallback buckets (Screenshots, Uncategorized).
        Only touches files the system wasn't sure about — real categories are left alone.
        """
        if not tree or not all_files:
            return tree

        FALLBACK_CATS = {"screenshots", "uncategorized", "unknown", "misc", "miscellaneous", "other"}

        reviewable = []
        for node in tree:
            cat = node.get("category", "Uncategorized")
            if cat.lower().strip() not in FALLBACK_CATS:
                continue
            for sub in node.get("subbuckets", []):
                for fid in sub.get("files", []):
                    if 0 <= fid < len(all_files):
                        f = all_files[fid]
                        name = self._sanitize(f.get("filename", ""))
                        path = f.get("path", "")
                        parent_folder = Path(path).parent.name if path else ""
                        content = extract_text(path, max_chars=200) if path else ""
                        content_preview = content[:200] if content else "(no text)"
                        reviewable.append((fid, name, parent_folder, content_preview, cat))

        if not reviewable:
            print(f"[LLM] Review agent: no files in fallback buckets, skipping")
            return tree

        file_lines = "\n".join([
            f"{a[0]}: {a[1]}/{a[2]} | {a[3]} | currently: {a[4]}" if a[2] else f"{a[0]}: {a[1]} | {a[3]} | currently: {a[4]}"
            for a in reviewable
        ])

        real_cats = sorted([node["category"] for node in tree
                           if node["category"].lower().strip() not in FALLBACK_CATS])
        cat_list = ", ".join(real_cats) if real_cats else "(none yet)"

        # Include registry hint
        registry_hint = self._registry.build_hint()

        prompt = f"""These files were put in fallback categories because the system wasn't sure. Look at each file's name, folder, and content. Assign a real subject category with a subcategory if possible.

Rules:
- Use real subject categories (Law, Cryptocurrency, Recipes, Mathematics, Finance, Travel, Work, Personal, etc.)
- Do NOT use "Screenshots" or "Uncategorized" — find a real category.
- If you genuinely cannot tell what a file is about, output: id: Keep — leave it where it is.
- Use ">" for subcategories: "id: Category > Subcategory"
- Keep categories short: one word or short phrase.
- Existing categories you can reuse: {cat_list}
{registry_hint}

Files to review:
{file_lines}

Output one line per file: "id: Category > Subcategory" (or "id: Category" or "id: Keep")
"""

        try:
            text = self._chat_complete(
                [{"role": "user", "content": prompt}],
                max_tokens=256,
                temperature=0.3,
            )
            # Parse hierarchical corrections
            corrections = self._parse_hierarchical_lines(text, all_files)

            if not corrections:
                print(f"[LLM] Review agent: no corrections for fallback files")
                return tree

            move_map = {}
            KEEP_MARKERS = {"keep", "leave", "same", "skip", ""}
            for fid, cat, subcat in corrections:
                cat_clean = cat.strip()
                if cat_clean.lower() in KEEP_MARKERS:
                    continue
                if cat_clean.lower() in FALLBACK_CATS:
                    continue
                if fid not in move_map:
                    move_map[fid] = (cat_clean, subcat.strip())

            if not move_map:
                print(f"[LLM] Review agent: no valid corrections")
                return tree

            # Apply corrections
            for fid, (target_cat, target_sub) in move_map.items():
                # Remove from current location
                for node in tree:
                    for sub in node.get("subbuckets", []):
                        if fid in sub.get("files", []):
                            sub["files"].remove(fid)
                            break
                    else:
                        continue
                    break

                # Add to target category (find existing or create new)
                found = False
                for node in tree:
                    if self._category_similarity(node["category"], target_cat) >= 0.8:
                        # Found the category — find matching subcategory or create
                        if target_sub:
                            for sub in node["subbuckets"]:
                                if sub.get("subcategory") and self._category_similarity(sub["subcategory"], target_sub) >= 0.8:
                                    sub["files"].append(fid)
                                    found = True
                                    break
                            if not found:
                                node["subbuckets"].append({"subcategory": target_sub, "files": [fid]})
                                found = True
                        else:
                            # No subcategory — add to empty subbucket or create one
                            for sub in node["subbuckets"]:
                                if not sub.get("subcategory"):
                                    sub["files"].append(fid)
                                    found = True
                                    break
                            if not found:
                                node["subbuckets"].append({"subcategory": "", "files": [fid]})
                                found = True
                        break

                if not found:
                    subs = [{"subcategory": target_sub, "files": [fid]}] if target_sub else [{"subcategory": "", "files": [fid]}]
                    tree.append({
                        "category": target_cat,
                        "subbuckets": subs,
                        "rationale": "Moved by review agent from fallback bucket",
                    })

            # Clean up empty nodes
            for node in tree[:]:
                node["subbuckets"] = [s for s in node.get("subbuckets", []) if s.get("files")]
                if not node["subbuckets"]:
                    tree.remove(node)

            tree.sort(key=lambda n: sum(len(s.get("files", [])) for s in n.get("subbuckets", [])), reverse=True)
            print(f"[LLM] Review agent: moved {len(move_map)} files from fallback buckets")
            return tree

        except Exception as e:
            print(f"[LLM] Review agent error: {e}, keeping Python merge")
            return tree

    def _restructure_single_tree(self, sub_tree: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert a single sub-tree into hierarchical tree format."""
        buckets = sub_tree.get("buckets", [])
        # Group by category, then by subcategory
        by_cat: Dict[str, Dict[str, List[int]]] = {}
        for b in buckets:
            cat = b.get("category", "Uncategorized")
            sub = b.get("subcategory", "")
            by_cat.setdefault(cat, {}).setdefault(sub, []).extend(b.get("files", []))

        tree = []
        for cat, subs in by_cat.items():
            subbuckets = [
                {"subcategory": sub, "files": list(dict.fromkeys(ids))}
                for sub, ids in subs.items()
            ]
            subbuckets.sort(key=lambda s: (s["subcategory"] == "", s["subcategory"]))
            tree.append({
                "category": cat,
                "subbuckets": subbuckets,
                "rationale": "Classified by content analysis",
            })
        tree.sort(key=lambda n: sum(len(s.get("files", [])) for s in n.get("subbuckets", [])), reverse=True)
        return tree

    def _fallback_tree(self, files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Extension-based fallback when no LLM available."""
        from .categorizer import DEFAULT_RULES
        by_cat: Dict[str, List[int]] = {}
        for f in files:
            ext = f.get("extension", "").lower()
            rule = DEFAULT_RULES.get(ext)
            cat = rule["bucket"] if rule else "Uncategorized"
            by_cat.setdefault(cat, []).append(f.get("id", 0))

        tree = []
        for cat, ids in by_cat.items():
            tree.append({
                "category": cat,
                "subbuckets": [{"subcategory": "", "files": ids}],
                "rationale": "Extension-based fallback (no LLM)",
            })
        return {"tree": tree}

    def _fallback_buckets(self, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Per-folder extension fallback."""
        from .categorizer import DEFAULT_RULES
        by_cat: Dict[str, List[int]] = {}
        for f in files:
            ext = f.get("extension", "").lower()
            rule = DEFAULT_RULES.get(ext)
            cat = rule["bucket"] if rule else "Uncategorized"
            by_cat.setdefault(cat, []).append(f.get("id", 0))

        return [
            {"category": cat, "subcategory": "", "files": ids, "rationale": "Extension fallback"}
            for cat, ids in by_cat.items()
        ]

    def _parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Defensively parse JSON from LLM output."""
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        brace_start = text.find('{')
        brace_end = text.rfind('}')
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            try:
                return json.loads(text[brace_start:brace_end + 1])
            except json.JSONDecodeError:
                pass
        return None

    def _sanitize(self, text: str) -> str:
        """Strip control chars, limit length."""
        cleaned = re.sub(r"[\x00-\x1f\x7f]", "", text)
        return cleaned[:255]

    # --- Legacy API ---

    def categorize_file_content(self, file_metadata: Dict[str, Any], sandbox_folders=None) -> Dict[str, Any]:
        """Legacy single-file categorization."""
        result = self.categorize_all([file_metadata])
        tree = result.get("tree", [])
        if tree:
            bucket = tree[0]
            return {
                "category": bucket["category"],
                "subcategory": "",
                "topic": "",
                "tags": [],
                "rationale": bucket.get("rationale", ""),
                "confidence": 0.8,
            }
        return self._fallback_single(file_metadata)

    def categorize_batch(self, files: list[Dict[str, Any]], batch_size: int = 10) -> list[Dict[str, Any]]:
        """Legacy batch API — now uses the three-tier pipeline."""
        result = self.categorize_all(files)
        file_results = [None] * len(files)
        for node in result.get("tree", []):
            cat = node["category"]
            for sub in node.get("subbuckets", []):
                for fid in sub.get("files", []):
                    if 0 <= fid < len(files):
                        file_results[fid] = {
                            "category": cat,
                            "subcategory": sub.get("subcategory", ""),
                            "topic": "",
                            "tags": [],
                            "rationale": node.get("rationale", ""),
                            "confidence": 0.8,
                        }
        for i, r in enumerate(file_results):
            if r is None:
                file_results[i] = self._fallback_single(files[i])
        return file_results

    def _fallback_single(self, file_metadata: Dict[str, Any]) -> Dict[str, Any]:
        from .categorizer import DEFAULT_RULES
        ext = file_metadata.get("extension", "").lower()
        rule = DEFAULT_RULES.get(ext)
        if rule:
            return {
                "category": rule["bucket"],
                "subcategory": "",
                "topic": "",
                "tags": rule.get("tags", []),
                "rationale": rule["rationale"],
                "confidence": rule["confidence"],
            }
        return {
            "category": "Uncategorized",
            "subcategory": "",
            "topic": "",
            "tags": [],
            "rationale": "Unknown file type",
            "confidence": 0.0,
        }