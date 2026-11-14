"""
The Maid — FastAPI HTTP Server
Handles all requests from Tauri frontend.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
import json
import os

from .scanner import FileScanner
from .sandbox import validate_path
from .models import LLMManager
from .tree_architect import TO_SORT, TreeArchitect, TreeRouter, load_model
from .preferences import Preferences, load_preferences, save_preferences
from .feedback import ACTIONS as FEEDBACK_ACTIONS, clean_folder_path, load_feedback, save_feedback
from .face_detector import FaceDetector, detect_faces_for_scan
from .face_cluster import FaceClusterer, cluster_faces_from_scan
from .face_tagger import rename_cluster_with_tags, get_clusters_for_ui
from .exif_reader import extract_exif

app = FastAPI(title="The Maid API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "http://127.0.0.1:1420"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
)

SETTINGS_PATH = os.path.expanduser("~/.the-maid/settings.json")
TREE_PATH = os.path.expanduser("~/.the-maid/tree.json")


def load_sandbox_folders() -> Optional[List[str]]:
    try:
        with open(SETTINGS_PATH, "r") as f:
            data = json.load(f)
            folders = data.get("sandbox_folders", [])
            if folders:
                return folders
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _sandbox_folders() -> Optional[List[str]]:
    return load_sandbox_folders()


def face_clustering_enabled() -> bool:
    """The "Face clustering" switch in Settings (off unless turned on)."""
    try:
        with open(SETTINGS_PATH, "r") as f:
            return bool(json.load(f).get("features", {}).get("face_clustering", False))
    except (OSError, json.JSONDecodeError, AttributeError):
        return False


# --- Models ---

class ScanRequest(BaseModel):
    directory: str = Field(..., description="Absolute path to scan")
    max_files: int = Field(default=100000, ge=1, le=100000)

class CategorizeRequest(BaseModel):
    files: List[dict] = Field(default_factory=list)
    directory: str = Field(default="", description="Scan root directory for relative path computation")

class FileProposal(BaseModel):
    file_id: str
    original_filename: str
    current_path: str
    proposed_path: str
    proposed_tags: List[str] = []
    faces_detected: List[str] = []
    rationale: str

class ApprovalRequest(BaseModel):
    proposals: List[FileProposal]
    approved_ids: List[str]

class Bucket(BaseModel):
    id: str
    name: str
    path: str

class TagFaceRequest(BaseModel):
    cluster_id: str
    name: str


# --- Tree Management Models ---

class TreeFileEntry(BaseModel):
    file_id: str = ""
    filename: str = ""
    path: str = ""
    proposed_path: str = ""
    size_bytes: int = 0
    rationale: str = ""
    confidence: float = 0.0
    tags: List[str] = []
    approved: bool = False
    dest_root: str = ""

class TreeSubCategory(BaseModel):
    name: str = ""
    rationale: str = ""
    files: List[TreeFileEntry] = []

class TreeCategoryModel(BaseModel):
    name: str = ""
    rationale: str = ""
    children: List[TreeSubCategory] = []

class TreeState(BaseModel):
    tree: List[TreeCategoryModel] = []
    approved_structure: bool = False
    total_files: int = 0
    total_categorized: int = 0
    summary: dict = {}

class MergeRequest(BaseModel):
    categories: List[dict] = []
    total_files: int = 0
    total_categorized: int = 0

class CategoryEdit(BaseModel):
    old_name: str
    new_name: Optional[str] = None  # rename
    target_category: Optional[str] = None  # move subcategory under another category
    delete: bool = False  # delete category, files → Uncategorized

class FileMove(BaseModel):
    file_id: str
    target_category: str
    target_subcategory: str = ""

class SubcategoryEdit(BaseModel):
    category_name: str
    old_subname: str
    new_subname: Optional[str] = None
    delete: bool = False

class MergeCategoriesRequest(BaseModel):
    source_name: str
    target_name: str

class BulkMoveRequest(BaseModel):
    file_ids: List[str] = []
    target_category: str
    target_subcategory: str = ""


# --- Endpoints ---

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}

@app.post("/scan")
async def scan_directory(request: ScanRequest):
    try:
        validate_path(request.directory, _sandbox_folders())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Run scan in thread pool so it doesn't block the event loop
    import asyncio
    scanner = FileScanner(max_files=request.max_files)
    loop = asyncio.get_event_loop()
    files = await loop.run_in_executor(None, scanner.scan_directory, request.directory)
    return {"files": files, "errors": scanner.errors, "count": scanner.scanned_count}

@app.post("/categorize")
def categorize_files(request: CategorizeRequest):
    """Design a new folder tree for the scanned files (see tree_architect).

    Returns the category tree for the frontend to render, plus a ``summary``
    comparing the current folder structure with the proposed one.
    """
    import json as _json
    import time as _time

    total = len(request.files)
    if total == 0:
        return {"categories": [], "total_files": 0, "total_categorized": 0}

    # Enrich files with face detection + EXIF before LLM categorization
    # Face detection + clustering add faces_detected and cluster_label per face.
    # EXIF extraction adds camera, GPS, date, dimensions for image files.
    # All three degrade gracefully — no crash if insightface/PIL unavailable.
    files = request.files
    if face_clustering_enabled():
        detector = FaceDetector()
        detect_faces_for_scan(files, detector)
        cluster_faces_from_scan(files)
    for f in files:
        f["exif"] = extract_exif(f.get("path", ""))

    llm = LLMManager()
    llm.load_model()

    # Emit start
    print(_json.dumps({"event": "categorize_start", "total": total}), flush=True)

    # Design the tree
    _cat_start = _time.monotonic()
    result = llm.categorize_all(files, _sandbox_folders(), scan_root=request.directory,
                               prefs=load_preferences(), feedback=load_feedback())
    _cat_elapsed = _time.monotonic() - _cat_start

    # Emit completion
    print(_json.dumps({"event": "categorize_complete", "total": total, "elapsed_seconds": round(_cat_elapsed, 1)}), flush=True)

    # Convert the designed tree → frontend format. Every file carries the
    # organised root it will be moved under, so execution builds ONE tree at
    # <dest_root>/<Category>/<sub/path>/ instead of nesting inside each
    # file's current folder.
    dest_root = os.path.abspath(request.directory) if request.directory else ""
    categories_list = []
    categorized_count = 0

    def _entry(f: dict, cat_name: str, sub_name: str, rationale: str) -> dict:
        rel = "/".join(x for x in (cat_name, sub_name, f.get("filename", "")) if x)
        return {
            "file_id": f.get("file_id", ""),
            "filename": f.get("filename", ""),
            "path": f.get("path", ""),
            "proposed_path": rel,
            "dest_root": dest_root,
            "size_bytes": f.get("size_bytes", 0),
            "rationale": rationale,
            "confidence": 0.0 if cat_name == TO_SORT else 0.8,
            "tags": [],
        }

    for node in result.get("tree", []):
        cat_name = node.get("category", TO_SORT)
        cat_children = []
        cat_count = 0
        for sub in node.get("subbuckets", []):
            sub_name = sub.get("subcategory", "")
            rationale = sub.get("rationale") or node.get("rationale", "")
            entries = [
                _entry(request.files[fid], cat_name, sub_name, rationale)
                for fid in sub.get("files", []) if 0 <= fid < total
            ]
            cat_count += len(entries)
            if sub_name:
                cat_children.append({"name": sub_name, "count": len(entries),
                                     "rationale": rationale, "files": entries})
            else:
                cat_children.extend({"name": e["filename"], **e} for e in entries)

        if cat_name not in (TO_SORT, "Uncategorized"):
            categorized_count += cat_count

        categories_list.append({
            "name": cat_name,
            "count": cat_count,
            "rationale": node.get("rationale", ""),
            "children": cat_children,
        })

    summary = result.get("summary", {})

    # Merge into persistent tree and save
    existing = _load_tree()
    _save_tree({
        "tree": categories_list,
        "approved_structure": existing.get("approved_structure", False),
        "total_files": total,
        "total_categorized": categorized_count,
        "summary": summary,
    })

    return {
        "categories": categories_list,
        "total_files": total,
        "total_categorized": categorized_count,
        "summary": summary,
    }

@app.post("/approve")
async def approve_and_clean(request: ApprovalRequest):
    sandbox_folders = _sandbox_folders()
    results = []
    for proposal in request.proposals:
        if proposal.file_id in request.approved_ids:
            try:
                validate_path(proposal.current_path, sandbox_folders)
                validate_path(proposal.proposed_path, sandbox_folders)
                # TODO: Execute move with trash safety
                results.append({"file_id": proposal.file_id, "status": "moved"})
            except Exception as e:
                results.append({"file_id": proposal.file_id, "status": "error", "detail": str(e)})
    return {"results": results}

@app.get("/buckets", response_model=List[Bucket])
async def get_buckets():
    # Read from settings.json (shared with Rust settings)
    try:
        with open(SETTINGS_PATH, "r") as f:
            data = json.load(f)
            buckets = data.get("buckets", [])
            return [Bucket(**b) for b in buckets]
    except (OSError, json.JSONDecodeError):
        return []

@app.post("/buckets")
async def add_bucket(bucket: Bucket):
    # Read current settings, append bucket, save
    try:
        with open(SETTINGS_PATH, "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    buckets = data.get("buckets", [])
    # Generate ID if empty
    if not bucket.id:
        bucket.id = str(len(buckets) + 1)
    buckets.append(bucket.dict())
    data["buckets"] = buckets
    with open(SETTINGS_PATH, "w") as f:
        json.dump(data, f, indent=2)
    return {"id": bucket.id, "status": "created"}

@app.get("/progress")
async def get_progress():
    return {"progress": 0.0, "status": "idle"}

@app.post("/metadata")
async def write_metadata(file_path: str, tags: List[str]):
    validate_path(file_path, _sandbox_folders())
    # TODO: Integrate ExifTool
    return {"file": file_path, "tags_written": len(tags)}

@app.post("/faces/detect")
def detect_faces(directory: str):
    """Detect faces in all images in a directory (Slice 6A)."""
    validate_path(directory, _sandbox_folders())
    scanner = FileScanner()
    scan_results = scanner.scan_directory(directory)
    detector = FaceDetector()
    if not detector.available:
        return {"status": "unavailable", "error": detector.error, "faces_found": 0}
    detect_faces_for_scan(scan_results, detector)
    total_faces = sum(len(f.get("faces_detected", [])) for f in scan_results)
    return {
        "status": "ok",
        "files_scanned": len(scan_results),
        "faces_found": total_faces,
        "error": detector.error,
    }

@app.post("/faces/cluster")
def cluster_faces(directory: str):
    """Detect + cluster faces in a directory (Slice 6A + 6B combined)."""
    validate_path(directory, _sandbox_folders())
    scanner = FileScanner()
    scan_results = scanner.scan_directory(directory)
    detector = FaceDetector()
    if not detector.available:
        return {"clusters": [], "status": "unavailable", "error": detector.error}
    detect_faces_for_scan(scan_results, detector)
    result = cluster_faces_from_scan(scan_results)
    clusterer = FaceClusterer()
    clusters = clusterer.get_clusters_for_ui()
    return {
        "clusters": clusters,
        "status": "ok",
        "n_clusters": result["n_clusters"],
        "n_noise": result["n_noise"],
        "error": detector.error,
    }

@app.get("/faces/clusters")
async def get_clusters():
    """Get all face clusters from the SQLite index (for UI)."""
    clusterer = FaceClusterer()
    clusters = get_clusters_for_ui(clusterer, _sandbox_folders())
    return {"clusters": clusters}

@app.post("/faces/tag")
async def tag_face_cluster(request: TagFaceRequest):
    """Rename a cluster and write XMP:PersonInImage to all photos (Slice 6C)."""
    try:
        cluster_id = int(request.cluster_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="cluster_id must be an integer")
    clusterer = FaceClusterer()
    result = rename_cluster_with_tags(clusterer, cluster_id, request.name, _sandbox_folders())
    return result


# --- Persistent Tree Endpoints ---

def _load_tree() -> dict:
    """Load tree from disk, return empty state if not found."""
    try:
        with open(TREE_PATH, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"tree": [], "approved_structure": False, "total_files": 0, "total_categorized": 0}

def _save_tree(data: dict) -> None:
    """Save tree to disk."""
    os.makedirs(os.path.dirname(TREE_PATH), exist_ok=True)
    with open(TREE_PATH, "w") as f:
        json.dump(data, f, indent=2)

@app.get("/tree")
async def get_tree():
    """Load the persistent categorization tree."""
    return _load_tree()

@app.post("/tree")
async def save_tree(state: TreeState):
    """Save the full tree state."""
    _save_tree(state.dict())
    return {"status": "ok"}

@app.put("/tree/merge")
async def merge_tree(request: MergeRequest):
    """Merge new categorization results into the existing persistent tree.
    New files go into their categories; existing files keep their assigned categories."""
    existing = _load_tree()
    existing_tree = existing.get("tree", [])
    # Build index of existing files by file_id
    seen: dict[str, tuple[str, str]] = {}  # file_id → (category, subcategory)
    for cat in existing_tree:
        cat_name = cat.get("name", "")
        for child in cat.get("children", []):
            if child.get("files"):
                # subcategory with files
                sub_name = child.get("name", "")
                for f in child["files"]:
                    seen[f.get("file_id", "")] = (cat_name, sub_name)
            elif child.get("file_id"):
                # direct file entry
                seen[child["file_id"]] = (cat_name, "")

    # Merge new categories into existing tree
    for new_cat in request.categories:
        new_name = new_cat.get("name", "Uncategorized")
        # Find or create the category in existing tree
        existing_cat = None
        for c in existing_tree:
            if c.get("name", "") == new_name:
                existing_cat = c
                break
        if not existing_cat:
            existing_cat = {"name": new_name, "children": []}
            existing_tree.append(existing_cat)

        for child in new_cat.get("children", []):
            if child.get("files"):
                # subcategory with files
                sub_name = child.get("name", "")
                existing_sub = None
                for s in existing_cat["children"]:
                    if s.get("name") == sub_name and s.get("files"):
                        existing_sub = s
                        break
                if not existing_sub:
                    existing_sub = {"name": sub_name, "files": []}
                    existing_cat["children"].append(existing_sub)
                for f in child["files"]:
                    fid = f.get("file_id", "")
                    if fid not in seen:
                        existing_sub["files"].append(f)
                        seen[fid] = (new_name, sub_name)
            elif child.get("file_id"):
                # direct file entry — add to category if not seen
                fid = child.get("file_id", "")
                if fid not in seen:
                    existing_cat["children"].append(child)
                    seen[fid] = (new_name, "")

    # Update counts
    total = request.total_files + existing.get("total_files", 0)
    cat_count = request.total_categorized + existing.get("total_categorized", 0)
    summary = existing.get("summary", {})
    _save_tree({
        "tree": existing_tree,
        "approved_structure": existing.get("approved_structure", False),
        "total_files": total,
        "total_categorized": cat_count,
        "summary": summary,
    })
    return {"status": "ok", "tree": existing_tree, "total_files": total,
            "total_categorized": cat_count, "summary": summary}

@app.put("/tree/category")
async def edit_category(edit: CategoryEdit):
    """Rename, move, or delete a category."""
    data = _load_tree()
    tree = data.get("tree", [])
    if edit.delete:
        # Move files to Uncategorized, remove category
        new_tree = []
        uncategorized = None
        for cat in tree:
            if cat.get("name") == edit.old_name:
                # create Uncategorized if not exists
                if not uncategorized:
                    uncategorized = {"name": "Uncategorized", "children": []}
                    new_tree.append(uncategorized)
                # move all subcategories/files to Uncategorized
                for child in cat.get("children", []):
                    uncategorized["children"].append(child)
            else:
                if cat.get("name") == "Uncategorized" and not uncategorized:
                    uncategorized = cat
                new_tree.append(cat)
        tree = new_tree
    elif edit.new_name:
        # Rename
        for cat in tree:
            if cat.get("name") == edit.old_name:
                cat["name"] = edit.new_name
                break
    data["tree"] = tree
    _save_tree(data)
    return {"status": "ok", "tree": tree}

def _is_subfolder(child: dict) -> bool:
    """A sub-folder entry (even an emptied one), as opposed to a direct file entry."""
    return "files" in child and not child.get("file_id")


@app.put("/tree/file")
async def move_file(move: FileMove):
    """Move a file between categories/subcategories in the tree."""
    data = _load_tree()
    tree = data.get("tree", [])
    # Find and remove file from current location
    found_file = None
    for cat in tree:
        for i, child in enumerate(cat.get("children", [])):
            if child.get("files"):
                for j, f in enumerate(child["files"]):
                    if f.get("file_id") == move.file_id:
                        found_file = child["files"].pop(j)
                        break
            elif child.get("file_id") == move.file_id:
                found_file = cat["children"].pop(i)
                break
        if found_file:
            break
    if not found_file:
        raise HTTPException(status_code=404, detail="File not found in tree")
    # Ensure found_file is a dict with file_id
    if not isinstance(found_file, dict):
        found_file = found_file.dict() if hasattr(found_file, 'dict') else dict(found_file)
    # Find or create target category
    target_cat = None
    for cat in tree:
        if cat.get("name") == move.target_category:
            target_cat = cat
            break
    if not target_cat:
        target_cat = {"name": move.target_category, "children": []}
        tree.append(target_cat)
    # Find or create target subcategory
    if move.target_subcategory:
        target_sub = None
        for child in target_cat["children"]:
            if child.get("name") == move.target_subcategory and _is_subfolder(child):
                target_sub = child
                break
        if not target_sub:
            target_sub = {"name": move.target_subcategory, "files": []}
            target_cat["children"].append(target_sub)
        target_sub["files"].append(found_file)
    else:
        target_cat["children"].append(found_file)
    data["tree"] = tree
    _save_tree(data)
    return {"status": "ok", "tree": tree}

@app.post("/tree/approve")
async def approve_structure():
    """Mark the tree structure as approved by the user."""
    data = _load_tree()
    data["approved_structure"] = True
    _save_tree(data)
    return {"status": "ok"}

def _unique_dest(dest: str) -> str:
    """Never overwrite: 'a.pdf' -> 'a (2).pdf' when the name is taken."""
    if not os.path.exists(dest):
        return dest
    stem, ext = os.path.splitext(dest)
    n = 2
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


def _tree_file_entries(tree: list):
    """Yield (category, subcategory, file_entry) for every file in the tree."""
    for cat in tree:
        cat_name = cat.get("name", "")
        for child in cat.get("children", []):
            if child.get("files"):
                for f in child["files"]:
                    yield cat_name, child.get("name", ""), f
            elif child.get("file_id"):
                yield cat_name, "", child


def _prune_empty_dirs(start: str, stop: str) -> None:
    """Remove folders emptied by the moves, up to (not including) the root."""
    stop = os.path.abspath(stop) if stop else ""
    cur = os.path.abspath(start)
    while stop and cur != stop and cur.startswith(stop + os.sep):
        try:
            os.rmdir(cur)  # only succeeds when empty
        except OSError:
            return
        cur = os.path.dirname(cur)


@app.post("/tree/execute")
async def execute_moves(approved_file_ids: List[str]):
    """Move approved files on disk into the designed tree.

    Files go to <dest_root>/<Category>/<sub/path>/<filename>, where dest_root is
    the folder that was scanned — one organised tree, not a copy of the
    category folders inside every existing folder. Name clashes get a
    ' (2)' suffix; nothing is ever overwritten. 'To Sort' files stay put.
    """
    import shutil
    data = _load_tree()
    tree = data.get("tree", [])
    sandbox = _sandbox_folders() or []
    approved = set(approved_file_ids)
    entries = list(_tree_file_entries(tree))
    sources = [f.get("path", "") for _, _, f in entries if f.get("path")]
    fallback_root = os.path.commonpath(sources) if sources else ""
    if fallback_root and os.path.isfile(fallback_root):
        fallback_root = os.path.dirname(fallback_root)
    results = []
    moved_paths = []
    for cat_name, sub_name, f in entries:
        fid = f.get("file_id", "")
        if fid not in approved or cat_name in ("Uncategorized", TO_SORT):
            continue
        src = f.get("path", "")
        if not src:
            results.append({"file_id": fid, "status": "error", "detail": "no source path"})
            continue
        try:
            validate_path(src, sandbox)
            root = f.get("dest_root") or fallback_root
            parts = [p for p in sub_name.split("/") if p and p not in (".", "..")]
            dest_dir = os.path.join(root, cat_name, *parts)
            dest = os.path.join(dest_dir, f.get("filename") or os.path.basename(src))
            validate_path(dest, sandbox)
            if os.path.abspath(src) == os.path.abspath(dest):
                results.append({"file_id": fid, "status": "already_in_place"})
                continue
            os.makedirs(dest_dir, exist_ok=True)
            dest = _unique_dest(dest)
            shutil.move(src, dest)
            f["path"] = dest
            moved_paths.append((src, dest))
            results.append({"file_id": fid, "status": "moved", "dest": dest})
            _prune_empty_dirs(os.path.dirname(src), root)
        except Exception as e:
            results.append({"file_id": fid, "status": "error", "detail": str(e)})
    if moved_paths:
        _save_tree(data)  # keep tree paths in sync with disk
        fb = load_feedback()  # and keep the user's rules attached to the moved files
        for old, new in moved_paths:
            fb.file_moved(old, new)
        save_feedback(fb)
    return {"results": results}


@app.get("/preferences")
async def get_preferences():
    """The user's saved tree preferences (defaults if never answered)."""
    return load_preferences().to_dict()


