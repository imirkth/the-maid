"""Tests for sandbox validation."""
import pytest
from pathlib import Path
from the_maid.sandbox import validate_path, is_safe_move

def test_valid_linux_paths():
    """Linux/macOS home directory paths should pass."""
    # These would pass on a real system with the user's home
    # For testing, we check the regex matches
    from the_maid.sandbox import SANDBOX_PATTERN
    
    valid = [
        "/home/user/Desktop",
        "/home/user/Downloads/file.txt",
        "/home/user/Documents/Work",
        "/home/user/Pictures/Vacation",
    ]
    
    for path in valid:
        assert SANDBOX_PATTERN.match(path), f"Should match: {path}"

def test_invalid_paths():
    """System paths should be rejected."""
    from the_maid.sandbox import SANDBOX_PATTERN
    
    invalid = [
        "/bin/bash",
        "/etc/passwd",
        "/usr/local/bin",
        "/var/log",
        "/opt/apps",
        "/home/user/.ssh",
        "/home/user/random_folder",
    ]
    
    for path in invalid:
        assert not SANDBOX_PATTERN.match(path), f"Should NOT match: {path}"

def test_windows_paths():
    """Windows paths should be validated."""
    from the_maid.sandbox import SANDBOX_PATTERN
    
    valid = [
        "/C:/Users/John/Desktop",
        "/C:/Users/John/Downloads",
        "/D:/Users/Jane/Pictures",
    ]
    
    for path in valid:
        assert SANDBOX_PATTERN.match(path), f"Should match: {path}"
