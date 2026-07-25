"""
The Maid — Sandbox Validation
Ensures all file operations stay within user-approved directories.
Hard-rejects system directories. No regex — just path containment.
"""

import os
from pathlib import Path

# System directories that are always out of scope
SYSTEM_DIRS = {
    "/bin", "/sbin", "/usr", "/etc", "/var", "/opt", "/lib", "/lib64",
    "/boot", "/dev", "/proc", "/sys", "/run", "/srv", "/root",
    "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
    "C:\\ProgramData", "C:\\System Volume Information",
    "C:\\$Recycle.Bin",
}

# Default sandbox folders (relative to home)
DEFAULT_SANDBOX_FOLDERS = ["Desktop", "Downloads", "Documents", "Pictures"]

# Maximum files per scan
MAX_FILES = 10_000


# Timeout per file (seconds)
FILE_TIMEOUT = 5.0


def _normalize(path: Path) -> str:
    """Resolve symlinks and normalize for comparison."""
    try:
        return str(path.resolve())
    except (OSError, RuntimeError):
        return str(path)


def _is_system_path(path: Path) -> bool:
    """Check if path is inside a system directory."""
    resolved = str(path.resolve()).replace('\\', '/')
    raw = str(path).replace('\\', '/')
    for sys_dir in SYSTEM_DIRS:
        sys_dir_norm = sys_dir.replace('\\', '/')
        if resolved.startswith(sys_dir_norm) or raw.startswith(sys_dir_norm):
            return True
    return False


def validate_path(path: str, sandbox_folders: list[str] | None = None) -> Path:
    """
    Validate that a path is within the sandbox.
    Expands ~ and resolves symlinks.
    Hard-rejects system directories.
    Raises ValueError if outside sandbox or in system dir.
    """
    expanded = os.path.expanduser(path)

    # Check raw input for Windows-style system paths before resolving
    # (Linux resolve() mangles Windows paths)
    raw_norm = expanded.replace('\\', '/')
    for sys_dir in SYSTEM_DIRS:
        sys_dir_norm = sys_dir.replace('\\', '/')
        if raw_norm.startswith(sys_dir_norm):
            raise ValueError(f"System directories are out of scope: '{path}'")

    resolved = Path(expanded).resolve()

    # Hard reject system paths
    if _is_system_path(resolved):
        raise ValueError(f"System directories are out of scope: '{path}'")

    # If sandbox_folders provided, check containment against them
    if sandbox_folders is not None:
        home = Path.home()
        allowed = [_normalize(home / f) for f in sandbox_folders]
        resolved_str = _normalize(resolved)
        for allowed_path in allowed:
            if resolved_str == allowed_path or resolved_str.startswith(allowed_path + os.sep):
                return resolved
        raise ValueError(
            f"Path '{path}' is outside the sandbox. "
            f"Allowed: {', '.join(sandbox_folders)}"
        )

    # No sandbox list = just reject system paths
    return resolved


def validate_paths(paths: list[str], sandbox_folders: list[str] | None = None) -> list[Path]:
    """Validate multiple paths."""
    return [validate_path(p, sandbox_folders) for p in paths]


def is_safe_move(source: Path, destination: Path, sandbox_folders: list[str] | None = None) -> bool:
    """Ensure move doesn't escape sandbox and destination is within approved directories."""
    try:
        validate_path(str(source), sandbox_folders)
        validate_path(str(destination), sandbox_folders)
        return True
    except ValueError:
        return False
