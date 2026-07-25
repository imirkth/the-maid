"""
Regression tests for Slice 6A (Face Detection + Encoding).
These tests exercise real edge cases that the mock-based suite does not cover.
"""

import pytest
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from the_maid.face_detector import (
    FaceDetector,
    detect_faces_for_scan,
    IMAGE_EXTENSIONS,
    EMBEDDING_DIM,
)


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="the-maid-face-regression-")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _make_mock_face(bbox, embedding, score):
    face = MagicMock()
    face.bbox = np.array(bbox)
    face.normed_embedding = np.array(embedding)
    face.det_score = score
    return face


class TestModelOutputValidation:
    """Validate that raw model outputs are sanitized before returning."""

    def test_confidence_nan_is_rejected(self, temp_dir):
        """A face with NaN confidence must not leak NaN into results."""
        img = Path(temp_dir, "photo.jpg")
        img.write_bytes(b"\xff\xd8\xff\xe0")

        face = _make_mock_face([0, 0, 10, 10], [0.1] * EMBEDDING_DIM, float("nan"))
        mock_app = MagicMock()
        mock_app.get.return_value = [face]

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = MagicMock()
            faces = detector.detect_faces(str(img))

        assert faces == [], "NaN confidence should cause face rejection"
        assert detector.error is not None

    def test_confidence_negative_is_rejected(self, temp_dir):
        """A face with negative confidence must not leak into results."""
        img = Path(temp_dir, "photo.jpg")
        img.write_bytes(b"\xff\xd8\xff\xe0")

        face = _make_mock_face([0, 0, 10, 10], [0.1] * EMBEDDING_DIM, -0.5)
        mock_app = MagicMock()
        mock_app.get.return_value = [face]

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = MagicMock()
            faces = detector.detect_faces(str(img))

        assert faces == [], "Negative confidence should cause face rejection"

    def test_inverted_bbox_is_normalized(self, temp_dir):
        """A bbox with x1 > x2 or y1 > y2 should be normalized to [x1,y1,x2,y2]."""
        img = Path(temp_dir, "photo.jpg")
        img.write_bytes(b"\xff\xd8\xff\xe0")

        face = _make_mock_face([100, 80, 10, 20], [0.1] * EMBEDDING_DIM, 0.95)
        mock_app = MagicMock()
        mock_app.get.return_value = [face]

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        with patch("PIL.Image.open") as mock_open:
            mock_open.return_value.convert.return_value = MagicMock()
            faces = detector.detect_faces(str(img))

        assert len(faces) == 1
        x1, y1, x2, y2 = faces[0]["bbox"]
        assert x1 < x2, "x1 must be less than x2 after normalization"
        assert y1 < y2, "y1 must be less than y2 after normalization"


class TestBatchErrorPropagation:
    """Errors in batch processing must not break the whole scan."""

    def test_corrupt_image_in_batch_returns_empty_faces(self, temp_dir):
        """A corrupt image in a batch must not crash; scan results are still returned."""
        good = Path(temp_dir, "good.jpg")
        bad = Path(temp_dir, "bad.jpg")
        good.write_bytes(b"\xff\xd8\xff\xe0")
        bad.write_bytes(b"not an image")

        scan_results = [
            {"file_id": "g0000001", "filename": "good.jpg", "path": str(good), "extension": ".jpg"},
            {"file_id": "b0000002", "filename": "bad.jpg", "path": str(bad), "extension": ".jpg"},
        ]

        mock_face = _make_mock_face([0, 0, 10, 10], [0.1] * EMBEDDING_DIM, 0.95)
        mock_app = MagicMock()
        mock_app.get.return_value = [mock_face]

        detector = FaceDetector()
        detector._available = True
        detector._FaceAnalysis = MagicMock(return_value=mock_app)

        # Patch PIL.Image.open so that bad.jpg raises OSError
        def selective_open(path):
            if "bad.jpg" in str(path):
                raise OSError("cannot identify image")
            mock_img = MagicMock()
            mock_img.convert.return_value = MagicMock()
            return mock_img

        with patch("PIL.Image.open", side_effect=selective_open):
            results = detect_faces_for_scan(scan_results, face_detector=detector)

        good_result = next(r for r in results if r["filename"] == "good.jpg")
        bad_result = next(r for r in results if r["filename"] == "bad.jpg")

        assert len(good_result["faces_detected"]) == 1
        assert bad_result["faces_detected"] == []
        # Corrupt image records detector.error; the important behavior is graceful degradation.
        assert detector.error is not None
