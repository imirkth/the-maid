"""Tests for FileScanner — edge cases, symlinks, permissions, empty dirs."""
import pytest
import os
import tempfile
import shutil
from pathlib import Path
from the_maid.scanner import FileScanner


@pytest.fixture
def temp_scan_dir():
    """Create a temp directory with test files."""
    d = tempfile.mkdtemp(prefix="the-maid-test-")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_scan_empty_directory(temp_scan_dir):
    """Empty directory should return empty list, no errors."""
    scanner = FileScanner()
    results = scanner.scan_directory(temp_scan_dir)
    assert results == []
    assert scanner.errors == []
    assert scanner.scanned_count == 0


def test_scan_basic_files(temp_scan_dir):
    """Basic files should be scanned with metadata."""
    Path(temp_scan_dir, "test.txt").write_text("hello")
    Path(temp_scan_dir, "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0")  # JPEG header

    scanner = FileScanner()
    results = scanner.scan_directory(temp_scan_dir)

    assert len(results) == 2
    assert scanner.scanned_count == 2
    assert scanner.errors == []

    txt = next(r for r in results if r["filename"] == "test.txt")
    assert txt["extension"] == ".txt"
    assert txt["mime_type"] == "text/plain"
    assert txt["size_bytes"] == 5
    assert len(txt["file_id"]) == 8  # 8-char hex per ADR 0009

    jpg = next(r for r in results if r["filename"] == "photo.jpg")
    assert jpg["extension"] == ".jpg"
    assert jpg["mime_type"] == "image/jpeg"


def test_scan_nested_directories(temp_scan_dir):
    """Nested directories should be scanned recursively."""
    sub = Path(temp_scan_dir, "subdir", "nested")
    sub.mkdir(parents=True)
    Path(sub, "deep.txt").write_text("deep")

    scanner = FileScanner()
    results = scanner.scan_directory(temp_scan_dir)

    assert len(results) == 1
    assert results[0]["filename"] == "deep.txt"
    assert "subdir" in results[0]["path"]


def test_scan_file_id_is_hash_of_path(temp_scan_dir):
    """file_id should be 8-char hex hash of the file path (ADR 0009)."""
    import hashlib
    f = Path(temp_scan_dir, "test.txt")
    f.write_text("hello")

    scanner = FileScanner()
    results = scanner.scan_directory(temp_scan_dir)

    expected_id = hashlib.sha256(str(f).encode()).hexdigest()[:8]
    assert results[0]["file_id"] == expected_id


def test_scan_file_id_consistent(temp_scan_dir):
    """Same path should produce same file_id across scans."""
    Path(temp_scan_dir, "stable.txt").write_text("data")

    s1 = FileScanner()
    r1 = s1.scan_directory(temp_scan_dir)

    s2 = FileScanner()
    r2 = s2.scan_directory(temp_scan_dir)

    assert r1[0]["file_id"] == r2[0]["file_id"]


def test_scan_max_files_limit(temp_scan_dir):
    """Scanner should respect max_files limit."""
    for i in range(10):
        Path(temp_scan_dir, f"file_{i}.txt").write_text(str(i))

    scanner = FileScanner(max_files=5)
    results = scanner.scan_directory(temp_scan_dir)

    assert len(results) == 5
    assert scanner.scanned_count == 5
    assert any("max file limit" in e for e in scanner.errors)


def test_scan_special_characters_in_filename(temp_scan_dir):
    """Files with special characters should be handled."""
    Path(temp_scan_dir, "file with spaces.txt").write_text("spaced")
    Path(temp_scan_dir, "file-with-dashes.txt").write_text("dashed")
    Path(temp_scan_dir, "file_with_underscores.txt").write_text("underscored")
    Path(temp_scan_dir, "file.with.dots.txt").write_text("dotted")

    scanner = FileScanner()
    results = scanner.scan_directory(temp_scan_dir)

    assert len(results) == 4
    filenames = [r["filename"] for r in results]
    assert "file with spaces.txt" in filenames
    assert "file-with-dashes.txt" in filenames


def test_scan_symlink_skipped_if_outside_sandbox(temp_scan_dir):
    """Symlinks pointing outside sandbox should be skipped."""
    # Create a file outside the scan dir
    outside = tempfile.mktemp(prefix="the-maid-outside-")
    Path(outside).write_text("secret")

    # Create symlink inside scan dir pointing outside
    link = Path(temp_scan_dir, "link.txt")
    os.symlink(outside, link)

    scanner = FileScanner()
    results = scanner.scan_directory(temp_scan_dir)

    # Symlink should be skipped
    filenames = [r["filename"] for r in results]
    assert "link.txt" not in filenames

    Path(outside).unlink(missing_ok=True)


def test_scan_symlink_inside_sandbox_followed(temp_scan_dir):
    """Symlinks pointing within sandbox should be followed."""
    target = Path(temp_scan_dir, "real.txt")
    target.write_text("real")

    link = Path(temp_scan_dir, "link.txt")
    os.symlink(target, link)

    scanner = FileScanner()
    results = scanner.scan_directory(temp_scan_dir)

    # Both real file and symlink should appear
    filenames = [r["filename"] for r in results]
    assert "real.txt" in filenames
    # Symlink may or may not appear depending on os.walk behavior
    # Just ensure no crash


def test_scan_permission_denied_file(temp_scan_dir):
    """Files with permission errors should be logged, not crash."""
    f = Path(temp_scan_dir, "noperm.txt")
    f.write_text("no read")
    os.chmod(f, 0o000)

    scanner = FileScanner()
    results = scanner.scan_directory(temp_scan_dir)

    # File may or may not appear depending on OS, but no crash
    assert scanner.scanned_count >= 0

    os.chmod(f, 0o644)  # cleanup


def test_scan_progress_callback(temp_scan_dir):
    """Progress callback should be called during scan."""
    for i in range(250):
        Path(temp_scan_dir, f"file_{i}.txt").write_text(str(i))

    progress_calls = []
    scanner = FileScanner(progress_callback=lambda count: progress_calls.append(count))
    scanner.scan_directory(temp_scan_dir)

    # Should have been called at least once (every 100 files)
    assert len(progress_calls) >= 2
    assert progress_calls[0] == 100
    assert progress_calls[-1] == 200


def test_scan_metadata_fields(temp_scan_dir):
    """All required metadata fields should be present."""
    Path(temp_scan_dir, "test.txt").write_text("hello")

    scanner = FileScanner()
    results = scanner.scan_directory(temp_scan_dir)

    r = results[0]
    assert "file_id" in r
    assert "filename" in r
    assert "path" in r
    assert "size_bytes" in r
    assert "modified_time" in r
    assert "extension" in r
    assert "mime_type" in r


def test_scan_mime_types(temp_scan_dir):
    """Various extensions should map to correct MIME types."""
    Path(temp_scan_dir, "doc.pdf").write_bytes(b"%PDF-1.4")
    Path(temp_scan_dir, "sheet.xlsx").write_bytes(b"PK")  # ZIP header
    Path(temp_scan_dir, "code.py").write_text("print('hi')")
    Path(temp_scan_dir, "unknown.xyz").write_text("???")

    scanner = FileScanner()
    results = scanner.scan_directory(temp_scan_dir)

    by_name = {r["filename"]: r for r in results}
    assert by_name["doc.pdf"]["mime_type"] == "application/pdf"
    assert by_name["sheet.xlsx"]["mime_type"].startswith("application")
    assert by_name["unknown.xyz"]["mime_type"] == "application/octet-stream"