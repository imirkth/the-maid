"""
The Maid — LLM client + folder tree pipeline entry point.

The folder tree itself is designed by ``tree_architect.TreeArchitect``: files
are profiled from their real content, curated folders are kept whole, dump
folders are dissolved, topics are clustered, photos are grouped by event and
the tree shape is bounded. The local LLM (Ollama / llama-server) is only asked
to *name* folders, which small models do reliably; without an LLM the folders
are named from their most distinctive keywords.

A compact profile of every leaf folder is saved to ~/.the-maid/tree_model.json
so that new files can be routed into the approved tree later.
"""

import os
import re
import requests
from typing import Optional, Dict, Any, List

from .registry import CategoryRegistry
from .preferences import Preferences
from .tree_architect import TreeArchitect, save_model

# LLM server configuration — set by Rust sidecar via env vars
LLM_BASE_URL = os.environ.get("THE_MAID_LLM_BASE_URL", "http://127.0.0.1:11434")
LLM_MODEL = os.environ.get("THE_MAID_LLM_MODEL", "gemma4:e2b")


class LLMManager:
    """Local LLM client and entry point of the folder tree pipeline."""

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
                # Whole-folder-structure prompts are ~2k tokens; ollama's default
                # num_ctx silently truncates the prompt head — request a real window.
                "num_ctx": 8192,
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

    # --- Folder tree pipeline ---

    def _namer(self, prompt: str) -> str:
        return self._chat_complete([{"role": "user", "content": prompt}], max_tokens=400, temperature=0.2)

    def categorize_all(
        self,
        files: List[Dict[str, Any]],
        sandbox_folders: Optional[list[str]] = None,
        scan_root: str = "",
        prefs: Optional[Preferences] = None,
    ) -> Dict[str, Any]:
        """
        Design a folder tree for ``files``.

        Returns {"tree": [{"category", "subbuckets": [{"subcategory", "files", "rationale"}],
        "rationale", "count"}], "summary": {...before/after structure stats...}}
        """
        if not files:
            return {"tree": [], "summary": {}}
        architect = TreeArchitect(scan_root, namer=self._namer if self._loaded else None, prefs=prefs)
        result = architect.build(files)
        save_model(result["model"])
        try:
            self._registry.register_from_tree(result["tree"])
        except Exception as e:  # registry is a convenience, never block a scan
            print(f"[LLM] registry update failed: {e}", flush=True)
        return {"tree": result["tree"], "summary": result["summary"]}

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
        """Legacy batch API — now backed by the tree architect."""
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