@app.put("/preferences")
async def put_preferences(data: dict):
    """Save the answers from the preference check; applied to every later build."""
    prefs = Preferences.from_dict({**data, "answered": True})
    for folder in prefs.protected:
        try:
            validate_path(folder, _sandbox_folders())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    save_preferences(prefs)
    return prefs.to_dict()


@app.post("/tree/choices")
def tree_choices(request: CategorizeRequest):
    """Preference check: questions whose options are previewed on the user's own files."""
    if request.directory:
        try:
            validate_path(request.directory, _sandbox_folders())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    files = request.files
    for f in files:
        if "exif" not in f:
            f["exif"] = extract_exif(f.get("path", ""))
    architect = TreeArchitect(request.directory, prefs=load_preferences())
    return architect.preview_choices(files)


class FeedbackRequest(BaseModel):
    action: Literal["pin", "unpin", "exclude", "include", "rename", "reset"]
    path: str = ""            # folder path in the tree: "Category/sub/path"
    new_path: str = ""        # rename only
    file_ids: List[str] = []  # files from the current tree...
    files: List[str] = []     # ...or absolute file paths


def _tree_folder_files(folder: str) -> List[str]:
    """Paths of the files currently in a tree folder (and the folders below it)."""
    folder = clean_folder_path(folder)
    out = []
    for cat, sub, f in _tree_file_entries(_load_tree().get("tree", [])):
        here = clean_folder_path(f"{cat}/{sub}" if sub else cat)
        if f.get("path") and (here == folder or here.startswith(folder + "/")):
            out.append(f["path"])
    return out


