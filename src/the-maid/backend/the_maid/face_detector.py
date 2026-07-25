"""
The Maid — Face Detection + Encoding (Slice 6A)
RetinaFace detection + ArcFace 128D embeddings via insightface.
Graceful degradation when insightface/models not available.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional

import numpy as np

# Image extensions eligible for face detection
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".heic"}

# 128D ArcFace embedding vector
EMBEDDING_DIM = 128


class FaceDetector:
    """
    Wraps insightface RetinaFace + ArcFace.
    Gracefully degrades to no-op when insightface or models are unavailable.
    """

    def __init__(self, model_path: Optional[str] = None, ctx_id: int = -1):
        """
        Args:
            model_path: Path to model pack directory. If None, uses insightface default.
            ctx_id: ONNX execution provider. -1 = CPU, 0 = GPU.
        """
        self._model = None
        self._available = False
        self._error = None
        self._model_path = model_path
        self._ctx_id = ctx_id

        try:
            from insightface.app import FaceAnalysis
            self._FaceAnalysis = FaceAnalysis
            self._available = True
        except ImportError:
            self._error = "insightface not installed"
            return

    def _ensure_model(self) -> bool:
        """Lazily load the model on first use. Returns True if ready."""
        if self._model is not None:
            return True
        if not self._available:
            return False
        try:
            self._model = self._FaceAnalysis(
                name="buffalo_l",
                root=self._model_path or "",
                providers=["CPUExecutionProvider"] if self._ctx_id < 0 else None,
            )
            self._model.prepare(ctx_id=self._ctx_id)
            return True
        except Exception as e:
            self._error = f"Model load failed: {e}"
            self._model = None
            return False

    @property
    def available(self) -> bool:
        """True if face detection can run (insightface installed + model loadable)."""
        return self._available and self._ensure_model()

    @property
    def error(self) -> Optional[str]:
        """Returns error message if face detection is unavailable."""
        return self._error

    def detect_faces(self, image_path: str) -> List[Dict[str, Any]]:
        """
        Detect faces in a single image.

        Returns list of face dicts:
            {bbox: [x1,y1,x2,y2], embedding: List[float], confidence: float}
        Returns empty list if no faces, not an image, or unavailable.
        """
        p = Path(image_path)
        if p.suffix.lower() not in IMAGE_EXTENSIONS:
            return []

        if not self._ensure_model():
            return []

        try:
            from PIL import Image
            img = np.array(Image.open(image_path).convert("RGB"))
        except Exception as e:
            self._error = f"Failed to load image {image_path}: {e}"
            return []

        try:
            faces = self._model.get(img)
        except Exception as e:
            self._error = f"Detection failed for {image_path}: {e}"
            return []

        results = []
        for face in faces:
            bbox = face.bbox.tolist() if hasattr(face.bbox, "tolist") else list(face.bbox)
            embedding = face.normed_embedding.tolist() if hasattr(face.normed_embedding, "tolist") else list(face.normed_embedding)
            results.append({
                "bbox": [round(c, 2) for c in bbox],
                "embedding": embedding,
                "confidence": float(face.det_score),
            })
        return results

    def detect_faces_batch(self, image_paths: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Detect faces across multiple images.
        Model loaded once, reused for all images.

        Returns {image_path: [face dicts]} for each image with faces.
        Images with no faces or errors are omitted from results.
        """
        if not self._ensure_model():
            return {}

        results = {}
        for path in image_paths:
            faces = self.detect_faces(path)
            if faces:
                results[path] = faces
        return results


def detect_faces_for_scan(
    scan_results: List[Dict[str, Any]],
    face_detector: Optional[FaceDetector] = None,
    enabled: bool = True,
) -> List[Dict[str, Any]]:
    """
    Post-scan face detection pass. Mutates scan_results in place,
    adding 'faces_detected' field with face data per file.

    Args:
        scan_results: Output from FileScanner.scan_directory()
        face_detector: FaceDetector instance. If None, creates default.
        enabled: If False, skips (faces_detected stays empty).

    Returns: The same scan_results list with faces_detected populated.
    """
    if not enabled:
        for f in scan_results:
            f.setdefault("faces_detected", [])
        return scan_results

    if face_detector is None:
        face_detector = FaceDetector()

    if not face_detector.available:
        # ponytail: graceful degradation — no faces, no crash
        for f in scan_results:
            f.setdefault("faces_detected", [])
        return scan_results

    # Filter to image files only
    image_files = [f for f in scan_results if f.get("extension", "").lower() in IMAGE_EXTENSIONS]

    # Batch detect
    face_map = face_detector.detect_faces_batch([f["path"] for f in image_files])

    for f in scan_results:
        faces = face_map.get(f["path"], [])
        # Store face count + cluster placeholders (clustering in Slice 6B)
        f["faces_detected"] = [
            {
                "bbox": face["bbox"],
                "confidence": face["confidence"],
                "embedding": face["embedding"],  # ponytail: keep embedding for clustering, drop when DB exists
            }
            for face in faces
        ]

    return scan_results