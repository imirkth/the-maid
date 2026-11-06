"""Tests for learning from the user's tree edits (pins, exclusions, renames)."""
import os

import pytest

from the_maid.feedback import Feedback, clean_folder_path, load_feedback, save_feedback
from the_maid.tree_architect import TreeArchitect, TreeRouter

from test_tree_architect import (  # noqa: F401  (fixture re-export)
    TAX, _folder_of, _placements, _scan, _write, messy_drive,
)


def _build(root, fb):
    files = _scan(root)
    result = TreeArchitect(str(root), feedback=fb).build(files)
    return result, _placements(result, files), files


def test_clean_folder_path():
    assert clean_folder_path(" Work / Clients//Acme ") == "Work/Clients/Acme"
    assert clean_folder_path("../../etc/passwd") == "etc/passwd"


def test_feedback_rules_and_roundtrip(tmp_path):
    fb = Feedback()
    fb.apply("pin", ["/a/x.pdf", "/a/y.pdf"], "Admin/Taxes")
    fb.apply("rename", [], "Admin", "Paperwork")
    assert fb.pinned_path("/a/x.pdf") == "Paperwork/Taxes"
    fb.apply("exclude", ["/a/y.pdf"])
    assert fb.is_excluded("/a/y.pdf") and fb.pinned_path("/a/y.pdf") is None
    fb.apply("include", ["/a/y.pdf"])
    assert not fb.is_excluded("/a/y.pdf")
    fb.file_moved("/a/x.pdf", "/b/x.pdf")
    assert fb.pinned_path("/b/x.pdf") == "Paperwork/Taxes"
    fb.apply("unpin", [], "Paperwork/Taxes")
    assert not fb.pins
    with pytest.raises(ValueError):
        fb.apply("pin", ["/a"], "")
    with pytest.raises(ValueError):
        fb.apply("explode")
    path = str(tmp_path / "fb.json")
    fb.apply("pin", ["/c.txt"], "Keep")
    save_feedback(fb, path)
    assert load_feedback(path) == fb
    assert load_feedback(str(tmp_path / "missing.json")) == Feedback()


def test_pinned_files_stay_where_the_user_put_them(messy_drive):
    cv = str(messy_drive / "Desktop/cv_2024.txt")
    recipe = str(messy_drive / "Misc/recette_0.txt")
    fb = Feedback()
    fb.apply("pin", [cv, recipe], "Me/Personal stuff")
    result, placed, _ = _build(messy_drive, fb)
    assert _folder_of(placed, "cv_2024") == {"Me/Personal stuff"}
    assert _folder_of(placed, "recette_0") == {"Me/Personal stuff"}
    assert result["summary"]["pinned_files"] == 2


def test_similar_files_join_a_pinned_folder(messy_drive):
    """Pin two tax papers: the other tax papers follow them on rebuild."""
    fb = Feedback()
    fb.apply("pin", [str(messy_drive / "Downloads/scan_000.txt"),
                     str(messy_drive / "Downloads/scan_001.txt")], "Admin/Taxes")
    _, placed, _ = _build(messy_drive, fb)
    assert _folder_of(placed, "scan_") == {"Admin/Taxes"}
    # unrelated files are not dragged in
    assert _folder_of(placed, "recette_") != {"Admin/Taxes"}


def test_excluded_files_are_left_out(messy_drive):
    fb = Feedback()
    fb.apply("exclude", [str(messy_drive / "Downloads/mystery.bin")])
    result, placed, _ = _build(messy_drive, fb)
    assert not _folder_of(placed, "mystery.bin")
    assert result["summary"]["protected"] == 1


def test_router_sends_new_files_to_pinned_folders(messy_drive, tmp_path):
    fb = Feedback()
    fb.apply("pin", [str(messy_drive / "Downloads/scan_000.txt"),
                     str(messy_drive / "Downloads/scan_001.txt")], "Admin/Taxes")
    result, _, _ = _build(messy_drive, fb)
    new = _write(tmp_path, "in/2026 return.txt", TAX)
    s = TreeRouter(result["model"]).route({"path": str(new), "filename": new.name, "extension": ".txt"})
    assert s["path"] == "Admin/Taxes"


def test_api_feedback_flow(messy_drive, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from the_maid import api, feedback, models, preferences, tree_architect

    state = tmp_path / "state"
    fb_path = str(state / "fb.json")
    monkeypatch.setattr(api, "load_feedback", lambda: feedback.load_feedback(fb_path))
    monkeypatch.setattr(api, "save_feedback", lambda f: feedback.save_feedback(f, fb_path))
    monkeypatch.setattr(api, "load_preferences", lambda: preferences.Preferences())
    monkeypatch.setattr(api, "TREE_PATH", str(state / "tree.json"))
    monkeypatch.setattr(models, "save_model", lambda m: tree_architect.save_model(m, str(state / "m.json")))
    monkeypatch.setattr(api, "_sandbox_folders", lambda: [str(tmp_path)])
    monkeypatch.setattr(models.LLMManager, "load_model", lambda self: False)
    monkeypatch.setattr(models.CategoryRegistry, "save", lambda self: None)
    client = TestClient(api.app)
    files = _scan(messy_drive)

    data = client.post("/categorize", json={"files": files, "directory": str(messy_drive)}).json()
    photos_ids = [f["file_id"] for c in data["categories"] if c["name"] == "Photos"
                  for ch in c["children"] for f in ch.get("files", [])]
    first_photo_folder = next(c for c in data["categories"] if c["name"] == "Photos")["children"][0]["name"]

    # rename a folder of the draft: its files are pinned under the new name
    r = client.post("/tree/feedback", json={"action": "rename", "path": f"Photos/{first_photo_folder}",
                                            "new_path": "Photos/Summer trip"})
    assert r.status_code == 200, r.text
    assert r.json()["folders"][0]["path"] == "Photos/Summer trip"

    # pin by file id
    tax_id = next(f["file_id"] for f in files if f["filename"] == "scan_000.txt")
    assert client.post("/tree/feedback", json={"action": "pin", "path": "Admin/Taxes",
                                               "file_ids": [tax_id]}).status_code == 200
    assert client.post("/tree/feedback", json={"action": "pin", "path": "X",
                                               "file_ids": ["nope"]}).status_code == 400
    assert client.post("/tree/feedback", json={"action": "pin", "path": "X",
                                               "files": ["/etc/passwd"]}).status_code == 400

    # rebuild honours the rules
    data = client.post("/categorize", json={"files": files, "directory": str(messy_drive)}).json()
    photos = next(c for c in data["categories"] if c["name"] == "Photos")
    assert any(ch["name"] == "Summer trip" for ch in photos["children"])
    assert any(c["name"] == "Admin" for c in data["categories"])
    assert data["summary"]["pinned_folders"] == 2

    # executing the moves keeps the rules attached to the moved files
    client.post("/tree/execute", json=photos_ids)
    fb = feedback.load_feedback(fb_path)
    assert all(os.path.exists(p) for p in fb.pins)

    assert client.post("/tree/feedback", json={"action": "reset"}).json()["pinned_files"] == 0
    assert client.get("/tree/feedback").json()["folders"] == []
