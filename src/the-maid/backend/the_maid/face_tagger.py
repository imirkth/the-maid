"""
The Maid — Face Tag Writer (Slice 6C)
Writes XMP:PersonInImage tags to photos via ExifTool.
Retroactive: naming a cluster writes to ALL photos in that cluster.
"""

import subprocess
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional

from .face_cluster import FaceClusterer


MAX_LABEL_LENGTH = 100


def _exiftool_available() -> bool:
    """Check if exiftool binary is on PATH."""
    return shutil.which("exiftool") is not None


def _write_xmp_tag(file_path: str, tag_name: str, tag_value: str) -> bool:
    """
    Write a single XMP tag to a file using exiftool.
    tag_name should be the full qualified tag, e.g. "XMP:PersonInImage".
    Returns True on success, False on failure.
    """
    if not _exiftool_available():
        return False

    if not _file_exists(file_path):
        return False

    try:
        result = subprocess.run(
            ["exiftool", "-overwrite_original",
             f"-XMP:{tag_name}={tag_value}", file_path],
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _clear_xmp_tag(file_path: str, tag_name: str = "PersonInImage") -> bool:
    """Clear a single XMP tag from a file."""
    if not _exiftool_available():
        return False
    if not _file_exists(file_path):
        return False
    try:
        result = subprocess.run(
            ["exiftool", "-overwrite_original",
             f"-XMP:{tag_name}=", file_path],
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _file_exists(file_path: str) -> bool:
    """Check if file exists. Separated for mocking."""
    return Path(file_path).exists()


def _sanitize_label(label: str) -> str:
    """
    Strip leading/trailing whitespace and clamp label length.
    Returns empty string if label is only whitespace.
    """
    cleaned = label.strip()
    if not cleaned:
        return ""
    return cleaned[:MAX_LABEL_LENGTH]


def rename_cluster_with_tags(
    clusterer: FaceClusterer,
    cluster_id: int,
    new_label: str,
    sandbox_folders: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Rename a cluster AND write XMP:PersonInImage to all photos in that cluster.

    Args:
        clusterer: FaceClusterer instance with data.
        cluster_id: The cluster to rename.
        new_label: The human name (e.g., "Sarah").
        sandbox_folders: If provided, skip files outside sandbox.

    Returns: {renamed: int, tagged: int, skipped: int, errors: [str]}
    """
    from .sandbox import validate_path

    sanitized = _sanitize_label(new_label)
    if not sanitized:
        return {"renamed": 0, "tagged": 0, "skipped": 0, "errors": ["Cluster label cannot be empty"], "success": False}

    # Update SQLite label
    renamed_count = clusterer.rename_cluster(cluster_id, sanitized)

    # Get all file paths in this cluster
    clusters = clusterer.get_clusters()
    target = None
    for c in clusters:
        if c["cluster_id"] == cluster_id:
            target = c
            break

    if target is None:
        return {"renamed": 0, "tagged": 0, "skipped": 0, "errors": ["Cluster not found"], "success": False}

    tagged = 0
    skipped = 0
    errors: List[str] = []

    for face in target["faces"]:
        file_path = face["file_path"]

        # Sandbox check
        if sandbox_folders is not None:
            try:
                validate_path(file_path, sandbox_folders)
            except ValueError:
                skipped += 1
                errors.append(f"Outside sandbox: {file_path}")
                continue

        if _write_xmp_tag(file_path, "XMP:PersonInImage", sanitized):
            tagged += 1
        else:
            skipped += 1
            if not _exiftool_available():
                errors.append("exiftool not installed")
            elif not Path(file_path).exists():
                errors.append(f"File not found: {file_path}")
            else:
                errors.append(f"exiftool failed: {file_path}")

    return {
        "renamed": renamed_count,
        "tagged": tagged,
        "skipped": skipped,
        "errors": errors,
        "success": tagged > 0 or len(target["faces"]) == 0,
    }


def get_clusters_for_ui(
    clusterer: FaceClusterer,
    sandbox_folders: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Get cluster data formatted for the UI.
    Includes representative face (first face) per cluster.
    Filters out files outside sandbox if provided.
    """
    from .sandbox import validate_path

    clusters = clusterer.get_clusters()
    result = []

    for c in clusters:
        faces = c["faces"]
        if sandbox_folders is not None:
            faces = [
                f for f in faces
                if _path_in_sandbox(f["file_path"], sandbox_folders)
            ]

        if not faces:
            continue

        # ponytail: representative face = first face's file path
        rep = faces[0]
        result.append({
            "cluster_id": c["cluster_id"],
            "cluster_label": c["cluster_label"],
            "face_count": len(faces),
            "representative_path": rep["file_path"],
            "faces": [{"file_id": f["file_id"], "file_path": f["file_path"]}
                      for f in faces],
        })

    return result


def _path_in_sandbox(path: str, sandbox_folders: Optional[List[str]] = None) -> bool:
    """Check if a path is within sandbox without raising."""
    from .sandbox import validate_path
    try:
        validate_path(path, sandbox_folders if sandbox_folders else None)
        return True
    except ValueError:
        return False
