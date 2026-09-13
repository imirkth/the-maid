"""
Tests for exif_reader module.
Tests extract_exif(), format_exif_compact(), and GPS DMS-to-decimal conversion.
"""

import os
import tempfile
from pathlib import Path

import pytest

from the_maid.exif_reader import (
    extract_exif,
    format_exif_compact,
    _dms_to_decimal,
)

# Real test image with EXIF data (if available)
REAL_IMAGE = "/media/imirk/39dd62bc-9e3c-4443-95e5-efc8bfed51bd/bakc up HD/Cryocare services/CIMC documents/internal ISO #1/IMG_20240615_081742.jpg"


class TestExtractExif:
    """Tests for extract_exif()."""

    def test_non_image_returns_empty(self):
        """Non-image files should return empty dict."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"hello world")
            f.flush()
            try:
                result = extract_exif(f.name)
                assert result == {}, f"Expected empty dict for .txt, got {result}"
            finally:
                os.unlink(f.name)

    def test_missing_file_returns_empty(self):
        """Non-existent files should return empty dict."""
        result = extract_exif("/nonexistent/path/file.jpg")
        assert result == {}, f"Expected empty dict for missing file, got {result}"

    def test_real_image_has_exif(self):
        """Test with a real image that has EXIF data."""
        if not os.path.exists(REAL_IMAGE):
            pytest.skip(f"Real test image not available: {REAL_IMAGE}")

        result = extract_exif(REAL_IMAGE)
        assert isinstance(result, dict)
        # Real phone photos should have at least width/height
        assert "width" in result, f"Expected width in EXIF, got keys: {list(result.keys())}"
        assert "height" in result, f"Expected height in EXIF, got keys: {list(result.keys())}"
        # Most phone photos have datetime_original
        assert "datetime_original" in result or "datetime" in result, \
            f"Expected datetime in EXIF, got keys: {list(result.keys())}"

    def test_real_image_dimensions(self):
        """Verify width/height are positive integers."""
        if not os.path.exists(REAL_IMAGE):
            pytest.skip(f"Real test image not available: {REAL_IMAGE}")

        result = extract_exif(REAL_IMAGE)
        if "width" in result:
            assert result["width"] > 0, f"Width should be positive, got {result['width']}"
        if "height" in result:
            assert result["height"] > 0, f"Height should be positive, got {result['height']}"

    def test_real_image_gps(self):
        """Verify GPS coordinates are reasonable if present."""
        if not os.path.exists(REAL_IMAGE):
            pytest.skip(f"Real test image not available: {REAL_IMAGE}")

        result = extract_exif(REAL_IMAGE)
        if "gps_lat" in result and "gps_lon" in result:
            lat = result["gps_lat"]
            lon = result["gps_lon"]
            assert -90 <= lat <= 90, f"Latitude out of range: {lat}"
            assert -180 <= lon <= 180, f"Longitude out of range: {lon}"


class TestFormatExifCompact:
    """Tests for format_exif_compact()."""

    def test_empty_dict_returns_empty(self):
        assert format_exif_compact({}) == ""

    def test_camera_only(self):
        result = format_exif_compact({"make": "Canon", "model": "EOS R6"})
        assert "Canon" in result
        assert "EOS R6" in result
        assert result.startswith("[EXIF:")
        assert result.endswith("]")

    def test_with_gps(self):
        result = format_exif_compact({
            "gps_lat": 35.6762,
            "gps_lon": 139.6503,
        })
        assert "35.68°N" in result
        assert "139.65°E" in result

    def test_with_dimensions(self):
        result = format_exif_compact({"width": 5472, "height": 3648})
        assert "5472x3648" in result

    def test_with_datetime(self):
        result = format_exif_compact({"datetime_original": "2024:06:15 08:17:42"})
        assert "2024-06-15" in result

    def test_all_fields(self):
        result = format_exif_compact({
            "make": "Xiaomi",
            "model": "Redmi K40",
            "datetime_original": "2024:06:15 08:17:42",
            "gps_lat": 32.04,
            "gps_lon": 120.78,
            "width": 4624,
            "height": 3472,
        })
        assert "Xiaomi Redmi K40" in result
        assert "2024-06-15" in result
        assert "32.04°N" in result
        assert "120.78°E" in result
        assert "4624x3472" in result
        assert result.startswith("[EXIF:")
        assert result.endswith("]")

    def test_negative_gps(self):
        result = format_exif_compact({"gps_lat": -33.87, "gps_lon": -151.21})
        assert "33.87°S" in result
        assert "151.21°W" in result

    def test_skips_empty_make(self):
        result = format_exif_compact({"make": "", "model": "", "width": 100, "height": 200})
        assert "100x200" in result
        # Should not have leading comma from empty make+model
        assert not result.startswith("[EXIF: ,")


class TestDmsToDecimal:
    """Tests for GPS DMS-to-decimal conversion."""

    def test_north_hemisphere(self):
        # Tokyo: 35°41'22" N
        dms = ((35, 1), (41, 1), (22, 1))
        result = _dms_to_decimal(dms, "N")
        assert abs(result - 35.689444) < 0.001

    def test_south_hemisphere(self):
        # Sydney: -33.87°
        dms = ((33, 1), (52, 1), (12, 1))
        result = _dms_to_decimal(dms, "S")
        assert result < 0
        assert abs(result - (-33.87)) < 0.01

    def test_east_hemisphere(self):
        dms = ((139, 1), (39, 1), (0, 1))
        result = _dms_to_decimal(dms, "E")
        assert result > 0
        assert abs(result - 139.65) < 0.01

    def test_west_hemisphere(self):
        dms = ((120, 1), (46, 1), (48, 1))
        result = _dms_to_decimal(dms, "W")
        assert result < 0

    def test_zero_degrees(self):
        dms = ((0, 1), (0, 1), (0, 1))
        result = _dms_to_decimal(dms, "N")
        assert result == 0.0

    def test_fractional_values(self):
        # EXIF often stores as fractions like 4624/1
        dms = ((35, 1), (40, 1), (12345, 1000))
        result = _dms_to_decimal(dms, "N")
        assert abs(result - 35.6704) < 0.001