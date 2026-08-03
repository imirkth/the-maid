"""
The Maid — LLM Manager
Handles local model loading and inference via a local llama.cpp HTTP server.

The Maid no longer embeds llama-cpp-python directly because that package
dragged in the vulnerable ``diskcache`` dependency (PYSEC-2026-2447).  Instead
we talk to a local ``llama-server`` or equivalent OpenAI-compatible endpoint.
Set ``THE_MAID_LLM_BASE_URL`` to point at the server (default: http://127.0.0.1:8080).
"""

import json
import os
import re
from pathlib import Path
from typing import Optional, Dict, Any

import requests

from .sandbox import validate_path

# Model configuration
MODEL_DIR = Path.home() / ".the-maid" / "models"
DEFAULT_MODEL = "qwen3-1.7b-q4_k_m.gguf"  # ~1GB, good at following instructions

# Model download URLs (placeholder — need actual URLs)
MODEL_URLS = {
    "qwen3-1.7b": "https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/main/qwen3-1.7b-q4_k_m.gguf",
    "qwen3-4b": "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/qwen3-4b-q4_k_m.gguf",
}


class LLMManager:
    """Manages local LLM inference for file categorization."""

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or (MODEL_DIR / DEFAULT_MODEL)
        self.llm = None
        self._loaded = False

    @staticmethod
    def _server_url() -> str:
        return os.environ.get("THE_MAID_LLM_BASE_URL", "http://127.0.0.1:8080").rstrip("/")

    def _complete(self, prompt: str, *, max_tokens: int = 256, temperature: float = 0.1) -> Dict[str, Any]:
        """Call the local llama.cpp /completion endpoint."""
        url = f"{self._server_url()}/completion"
        response = requests.post(
            url,
            json={
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stop": ["\n}"],
            },
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        content = data.get("content", data.get("choices", [{}])[0].get("text", ""))
        return {"choices": [{"text": content}]}

    def load_model(self) -> bool:
        """Probe the local llama.cpp server. Returns True if it responds."""
        try:
            url = f"{self._server_url()}/health"
            response = requests.get(url, timeout=5)
            if response.status_code != 200:
                print(f"[LLM] Local LLM server not ready: {response.status_code}")
                return False

            self.llm = self._complete
            self._loaded = True
            print(f"[LLM] Connected to local LLM server at {self._server_url()}")
            return True
        except requests.exceptions.ConnectionError:
            print(
                "[LLM] No local LLM server found. "
                "Start one with: llama-server -m <model.gguf> --port 8080"
            )
            return False
        except Exception as e:
            print(f"[LLM] Failed to connect to local LLM server: {e}")
            return False

    def categorize_file(
        self,
        file_metadata: Dict[str, Any],
        sandbox_folders: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        """
        Categorize a file and propose destination.
        Returns: {proposed_path, tags, rationale}
        """
        if not self._loaded:
            return {
                "proposed_path": file_metadata["path"],
                "tags": [],
                "rationale": "LLM not loaded — skipping categorization",
            }

        # Build prompt
        prompt = self._build_categorization_prompt(file_metadata)

        try:
            response = self.llm(prompt, max_tokens=256, temperature=0.1)
            text = response["choices"][0]["text"]

            # Parse JSON response
            try:
                result = json.loads(text)
                return self._sanitize_categorization_result(
                    result, file_metadata, sandbox_folders
                )
            except json.JSONDecodeError:
                return {
                    "proposed_path": file_metadata["path"],
                    "tags": [],
                    "rationale": f"LLM returned non-JSON: {text[:100]}",
                }

        except Exception as e:
            return {
                "proposed_path": file_metadata["path"],
                "tags": [],
                "rationale": f"Inference error: {e}",
            }

    def _sanitize_filename_for_prompt(self, filename: str) -> str:
        """Strip control chars, limit length, escape backslashes/quotes."""
        # ponytail: minimal sanitization for prompt injection; keep printable
        cleaned = re.sub(r"[\x00-\x1f\x7f]", "", filename)
        cleaned = cleaned.replace("\\", "\\\\").replace('"', '\\"')
        return cleaned[:255]

    def _sanitize_categorization_result(
        self,
        result: Dict[str, Any],
        file_metadata: Dict[str, Any],
        sandbox_folders: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        """Validate LLM output path against sandbox; fall back on escape."""
        proposed = result.get("proposed_path", file_metadata.get("path", ""))
        try:
            validate_path(proposed, sandbox_folders)
        except ValueError:
            # ponytail: LLM proposed path escapes sandbox; fall back to current path
            return {
                "proposed_path": file_metadata.get("path", proposed),
                "tags": result.get("tags", []),
                "rationale": (
                    f"LLM proposed path rejected; kept current location. "
                    f"Original rationale: {result.get('rationale', '')}"
                ),
            }
        return result

    def _build_categorization_prompt(self, metadata: Dict[str, Any]) -> str:
        """Build structured prompt for file categorization."""
        safe_filename = self._sanitize_filename_for_prompt(
            metadata.get("filename", "")
        )
        return f"""You are a file organizer AI. Given file metadata, propose a better location and tags.

File: {safe_filename}
Extension: {metadata.get("extension", "")}
Size: {metadata.get("size_bytes", 0)} bytes
Modified: {metadata.get("modified_time", "")}

Respond in JSON:
{{
    "proposed_path": "/Users/.../Destination/filename.ext",
    "tags": ["tag1", "tag2"],
    "rationale": "Why this location and tags"
}}

JSON:"""

    def download_model(self, model_name: str = "qwen3-1.7b") -> bool:
        """Download a model from HuggingFace."""
        url = MODEL_URLS.get(model_name)
        if not url:
            print(f"[LLM] Unknown model: {model_name}")
            return False

        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        destination = MODEL_DIR / f"{model_name}-q4_k_m.gguf"

        print(f"[LLM] Downloading {model_name} to {destination}...")
        # TODO: Implement download with progress
        print("[LLM] Download not yet implemented — please download manually")
        return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "download":
        manager = LLMManager()
        manager.download_model()
    else:
        print("Usage: python -m the_maid.models download")
