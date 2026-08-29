"""
The Maid — FastAPI HTTP Server
Handles all requests from Tauri frontend.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import json
import os

from .scanner import FileScanner
from .sandbox import validate_path
from .models import LLMManager
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

class TreeSubCategory(BaseModel):
    name: str = ""
    files: List[TreeFileEntry] = []

class TreeCategoryModel(BaseModel):
    name: str = ""
    children: List[TreeSubCategory] = []

class TreeState(BaseModel):
    tree: List[TreeCategoryModel] = []
    approved_structure: bool = False
    total_files: int = 0
    total_categorized: int = 0

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
async def categorize_files(request: CategorizeRequest):
    """Two-tier categorization pipeline.

    Tier 1: Sub-agents categorize files per-folder → local category trees
    Tier 2: Main agent merges all sub-trees → unified tree

    Returns a category tree structure for the frontend to render.
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
    detector = FaceDetector()
    detect_faces_for_scan(files, detector)
    cluster_faces_from_scan(files)
    for f in files:
        f["exif"] = extract_exif(f.get("path", ""))

    llm = LLMManager()
    llm_loaded = llm.load_model()

    # Emit start
    print(_json.dumps({"event": "categorize_start", "total": total}), flush=True)

    # Run the two-tier pipeline
    _cat_start = _time.monotonic()
    result = llm.categorize_all(files, _sandbox_folders(), scan_root=request.directory)
    _cat_elapsed = _time.monotonic() - _cat_start

    # Emit completion
    print(_json.dumps({"event": "categorize_complete", "total": total, "elapsed_seconds": round(_cat_elapsed, 1)}), flush=True)

    # Convert unified tree → frontend format
    categories_list = []
    categorized_count = 0

    for node in result.get("tree", []):
        cat_name = node.get("category", "Uncategorized")
        subbuckets = node.get("subbuckets", [])
        rationale = node.get("rationale", "")

        cat_children = []
        cat_count = 0

        for sub in subbuckets:
            sub_name = sub.get("subcategory", "")
            file_ids = sub.get("files", [])
            cat_count += len(file_ids)

            if sub_name:
                # Named subcategory → nested bucket
                sub_files = []
                for fid in file_ids:
                    if 0 <= fid < total:
                        f = request.files[fid]
                        current = f.get("path", "")
                        proposed = f"{cat_name}/{sub_name}/{f.get('filename', '')}" if sub_name else f"{cat_name}/{f.get('filename', '')}"
                        sub_files.append({
                            "file_id": f.get("file_id", ""),
                            "filename": f.get("filename", ""),
                            "path": current,
                            "proposed_path": proposed,
                            "size_bytes": f.get("size_bytes", 0),
                            "rationale": rationale,
                            "confidence": 0.8,
                            "tags": [],
                        })
                cat_children.append({
                    "name": sub_name,
                    "count": len(sub_files),
                    "files": sub_files,
                })
            else:
                # No subcategory → files directly under category
                for fid in file_ids:
                    if 0 <= fid < total:
                        f = request.files[fid]
                        current = f.get("path", "")
                        proposed = f"{cat_name}/{f.get('filename', '')}"
                        cat_children.append({
                            "name": f.get("filename", ""),
                            "file_id": f.get("file_id", ""),
                            "filename": f.get("filename", ""),
                            "path": current,
                            "proposed_path": proposed,
                            "size_bytes": f.get("size_bytes", 0),
                            "rationale": rationale,
                            "confidence": 0.8,
                            "tags": [],
                        })

        if cat_name != "Uncategorized":
            categorized_count += cat_count

        categories_list.append({
            "name": cat_name,
            "count": cat_count,
            "children": cat_children,
        })

    # Sort by count descending
    categories_list.sort(key=lambda c: c["count"], reverse=True)

    # Merge into persistent tree and save
    existing = _load_tree()
    _save_tree({
        "tree": categories_list,
        "approved_structure": existing.get("approved_structure", False),
        "total_files": total,
        "total_categorized": categorized_count,
    })

    return {
        "categories": categories_list,
        "total_files": total,
        "total_categorized": categorized_count,
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
async def detect_faces(directory: str):
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
async def cluster_faces(directory: str):
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
    _save_tree({
        "tree": existing_tree,
        "approved_structure": existing.get("approved_structure", False),
        "total_files": total,
        "total_categorized": cat_count,
    })
    return {"status": "ok", "tree": existing_tree, "total_files": total, "total_categorized": cat_count}

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
            if child.get("name") == move.target_subcategory and child.get("files"):
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

@app.post("/tree/execute")
async def execute_moves(approved_file_ids: List[str]):
    """Move approved files on disk according to the tree. Uses trash for safety."""
    import shutil
    import send2trash
    data = _load_tree()
    tree = data.get("tree", [])
    sandbox = _sandbox_folders() or []
    results = []
    for cat in tree:
        cat_name = cat.get("name", "")
        if cat_name == "Uncategorized":
            continue
        for child in cat.get("children", []):
            if child.get("files"):
                sub_name = child.get("name", "")
                for f in child["files"]:
                    fid = f.get("file_id", "")
                    if fid not in approved_file_ids:
                        continue
                    src = f.get("path", "")
                    if not src:
                        results.append({"file_id": fid, "status": "error", "detail": "no source path"})
                        continue
                    try:
                        validate_path(src, sandbox)
                        dest_dir = os.path.join(os.path.dirname(src), cat_name, sub_name) if sub_name else os.path.join(os.path.dirname(src), cat_name)
                        os.makedirs(dest_dir, exist_ok=True)
                        dest = os.path.join(dest_dir, f.get("filename", os.path.basename(src)))
                        if os.path.exists(dest) and os.path.abspath(src) != os.path.abspath(dest):
                            # Conflict: trash the existing one (recoverable)
                            send2trash.send2trash(dest)
                        if os.path.abspath(src) != os.path.abspath(dest):
                            shutil.move(src, dest)
                            results.append({"file_id": fid, "status": "moved", "dest": dest})
                        else:
                            results.append({"file_id": fid, "status": "already_in_place"})
                    except Exception as e:
                        results.append({"file_id": fid, "status": "error", "detail": str(e)})
    return {"results": results}