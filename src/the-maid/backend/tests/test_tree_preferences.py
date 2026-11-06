"""Tests for personal tree preferences and the preference check."""
import os
from datetime import datetime

import pytest

from the_maid.preferences import Preferences, load_preferences, save_preferences
from the_maid.tree_architect import TreeArchitect, Unit, build_topic_nodes, vectorize_units

from test_tree_architect import (  # noqa: F401  (fixture re-export)
    TAX, BANK, RECIPE, _folder_of, _placements, _scan, _write, messy_drive,
)


def _set_year(path, year):
    t = datetime(year, 6, 1).timestamp()
    os.utime(path, (t, t))


@pytest.fixture
def dated_drive(messy_drive):
    """Tax papers spread over several years (by modification date)."""
    for i, p in enumerate(sorted((messy_drive / "Downloads").glob("scan_*.txt"))):
        _set_year(p, 2019 + i % 3)
    return messy_drive


def _build(root, **prefs):
    files = _scan(root)
    result = TreeArchitect(str(root), prefs=Preferences.from_dict(prefs)).build(files)
    return result, _placements(result, files)


def test_preferences_validation_and_roundtrip(tmp_path):
    p = Preferences.from_dict({"inside_topics": "bogus", "photos": "months", "depth": "shallow",
                               "areas": ["Work", "work", "Family/Kids", 3, ""], "protected": ["rel/x"]})
    assert p.inside_topics == "auto" and p.photos == "months" and p.depth == "shallow"
    assert p.areas == ["Work", "Family Kids"]
    assert p.protected == [os.path.abspath("rel/x")]
    path = str(tmp_path / "prefs.json")
    save_preferences(p, path)
    assert load_preferences(path) == p
    assert load_preferences(str(tmp_path / "missing.json")) == Preferences()


def test_inside_topics_by_year(dated_drive):
    _, placed = _build(dated_drive, inside_topics="year")
    tax = _folder_of(placed, "scan_")
    assert len(tax) == 3 and {p.rsplit("/", 1)[1] for p in tax} == {"2019", "2020", "2021"}


def test_inside_topics_default_keeps_subject_folders_flat(dated_drive):
    _, placed = _build(dated_drive)
    assert len(_folder_of(placed, "scan_")) == 1


def test_photos_by_month(messy_drive):
    _, placed = _build(messy_drive, photos="months")
    assert _folder_of(placed, "IMG_202306") == {"Photos/2023-06"}
    assert _folder_of(placed, "IMG_202312") == {"Photos/2023-12"}
    assert _folder_of(placed, "Eleanor") == {"Photos/Albums/Eleanor"}


def test_main_areas_group_subject_folders(messy_drive):
    _, placed = _build(messy_drive, areas=["Bank", "Recipe"])
    assert next(iter(_folder_of(placed, "releve_"))).startswith("Bank/")
    assert next(iter(_folder_of(placed, "recette_"))).startswith("Recipe/")
    assert not next(iter(_folder_of(placed, "cv_"))).startswith(("Bank", "Recipe"))


def test_main_areas_use_the_llm_when_available(messy_drive):
    def namer(prompt):
        if "main areas" in prompt:   # assign every folder to area A
            n = sum(1 for line in prompt.splitlines() if line[:1].isdigit() and " — " in line)
            return "\n".join(f"{i}: A" for i in range(n))
        return ""
    files = _scan(messy_drive)
    result = TreeArchitect(str(messy_drive), namer=namer, prefs=Preferences(areas=["Life"])).build(files)
    cats = {n["category"] for n in result["tree"]}
    assert "Life" in cats and "Photos" in cats      # media stays at the top
    assert not cats & {"Tax", "Invoice", "Curriculum"}


def test_protected_folders_are_left_out(messy_drive):
    result, placed = _build(messy_drive, protected=[str(messy_drive / "Projects")])
    assert not _folder_of(placed, "Greenhouse build")
    assert result["summary"]["protected"] == 6


def test_shallow_depth_never_splits_subjects():
    from collections import Counter
    from the_maid.tree_architect import FileProfile
    units = []
    for i in range(80):
        topic = ["tax", "bank", "recipe", "garden"][i % 4]
        sub = f"{topic}{'abc'[i % 3]}x"
        terms = Counter({topic: 3, sub: 3})
        units.append(Unit(key=str(i), files=[FileProfile(i, "", f"{i}.txt", [], "document", terms)]))
    vectorize_units(units)
    assert all(not n.children for n in build_topic_nodes(units, None, None, 0, max_depth=0))


def test_preview_choices_only_asks_questions_that_matter(dated_drive):
    files = _scan(dated_drive)
    out = TreeArchitect(str(dated_drive)).preview_choices(files)
    ids = [q["id"] for q in out["questions"]]
    assert "photos" in ids
    for q in out["questions"]:
        previews = {tuple(o["preview"]) for o in q["options"]}
        assert len(previews) > 1, q["id"]
    photos = next(q for q in out["questions"] if q["id"] == "photos")
    assert any("2023-06" in line for o in photos["options"] for line in o["preview"])
    assert {c["name"] for c in out["protect_candidates"]} >= {"Projects/Greenhouse build", "Pictures/Eleanor"}
    assert out["suggested_areas"]


def test_api_preferences_flow(dated_drive, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from the_maid import api, models, preferences, tree_architect

    prefs_path = str(tmp_path / "state" / "prefs.json")
    monkeypatch.setattr(api, "load_preferences", lambda: preferences.load_preferences(prefs_path))
    monkeypatch.setattr(api, "save_preferences", lambda p: preferences.save_preferences(p, prefs_path))
    monkeypatch.setattr(api, "TREE_PATH", str(tmp_path / "state" / "tree.json"))
    monkeypatch.setattr(models, "save_model", lambda m: tree_architect.save_model(m, str(tmp_path / "state" / "m.json")))
    monkeypatch.setattr(api, "_sandbox_folders", lambda: [str(tmp_path)])
    monkeypatch.setattr(models.LLMManager, "load_model", lambda self: False)
    monkeypatch.setattr(models.CategoryRegistry, "save", lambda self: None)
    client = TestClient(api.app)
    files = _scan(dated_drive)

    assert client.get("/preferences").json()["answered"] is False
    choices = client.post("/tree/choices", json={"files": files, "directory": str(dated_drive)}).json()
    assert choices["questions"]

    saved = client.put("/preferences", json={"photos": "months", "inside_topics": "year"}).json()
    assert saved["answered"] is True and saved["photos"] == "months"
    assert client.put("/preferences", json={"protected": ["/etc"]}).status_code == 400

    data = client.post("/categorize", json={"files": files, "directory": str(dated_drive)}).json()
    photos = next(c for c in data["categories"] if c["name"] == "Photos")
    assert any(ch["name"] == "2023-06" for ch in photos["children"])
    assert data["summary"]["preferences"]["inside_topics"] == "year"
