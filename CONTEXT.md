# Domain Glossary — The Maid

## Product

- **The Maid** — A local-first AI file organizer & digital asset manager. One-time purchase native desktop app. Not SaaS. Also the in-app persona: speaks as "I" in all user-facing text during normal operation ("I found 47 files", "I suggest moving these to..."). Drops to third-person for technical errors ("The Maid encountered an error. Please restart the application.").
- **HITL** (Human-in-the-Loop) — The AI proposes, the human approves. Never auto-execute file moves.
- **Cleanup Plan** — A structured JSON payload of proposed file actions: `current_path` → `proposed_path` (a **Bucket**) + `metadata_tags`.
- **Bucket** — A user-approved folder path on disk. The Maid only proposes moves into sanctioned buckets. Renaming a bucket in the Bucket Manager renames the actual folder.
- **Execution Model** — Per-file atomicity. Each approved file move is independent. Partial execution is expected; The Maid reports per-file status. User retries failed items via the Approval UI.

## Core Principles

- **Absolute Privacy** — All processing local. Zero cloud uploads. No telemetry.
- **Metadata-First DAM** — Tags baked into files (IPTC/XMP), not locked in proprietary DB.
- **Sandboxed** — Only user-defined folders (default: `~/Desktop`, `~/Downloads`, `~/Documents`, `~/Pictures`). System dirs out of scope. Out-of-scope paths are hard-rejected. Scan button is disabled until at least one folder is selected for scanning.

## Pricing

- **One-time lifetime license** — $30–$50. No subscription, no recurring fees.

## Tech Stack

- **Frontend UI** — Tauri (React/Rust) for native desktop feel.
- **Backend Orchestrator** — Python or Rust.
- **LLM Engine** — Embedded `llama.cpp` sidecar or local Ollama if present. Small, fast models (1B-4B parameters).
- **Model Bundle** — Text LLM (~500MB) is always bundled. Face models (~100MB) and Vision/OCR model (~1GB) are optional downloads selected during setup.
- **Settings Persistence** — Tauri Store (cross-platform, encrypted, OS-native backup). Face embeddings use separate SQLite database (ADR 0006).
- **Face Recognition** — insightface or dlib + ArcFace (128D embeddings) + DBSCAN clustering.

## Pipeline Stages

- **Pre-Processing (Extraction)** — Read EXIF (images), rasterize PDF first page, extract text from .docx/.xlsx.
- **AI Routing** — Send extracted text to local LLM to map files to predefined folders.
- **Face Clustering** — Detect → Encode (ArcFace) → Cluster (DBSCAN) → Tag. Unknown faces are bucketed as `Unknown_Person_N`. Naming a cluster (e.g., "Sarah") writes `XMP:PersonInImage=Sarah` to **all** photos in that cluster, retroactively.

## Output Format

- **JSON Payload** — Array of file objects with `file_id`, `original_filename`, `current_path`, `proposed_path`, `proposed_tags`, `faces_detected`, `rationale`.

## File Types

- **Image/Video** — EXIF-based instant categorization when GPS/timestamp match known parameters.
- **PDF** — PyMuPDF rasterizes first page for OCR.
- **Word/Excel** — python-docx/pandas extract first 500 words or column headers. No vision models.
