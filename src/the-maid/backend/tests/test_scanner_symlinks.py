"""Regression: symlinks pointing to other allowed sandbox folders should be scanned."""
import os
import tempfile
import shutil
from pathlib import Path

import pytest

from the_maid.scanner import FileScanner


@pytest.fixture
def sandboxed_pair():
    """Create two temp directories inside different sandbox folders."""
    desktop = tempfile.mkdtemp(prefix="the-maid-desktop-", dir=str(Path.home() / "Desktop"))
    downloads = tempfile.mkdtemp(prefix="the-maid-downloads-", dir=str(Path.home() / "Downloads"))
    yield desktop, downloads
    shutil.rmtree(desktop, ignore_errors=True)
    shutil.rmtree(downloads, ignore_errors=True)


def test_symlink_to_other_sandbox_folder_is_scanned(sandboxed_pair):
    """Symlink from Desktop → Downloads must be scanned when both are allowed."""
    desktop, downloads = sandboxed_pair
    Path(downloads, "real.txt").write_text("real")

    link = Path(desktop, "link_to_downloads.txt")
    os.symlink(Path(downloads, "real.txt"), link)

    scanner = FileScanner()
    results = scanner.scan_directory(desktop, sandbox_folders=["Desktop", "Downloads"])

    filenames = [r["filename"] for r in results]
    assert "link_to_downloads.txt" in filenames


def test_symlink_to_outside_sandbox_is_skipped(sandboxed_pair):
    """Symlink from Desktop → /tmp must be skipped."""
    desktop, _ = sandboxed_pair
    outside = tempfile.mktemp(prefix="the-maid-outside-")
    Path(outside).write_text("secret")

    link = Path(desktop, "escape_link.txt")
    os.symlink(outside, link)

    scanner = FileScanner()
    results = scanner.scan_directory(desktop, sandbox_folders=["Desktop"])

    filenames = [r["filename"] for r in results]
    assert "escape_link.txt" not in filenames

    Path(outside).unlink(missing_ok=True)


def test_broken_symlink_is_skipped(sandboxed_pair):
    """Broken symlinks must not crash the scanner."""
    desktop, _ = sandboxed_pair
    link = Path(desktop, "broken_link.txt")
    os.symlink("/nonexistent/path/that/does/not/exist", link)

    scanner = FileScanner()
    results = scanner.scan_directory(desktop, sandbox_folders=["Desktop"])

    filenames = [r["filename"] for r in results]
    assert "broken_link.txt" not in filenames
    assert scanner.errors == []
