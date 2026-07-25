"""
Real ExifTool integration tests for face_tagger.py.
These tests require exiftool on PATH. They are skipped if not installed.
"""

import pytest
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from the_maid.face_tagger import (
    _write_xmp_tag,
    _clear_xmp_tag,
    _exiftool_available,
)


pytestmark = pytest.mark.skipif(
    not _exiftool_available(),
    reason="exiftool not installed"
)


@pytest.fixture
def temp_jpg():
    d = tempfile.mkdtemp(prefix="the-maid-exiftool-test-")
    path = Path(d) / "photo.jpg"
    path.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00"
        + bytes([int(16 + 16 * (i % 2)) for i in range(64)])
        + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b"
        b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00"
        b"\x7f"
        b"\xff\xd9"
    )
    yield str(path)
    shutil.rmtree(d, ignore_errors=True)


class TestRealExifTool:
    def test_write_and_read_xmp_tag(self, temp_jpg):
        assert _write_xmp_tag(temp_jpg, "XMP:PersonInImage", "Sarah")
        import subprocess
        result = subprocess.run(
            ["exiftool", "-XMP:PersonInImage", "-s3", temp_jpg],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0
        assert "Sarah" in result.stdout

    def test_clear_xmp_tag(self, temp_jpg):
        assert _write_xmp_tag(temp_jpg, "XMP:PersonInImage", "Sarah")
        assert _clear_xmp_tag(temp_jpg)
        import subprocess
        result = subprocess.run(
            ["exiftool", "-XMP:PersonInImage", "-s3", temp_jpg],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_write_missing_file_returns_false(self):
        assert not _write_xmp_tag("/nonexistent/path/file.jpg", "XMP:PersonInImage", "Sarah")

    def test_write_long_name(self, temp_jpg):
        long_name = "A" * 500
        assert _write_xmp_tag(temp_jpg, "XMP:PersonInImage", long_name)

    def test_write_special_characters(self, temp_jpg):
        special = "Sarah-O'Connor 佐藤"
        assert _write_xmp_tag(temp_jpg, "XMP:PersonInImage", special)

    def test_write_no_exiftool_path_missing(self, temp_jpg):
        with patch("the_maid.face_tagger.shutil.which", return_value=None):
            assert not _write_xmp_tag(temp_jpg, "XMP:PersonInImage", "Sarah")
