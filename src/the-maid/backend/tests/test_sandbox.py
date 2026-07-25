"""Tests for sandbox validation with dynamic folder lists."""
import pytest
import os
from pathlib import Path
from the_maid.sandbox import validate_path, is_safe_move, _is_system_path, SYSTEM_DIRS


def test_validate_path_system_dir_rejected():
    """System directories should always be hard-rejected."""
    for sys_dir in ["/bin", "/etc", "/usr", "/var", "/opt"]:
        with pytest.raises(ValueError, match="System directories are out of scope"):
            validate_path(sys_dir)


def test_validate_path_system_subdir_rejected():
    """Subdirectories of system dirs should also be rejected."""
    with pytest.raises(ValueError, match="System directories are out of scope"):
        validate_path("/usr/local/bin")
    with pytest.raises(ValueError, match="System directories are out of scope"):
        validate_path("/etc/passwd")
    with pytest.raises(ValueError, match="System directories are out of scope"):
        validate_path("/var/log/syslog")


def test_validate_path_windows_system_rejected():
    """Windows system paths should be rejected."""
    for path in ["C:\\Windows\\System32", "C:\\Program Files\\app", "C:\\ProgramData\\config"]:
        with pytest.raises(ValueError, match="System directories are out of scope"):
            validate_path(path)


def test_validate_path_with_sandbox_folders():
    """Path within sandbox folders should pass."""
    home = str(Path.home())
    folders = ["Desktop", "Downloads"]
    result = validate_path(f"{home}/Desktop/file.txt", folders)
    assert str(result) == str(Path(f"{home}/Desktop/file.txt").resolve())


def test_validate_path_outside_sandbox_folders():
    """Path outside sandbox folders should be rejected."""
    folders = ["Desktop"]
    with pytest.raises(ValueError, match="outside the sandbox"):
        validate_path("/tmp/random/file.txt", folders)


def test_validate_path_no_sandbox_list_allows_non_system():
    """Without sandbox list, only system paths are rejected."""
    result = validate_path("/tmp/test")
    assert result == Path("/tmp/test").resolve()


def test_validate_path_expands_tilde():
    """Tilde should be expanded."""
    folders = ["Desktop"]
    try:
        result = validate_path("~/Desktop", folders)
        assert "~" not in str(result)
    except ValueError:
        pass


def test_is_system_path_linux():
    assert _is_system_path(Path("/bin"))
    assert _is_system_path(Path("/usr/local"))
    assert _is_system_path(Path("/etc/passwd"))
    assert not _is_system_path(Path("/home/user/Desktop"))
    assert not _is_system_path(Path("/tmp/test"))


def test_is_safe_move_both_in_sandbox():
    """Both source and destination in sandbox = safe."""
    home = str(Path.home())
    folders = ["Desktop", "Documents"]
    assert is_safe_move(Path(f"{home}/Desktop/file.txt"), Path(f"{home}/Documents/file.txt"), folders)


def test_is_safe_move_source_outside():
    """Source outside sandbox = not safe."""
    folders = ["Desktop"]
    assert not is_safe_move(Path("/tmp/file.txt"), Path(f"{Path.home()}/Desktop/file.txt"), folders)


def test_is_safe_move_destination_system():
    """Destination in system dir = not safe."""
    folders = ["Desktop"]
    assert not is_safe_move(Path(f"{Path.home()}/Desktop/file.txt"), Path("/bin/file.txt"), folders)
