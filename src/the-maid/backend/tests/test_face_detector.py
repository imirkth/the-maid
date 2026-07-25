"""
Tests for FaceDetector — graceful degradation, mocking, integration with scanner.
No real insightface/models required.
"""

import pytest
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from typing import List

import numpy as np

from the_maid.face_detector import (
    FaceDetector,
    detect_faces_for_scan,
    IMAGE_EXTENSIONS,
    EMBEDDING_DIM,
)


# ─── Fixtures ───

@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="the-maid-face-test-")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def fake_image(temp_dir):
    """Create a minimal fake image file."""
    p = Path(temp_dir, "photo.jpg")
    p.write_bytes(b"\xff\xd8\xff\xe0")  # JPEG header
    return str(p)


@pytest.fixture
def scan_results_with_images(temp_dir):
    """Scan-like results with image and non-image files."""
    img1 = Path(temp_dir, "photo1.jpg")
    img2 = Path(temp_dir, "photo2.png")
    doc = Path(temp_dir, "notes.txt")
    for p in [img1, img2, doc]:
        p.write_bytes(b"\x00" * 10)

    return [
        {"file_id": "aaa11111", "filename": "photo1.jpg", "path": str(img1),
         "extension": ".jpg", "size_bytes": 10},
        {"file_id": "bbb22222", "filename": "photo2.png", "path": str(img2),
         "extension": ".png", "size_bytes": 10},
        {"file_id": "ccc33333", "filename": "notes.txt", "path": str(doc),
         "extension": ".txt", "size_bytes": 10},
    ]


def _make_mock_face(bbox, embedding, score):
    """Create a mock insightface Face object."""
    import numpy as np
    face = MagicMock()
    face.bbox = np.array(bbox)
    face.normed_embedding = np.array(embedding)
    face.det_score = score
    return face


# ─── Graceful Degradation ───

class TestGracefulDegradation:
    """FaceDetector must not crash when insightface is missing."""

    def test_no_insightface_returns_empty(self):
        """When insightface is not installed, detect_faces returns []."""
        with patch.dict("sys.modules", {"insightface": None, "insightface.app": None}):
            detector = FaceDetector()
            assert not detector.available
            assert detector.error == "insightface not installed"
            assert detector.detect_faces("/some/image.jpg") == []

    def test_no_insightface_batch_returns_empty(self):
        """Batch detection returns {} when unavailable."""
        with patch.dict("sys.modules", {"insightface": None, "insightface.app": None}):
            detector = FaceDetector()
            assert detector.detect_faces_batch(["/a.jpg", "/b.png"]) == {}

    def test_detect_faces_for_scan_disabled(self, scan_results_with_images):
        """When enabled=False, faces_detected stays empty."""
        results = detect_faces_for_scan(
            scan_results_with_images, enabled=False
        )
        for r in results:
            assert r["faces_detected"] == []

    def test_detect_faces_for_scan_no_detector(self, scan_results_with_images):
        """When detector can't load, graceful degradation — empty faces."""
        with patch.dict("sys.modules", {"insightface": None, "insightface.app": None}):
            results = detect_faces_for_scan(scan_results_with_images)
        for r in results:
            assert r["faces_detected"] == []


# ─── Image Extension Filtering ───

class TestImageFiltering:
    """Non-image files should be skipped."""

    def test_non_image_returns_empty(self, temp_dir):
        """detect_faces on non-image file returns []."""
        txt = Path(temp_dir, "doc.txt")
        txt.write_text("hello")
        detector = FaceDetector()
        # Even if model were available, non-image should return []
        assert detector.detect_faces(str(txt)) == []

    def test_image_extensions_set(self):
        """IMAGE_EXTENSIONS should cover common image formats."""
        assert ".jpg" in IMAGE_EXTENSIONS
        assert ".jpeg" in IMAGE_EXTENSIONS
        assert ".png" in IMAGE_EXTENSIONS
        assert ".bmp" in IMAGE_EXTENSIONS
        assert ".webp" in IMAGE_EXTENSIONS
        assert ".heic" in IMAGE_EXTENSIONS
        # Non-images
        assert ".txt" not in IMAGE_EXTENSIONS
        assert ".pdf" not in IMAGE_EXTENSIONS
        assert ".mp4" not in IMAGE_EXTENSIONS


# ─── Mocked Detection ───

