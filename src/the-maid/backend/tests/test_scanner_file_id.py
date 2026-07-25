"""Regression test: file_id must be an 8-char hex hash of current_path per ADR 0009."""
import hashlib
import tempfile
import shutil
from pathlib import Path

import pytest

from the_maid.scanner import FileScanner


@pytest.fixture
def sandboxed_scan_dir():
    """Create a temp directory inside ~/Desktop so the scanner accepts it."""
    d = tempfile.mkdtemp(prefix="the-maid-test-", dir=str(Path.home() / "Desktop"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_file_id_is_sha256_hash_of_path(sandboxed_scan_dir):
    """file_id must be the first 8 hex chars of SHA256(current_path)."""
    f = Path(sandboxed_scan_dir) / "test.txt"
    f.write_text("hello")

    scanner = FileScanner()
    results = scanner.scan_directory(sandboxed_scan_dir, sandbox_folders=["Desktop"])

    expected_id = hashlib.sha256(str(f).encode()).hexdigest()[:8]
    assert results[0]["file_id"] == expected_id


def test_file_id_is_deterministic_for_same_path(sandboxed_scan_dir):
    """Scanning the same path twice must yield the same file_id."""
    Path(sandboxed_scan_dir, "stable.txt").write_text("data")

    s1 = FileScanner()
    r1 = s1.scan_directory(sandboxed_scan_dir, sandbox_folders=["Desktop"])

    s2 = FileScanner()
    r2 = s2.scan_directory(sandboxed_scan_dir, sandbox_folders=["Desktop"])

    assert r1[0]["file_id"] == r2[0]["file_id"]
