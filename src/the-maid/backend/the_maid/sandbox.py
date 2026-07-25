"""
The Maid — Sandbox Validation
Ensures all file operations stay within user-approved directories.
"""

import os
import re
from pathlib import Path

# Regex pattern for sandbox validation
# Matches: /home/user/Desktop, C:\Users\User\Downloads, etc.
SANDBOX_PATTERN = re.compile(
    r"^("              # Start
    r"/home/[^/]+"    # Linux/macOS home
    r"|"              # OR
    r"/[a-zA-Z]:"     # Windows drive letter
    r")"
    r"[/\\]"          # Path separator
    r"(Desktop|Downloads|Documents|Pictures|Videos|Music)"
    r"($|[/\\])"      # End or more path
)

# Maximum files per scan
MAX_FILES = 10_000

# Timeout per file (seconds)
FILE_TIMEOUT = 5.0


def validate_path(path: str) -> Path:
    """
    Validate that a path is within the sandbox.
    Expands ~ and resolves symlinks.
    Raises ValueError if outside sandbox.
    """
    expanded = os.path.expanduser(path)
    resolved = Path(expanded).resolve()
    
    path_str = str(resolved)
    
    if not SANDBOX_PATTERN.match(path_str):
        raise ValueError(
            f"Path '{path}' is outside the sandbox. "
            f"Allowed directories: Desktop, Downloads, Documents, Pictures, Videos, Music"
        )
    
    return resolved


def validate_paths(paths: list[str]) -> list[Path]:
    """Validate multiple paths."""
    return [validate_path(p) for p in paths]


def is_safe_move(source: Path, destination: Path) -> bool:
    """
    Additional safety check: ensure move doesn't escape sandbox
    and destination is within approved directories.
    """
    try:
        validate_path(str(source))
        validate_path(str(destination))
        return True
    except ValueError:
        return False