class TestMockedDetection:
    """Test detection logic with mocked insightface."""

    def _mock_pil_open(self):
        """Patch PIL.Image.open to return a fake array."""
        import numpy as np
        mock_img = MagicMock()
        mock_img.convert.return_value = MagicMock()
        return patch("PIL.Image.open", return_value=mock_img), mock_img

    def test_detect_faces_with_mock(self, fake_image):
        """detect_faces returns face data when model succeeds."""
        mock_face = _make_mock_face(
            bbox=[10, 20, 100, 120],
            embedding=[0.1] * EMBEDDING_DIM,
            score=0.95,
        )

        mock_app = MagicMock()
        mock_app.get.return_value = [mock_face]

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = MagicMock()
            faces = detector.detect_faces(fake_image)

        assert len(faces) == 1
        assert faces[0]["bbox"] == [10.0, 20.0, 100.0, 120.0]
        assert len(faces[0]["embedding"]) == EMBEDDING_DIM
        assert faces[0]["confidence"] == 0.95

    def test_detect_faces_no_faces_found(self, fake_image):
        """Image with no faces returns empty list."""
        mock_app = MagicMock()
        mock_app.get.return_value = []

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = MagicMock()
            faces = detector.detect_faces(fake_image)
        assert faces == []

    def test_detect_faces_multiple(self, fake_image):
        """Multiple faces in one image."""
        mock_faces = [
            _make_mock_face([0, 0, 50, 50], [0.1] * EMBEDDING_DIM, 0.9),
            _make_mock_face([60, 60, 120, 120], [0.2] * EMBEDDING_DIM, 0.8),
        ]

        mock_app = MagicMock()
        mock_app.get.return_value = mock_faces

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = MagicMock()
            faces = detector.detect_faces(fake_image)
        assert len(faces) == 2
        assert faces[0]["confidence"] == 0.9
        assert faces[1]["confidence"] == 0.8

    def test_detect_faces_uppercase_extension(self, fake_image):
        """Uppercase extension should still be recognized as image."""
        mock_face = _make_mock_face(
            bbox=[10, 20, 100, 120],
            embedding=[0.1] * EMBEDDING_DIM,
            score=0.95,
        )
        mock_app = MagicMock()
        mock_app.get.return_value = [mock_face]

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        uppercase_path = fake_image.replace(".jpg", ".JPG")
        Path(fake_image).rename(uppercase_path)

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = MagicMock()
            faces = detector.detect_faces(uppercase_path)

        assert len(faces) == 1
        assert faces[0]["bbox"] == [10.0, 20.0, 100.0, 120.0]

    def test_detect_faces_corrupt_image(self, fake_image):
        """Corrupt/unreadable image returns empty list and records error."""
        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=MagicMock())

        with patch("PIL.Image.open", side_effect=OSError("cannot identify image")):
            faces = detector.detect_faces(fake_image)

        assert faces == []
        assert "cannot identify image" in (detector.error or "")

    def test_detect_faces_invalid_embedding_dimension(self, fake_image):
        """Face with wrong embedding dimension is skipped."""
        face = MagicMock()
        face.bbox = np.array([0, 0, 10, 10])
        face.normed_embedding = np.array([0.1] * 64)  # not 128
        face.det_score = 0.95

        mock_app = MagicMock()
        mock_app.get.return_value = [face]

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = MagicMock()
            faces = detector.detect_faces(fake_image)

        assert faces == []
        assert "Invalid embedding dimension" in (detector.error or "")

    def test_detect_faces_non_finite_embedding(self, fake_image):
        """Face with NaN/Inf embedding is skipped."""
        face = MagicMock()
        face.bbox = np.array([0, 0, 10, 10])
        face.normed_embedding = np.array([float("nan")] + [0.1] * 127)
        face.det_score = 0.95

        mock_app = MagicMock()
        mock_app.get.return_value = [face]

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = MagicMock()
            faces = detector.detect_faces(fake_image)

        assert faces == []
        assert "Invalid embedding values" in (detector.error or "")

    def test_detect_faces_multiple_bbox_format(self, fake_image):
        """Multiple faces preserve bbox [x1, y1, x2, y2] format."""
        mock_faces = [
            _make_mock_face([0, 0, 50, 50], [0.1] * EMBEDDING_DIM, 0.9),
            _make_mock_face([60, 60, 120, 120], [0.2] * EMBEDDING_DIM, 0.8),
        ]

        mock_app = MagicMock()
        mock_app.get.return_value = mock_faces

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = MagicMock()
            faces = detector.detect_faces(fake_image)

        assert len(faces) == 2
        assert faces[0]["bbox"] == [0.0, 0.0, 50.0, 50.0]
        assert faces[1]["bbox"] == [60.0, 60.0, 120.0, 120.0]

    def test_detect_faces_model_error(self, fake_image):
        """Model error returns empty list, sets error message."""
        mock_app = MagicMock()
        mock_app.get.side_effect = RuntimeError("ONNX crash")

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = MagicMock()
            faces = detector.detect_faces(fake_image)
        assert faces == []
        assert "ONNX crash" in (detector.error or "")

    def test_batch_detect(self, scan_results_with_images):
        """Batch detection processes multiple images."""
        mock_faces = [_make_mock_face([0, 0, 50, 50], [0.1] * EMBEDDING_DIM, 0.9)]

        mock_app = MagicMock()
        mock_app.get.return_value = mock_faces

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        image_paths = [f["path"] for f in scan_results_with_images if f["extension"] in IMAGE_EXTENSIONS]
        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = MagicMock()
            results = detector.detect_faces_batch(image_paths)

        # Only images processed, both returned faces
        assert len(results) == 2
        for path, faces in results.items():
            assert len(faces) == 1
            assert faces[0]["confidence"] == 0.9


