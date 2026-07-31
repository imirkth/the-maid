"""Performance test: 10,000 files in <30 seconds (ADR requirement)."""
import tempfile
import shutil
import time
from pathlib import Path

import pytest

from the_maid.scanner import FileScanner


@pytest.fixture
def large_dir():
    """Create a directory with 10,000 small files."""
    d = tempfile.mkdtemp(prefix="the-maid-perf-")
    for i in range(10_000):
        Path(d, f"file_{i:05d}.txt").write_text(f"content {i}")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.mark.slow
def test_scan_10k_files_under_30_seconds(large_dir):
    """Scan 10,000 files in under 30 seconds on mid-range hardware."""
    scanner = FileScanner(max_files=10_000)
    start = time.monotonic()
    results = scanner.scan_directory(large_dir)
    elapsed = time.monotonic() - start

    assert len(results) == 10_000
    assert elapsed < 30.0, f"Scan took {elapsed:.1f}s, expected <30s"