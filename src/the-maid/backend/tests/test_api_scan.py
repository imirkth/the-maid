"""Tests for the /scan API endpoint — wiring scanner to HTTP."""
import pytest
import tempfile
import shutil
from pathlib import Path
from fastapi.testclient import TestClient

from the_maid.api import app

client = TestClient(app)


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="the-maid-test-")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_scan_endpoint_returns_files(temp_dir):
    """POST /scan should return file metadata from the scanner."""
    Path(temp_dir, "test.txt").write_text("hello")
    Path(temp_dir, "image.jpg").write_bytes(b"\xff\xd8\xff\xe0")

    resp = client.post("/scan", json={"directory": temp_dir, "max_files": 100})

    assert resp.status_code == 200
    data = resp.json()
    assert "files" in data
    assert "count" in data
    assert "errors" in data
    assert data["count"] == 2
    assert len(data["files"]) == 2

    filenames = [f["filename"] for f in data["files"]]
    assert "test.txt" in filenames
    assert "image.jpg" in filenames


def test_scan_endpoint_empty_dir(temp_dir):
    """POST /scan on empty dir returns zero files."""
    resp = client.post("/scan", json={"directory": temp_dir, "max_files": 100})

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert data["files"] == []
    assert data["errors"] == []


def test_scan_endpoint_system_dir_rejected():
    """POST /scan with system dir returns 400."""
    resp = client.post("/scan", json={"directory": "/etc", "max_files": 100})
    assert resp.status_code == 400
    assert "out of scope" in resp.json()["detail"]


def test_scan_endpoint_nested_files(temp_dir):
    """POST /scan recursively finds nested files."""
    sub = Path(temp_dir, "sub", "nested")
    sub.mkdir(parents=True)
    Path(sub, "deep.txt").write_text("deep")
    Path(temp_dir, "top.txt").write_text("top")

    resp = client.post("/scan", json={"directory": temp_dir, "max_files": 100})
    data = resp.json()
    assert data["count"] == 2
    filenames = [f["filename"] for f in data["files"]]
    assert "deep.txt" in filenames
    assert "top.txt" in filenames


def test_scan_endpoint_metadata_fields(temp_dir):
    """Scan response files must have all required metadata fields."""
    Path(temp_dir, "test.txt").write_text("hello")

    resp = client.post("/scan", json={"directory": temp_dir, "max_files": 100})
    f = resp.json()["files"][0]

    assert "file_id" in f
    assert "filename" in f
    assert "path" in f
    assert "size_bytes" in f
    assert "modified_time" in f
    assert "extension" in f
    assert "mime_type" in f


def test_scan_endpoint_max_files_limit(temp_dir):
    """Scanner respects max_files via API."""
    for i in range(10):
        Path(temp_dir, f"f{i}.txt").write_text(str(i))

    resp = client.post("/scan", json={"directory": temp_dir, "max_files": 5})
    data = resp.json()
    assert data["count"] == 5
    assert len(data["files"]) == 5
    assert any("max file limit" in e for e in data["errors"])


def test_scan_endpoint_health():
    """GET /health returns ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"