# ─── Scanner Integration ───

class TestScannerIntegration:
    """detect_faces_for_scan integrates with scanner output."""

    def test_faces_added_to_scan_results(self, scan_results_with_images):
        """Face data is added to image files, not to non-images."""
        mock_faces = [_make_mock_face([0, 0, 50, 50], [0.1] * EMBEDDING_DIM, 0.9)]

        mock_app = MagicMock()
        mock_app.get.return_value = mock_faces

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = MagicMock()
            results = detect_faces_for_scan(scan_results_with_images, face_detector=detector)

        # Images have faces
        img1 = next(r for r in results if r["filename"] == "photo1.jpg")
        assert len(img1["faces_detected"]) == 1
        assert img1["faces_detected"][0]["confidence"] == 0.9

        img2 = next(r for r in results if r["filename"] == "photo2.png")
        assert len(img2["faces_detected"]) == 1

        # Text file has no faces
        doc = next(r for r in results if r["filename"] == "notes.txt")
        assert doc["faces_detected"] == []

    def test_detect_faces_for_scan_batch_exception_graceful(self, scan_results_with_images):
        """If batch detection raises, scan results are still returned with empty faces."""
        detector = MagicMock()
        detector.available = True
        detector.detect_faces_batch.side_effect = RuntimeError("batch boom")
        detector._error = None
        type(detector).error = property(lambda self: self._error)

        results = detect_faces_for_scan(scan_results_with_images, face_detector=detector, enabled=True)

        assert isinstance(results, list)
        assert len(results) == len(scan_results_with_images)
        for r in results:
            assert r["faces_detected"] == []
        assert "batch boom" in (detector.error or "")

    def test_detect_faces_for_scan_preserves_faces_detected_key(self, scan_results_with_images):
        """Every scan result gets a faces_detected key even when batch fails."""
        detector = MagicMock()
        detector.available = True
        detector.detect_faces_batch.side_effect = RuntimeError("batch boom")
        detector._error = None

        results = detect_faces_for_scan(scan_results_with_images, face_detector=detector, enabled=True)
        for r in results:
            assert "faces_detected" in r

    def test_faces_not_added_when_disabled(self, scan_results_with_images):
        """When enabled=False, no faces added even if detector works."""
        mock_app = MagicMock()
        mock_app.get.return_value = [_make_mock_face([0, 0, 50, 50], [0.1] * EMBEDDING_DIM, 0.9)]

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        results = detect_faces_for_scan(
            scan_results_with_images, face_detector=detector, enabled=False
        )

        for r in results:
            assert r["faces_detected"] == []

    def test_embedding_in_face_data(self, scan_results_with_images):
        """Face data includes 128D embedding for clustering (Slice 6B)."""
        mock_faces = [_make_mock_face([0, 0, 50, 50], [0.5] * EMBEDDING_DIM, 0.9)]

        mock_app = MagicMock()
        mock_app.get.return_value = mock_faces

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = MagicMock()
            results = detect_faces_for_scan(scan_results_with_images, face_detector=detector)

        img = next(r for r in results if r["filename"] == "photo1.jpg")
        assert len(img["faces_detected"][0]["embedding"]) == EMBEDDING_DIM

    def test_empty_scan_results(self):
        """Empty scan results should not crash."""
        results = detect_faces_for_scan([])
        assert results == []

    def test_preserves_existing_fields(self, scan_results_with_images):
        """Face detection should not remove existing scan metadata."""
        mock_app = MagicMock()
        mock_app.get.return_value = []

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        results = detect_faces_for_scan(scan_results_with_images, face_detector=detector)

        for r in results:
            assert "file_id" in r
            assert "filename" in r
            assert "path" in r
            assert "extension" in r
            assert "faces_detected" in r


# ─── Model Loading ───

class TestModelLoading:
    """Test lazy model loading behavior."""

    def test_lazy_loading(self):
        """Model is not loaded until first use."""
        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock()

        # Model not loaded yet
        assert detector._model is None

        # Trigger load
        detector._ensure_model()
        assert detector._model is not None
        detector._FaceAnalysis.assert_called_once()

    def test_model_load_failure(self):
        """Model load failure sets error, available stays False."""
        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(side_effect=RuntimeError("missing model file"))

        assert not detector._ensure_model()
        assert "missing model file" in (detector.error or "")
        assert detector._model is None

    def test_model_loaded_once(self):
        """Model is loaded only once, reused on subsequent calls."""
        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock()

        detector._ensure_model()
        detector._ensure_model()
        detector._ensure_model()
        detector._FaceAnalysis.assert_called_once()