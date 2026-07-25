"""Tests for scanner stdout event format."""
import json
import pytest
import tempfile
import shutil
from pathlib import Path

from the_maid.scanner import FileScanner


@pytest.fixture
def temp_scan_dir():
    d = tempfile.mkdtemp(prefix="the-maid-test-")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_scan_progress_event_format(temp_scan_dir, capsys):
    """Progress event must include both count and progress float 0-1."""
    for i in range(250):
        Path(temp_scan_dir, f"file_{i}.txt").write_text(str(i))

    scanner = FileScanner(max_files=250)
    scanner.scan_directory(temp_scan_dir)

    captured = capsys.readouterr()
    progress_lines = [l for l in captured.out.splitlines() if '"event": "scan_progress"' in l]
    assert len(progress_lines) >= 2

    first = json.loads(progress_lines[0])
    assert "count" in first
    assert "progress" in first
    assert 0.0 <= first["progress"] <= 1.0
    assert first["progress"] == pytest.approx(first["count"] / 250, abs=0.01)


def test_scan_complete_event_format(temp_scan_dir, capsys):
    """Complete event must include count."""
    Path(temp_scan_dir, "test.txt").write_text("hello")

    scanner = FileScanner()
    scanner.scan_directory(temp_scan_dir)

    captured = capsys.readouterr()
    complete_lines = [l for l in captured.out.splitlines() if '"event": "scan_complete"' in l]
    assert len(complete_lines) == 1
    complete = json.loads(complete_lines[0])
    assert complete["count"] == 1
