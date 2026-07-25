# The Maid — Build Plan

## Phase 1: Foundation (Current) — PARTIALLY COMPLETE
- [x] Set up Tauri project scaffolding (manual — `cargo create-tauri-app` non-interactive)
- [x] Verify Rust toolchain + cargo-tauri (rustc 1.97.1, cargo-create-tauri-app v4.7.3)
- [ ] Set up Python virtual environment
- [ ] Install core deps: PyMuPDF, python-docx, pandas, Pillow, pyexiftool
- [x] Create IPC layer (Rust ↔ Python) — FastAPI on :9473 stubbed
- [x] Build basic file scanner (recursive directory walk) — Python scanner module ready
- [ ] Add EXIF extraction for images
- [ ] Add text extraction for PDFs (first page only)
- [ ] Add text extraction for .docx/.xlsx (first 500 words)

## Phase 2: AI Integration
- [ ] Download llama.cpp binary (sidecar)
- [ ] Test with small model (qwen3:1.7b or gemma4:2b)
- [ ] Build prompt template for file categorization
- [ ] Implement JSON proposal schema
- [ ] Add rationale field to proposals
- [ ] Wire Rust → Python → llama.cpp inference pipeline

## Phase 3: HITL UI — PARTIALLY COMPLETE
- [x] Build approval checklist React component (simple + advanced toggle)
- [x] Show: current_path → proposed_path + tags + rationale
- [x] Allow unchecking individual items
- [x] "Approve & Clean" button
- [ ] Execute file moves via Rust fs commands (stubbed)

## Phase 4: Metadata Injection
- [ ] Integrate ExifTool wrapper
- [ ] Write IPTC/XMP keywords into image files
- [ ] Verify native OS search finds tagged files
- [ ] Test with Spotlight (macOS) and Windows Search

## Phase 5: Face Clustering
- [ ] Install insightface/dlib + ArcFace
- [ ] Detect faces in images (bounding boxes)
- [ ] Encode faces to 128D vectors
- [ ] Run DBSCAN clustering
- [ ] Generate Unknown_Person_XX buckets
- [ ] HITL: "Who is this?" → tag all clustered images
- [ ] Cache face embeddings for incremental scans

## Phase 6: Polish & Distribution
- [x] Sandbox enforcement (allowed dirs only) — regex implemented in Rust + Python
- [ ] Error handling & recovery
- [x] Progress bars for long scans — React component ready
- [ ] App icon & branding
- [ ] Build release binaries (Windows, macOS, Linux)
- [ ] Code signing (optional)
- [ ] Pricing page ($30–$50)
- [ ] Payment integration (Stripe/Paddle one-time)

## Decisions Locked (July 25)
1. **LLM:** `qwen3-1.7b` (GGUF, ~1GB) — smallest viable, good JSON instruction following
2. **IPC:** FastAPI HTTP on localhost:9473 — simplest to debug, language-agnostic
3. **OCR:** Qwen2.5-VL on-demand (downloadable) — better accuracy, optional download
4. **Sandbox:** Regex `^(/home/[^/]+|/[a-zA-Z]:)(Desktop|Downloads|Documents|Pictures|Videos|Music)`
5. **Performance:** 10,000 files max per scan, 5s timeout per file
6. **Onboarding:** 3-step wizard (folders → buckets → scan) — React component built

## Still Blocked
- Python venv setup + dependency install (needs `pip install`)
- Frontend npm install + vite dev server test
- llama.cpp model download (needs actual GGUF URL)