"""
The Maid — File Scanner
Recursive directory walk with metadata extraction.
Emits progress events as JSON stdout lines for Tauri event forwarding.
"""

import os
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime

from .sandbox import validate_path, MAX_FILES


# Folders of tool-generated files (libraries, caches, VCS data). Each is listed
# as ONE entry instead of thousands of files, so it doesn't eat the scan limit,
# and it moves as a whole with the project that holds it.
BUNDLE_DIR_NAMES = {
    "node_modules", "site-packages", "dist-packages", "__pycache__", ".git", ".hg", ".svn",
    ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".gradle", ".ipynb_checkpoints",
    "venv", ".venv", "virtualenv",
}

# Lock / system files that aren't documents: never listed.
JUNK_FILE_NAMES = {".ds_store", "thumbs.db", "desktop.ini", "ehthumbs.db"}


def is_junk_file(name: str) -> bool:
    low = name.lower()
    return (low in JUNK_FILE_NAMES or name.startswith("~$")          # Office owner/lock file
            or name.startswith(".~lock.") or low.startswith("._"))  # LibreOffice lock, macOS resource fork


def is_bundle_dir(path: Path) -> bool:
    """A virtualenv, conda env, dependency or cache folder (whatever it is called)."""
    if path.name.lower() in BUNDLE_DIR_NAMES:
        return True
    try:
        return (path / "pyvenv.cfg").is_file() or (path / "conda-meta").is_dir()
    except OSError:
        return False


def _count_files(path: Path) -> tuple:
    """(file count, total bytes) under a folder, without following links."""
    count = size = 0
    stack = [str(path)]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            count += 1
                            size += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return count, size


class FileScanner:
    """Scans directories and extracts file metadata."""

    def __init__(self, max_files: int = MAX_FILES, progress_callback: Optional[Callable] = None):
        self.max_files = max_files
        self.scanned_count = 0
        self.errors: List[str] = []
        self._progress_callback = progress_callback

    def scan_directory(self, directory: str, sandbox_folders: list[str] | None = None) -> List[Dict[str, Any]]:
        """
        Recursively scan a directory and return file metadata.
        Respects sandbox boundaries. Skips symlinks pointing outside sandbox.
        """
        root = validate_path(directory, sandbox_folders)
        results = []

        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            # Skip symlinked dirs that point outside sandbox
            dirnames[:] = [
                d for d in dirnames
                if self._is_safe_dir(Path(dirpath) / d, sandbox_folders)
            ]
            # Library / cache folders count as one entry and are not walked into
            bundles = [d for d in dirnames if is_bundle_dir(Path(dirpath) / d)]
            dirnames[:] = [d for d in dirnames if d not in bundles]
            for d in bundles:
                if self.scanned_count >= self.max_files:
                    break
                try:
                    results.append(self._bundle_metadata(Path(dirpath) / d))
                    self.scanned_count += 1
                except (PermissionError, OSError) as e:
                    self.errors.append(f"Error scanning {Path(dirpath) / d}: {e}")

            for filename in filenames:
                if is_junk_file(filename):
                    continue
                if self.scanned_count >= self.max_files:
                    self.errors.append(f"Reached max file limit ({self.max_files})")
                    break

                file_path = Path(dirpath) / filename

                # Skip symlinks pointing outside the sandbox
                if file_path.is_symlink():
                    try:
                        target = file_path.resolve()
                        validate_path(str(target), sandbox_folders)
                    except (OSError, RuntimeError, ValueError):
                        continue  # skip symlinks escaping sandbox or broken

                try:
                    metadata = self._extract_metadata(file_path)
                    results.append(metadata)
                    self.scanned_count += 1
                except (PermissionError, OSError) as e:
                    self.errors.append(f"Error scanning {file_path}: {e}")

                # Emit progress every 100 files
                if self._progress_callback and self.scanned_count % 100 == 0:
                    self._progress_callback(self.scanned_count)
                if self.scanned_count % 100 == 0:
                    emit_progress(self.scanned_count, self.max_files)

            if self.scanned_count >= self.max_files:
                break

        if self._progress_callback:
            self._progress_callback(self.scanned_count)
        emit_complete(self.scanned_count)

        return results

    def _is_safe_dir(self, path: Path, sandbox_folders: list[str] | None) -> bool:
        """Check if a directory is safe to enter (not a symlink escaping sandbox)."""
        if not path.is_symlink():
            return True
        try:
            target = path.resolve()
            validate_path(str(target), sandbox_folders)
            return True
        except ValueError:
            return False

    def _extract_metadata(self, file_path: Path) -> Dict[str, Any]:
        """Extract basic metadata from a file."""
        stat = file_path.stat()

        return {
            "file_id": self._generate_id(str(file_path)),
            "filename": file_path.name,
            "path": str(file_path),
            "size_bytes": stat.st_size,
            "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "extension": file_path.suffix.lower(),
            "mime_type": self._guess_mime(file_path),
        }

    def _bundle_metadata(self, dir_path: Path) -> Dict[str, Any]:
        stat = dir_path.stat()
        count, size = _count_files(dir_path)
        return {
            "file_id": self._generate_id(str(dir_path)),
            "filename": dir_path.name,
            "path": str(dir_path),
            "size_bytes": size,
            "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "extension": "",
            "mime_type": "inode/directory",
            "is_folder": True,          # moved as a whole
            "file_count": count,
        }

    def _generate_id(self, path_str: str) -> str:
        """Generate 8-char hex ID from path (ADR 0009)."""
        return hashlib.sha256(path_str.encode()).hexdigest()[:8]

    def _guess_mime(self, file_path: Path) -> str:
        """Guess MIME type from extension."""
        ext_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".csv": "text/csv",
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".avi": "video/x-msvideo",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".zip": "application/zip",
            ".tar": "application/x-tar",
            ".gz": "application/gzip",
        }
        return ext_map.get(file_path.suffix.lower(), "application/octet-stream")


def emit_progress(count: int, max_files: int) -> None:
    """Print progress as JSON stdout line for Tauri event forwarding."""
    progress = min(count / max_files, 1.0) if max_files > 0 else 0.0
    print(json.dumps({"event": "scan_progress", "count": count, "progress": progress}), flush=True)


def emit_complete(count: int) -> None:
    """Print completion as JSON stdout line."""
    print(json.dumps({"event": "scan_complete", "count": count}), flush=True)
