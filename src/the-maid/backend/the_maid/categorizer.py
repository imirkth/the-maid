"""
The Maid — Rule-Based File Categorizer (LLM Routing Stub)
Maps scanned files to buckets with rationale. Placeholder for future LLM integration.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
from .cleanup_plan import CleanupPlan, CleanupItem, generate_file_id

# Default extension → bucket mapping
DEFAULT_RULES: Dict[str, Dict[str, Any]] = {
    # Images
    ".jpg":   {"bucket": "Pictures",  "tags": ["image"],       "confidence": 0.95, "rationale": "Image file — moved to Pictures"},
    ".jpeg":  {"bucket": "Pictures",  "tags": ["image"],       "confidence": 0.95, "rationale": "Image file — moved to Pictures"},
    ".png":   {"bucket": "Pictures",  "tags": ["image"],       "confidence": 0.95, "rationale": "Image file — moved to Pictures"},
    ".gif":   {"bucket": "Pictures",  "tags": ["image"],       "confidence": 0.95, "rationale": "Image file — moved to Pictures"},
    ".bmp":   {"bucket": "Pictures",  "tags": ["image"],       "confidence": 0.95, "rationale": "Image file — moved to Pictures"},
    ".webp":  {"bucket": "Pictures",  "tags": ["image"],       "confidence": 0.95, "rationale": "Image file — moved to Pictures"},
    ".svg":   {"bucket": "Pictures",  "tags": ["image", "vector"], "confidence": 0.90, "rationale": "Vector image — moved to Pictures"},
    ".heic":  {"bucket": "Pictures",  "tags": ["image"],       "confidence": 0.95, "rationale": "Image file — moved to Pictures"},
    ".raw":   {"bucket": "Pictures",  "tags": ["image", "raw"], "confidence": 0.90, "rationale": "RAW image — moved to Pictures"},
    # Videos
    ".mp4":   {"bucket": "Videos",    "tags": ["video"],       "confidence": 0.95, "rationale": "Video file — moved to Videos"},
    ".mov":   {"bucket": "Videos",    "tags": ["video"],       "confidence": 0.95, "rationale": "Video file — moved to Videos"},
    ".avi":   {"bucket": "Videos",    "tags": ["video"],       "confidence": 0.95, "rationale": "Video file — moved to Videos"},
    ".mkv":   {"bucket": "Videos",    "tags": ["video"],       "confidence": 0.95, "rationale": "Video file — moved to Videos"},
    ".wmv":   {"bucket": "Videos",    "tags": ["video"],       "confidence": 0.90, "rationale": "Video file — moved to Videos"},
    # Audio
    ".mp3":   {"bucket": "Music",     "tags": ["audio"],       "confidence": 0.95, "rationale": "Audio file — moved to Music"},
    ".wav":   {"bucket": "Music",     "tags": ["audio"],       "confidence": 0.95, "rationale": "Audio file — moved to Music"},
    ".flac":  {"bucket": "Music",     "tags": ["audio", "lossless"], "confidence": 0.95, "rationale": "Lossless audio — moved to Music"},
    ".aac":   {"bucket": "Music",     "tags": ["audio"],       "confidence": 0.95, "rationale": "Audio file — moved to Music"},
    # Documents
    ".pdf":   {"bucket": "Documents", "tags": ["document"],    "confidence": 0.95, "rationale": "PDF document — moved to Documents"},
    ".doc":   {"bucket": "Documents", "tags": ["document"],    "confidence": 0.90, "rationale": "Word document — moved to Documents"},
    ".docx":  {"bucket": "Documents", "tags": ["document"],    "confidence": 0.95, "rationale": "Word document — moved to Documents"},
    ".xls":   {"bucket": "Documents", "tags": ["spreadsheet"], "confidence": 0.90, "rationale": "Spreadsheet — moved to Documents"},
    ".xlsx":  {"bucket": "Documents", "tags": ["spreadsheet"], "confidence": 0.95, "rationale": "Spreadsheet — moved to Documents"},
    ".ppt":   {"bucket": "Documents", "tags": ["presentation"], "confidence": 0.90, "rationale": "Presentation — moved to Documents"},
    ".pptx":  {"bucket": "Documents", "tags": ["presentation"], "confidence": 0.95, "rationale": "Presentation — moved to Documents"},
    ".txt":   {"bucket": "Documents", "tags": ["text"],        "confidence": 0.80, "rationale": "Text file — moved to Documents"},
    ".md":    {"bucket": "Documents", "tags": ["text", "markdown"], "confidence": 0.80, "rationale": "Markdown file — moved to Documents"},
    ".csv":   {"bucket": "Documents", "tags": ["data", "csv"], "confidence": 0.85, "rationale": "CSV data file — moved to Documents"},
    ".rtf":   {"bucket": "Documents", "tags": ["document"],    "confidence": 0.85, "rationale": "Rich text document — moved to Documents"},
    # Archives
    ".zip":   {"bucket": "Archives",  "tags": ["archive"],      "confidence": 0.90, "rationale": "Archive file — moved to Archives"},
    ".tar":   {"bucket": "Archives",  "tags": ["archive"],      "confidence": 0.90, "rationale": "Archive file — moved to Archives"},
    ".gz":    {"bucket": "Archives",  "tags": ["archive"],      "confidence": 0.85, "rationale": "Compressed archive — moved to Archives"},
    ".7z":    {"bucket": "Archives",  "tags": ["archive"],      "confidence": 0.90, "rationale": "Archive file — moved to Archives"},
    ".rar":   {"bucket": "Archives",  "tags": ["archive"],      "confidence": 0.90, "rationale": "Archive file — moved to Archives"},
    # Code
    ".py":    {"bucket": "Code",      "tags": ["python"],      "confidence": 0.90, "rationale": "Python source file — moved to Code"},
    ".js":    {"bucket": "Code",      "tags": ["javascript"],  "confidence": 0.90, "rationale": "JavaScript file — moved to Code"},
    ".ts":    {"bucket": "Code",      "tags": ["typescript"],  "confidence": 0.90, "rationale": "TypeScript file — moved to Code"},
    ".rs":    {"bucket": "Code",      "tags": ["rust"],         "confidence": 0.90, "rationale": "Rust source file — moved to Code"},
    ".html":  {"bucket": "Code",      "tags": ["web"],          "confidence": 0.75, "rationale": "HTML file — moved to Code"},
    ".css":   {"bucket": "Code",      "tags": ["web"],          "confidence": 0.75, "rationale": "CSS file — moved to Code"},
    ".json":  {"bucket": "Code",      "tags": ["config"],      "confidence": 0.60, "rationale": "JSON file — moved to Code"},
    ".xml":   {"bucket": "Code",      "tags": ["config"],      "confidence": 0.60, "rationale": "XML file — moved to Code"},
    ".yaml":  {"bucket": "Code",      "tags": ["config"],      "confidence": 0.60, "rationale": "YAML config — moved to Code"},
    ".yml":   {"bucket": "Code",      "tags": ["config"],      "confidence": 0.60, "rationale": "YAML config — moved to Code"},
}

# Extensions with ambiguous categorization → lower confidence
AMBIGUOUS_EXTENSIONS = {".json", ".xml", ".yaml", ".yml", ".html", ".css"}


def categorize(scan_results: List[Dict[str, Any]],
               buckets: Optional[List[Dict[str, str]]] = None,
               rules: Optional[Dict[str, Dict[str, Any]]] = None) -> CleanupPlan:
    """
    Map scan results to a CleanupPlan using rule-based categorization.

    Args:
        scan_results: List of file metadata dicts from scanner.scan_directory()
        buckets: List of {name, path} dicts defining destination folders.
                 If None, uses default bucket paths under home directory.
        rules: Custom extension→bucket rules. If None, uses DEFAULT_RULES.

    Returns:
        CleanupPlan with proposed move actions and rationale for each file.
    """
    rules = rules or DEFAULT_RULES
    bucket_map = _resolve_buckets(buckets)

    items = []
    for f in scan_results:
        ext = f.get("extension", "").lower()
        rule = rules.get(ext)

        if rule:
            bucket_name = rule["bucket"]
            bucket_path = bucket_map.get(bucket_name)
            if bucket_path:
                proposed_path = str(Path(bucket_path) / f["filename"])
                items.append(CleanupItem(
                    file_id=f["file_id"],
                    original_filename=f["filename"],
                    current_path=f["path"],
                    proposed_action="move",
                    proposed_path=proposed_path,
                    proposed_tags=list(rule.get("tags", [])),
                    faces_detected=[],
                    rationale=rule["rationale"],
                    confidence=rule["confidence"],
                ))
            else:
                # Rule exists but no bucket configured — tag only
                items.append(_tag_only_item(f, f"No bucket configured for {bucket_name}"))
        else:
            # Unknown extension — tag only, low confidence
            items.append(_tag_only_item(f, "Unknown file type — no move proposed"))

    return CleanupPlan(items=items)


def _tag_only_item(f: Dict[str, Any], rationale: str) -> CleanupItem:
    """Create a tag-only item (no move) for files we can't categorize."""
    return CleanupItem(
        file_id=f["file_id"],
        original_filename=f["filename"],
        current_path=f["path"],
        proposed_action="tag",
        proposed_path=f["path"],  # same path for tag-only
        proposed_tags=[],
        faces_detected=[],
        rationale=rationale,
        confidence=0.0,
    )


def _resolve_buckets(buckets: Optional[List[Dict[str, str]]]) -> Dict[str, str]:
    """
    Resolve bucket definitions to {name: absolute_path}.
    If None, use default paths under user's home directory.
    """
    if buckets is None:
        home = str(Path.home())
        return {
            "Pictures":  str(Path(home) / "Pictures"),
            "Videos":    str(Path(home) / "Videos"),
            "Music":     str(Path(home) / "Music"),
            "Documents": str(Path(home) / "Documents"),
            "Archives":  str(Path(home) / "Downloads" / "Archives"),
            "Code":      str(Path(home) / "Documents" / "Code"),
        }

    return {b["name"]: b["path"] for b in buckets}