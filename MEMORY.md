# MEMORY.md - Long-Term Memory

## Project: The Maid

**Status:** Just spawned — initial setup phase.

**Concept:** Local-first AI file organizer & digital asset manager. $30–$50 one-time license. Zero cloud uploads.

**Golden Rule:** Human-In-The-Loop (HITL). AI proposes, human approves, then execute.

**Tech Stack:**
- Frontend: Tauri (React/Rust)
- Backend: Python or Rust
- LLM: Embedded llama.cpp (sidecar) or local Ollama
- Vision/OCR: Qwen2.5-VL, GLM-4.1V, olmocr2
- Metadata: ExifTool (IPTC/XMP)
- Face Recognition: insightface / dlib + ArcFace + DBSCAN

**Key Features:**
1. File scanning with tiered extraction (EXIF → OCR → AI)
2. Proposed cleanup plan with JSON schema
3. Metadata injection (IPTC/XMP keywords)
4. Face clustering (detect → encode → cluster → tag)
5. Native OS search integration (Spotlight, Windows Search)

**Sandbox:**
- Allowed: ~/Desktop, ~/Downloads, ~/Documents, ~/Pictures
- Forbidden: /bin, /usr, /etc, /Program Files, /System32

**Commercial:**
- Price: $30–$50 one-time lifetime license
- Target: Privacy-conscious users, professionals handling sensitive documents
- Distribution: Direct download (no app store dependency)

## Key Decisions
- _(To be filled as decisions are made)_

## Next Steps
1. Set up Tauri project scaffolding
2. Integrate llama.cpp sidecar binary
3. Build file scanner with EXIF extraction
4. Implement JSON proposal schema
5. Create approval UI (checklist)
6. Add face clustering pipeline
7. Test on real messy directories
