"""
The Maid — LLM Manager
Handles local model loading and inference via llama-cpp-python.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
import json

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
    
    def load_model(self) -> bool:
        """Load the GGUF model. Returns True if successful."""
        try:
            from llama_cpp import Llama
            
            if not self.model_path.exists():
                print(f"[LLM] Model not found at {self.model_path}")
                print(f"[LLM] Run: python -m the_maid.models download")
                return False
            
            print(f"[LLM] Loading model: {self.model_path}")
            self.llm = Llama(
                model_path=str(self.model_path),
                n_ctx=4096,
                n_threads=4,
                verbose=False,
            )
            self._loaded = True
            print("[LLM] Model loaded successfully")
            return True
            
        except ImportError:
            print("[LLM] llama-cpp-python not installed. Run: pip install llama-cpp-python")
            return False
        except Exception as e:
            print(f"[LLM] Failed to load model: {e}")
            return False
    
    def categorize_file(self, file_metadata: Dict[str, Any]) -> Dict[str, Any]:
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
                return result
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
    
    def _build_categorization_prompt(self, metadata: Dict[str, Any]) -> str:
        """Build structured prompt for file categorization."""
        return f"""You are a file organizer AI. Given file metadata, propose a better location and tags.

File: {metadata["filename"]}
Extension: {metadata["extension"]}
Size: {metadata["size_bytes"]} bytes
Modified: {metadata["modified_time"]}

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
