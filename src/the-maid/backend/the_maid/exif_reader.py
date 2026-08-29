"""
The Maid — EXIF Reader Module
Reads key EXIF fields from image files using PIL (already installed via insightface).
No new dependencies. Uses PIL's _getexif() for reading.
"""

from pathlib import Path
from typing import Dict, Any

# Image extensions that may contain EXIF
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif"}

# EXIF tag IDs we care about
_EXIF_TAGS = {
    0x010F: "make",        # Camera manufacturer
    0x0110: "model",       # Camera model
    0x0132: "datetime",    # DateTime (modification)
    0x9003: "datetime_original",  # DateTimeOriginal
    0x011A: "x_resolution",
    0x011B: "y_resolution",
    0x0112: "orientation",
    0x0131: "software",
    0x0100: "image_width",
    0x0101: "image_height",
}

# GPS IFD pointer
_GPS_IFD_POINTER = 0x8825
# GPS sub-tags
_GPS_LATITUDE_REF = 0x0001
_GPS_LATITUDE = 0x0002
_GPS_LONGITUDE_REF = 0x0003
_GPS_LONGITUDE = 0x0004


def _dms_to_decimal(dms: tuple, ref: str) -> float:
    """Convert EXIF DMS rational values to decimal degrees.
    dms is ((deg_num, deg_den), (min_num, min_den), (sec_num, sec_den)).
    ref is 'N', 'S', 'E', or 'W'.
    """
    def _ratio(val):
        if isinstance(val, tuple) and len(val) == 2 and val[1] != 0:
            return val[0] / val[1]
        return float(val) if val else 0.0

    degrees = _ratio(dms[0]) if len(dms) > 0 else 0.0
    minutes = _ratio(dms[1]) if len(dms) > 1 else 0.0
    seconds = _ratio(dms[2]) if len(dms) > 2 else 0.0

    decimal = degrees + minutes / 60.0 + seconds / 3600.0
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


def extract_exif(file_path: str) -> Dict[str, Any]:
    """Extract key EXIF fields from an image file.

    Returns a dict with keys: make, model, datetime_original, gps_lat,
    gps_lon, width, height, orientation, software.
    For non-image files or files without EXIF, returns empty dict.
    """
    p = Path(file_path)
    if p.suffix.lower() not in IMAGE_EXTENSIONS:
        return {}

    try:
        from PIL import Image
    except ImportError:
        return {}

    try:
        img = Image.open(file_path)
    except Exception:
        return {}

    # Get image dimensions from PIL directly (always available)
    result: Dict[str, Any] = {}
    result["width"] = img.width
    result["height"] = img.height

    # Try to get EXIF data
    exif_data = getattr(img, "_getexif", lambda: None)()
    if not exif_data:
        # No EXIF, but we still have dimensions
        return result

    # Map known tags
    for tag_id, key in _EXIF_TAGS.items():
        if tag_id in exif_data:
            val = exif_data[tag_id]
            # Don't overwrite width/height from EXIF if PIL already gave us good values
            if key in ("image_width", "image_height"):
                continue
            result[key] = val

    # Use datetime_original if available, fall back to datetime
    if "datetime_original" not in result and "datetime" in result:
        result["datetime_original"] = result.pop("datetime")

    # Parse GPS
    gps_ifd = exif_data.get(_GPS_IFD_POINTER)
    if gps_ifd:
        try:
            lat_ref = gps_ifd.get(_GPS_LATITUDE_REF, "N")
            lat_dms = gps_ifd.get(_GPS_LATITUDE)
            lon_ref = gps_ifd.get(_GPS_LONGITUDE_REF, "E")
            lon_dms = gps_ifd.get(_GPS_LONGITUDE)

            if lat_dms and lon_dms:
                result["gps_lat"] = round(_dms_to_decimal(lat_dms, lat_ref), 6)
                result["gps_lon"] = round(_dms_to_decimal(lon_dms, lon_ref), 6)
        except Exception:
            pass  # ponytail: bad GPS data is common, just skip it

    return result


def format_exif_compact(exif: Dict[str, Any]) -> str:
    """Format EXIF dict as a compact one-line string for LLM prompts.
    Returns empty string if no meaningful data.
    """
    if not exif:
        return ""

    parts = []

    # Camera make + model
    make = exif.get("make", "").strip() if isinstance(exif.get("make"), str) else ""
    model = exif.get("model", "").strip() if isinstance(exif.get("model"), str) else ""
    camera = " ".join(filter(None, [make, model])).strip()
    if camera:
        parts.append(camera)

    # Date taken
    dt = exif.get("datetime_original", "")
    if dt:
        # EXIF datetime format: "YYYY:MM:DD HH:MM:SS" → normalize to "YYYY-MM-DD"
        if isinstance(dt, str) and ":" in dt[:5]:
            dt = dt.replace(":", "-", 2).split()[0]
        parts.append(dt)

    # GPS
    lat = exif.get("gps_lat")
    lon = exif.get("gps_lon")
    if lat is not None and lon is not None:
        parts.append(f"GPS: {lat:.2f}°{'N' if lat >= 0 else 'S'} {lon:.2f}°{'E' if lon >= 0 else 'W'}")

    # Dimensions
    w = exif.get("width")
    h = exif.get("height")
    if w and h:
        parts.append(f"{w}x{h}")

    if not parts:
        return ""

    return "[EXIF: " + ", ".join(parts) + "]"