"""Tests that API endpoints enforce sandbox_folders from settings."""
import json
import os
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

from the_maid.api import app, SETTINGS_PATH

client = TestClient(app)


def _write_settings(tmp: str, sandbox_folders: list[str]):
    """Override settings path by monkey-patching module global."""
    # ponytail: patch the module global so tests don't touch real HOME
    import the_maid.api as api_module
    api_module.SETTINGS_PATH = os.path.join(tmp, "settings.json")
    with open(api_module.SETTINGS_PATH, "w") as f:
        json.dump({"sandbox_folders": sandbox_folders}, f)


def _clear_settings_path():
    import the_maid.api as api_module
    api_module.SETTINGS_PATH = os.path.expanduser("~/.the-maid/settings.json")


def test_scan_rejects_path_outside_sandbox():
    tmp = tempfile.mkdtemp(prefix="the-maid-api-sandbox-")
    _write_settings(tmp, ["Desktop"])
    try:
        resp = client.post("/scan", json={"directory": tmp, "max_files": 100})
        assert resp.status_code == 400, resp.text
        assert "outside the sandbox" in resp.json()["detail"]
    finally:
        _clear_settings_path()


def test_scan_accepts_path_inside_sandbox():
    tmp = tempfile.mkdtemp(prefix="the-maid-api-sandbox-")
    sandbox = Path(tmp, "Desktop")
    sandbox.mkdir()
    Path(sandbox, "file.txt").write_text("hello")
    _write_settings(str(tmp), [str(sandbox)])
    try:
        resp = client.post("/scan", json={"directory": str(sandbox), "max_files": 100})
        assert resp.status_code == 200, resp.text
        assert resp.json()["count"] == 1
    finally:
        _clear_settings_path()
