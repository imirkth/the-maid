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
        scan_root: str = "",
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
        # Accumulated tree from previous batches — fed to each new batch so the
        # LLM can place files consistently (e.g. all Eleanor photos in Photos > Eleanor,
        # not split across Photos/Personal/Uncategorized).
        accumulated_tree: List[Dict[str, Any]] = []

        if len(indexed) <= MAX_FILES_PER_SUBAGENT:
            tree = self._classify_batch(indexed, accumulated_tree, scan_root)
        else:
            # Chunk by MAX_FILES_PER_SUBAGENT, then merge
            sub_trees = []
            total_chunks = (len(indexed) + MAX_FILES_PER_SUBAGENT - 1) // MAX_FILES_PER_SUBAGENT
            import time as _time
            _batch_start = _time.monotonic()
            for chunk_idx, chunk_start in enumerate(range(0, len(indexed), MAX_FILES_PER_SUBAGENT)):
                chunk = indexed[chunk_start:chunk_start + MAX_FILES_PER_SUBAGENT]
                tree = self._classify_batch(chunk, accumulated_tree, scan_root)
                sub_trees.append(tree)
                # Grow the accumulated tree for the next batch
                accumulated_tree = self._merge_into_accumulated(accumulated_tree, tree)
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
            # Final tree is the accumulated tree (already merged incrementally)
            tree = accumulated_tree if len(sub_trees) > 1 else sub_trees[0]

        # Photo sub-clustering: split large photo folders by year/month
        tree = self._subcluster_photos(tree, indexed)

        # Review agent — LLM fixes fallback buckets
        reviewed_tree = self._review_agent(tree, indexed)

        # Save to registry
        self._registry.register_from_tree(reviewed_tree)
        self._registry.save()

        return {"tree": reviewed_tree}

    def _classify_batch(self, files: List[Dict[str, Any]], accumulated_tree: Optional[List[Dict[str, Any]]] = None, scan_root: str = "") -> List[Dict[str, Any]]:
        """
        Classify a batch of files in a single LLM call.
        The manifest includes folder context so the LLM sees the full directory hierarchy.
        If accumulated_tree is provided, the LLM also sees categories from previous batches
        and is instructed to reuse them for consistency.
        Returns a tree: [{"category": ..., "subbuckets": [{"subcategory": ..., "files": [...]}], "rationale": ...}]
        """
        if not files:
            return []

        manifest = self._build_manifest(files, scan_root)
        file_count = len(files)

        # Registry hint disabled — it accumulates garbage from broken runs and poisons
        # the prompt for small models (6KB of noise made Gemma 4 E2B give up entirely).
        # TODO: re-enable with sanitization once we filter out path-like / garbage entries.
        registry_hint = ""

        # Build accumulated tree hint from previous batches
        tree_hint = ""
        if accumulated_tree:
            tree_summary = self._summarize_tree(accumulated_tree)
            if tree_summary:
                tree_hint = f"\nCATEGORIES FROM PREVIOUS BATCHES (reuse these for consistency — do not create duplicate categories for the same topic):\n{tree_summary}\n"

        # Ultra-simple prompt tuned for small models (Gemma 4 E2B / 5B params).
        # Long prompts confuse small models — they echo paths instead of outputting categories.
        # Keep it short, explicit, and impossible to get wrong.
        prev_cats = tree_hint + registry_hint

        # ── Folder-first categorization ──
        # With only ~13 unique folders, pre-compute category per folder, not per file.
        # The LLM only picks categories for folders + root files (maybe 20 items total).
        # This avoids the 5B model's fatal flaw: seeing .jpg → Photos even in business folders.
        #
        # Step 1: Group files by folder key
        folder_groups: Dict[str, List[Dict[str, Any]]] = {}
        root_files: List[Dict[str, Any]] = []
        for f in files:
            path = f.get("path", "")
            rel = path.replace(scan_root + "/", "") if scan_root else path
            parts = [p for p in rel.split("/") if p]
            if len(parts) > 1:
                folder_key = "/".join(parts[:-1])
                f["_subcat"] = parts[-2]  # last folder segment
                folder_groups.setdefault(folder_key, []).append(f)
            else:
                f["_subcat"] = ""
                root_files.append(f)

        # Step 2: Build folder manifest for LLM — one line per FOLDER, not per file
        folder_lines = []
        folder_idx = 0
        folder_id_map = {}  # llm_id -> folder_key
        for folder_key, folder_files in sorted(folder_groups.items(), key=lambda x: -len(x[1])):
            sample_file = folder_files[0]
            sample_path = sample_file.get("path", "").replace(scan_root + "/", "") if scan_root else sample_file.get("path", "")
            exts = set()
            for ff in folder_files:
                p = ff.get("path", "")
                if "." in p:
                    exts.add(p.rsplit(".", 1)[-1].lower())
            ext_str = ", ".join(sorted(exts)[:5])
            # Show up to 3 sample filenames so LLM can understand what the folder contains
            sample_names = [ff.get("path", "").split("/")[-1][:40] for ff in folder_files[:3]]
            samples_str = "; ".join(sample_names)
            folder_lines.append(f"{folder_idx}: {folder_key} ({len(folder_files)} files, types: {ext_str}) samples: {samples_str}")
            folder_id_map[folder_idx] = folder_key
            folder_idx += 1
        folder_manifest = "\n".join(folder_lines)

        # Step 3: Also build root file manifest — include text content for content-based categorization
        # This is critical for Desktop/Downloads scans where files have no folder structure
        root_lines = []
        root_id_map = {}
        for ri, f in enumerate(root_files):
            fid = f.get("id", 0)
            name = self._sanitize(f.get("filename", ""))
            text = extract_text(f.get("path", ""), max_chars=200) if f.get("path") else ""
            exif = format_exif_compact(f.get("exif", {})) if f.get("exif") else ""
            exif_str = f" [EXIF: {exif}]" if exif else ""
            text_str = text[:200] if text else f"(no text content, file type: .{name.rsplit('.', 1)[-1].lower() if '.' in name else 'unknown'})"
            root_lines.append(f"{folder_idx + ri}: {name}{exif_str} | {text_str}")
            root_id_map[folder_idx + ri] = fid
        root_manifest = "\n".join(root_lines)

        # Step 4: Ask LLM to categorize FOLDERS (not files) + root files
        total_items = folder_idx + len(root_files)
        prompt = f"""Pick a category for each folder or file below.

Categories: Photos, Finance, Law, Work, Software, Travel, Personal, Education, Health, Media, Documents, Uncategorized

Folder rules (look at the folder NAME and sample filenames, not the file extensions):
- Person name folders (Eleanor, Sarah, John) → Photos
- Business/legal/company folders (Cryocare, Mamillon, Incorporation, CIMC, ISO) → Law
- Folders with "services", "documents", "expenses", "archives", "OSL" → Law (business documents)
- Folders inside a business folder (e.g. "Cryocare services/CIMC documents/internal ISO #1") → Law
- Folders with "internal", "ISO", "CICU", "design", "certificate" → Law (compliance/inspection documents)
- Video folders (Standard Work Videos) → Media
- Folders with crypto/wallet/blockchain names → Finance
- Use "Uncategorized" only if you truly cannot tell

Folders:
{folder_manifest}

Root files (no folder):
{root_manifest}
{prev_cats}
Output: N: Category (one per line)

0: Photos
1: Law

Now categorize all {total_items} items:
"""

        try:
            text = self._chat_complete(
                [{"role": "user", "content": prompt}],
                max_tokens=max(512, total_items * 10),
                temperature=0.3,
            )

            # Parse the folder-level categories
            folder_categories = {}  # folder_key -> category
            for line in text.strip().split("\n"):
                m = re.match(r'^(\d+)\s*:\s*(.+)', line.strip())
                if not m:
                    continue
                item_id = int(m.group(1))
                cat = m.group(2).strip().strip('*`"\'')
                # Reject garbage
                if len(cat) > 50 or '/' in cat or '|' in cat:
                    continue
                if item_id in folder_id_map:
                    folder_key = folder_id_map[item_id]
                    folder_categories[folder_key] = cat
                elif item_id in root_id_map:
                    fid = root_id_map[item_id]
                    folder_categories[f"__root_{fid}"] = cat

            # Step 5: Build assignments from folder categories
            assignments = []
            for f in files:
                fid = f.get("id", 0)
                folder_key = None
                path = f.get("path", "")
                rel = path.replace(scan_root + "/", "") if scan_root else path
                parts = [p for p in rel.split("/") if p]
                if len(parts) > 1:
                    folder_key = "/".join(parts[:-1])

                if folder_key and folder_key in folder_categories:
                    cat = folder_categories[folder_key]
                    subcat = f.get("_subcat", "")
                elif f"__root_{fid}" in folder_categories:
                    cat = folder_categories[f"__root_{fid}"]
                    # For root files (Desktop/Downloads scans), derive subcategory from filename/content
                    fname = f.get("filename", "")
                    fname_lower = fname.lower()
                    if "wallet" in fname_lower or "crypto" in fname_lower or "curecoin" in fname_lower:
                        subcat = "Cryptocurrency"
                        if cat == "Uncategorized":
                            cat = "Finance"
                    elif "UTC--" in fname:
                        subcat = "Timestamp"
                        if cat == "Uncategorized":
                            cat = "Finance"
                    elif "mon compte" in fname_lower or "compte" in fname_lower:
                        subcat = "Banking"
                        if cat == "Uncategorized":
                            cat = "Finance"
                    elif "atom address" in fname_lower:
                        subcat = "Cryptocurrency"
                        if cat == "Uncategorized":
                            cat = "Finance"
                    elif fname.startswith("~$"):
                        # Office temp file — same category as parent file
                        subcat = ""
                    else:
                        subcat = ""
                else:
                    cat = "Uncategorized"
                    subcat = f.get("_subcat", "")

                assignments.append((fid, cat, subcat))

            if assignments:
                return self._build_tree_from_assignments(assignments)
        except Exception as e:
            print(f"[LLM] Classification error: {e}")
            import traceback; traceback.print_exc()

        # Fallback to extension rules
        return self._fallback_tree(files).get("tree", [])

    @staticmethod
    def _parse_photo_date(f: Dict[str, Any]) -> Optional[str]:
        """Extract YYYY-MM from EXIF datetime or filename pattern.
        Handles: 20230506_042311916_iOS.heic, IMG_20240615_081742.jpg, EXIF datetime."""
        # Try EXIF first
        exif = f.get("exif", {})
        if exif and exif.get("datetime_original"):
            dt = exif["datetime_original"]
            if len(dt) >= 7:
                return dt[:7].replace(":", "-")
        # Try filename: 20230506_042311916_iOS -> 2023-05
        fname = f.get("filename", "")
        m = re.search(r'(\d{4})(\d{2})(\d{2})', fname)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
        return None

    @staticmethod
    def _parse_photo_year(f: Dict[str, Any]) -> Optional[str]:
        """Extract YYYY from EXIF or filename."""
        ym = LLMManager._parse_photo_date(f)
        return ym[:4] if ym else None

    def _subcluster_photos(self, tree: List[Dict[str, Any]], files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Post-process: split large photo subcategories by year/month.
        Only applies to Photos category subbuckets with > 50 files.
        Uses EXIF datetime or filename date patterns (20230506_...) for clustering."""
        PHOTO_SUBCLUSTER_THRESHOLD = 50
        MONTH_SPLIT_THRESHOLD = 20

        for node in tree:
            if node.get("category") != "Photos":
                continue
            new_subbuckets = []
            for sub in node.get("subbuckets", []):
                file_ids = sub.get("files", [])
                sub_name = sub.get("subcategory", "")
                if len(file_ids) <= PHOTO_SUBCLUSTER_THRESHOLD:
                    new_subbuckets.append(sub)
                    continue

                # Large photo subbucket -- split by date
                dated: Dict[str, List[int]] = {}
                undated: List[int] = []
                for fid in file_ids:
                    if fid >= len(files):
                        continue
                    year = self._parse_photo_year(files[fid])
                    if year:
                        dated.setdefault(year, []).append(fid)
                    else:
                        undated.append(fid)

                if not dated:
                    new_subbuckets.append(sub)
                    continue

                # Split by year, then by month if year is big enough
                for year in sorted(dated.keys()):
                    year_ids = dated[year]
                    if len(year_ids) <= MONTH_SPLIT_THRESHOLD:
                        new_subbuckets.append({
                            "subcategory": f"{sub_name} {year}" if sub_name else year,
                            "files": year_ids,
                        })
                    else:
                        month_groups: Dict[str, List[int]] = {}
                        for fid in year_ids:
                            ym = self._parse_photo_date(files[fid])
                            if ym:
                                month_groups.setdefault(ym, []).append(fid)
                            else:
                                month_groups.setdefault(f"{year}-unknown", []).append(fid)
                        for ym in sorted(month_groups.keys()):
                            new_subbuckets.append({
                                "subcategory": f"{sub_name} {ym}" if sub_name else ym,
                                "files": month_groups[ym],
                            })

                # Attach undated files
                if undated:
                    new_subbuckets.append({
                        "subcategory": f"{sub_name} (undated)" if sub_name else "undated",
                        "files": undated,
                    })

            node["subbuckets"] = new_subbuckets
            node["count"] = sum(len(s.get("files", [])) for s in new_subbuckets)
        return tree

    @staticmethod
    def _summarize_tree(tree: List[Dict[str, Any]]) -> str:
        """Compact one-line-per-category summary of the accumulated tree for the LLM prompt.
        e.g. 'Photos > Eleanor (12 files)\nFinance > Cryptocurrency (3 files)'"""
        lines = []
        for node in tree:
            cat = node.get("category", "")
            count = node.get("count", 0)
            subs = node.get("subbuckets", [])
            if subs:
                sub_names = [s.get("subcategory", "") for s in subs if s.get("subcategory")]
                if sub_names:
                    lines.append(f"{cat} > {', '.join(sub_names)} ({count} files)")
                else:
                    lines.append(f"{cat} ({count} files)")
            else:
                lines.append(f"{cat} ({count} files)")
        return "\n".join(lines) if lines else ""

    def _merge_into_accumulated(self, accumulated: List[Dict[str, Any]], new_tree: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merge a new batch's tree into the accumulated tree.
        Same-category + same-subcategory buckets get their file lists combined.
        Category/subcategory matching is case-insensitive."""
        # Build a lookup from the accumulated tree
        lookup: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for node in accumulated:
            cat = node.get("category", "")
            cat_key = cat.lower()
            lookup[cat_key] = {}
            for sub in node.get("subbuckets", []):
                sub_name = sub.get("subcategory", "")
                sub_key = sub_name.lower()
                lookup[cat_key][sub_key] = sub

        # Merge new tree nodes into the accumulated tree
        for new_node in new_tree:
            cat = new_node.get("category", "")
            cat_key = cat.lower()
            if cat_key not in lookup:
                # New top-level category — append as-is
                accumulated.append(new_node)
                lookup[cat_key] = {}
                for sub in new_node.get("subbuckets", []):
                    sub_name = sub.get("subcategory", "")
                    lookup[cat_key][sub_name.lower()] = sub
            else:
                # Existing category — merge subbuckets
                existing_node = next(n for n in accumulated if n.get("category", "").lower() == cat_key)
                for new_sub in new_node.get("subbuckets", []):
                    sub_name = new_sub.get("subcategory", "")
                    sub_key = sub_name.lower()
                    if sub_key in lookup[cat_key]:
                        # Existing subcategory — combine file lists
                        existing_sub = lookup[cat_key][sub_key]
                        existing_files = list(dict.fromkeys(existing_sub.get("files", []) + new_sub.get("files", [])))
                        existing_sub["files"] = existing_files
                    else:
                        # New subcategory under existing category
                        existing_node.setdefault("subbuckets", []).append(new_sub)
                        lookup[cat_key][sub_key] = new_sub
                # Update count
                existing_node["count"] = sum(len(s.get("files", [])) for s in existing_node.get("subbuckets", []))

        # Recalculate all counts
        for node in accumulated:
            node["count"] = sum(len(s.get("files", [])) for s in node.get("subbuckets", []))

        return accumulated

    def _build_tree_from_assignments(self, assignments: List[Tuple[int, str, str]]) -> List[Dict[str, Any]]:
        """Build a hierarchical tree from (file_id, category, subcategory) assignments.
        Post-processes subcategories: strips full paths to last folder name,
        removes file extensions used as subcategories."""
        # Clean up subcategories
        cleaned = []
        for fid, cat, subcat in assignments:
            # Strip full nested paths in subcategory: "Cryocare services/CIMC documents/internal ISO #1"
            # → just "internal ISO #1" (last folder segment)
            if '/' in subcat:
                parts = [p.strip() for p in subcat.split('/') if p.strip()]
                if parts:
                    subcat = parts[-1]
            # Remove file extensions used as subcategory
            if subcat and re.match(r'^\.[a-z0-9]{1,5}$', subcat, re.IGNORECASE):
                subcat = ""
            # Strip leading/trailing punctuation
            subcat = subcat.strip('*`"\' ')
            cleaned.append((fid, cat, subcat))

        # Group by category → subcategory → file_ids
        by_cat: Dict[str, Dict[str, List[int]]] = {}
        for fid, cat, subcat in cleaned:
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

    def _build_manifest(self, files: List[Dict[str, Any]], scan_root: str = "") -> str:
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
            rel_path = self._relative_path_hint(path, scan_root)
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

    def _relative_path_hint(self, path: str, scan_root: str = "") -> str:
        """Extract a meaningful relative path from the full path.
        Trims the scan root prefix to show the folder hierarchy the user created.
        Uses scan_root when provided (handles /media/... and any mount path).
        Falls back to heuristic trimming for home dirs and standard scan roots.
        e.g. /media/UUID/bakc up HD/Cryocare services/contract.pdf, root=/media/UUID/bakc up HD
             -> 'Cryocare services'
        """
        if not path:
            return ""

        # Primary path: strip scan_root prefix directly (handles /media/..., external drives, etc.)
        if scan_root:
            root = str(Path(scan_root).resolve())
            p = str(Path(path).resolve())
            if p.startswith(root + "/"):
                rel = p[len(root) + 1:]  # e.g. "Cryocare services/contract.pdf"
                # Return everything except the filename
                parts = rel.split("/")
                return "/".join(parts[:-1]) if len(parts) > 1 else ""

        # Fallback: heuristic trimming for home dirs and standard scan roots
        p = Path(path)
        parts = p.parts
        trim_prefixes = {"home", "Users", "root", "tmp"}
        start = 0
        for i, part in enumerate(parts):
            if part in trim_prefixes:
                start = i + 2  # skip /home/user
                break
        scan_roots = {"Downloads", "Desktop", "Documents", "Pictures", "Videos", "Music"}
        for i in range(start, len(parts) - 1):
            if parts[i] in scan_roots:
                start = i + 1
                break
        rel_parts = parts[start:-1] if start < len(parts) - 1 else []
        return "/".join(rel_parts) if rel_parts else ""

    @staticmethod
    def _find_file_by_path_echo(rest: str, files: List[Dict[str, Any]]) -> Optional[int]:
        """When a small model outputs 'id: path/to/file: category' instead of 'N: category',
        try to find the file ID by matching the path echo against file paths."""
        # Take the part before the last colon as the path echo
        if ':' in rest:
            path_echo = rest[:rest.rindex(':')].strip()
        else:
            path_echo = rest.strip()
        
        # Try to match by filename (last segment of the path echo)
        if '/' in path_echo:
            filename = path_echo.split('/')[-1].strip()
        else:
            filename = path_echo.strip()
        
        if not filename or len(filename) < 2:
            return None
        
        # Find the file whose path ends with this filename
        for f in files:
            fpath = f.get("path", "")
            fname = f.get("filename", "")
            if fpath and fpath.endswith(filename):
                return f.get("id")
            if fname == filename:
                return f.get("id")
        return None

    def _parse_hierarchical_lines(self, text: str, files: List[Dict[str, Any]]) -> List[Tuple[int, str, str]]:
        """Parse 'id: Category > Subcategory' lines from LLM output.

        Returns list of (file_id, category, subcategory) tuples.
        Subcategory is "" if the model only output a top-level category.

        Handles several LLM output formats:
        - "0: Category > Subcategory" (ideal)
        - "0: filename | content | Category > Subcategory" (pipe echo)
        - "id: path/to/file: Category > Subcategory" (colon echo, common with small models)
        - "id: path/to/file: folder/path" (path echo, no > separator)
        """
        assignments = []
        valid_ids = {f.get("id", 0) for f in files}
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            # Try several formats:
            # "N: Category > Subcategory" (ideal)
            # "id: N: Category > Subcategory" (redundant id prefix)
            # "id: path/to/file: folder/path" (path echo with id prefix, no file number)
            # "N: path/to/file: folder/path" (path echo)
            # "id: path | content | Category > Sub" (manifest echo)
            match = re.match(r'^(?:id\s*:\s*)?(\d+)\s*:\s*(.+)', line, re.IGNORECASE)
            if not match:
                # Try "id: <something>: <category>" format (no file number, small model echo)
                # Map it by looking up the filename in the manifest
                match2 = re.match(r'^id\s*:\s*(.+)', line, re.IGNORECASE)
                if match2:
                    rest = match2.group(1).strip()
                    # Find the file by matching the path/filename in the manifest
                    fid = self._find_file_by_path_echo(rest, files)
                    if fid is not None:
                        # Extract category part after last colon (if any)
                        if ':' in rest:
                            cat_part = rest[rest.rindex(':') + 1:].strip()
                        else:
                            cat_part = rest
                        # Convert path to > hierarchy
                        if '/' in cat_part and '>' not in cat_part:
                            path_parts = [p.strip() for p in cat_part.split('/') if p.strip()]
                            if len(path_parts) >= 2:
                                cat_part = ' > '.join(path_parts[-2:])
                            elif len(path_parts) == 1:
                                cat_part = path_parts[0]
                        if cat_part and fid in valid_ids:
                            parts = [p.strip() for p in cat_part.split('>') if p.strip()]
                            if len(parts) == 1:
                                assignments.append((fid, parts[0], ""))
                            elif len(parts) >= 2:
                                assignments.append((fid, parts[0], " > ".join(parts[1:MAX_DEPTH])))
                continue

            fid = int(match.group(1))
            rest = match.group(2).strip()

            # Handle pipe echo: "filename | content | Category > Sub"
            if '|' in rest:
                rest = rest.split('|')[-1].strip()

            # Handle colon echo: "path/to/file: Category > Sub" or "path: folder/path"
            # Small models echo the file path before the actual category.
            if '>' in rest:
                # Has hierarchy separator — find where the category starts.
                gt_pos = rest.index('>')
                before_gt = rest[:gt_pos]
                if ':' in before_gt:
                    # "path/to/file: Category > Sub" — take after last colon before >
                    rest = rest[rest.rindex(':', 0, gt_pos) + 1:].strip()
            elif ':' in rest[1:]:
                # No > but has extra colon: "path/to/file: folder/path"
                rest = rest[rest.rindex(':') + 1:].strip()
                # Convert path separators to > for hierarchy
                if '/' in rest:
                    path_parts = [p.strip() for p in rest.split('/') if p.strip()]
                    if len(path_parts) >= 2:
                        rest = ' > '.join(path_parts[-2:])  # last two segments as Cat > Sub
                    elif len(path_parts) == 1:
                        rest = path_parts[0]

            # Strip quotes, markdown
            rest = rest.strip('*`"\'')

            # Reject garbage: too long, looks like content
            if len(rest) > 100:
                continue
            if 'no text content' in rest.lower() or 'file type:' in rest.lower():
                continue
            # Reject if it still looks like a file path (has extension at end)
            if re.search(r'\.\w{1,5}$', rest) and '/' in rest:
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

        # Registry hint disabled — accumulates garbage that poisons small model prompts
        registry_hint = ""

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