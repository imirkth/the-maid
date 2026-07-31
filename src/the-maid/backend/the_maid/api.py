"""
The Maid — FastAPI HTTP Server
Handles all requests from Tauri frontend.
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import os
import uuid

from .scanner import FileScanner
from .sandbox import validate_path
from .models import LLMManager

app = FastAPI(title="The Maid API", version="0.1.0")

# CORS for development (Tauri dev server on :1420)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "http://127.0.0.1:1420"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Models ---

class ScanRequest(BaseModel):
    directory: str = Field(..., description="Absolute path to scan")
    max_files: int = Field(default=10000, ge=1, le=50000)

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

# --- Endpoints ---

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}

@app.post("/scan")
async def scan_directory(request: ScanRequest):
    """Scan a directory and return file metadata.
    Returns raw file list — AI categorization happens in a later stage.
    Emits progress events via stdout for Tauri event forwarding."""
    try:
        validate_path(request.directory)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    scanner = FileScanner(max_files=request.max_files)
    files = scanner.scan_directory(request.directory)
    return {"files": files, "errors": scanner.errors, "count": scanner.scanned_count}

@app.post("/approve")
async def approve_and_clean(request: ApprovalRequest):
    """Execute approved file moves."""
    results = []
    for proposal in request.proposals:
        if proposal.file_id in request.approved_ids:
            try:
                validate_path(proposal.current_path)
                validate_path(proposal.proposed_path)
                # TODO: Execute move with trash safety
                results.append({"file_id": proposal.file_id, "status": "moved"})
            except Exception as e:
                results.append({"file_id": proposal.file_id, "status": "error", "detail": str(e)})
    return {"results": results}

@app.get("/buckets", response_model=List[Bucket])
async def get_buckets():
    """Get user's approved destination buckets."""
    # TODO: Load from ~/.the-maid/buckets.json
    return [
        Bucket(id="1", name="Desktop", path="~/Desktop"),
        Bucket(id="2", name="Documents", path="~/Documents"),
        Bucket(id="3", name="Pictures", path="~/Pictures"),
    ]

@app.post("/buckets")
async def add_bucket(bucket: Bucket):
    """Add a new approved bucket."""
    validate_path(bucket.path)
    # TODO: Save to buckets.json
    return {"id": bucket.id, "status": "created"}

@app.get("/progress")
async def get_progress():
    """Get current scan progress (0.0 - 1.0)."""
    # TODO: Implement progress tracking
    return {"progress": 0.0, "status": "idle"}

@app.post("/metadata")
async def write_metadata(file_path: str, tags: List[str]):
    """Write IPTC/XMP tags to a file via ExifTool."""
    validate_path(file_path)
    # TODO: Integrate ExifTool
    return {"file": file_path, "tags_written": len(tags)}

@app.post("/faces/cluster")
async def cluster_faces(directory: str):
    """Cluster faces in images within a directory."""
    validate_path(directory)
    # TODO: Implement face clustering pipeline
    return {"clusters": [], "status": "not_implemented"}

@app.post("/faces/tag")
async def tag_face_cluster(request: TagFaceRequest):
    """Tag a face cluster with a name."""
    # TODO: Update SQLite face index and write XMP tags
    return {"cluster_id": request.cluster_id, "name": request.name, "status": "tagged"}
