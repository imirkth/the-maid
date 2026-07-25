# Product Specification: "The Maid"
## Local-First AI File Organizer & Digital Asset Manager

### 1. Core Concept & Value Proposition
"The Maid" is a micro-SaaS desktop utility designed to solve the "Desktop of Doom" problem. It acts as an intelligent, privacy-first file organizer. Instead of blindly moving files, it acts as an intelligent taxonomist—scanning messy directories, using local AI to determine context, and generating a proposed cleanup plan.

**The Moat:** Absolute privacy. Zero cloud uploads. A $30–$50 one-time lifetime license. All processing happens locally, making it safe for financial PDFs, work documents, and personal photos.

### 2. The Golden Rule: Human-In-the-Loop (HITL)
The AI is strictly forbidden from executing file moves autonomously.
* The system generates a structured JSON payload of proposed actions (`current_path` -> `proposed_path` + `metadata_tags`).
* The user is presented with a simple checklist UI.
* The user reviews, unchecks any mistakes, and clicks "Approve & Clean".
* Execution happens instantaneously via native file system commands (`mv`).

### 3. System Architecture & Tech Stack
Designed to be lightweight and deployable as a standalone native app without requiring the user to manually install dependencies like Ollama.

* **Frontend UI:** Tauri (React/Rust) for a native desktop feel.
* **Backend Orchestrator:** Python or Rust.
* **LLM Engine:** Embedded `llama.cpp` (sidecar binary) or integration with local Ollama if present. Uses small, fast models (1B-4B parameters like `qwen3:4b` or `gemma4:e2b`).
* **Image Processing / OCR:** Fast vision models (e.g., `Qwen2.5-VL` or `GLM-4.1V` / `olmocr2`) optimized for OCR and tag generation.
* **Metadata Injection:** `ExifTool` (via Python wrapper) for writing IPTC/XMP tags.
* **Face Recognition:** `insightface` or `dlib` + ArcFace (for 128D embeddings) + DBSCAN (for unsupervised clustering).

### 4. Processing Pipeline & Routing Rules
To maintain speed and reduce compute, the system uses a tiered extraction approach before waking up the AI.

#### A. The Sandbox Guardrails
* The agent is strictly sandboxed. It can only read/write in user-defined folders (default: `~/Desktop`, `~/Downloads`, `~/Documents`, `~/Pictures`).
* System directories (`/bin`, `Program Files`, `System32`) are completely out of scope.

#### B. Pre-Processing (Extraction)
* **Images/Video:** Read EXIF data first (GPS, timestamp). If location/time match known parameters, categorize instantly without AI.
* **PDFs:** Use `PyMuPDF` to rasterize *only the first page* to an image for OCR.
* **Word/Excel (.docx, .xlsx):** Use `python-docx` and `pandas` to extract the first 500 words or column headers. Do not use vision models for these.

#### C. The AI Routing
* Extracted text is sent to the local LLM with a strict prompt: *"Based on this text, map this file to one of the user's predefined folders."*

### 5. Advanced Feature: Next-Gen Digital Asset Management (DAM)
The app does not maintain a proprietary, locked-in database for search. It modifies the files themselves.

* **Image Tagging:** When the vision model detects subjects ("receipt", "beach", "meme"), the system uses `ExifTool` to permanently write these as standard IPTC/XMP keywords directly into the JPEG/PNG file.
* **Searchability:** Because the tags are baked into the file DNA, native OS search (macOS Spotlight, Windows Search) can instantly find them regardless of the folder they reside in.

### 6. Face Clustering Pipeline (No Pre-Training Required)
The app groups people without needing to know who they are beforehand, matching the Apple/Google Photos experience locally.

1. **Detect:** Scan image for face geometry (Bounding box).
2. **Encode:** Run cropped face through ArcFace to generate a 128-dimensional mathematical vector.
3. **Cluster:** Run DBSCAN algorithm across all vectors in the directory to group identical vectors into buckets (e.g., `Unknown_Person_01`).
4. **Tag:** The HITL UI asks the user, "Who is this?" for a bucket. The user types a name, and `ExifTool` writes that name into the metadata of all 200 clustered photos simultaneously. Future scans detecting this 128D vector are automatically mapped to this name.

### 7. JSON Output Schema Example
The communication between the Python orchestrator and the Tauri UI must follow a strict schema:

```json
[
 {
 "file_id": "8f7d9a",
 "original_filename": "IMG_9921.JPG",
 "current_path": "/Users/user/Downloads/IMG_9921.JPG",
 "proposed_path": "/Users/user/Pictures/Bali-22/IMG_9921.JPG",
 "proposed_tags": ["beach", "sunset", "vacation"],
 "faces_detected": ["Unknown_Person_01"],
 "rationale": "EXIF GPS data matches Indonesia 2022; vision model detected beach environment."
 },
 {
 "file_id": "2b4c1x",
 "original_filename": "invoice_uber_jan.pdf",
 "current_path": "/Users/user/Desktop/invoice_uber_jan.pdf",
 "proposed_path": "/Users/user/Documents/Expenses_2026/invoice_uber_jan.pdf",
 "proposed_tags": ["receipt", "transport"],
 "faces_detected": [],
 "rationale": "Page 1 OCR extracted 'Uber' and 'Total: $24.50'."
 }
]
```