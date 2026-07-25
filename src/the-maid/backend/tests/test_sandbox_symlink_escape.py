"""Regression test: sandbox escape via symlinks, junctions, or relative paths."""
import os
import tempfile
import shutil
from pathlib import Path

import pytest

from the_maid.sandbox import validate_path, is_safe_move


@pytest.fixture
def sandboxed_desktop():
    """Create a real Desktop directory under the current user's home."""
    desktop = Path.home() / "Desktop"
    desktop.mkdir(exist_ok=True)
    yield desktop


def test_symlink_file_inside_desktop_to_outside_is_rejected(sandboxed_desktop):
    """A symlink inside ~/Desktop pointing outside the sandbox must be rejected."""
    outside = tempfile.NamedTemporaryFile(delete=False, prefix="the-maid-secret-")
    outside.write(b"secret")
    outside.close()

    link = sandboxed_desktop / "escape_link.txt"
    os.symlink(outside.name, link)
    try:
        with pytest.raises(ValueError, match="outside the sandbox"):
            validate_path(str(link), sandbox_folders=["Desktop"])
    finally:
        link.unlink(missing_ok=True)
        Path(outside.name).unlink(missing_ok=True)


def test_symlink_directory_inside_desktop_to_outside_is_rejected(sandboxed_desktop):
    """A directory symlink inside ~/Desktop pointing outside must be rejected."""
    out_dir = tempfile.mkdtemp(prefix="the-maid-outdir-")
    Path(out_dir, "secret.txt").write_text("secret")

    link_dir = sandboxed_desktop / "escape_dir"
    os.symlink(out_dir, link_dir)
    try:
        with pytest.raises(ValueError, match="outside the sandbox"):
            validate_path(str(link_dir / "secret.txt"), sandbox_folders=["Desktop"])
    finally:
        link_dir.unlink(missing_ok=True)
        shutil.rmtree(out_dir, ignore_errors=True)


def test_relative_path_escape_from_desktop_is_rejected(sandboxed_desktop):
    """Relative path traversal inside ~/Desktop must resolve inside the sandbox."""
    with pytest.raises(ValueError, match="outside the sandbox"):
        validate_path(str(sandboxed_desktop / ".." / ".bashrc"), sandbox_folders=["Desktop"])


def test_is_safe_move_rejects_symlink_destination_outside_sandbox(sandboxed_desktop):
    """A move whose destination is a symlink escaping the sandbox is unsafe."""
    src = sandboxed_desktop / "src.txt"
    src.write_text("x")

    outside = tempfile.NamedTemporaryFile(delete=False, prefix="the-maid-dst-")
    outside.close()
    dst_link = sandboxed_desktop / "dst_link.txt"
    os.symlink(outside.name, dst_link)
    try:
        assert not is_safe_move(src, dst_link, sandbox_folders=["Desktop"])
    finally:
        src.unlink(missing_ok=True)
        dst_link.unlink(missing_ok=True)
        Path(outside.name).unlink(missing_ok=True)
