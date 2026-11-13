"""Tests for the Tree Architect (content-aware folder tree design)."""
import os
from datetime import datetime, timedelta

import pytest

from the_maid.scanner import FileScanner
from the_maid.tree_architect import (
    TO_SORT,
    TreeArchitect,
    TreeRouter,
    build_events,
    build_units,
    is_generic_folder,
    profile_file,
    tokenize,
)


# --- A realistic messy drive ------------------------------------------------

TAX = "Tax return income declaration taxable deduction revenue fiscal year tax office refund"
INVOICE = "Invoice number amount due payment total VAT customer billing invoice date supplier"
BANK = "Bank statement account balance transfer debit credit card bank fees savings account"
RECIPE = "Recipe ingredients flour sugar butter eggs oven bake minutes preheat whisk dough"
CV = "Curriculum vitae experience skills education employment resume references languages"
COURSE = "Lecture notes course exam chapter theorem exercise homework professor semester university"


def _write(root, rel, text=""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


@pytest.fixture
def messy_drive(tmp_path):
    root = tmp_path / "drive"
    # Downloads dump: mixed subjects with no structure
    for i in range(6):
        _write(root, f"Downloads/scan_{i:03d}.txt", f"{TAX} {2018 + i}")
        _write(root, f"Downloads/doc{i}.txt", f"{INVOICE} acme corp order {i}")
        _write(root, f"Downloads/releve_{i}.txt", f"{BANK} month {i}")
    for i in range(5):
        _write(root, f"Misc/recette_{i}.txt", f"{RECIPE} cake {i}")
        _write(root, f"Desktop/notes_{i}.md", f"{COURSE} algebra")
    _write(root, "Desktop/cv_2024.txt", CV)
    _write(root, "Desktop/cv_old.txt", CV)
    _write(root, "Desktop/cv_english.txt", CV)
    # A curated project folder: must stay together
    for i in range(5):
        _write(root, f"Projects/Greenhouse build/plan_{i}.txt", f"greenhouse timber glazing frame {i}")
    _write(root, "Projects/Greenhouse build/receipts/wood.txt", f"{INVOICE} timber")
    # Photos: two trips, plus screenshots and installers
    for i in range(6):
        _write(root, f"DCIM/IMG_202306{10 + (i % 2):02d}_1200{i}.jpg")
        _write(root, f"DCIM/IMG_202312{24 + (i % 2):02d}_0900{i}.jpg")
    _write(root, "Desktop/Screenshot 2024-01-03 at 10.00.00.png")
    _write(root, "Downloads/setup_tool.exe")
    _write(root, "Downloads/backup.zip")
    _write(root, "Downloads/mystery.bin")
    # A named photo album folder
    for i in range(4):
        _write(root, f"Pictures/Eleanor/IMG_{i}.jpg")
    return root


def _scan(root):
    files = FileScanner(max_files=10000).scan_directory(str(root))
    assert files, "scanner found nothing"
    return files


def _placements(result, files):
    """file name -> 'Category/sub/path' for easy assertions."""
    out = {}
    for node in result["tree"]:
        for sub in node["subbuckets"]:
            for fid in sub["files"]:
                path = node["category"] + ("/" + sub["subcategory"] if sub["subcategory"] else "")
                out[os.path.relpath(files[fid]["path"])] = path
    return out


def _folder_of(placed, needle):
    return {v for k, v in placed.items() if needle in k}


# --- Unit tests ------------------------------------------------------------

def test_tokenize_drops_noise_numbers_and_accents():
    assert tokenize("IMG_20230506 Facturé_EDF copy (2).pdf") == ["facture", "edf"]
    assert tokenize("MyTaxReturn") == ["tax", "return"]
    assert tokenize("invoices") == ["invoice"]


@pytest.mark.parametrize("name,generic", [
    ("Downloads", True), ("New folder", True), ("2023", True), ("100APPLE", True),
    ("Misc", True), ("Nouveau dossier", True),
    ("Greenhouse build", False), ("Eleanor", False), ("Taxes", False),
])
def test_generic_folder_detection(name, generic):
    assert is_generic_folder(name) is generic


def test_named_folders_become_units_and_dumps_dissolve(messy_drive):
    files = _scan(messy_drive)
    profiles = [profile_file(i, f, str(messy_drive)) for i, f in enumerate(files)]
    units = build_units(profiles)
    named = {u.name: u.size for u in units if u.name}
    assert named.get("Greenhouse build") == 6      # includes receipts/ sub-folder
    assert named.get("Eleanor") == 4
    assert "Downloads" not in named and "Misc" not in named and "DCIM" not in named


def test_events_split_on_time_gaps():
    class P:  # minimal FileProfile stand-in
        def __init__(self, d):
            self.date, self.gps = d, None
    base = datetime(2023, 6, 10, 12)
    trip1 = [P(base + timedelta(hours=h)) for h in range(0, 30, 5)]
    trip2 = [P(datetime(2023, 12, 24) + timedelta(hours=h)) for h in range(5)]
    stray = [P(datetime(2023, 8, 1))]
    events = build_events(trip1 + trip2 + stray)
    labels = [e[1] for e in events]
    assert labels[0].startswith("2023-06-10 to 06-11")
    assert any(lbl.startswith("2023-12-24") for lbl in labels)
    assert "2023-08 other" in labels


# --- End to end ------------------------------------------------------------

def test_builds_a_new_tree_not_a_copy_of_the_old_one(messy_drive):
    files = _scan(messy_drive)
    result = TreeArchitect(str(messy_drive)).build(files)
    placed = _placements(result, files)
    assert len(placed) == len(files), "every file is placed exactly once"

    # Each subject from the Downloads dump lands in its own folder...
    tax = _folder_of(placed, "scan_")
    invoices = _folder_of(placed, "Downloads/doc")
    bank = _folder_of(placed, "releve_")
    for group in (tax, invoices, bank):
        assert len(group) == 1, group
    assert len(tax | invoices | bank) == 3
    # ...and dump folder names never appear in the new tree
    for path in placed.values():
        assert "Downloads" not in path and "Misc" not in path and "DCIM" not in path

    # Curated folder kept intact, including its inner structure
    gh = _folder_of(placed, "Greenhouse build/plan_")
    assert len(gh) == 1 and next(iter(gh)).endswith("Greenhouse build")
    assert _folder_of(placed, "receipts/wood")  == {next(iter(gh)) + "/receipts"}

    # Photos organised by event, album kept, screenshot separated
    june = _folder_of(placed, "IMG_202306")
    dec = _folder_of(placed, "IMG_202312")
    assert len(june) == 1 and len(dec) == 1 and june != dec
    assert next(iter(june)).startswith("Photos/2023-06-10")
    assert _folder_of(placed, "Eleanor") == {"Photos/Albums/Eleanor"}
    assert _folder_of(placed, "Screenshot") == {"Photos/Screenshots"}

    # Software separated; unreadable unknowns are honestly marked to sort
    assert _folder_of(placed, "setup_tool.exe") == {"Software & Archives"}
    assert next(iter(_folder_of(placed, "mystery.bin"))).startswith(TO_SORT)


def test_tree_shape_is_bounded(messy_drive):
    files = _scan(messy_drive)
    result = TreeArchitect(str(messy_drive)).build(files)
    summary = result["summary"]
    assert summary["after"]["top_level"] <= 12
    assert summary["after"]["max_depth"] <= 4
    assert summary["after"]["loose_files"] == 0
    for node in result["tree"]:
        assert node["category"] and "/" not in node["category"]
        for sub in node["subbuckets"]:
            assert sub["rationale"], "every folder explains itself"


def test_llm_names_are_used_when_valid_and_ignored_when_garbage(messy_drive):
    files = _scan(messy_drive)
    calls = []

    def namer(prompt):
        calls.append(prompt)
        n = prompt.count("\n")
        return "\n".join(f"{i}: Topic {chr(65 + i)}" for i in range(n)) + "\n0: /etc/passwd"

    result = TreeArchitect(str(messy_drive), namer=namer).build(files)
    assert calls, "LLM used for naming"
    cats = [n["category"] for n in result["tree"]]
    assert any(c.startswith("Topic ") for c in cats)
    assert all("/" not in c for c in cats)
    assert "Photos" in cats  # media branch names are not delegated to the LLM


def test_no_files_returns_empty_tree():
    assert TreeArchitect("").build([])["tree"] == []


def test_router_sends_new_files_to_matching_folder(messy_drive, tmp_path):
    files = _scan(messy_drive)
    arch = TreeArchitect(str(messy_drive))
    result = arch.build(files)
    placed = _placements(result, files)
    tax_folder = next(iter(_folder_of(placed, "scan_")))

    new = _write(tmp_path, "incoming/2025 papers.txt", TAX)
    router = TreeRouter(result["model"])
    suggestion = router.route({"path": str(new), "filename": new.name, "extension": ".txt"})
    assert tax_folder.startswith(suggestion["path"]) or suggestion["path"].startswith(tax_folder)
    assert suggestion["confidence"] > 0

    junk = _write(tmp_path, "incoming/zzqx.txt", "qwxz vbnm")
    assert router.route({"path": str(junk), "filename": junk.name, "extension": ".txt"})["path"].startswith(TO_SORT)


# --- API: categorize then execute builds ONE organised tree ----------------

def test_api_categorize_and_execute_moves_into_single_tree(messy_drive, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from the_maid import api, models, tree_architect

    monkeypatch.setattr(api, "TREE_PATH", str(tmp_path / "state" / "tree.json"))
    monkeypatch.setattr(tree_architect, "MODEL_PATH", str(tmp_path / "state" / "model.json"))
    monkeypatch.setattr(models, "save_model", lambda m: tree_architect.save_model(m, str(tmp_path / "state" / "model.json")))
    monkeypatch.setattr(api, "load_model", lambda: tree_architect.load_model(str(tmp_path / "state" / "model.json")))
    monkeypatch.setattr(api, "_sandbox_folders", lambda: [str(tmp_path)])
    monkeypatch.setattr(models.LLMManager, "load_model", lambda self: False)
    monkeypatch.setattr(models.CategoryRegistry, "save", lambda self: None)
    # existing file at a destination must never be overwritten
    client = TestClient(api.app)

    files = _scan(messy_drive)
    resp = client.post("/categorize", json={"files": files, "directory": str(messy_drive)})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["summary"]["files"] == len(files)
    names = [c["name"] for c in data["categories"]]
    assert "Photos" in names and names[-1] == TO_SORT

    all_ids = [f["file_id"] for f in files]
    resp = client.post("/tree/execute", json=all_ids)
    assert resp.status_code == 200, resp.text
    results = resp.json()["results"]
    moved = [r for r in results if r["status"] == "moved"]
    assert moved and not [r for r in results if r["status"] == "error"]
    for r in moved:
        rel = os.path.relpath(r["dest"], messy_drive)
        top = rel.split(os.sep)[0]
        assert top in names, f"{rel} is not under a top-level folder of the new tree"
    # the event folder is at <root>/Photos/<event>, not nested inside DCIM
    assert (messy_drive / "Photos").is_dir()
    assert not (messy_drive / "DCIM").exists(), "emptied dump folders are cleaned up"
    assert (messy_drive / "Downloads" / "mystery.bin").exists(), "'To Sort' files are left in place"

    # Routing endpoint uses the saved model
    resp = client.post("/tree/route", json={"files": [{"path": str(messy_drive / 'x.jpg'), "filename": "IMG_20240101_1.jpg", "extension": ".jpg"}]})
    assert resp.json()["suggestions"][0]["path"].startswith("Photos/")


def test_execute_never_overwrites(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from the_maid import api
    import json as _json

    root = tmp_path / "root"
    _write(root, "Downloads/a.txt", "new")
    _write(root, "Tax/a.txt", "existing")
    state = tmp_path / "tree.json"
    state.write_text(_json.dumps({"tree": [{"name": "Tax", "children": [
        {"name": "a.txt", "file_id": "f1", "filename": "a.txt",
         "path": str(root / "Downloads/a.txt"), "dest_root": str(root)}]}]}))
    monkeypatch.setattr(api, "TREE_PATH", str(state))
    monkeypatch.setattr(api, "_sandbox_folders", lambda: [str(tmp_path)])
    r = TestClient(api.app).post("/tree/execute", json=["f1"]).json()["results"][0]
    assert r["status"] == "moved" and r["dest"].endswith("a (2).txt")
    assert (root / "Tax/a.txt").read_text() == "existing"


# --- Projects stay whole ("the deeper the path, the stronger the signal") ---

@pytest.fixture
def code_drive(tmp_path):
    root = tmp_path / "home"
    proj = "PycharmProjects/AI_trading"
    _write(root, f"{proj}/requirements.txt", "tensorflow\nscikit-learn\npandas")
    _write(root, f"{proj}/train.py", "import tensorflow as tf\nmodel = tf.keras.Sequential()")
    _write(root, f"{proj}/data/btcusd_4h.csv", "date,open,high,low,close")
    _write(root, f"{proj}/data/btcusd_1d.csv", "date,open,high,low,close")
    for name in ("scaler.pkl", "scaler_4hr.pkl", "scaler_4hrs.pkl"):
        _write(root, f"{proj}/data/{name}")
    # A venv bigger than the rest of the drive: must not become its own topics
    for pkg in ("tensorflow", "numpy", "setuptools", "termcolor"):
        for i in range(40):
            _write(root, f"{proj}/venv/lib/python3.12/site-packages/{pkg}/mod_{i}.py",
                   f"# {pkg} internals {i}\nimport {pkg}")
            _write(root, f"{proj}/venv/lib/python3.12/site-packages/{pkg}/__pycache__/mod_{i}.cpython-312.pyc")
    for i in range(6):
        _write(root, f"Documents/Taxes/tax_{i}.txt", f"{TAX} {2018 + i}")
        _write(root, f"Recipes/recette_{i}.txt", f"{RECIPE} cake {i}")
    return root


def test_project_folder_is_one_unit_even_when_huge(code_drive):
    files = _scan(code_drive)
    profiles = [profile_file(i, f, str(code_drive)) for i, f in enumerate(files)]
    units = build_units(profiles)
    proj = [u for u in units if u.name == "AI_trading"]
    assert len(proj) == 1 and proj[0].project
    assert proj[0].size == sum(1 for f in files if "AI_trading" in f["path"])


def test_project_keeps_its_inner_structure(code_drive):
    files = _scan(code_drive)
    result = TreeArchitect(str(code_drive)).build(files)
    placed = _placements(result, files)
    homes = {v.split("AI_trading")[0] for k, v in placed.items() if "AI_trading" in k}
    assert len(homes) == 1, f"project split across {homes}"
    scalers = _folder_of(placed, "scaler")
    assert len(scalers) == 1 and next(iter(scalers)).endswith("AI_trading/data")
    venv = [f for f in files if f.get("is_folder")]
    assert [f["filename"] for f in venv] == ["venv"] and venv[0]["file_count"] == 320
    assert placed[os.path.relpath(venv[0]["path"])] == "Code projects/AI_trading"


def test_project_beside_other_folders_is_not_swallowed_by_its_parent(code_drive):
    """A small parent ("PycharmProjects") holding a project and sibling folders must not
    become the unit: the project below it stays its own unit (venv scanned as one entry)."""
    for name in ("RL_CG_LOG", "NN_gene", "kaggle_2_sigma"):
        for i in range(3):
            _write(code_drive, f"PycharmProjects/{name}/run_{i}.log", f"epoch {i} loss")
    files = _scan(code_drive)
    profiles = [profile_file(i, f, str(code_drive)) for i, f in enumerate(files)]
    units = build_units(profiles)
    holders = {u.name for u in units if any("AI_trading" in f.path for f in u.files)}
    assert holders == {"AI_trading"}, holders
    assert [u for u in units if u.name == "AI_trading"][0].project
    placed = _placements(TreeArchitect(str(code_drive)).build(files), files)
    assert all(v.startswith("Code projects/AI_trading") for k, v in placed.items() if "AI_trading" in k)


def test_files_under_a_big_named_folder_stay_with_it(tmp_path):
    """Generic sub-folders of a too-big folder fall back to that folder, not to loose files."""
    root = tmp_path / "drive"
    for i in range(30):
        _write(root, f"Thesis/Chapter one/part_{i}.txt", f"{COURSE} chapter one {i}")
        _write(root, f"Thesis/Chapter two/part_{i}.txt", f"{COURSE} chapter two {i}")
    for i in range(4):
        _write(root, f"Thesis/data/sample_{i}.csv", "a,b,c")
    for i in range(6):
        _write(root, f"Recipes/recette_{i}.txt", f"{RECIPE} {i}")
    files = _scan(root)
    profiles = [profile_file(i, f, str(root)) for i, f in enumerate(files)]
    units = build_units(profiles)
    data = [u for u in units if any("sample_" in f.filename for f in u.files)]
    assert len(data) == 1 and data[0].name == "Thesis" and data[0].size == 4


def test_code_projects_get_their_own_branch(code_drive):
    files = _scan(code_drive)
    placed = _placements(TreeArchitect(str(code_drive)).build(files), files)
    proj = {v for k, v in placed.items() if "AI_trading" in k}
    assert all(v.startswith("Code projects/AI_trading") for v in proj)
    assert not any(v.startswith("Code projects") for k, v in placed.items() if "AI_trading" not in k)


def test_wallet_files_are_kept_together(messy_drive):
    _write(messy_drive, "UTC--2017-12-04T10-11-12.123Z--a1b2c3", '{"crypto": {}}')
    _write(messy_drive, "UTC--2018-01-02T10-11-12.123Z--d4e5f6", '{"crypto": {}}')
    _write(messy_drive, "Downloads/my little wallet.dat")
    _write(messy_drive, "curecoinwallet.dat")
    files = _scan(messy_drive)
    placed = _placements(TreeArchitect(str(messy_drive)).build(files), files)
    names = {k: os.path.basename(k) for k in placed}
    wallets = {v for k, v in placed.items() if names[k].startswith("UTC--") or "wallet" in names[k]}
    assert wallets == {"Crypto wallets"}


def test_named_installer_folder_goes_to_software(tmp_path):
    root = tmp_path / "drive"
    for i in range(6):
        _write(root, f"Data/programme/setup_{i}.exe")
        _write(root, f"Data/programme/matlab/toolbox/libmx_{i}.dll")
        _write(root, f"Data/programme/matlab/toolbox/plot_{i}.m", "function plot")
        _write(root, f"Data/programme/matlab/toolbox/readme_{i}.txt", "toolbox help")
        _write(root, f"Cryocare services/invoice_{i}.txt", f"{INVOICE} cryocare {i}")
        _write(root, f"Recipes/recette_{i}.txt", f"{RECIPE} {i}")
    files = _scan(root)
    placed = _placements(TreeArchitect(str(root)).build(files), files)
    assert all(v.startswith("Software & Archives/programme") for v in _folder_of(placed, "programme"))