@app.post("/tree/feedback")
async def record_feedback(req: FeedbackRequest):
    """Record a tree edit as a rule the builder follows on every rebuild.

    pin      path + files/file_ids — these files belong in this folder; with no
             files, pins everything currently in that folder ("accept folder").
    unpin    files, or a whole folder via path — let the builder decide again.
    exclude  files — leave them out of the plan; include undoes it.
    rename   path -> new_path — moves the folder's pins and pins its files.
    reset    forget every rule.
    """
    assert req.action in FEEDBACK_ACTIONS
    files = list(req.files)
    if req.file_ids:
        by_id = {f.get("file_id"): f.get("path") for _, _, f in _tree_file_entries(_load_tree().get("tree", []))}
        missing = [i for i in req.file_ids if not by_id.get(i)]
        if missing:
            raise HTTPException(status_code=400, detail=f"unknown file ids: {', '.join(missing[:5])}")
        files += [by_id[i] for i in req.file_ids]
    if req.action in ("pin", "rename") and not files and req.path:
        files = _tree_folder_files(req.path)
    sandbox = _sandbox_folders()
    for f in files:
        try:
            validate_path(f, sandbox)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    fb = load_feedback()
    try:
        fb.apply(req.action, files, req.path, req.new_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    save_feedback(fb)
    return _feedback_view(fb)


@app.get("/tree/feedback")
async def get_feedback():
    return _feedback_view(load_feedback())


def _feedback_view(fb) -> dict:
    return {
        "folders": [{"path": k, "files": len(v)} for k, v in sorted(fb.folders().items())],
        "pinned_files": len(fb.pins),
        "excluded_files": len(fb.excluded),
    }


class RouteRequest(BaseModel):
    files: List[dict] = []
    directory: str = ""


@app.post("/tree/route")
def route_files(request: RouteRequest):
    """Suggest where new files belong in the approved tree ("keep it live")."""
    router = TreeRouter(load_model())
    return {"suggestions": [
        {"file_id": f.get("file_id", ""), **router.route(f, request.directory)}
        for f in request.files
    ]}


@app.put("/tree/subcategory")
async def edit_subcategory(edit: SubcategoryEdit):
    """Rename or delete a subcategory within a category.
    Delete moves files to parent category (as direct children)."""
    data = _load_tree()
    tree = data.get("tree", [])
    for cat in tree:
        if cat.get("name") != edit.category_name:
            continue
        children = cat.get("children", [])
        if edit.delete:
            # Move files from subcategory to parent category as direct children
            new_children = []
            for child in children:
                if child.get("name") == edit.old_subname and child.get("files"):
                    # Promote files to direct children of category
                    for f in child["files"]:
                        new_children.append(f)
                else:
                    new_children.append(child)
            cat["children"] = new_children
        elif edit.new_subname:
            for child in children:
                if child.get("name") == edit.old_subname and child.get("files"):
                    child["name"] = edit.new_subname
                    break
        break
    data["tree"] = tree
    _save_tree(data)
    return {"status": "ok", "tree": tree}


@app.put("/tree/merge-categories")
async def merge_categories_endpoint(req: MergeCategoriesRequest):
    """Merge source category into target. Moves all children to target, removes source."""
    data = _load_tree()
    tree = data.get("tree", [])
    source_cat = None
    target_cat = None
    for cat in tree:
        if cat.get("name") == req.source_name:
            source_cat = cat
        if cat.get("name") == req.target_name:
            target_cat = cat
    if not source_cat:
        raise HTTPException(status_code=404, detail=f"Source category '{req.source_name}' not found")
    if not target_cat:
        raise HTTPException(status_code=404, detail=f"Target category '{req.target_name}' not found")
    if source_cat is target_cat:
        raise HTTPException(status_code=400, detail="Cannot merge category into itself")
    # Move all children from source to target
    for child in source_cat.get("children", []):
        target_cat["children"].append(child)
    # Remove source from tree
    tree = [c for c in tree if c.get("name") != req.source_name]
    data["tree"] = tree
    _save_tree(data)
    return {"status": "ok", "tree": tree}


@app.put("/tree/bulk-move")
async def bulk_move_files(req: BulkMoveRequest):
    """Move multiple files to a target category/subcategory at once."""
    data = _load_tree()
    tree = data.get("tree", [])
    # Collect and remove all target files from their current locations
    found_files = []
    wanted = set(req.file_ids)
    for cat in tree:
        kept_children = []  # rebuilt, never popped while iterating (that skipped neighbours)
        for child in cat.get("children", []):
            if _is_subfolder(child):
                remaining = []
                for f in child["files"]:
                    (found_files if f.get("file_id") in wanted else remaining).append(f)
                child["files"] = remaining
                kept_children.append(child)
            elif child.get("file_id") in wanted:
                found_files.append(child)
            else:
                kept_children.append(child)
        cat["children"] = kept_children
    # Find or create target category
    target_cat = None
    for cat in tree:
        if cat.get("name") == req.target_category:
            target_cat = cat
            break
    if not target_cat:
        target_cat = {"name": req.target_category, "children": []}
        tree.append(target_cat)
    if req.target_subcategory:
        target_sub = None
        for child in target_cat["children"]:
            if child.get("name") == req.target_subcategory and _is_subfolder(child):
                target_sub = child
                break
        if not target_sub:
            target_sub = {"name": req.target_subcategory, "files": []}
            target_cat["children"].append(target_sub)
        target_sub["files"].extend(found_files)
    else:
        target_cat["children"].extend(found_files)
    data["tree"] = tree
    _save_tree(data)
    return {"status": "ok", "tree": tree, "moved": len(found_files)}