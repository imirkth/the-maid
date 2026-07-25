# The Maid

Local-first AI file organizer & digital asset manager.
Privacy-native. Zero cloud. One-time license.

## Status
Just initialized. Waiting for kickoff.

## Architecture
- Tauri (React/Rust) desktop app
- Python orchestrator backend
- Embedded llama.cpp sidecar for local LLM
- ExifTool for metadata injection
- Face clustering: insightface/dlib + ArcFace + DBSCAN

## Key Principles
1. **Human-in-the-Loop (HITL)** — AI proposes, human approves. Never auto-execute moves.
2. **Absolute Privacy** — All processing local. No cloud uploads.
3. **Metadata-First DAM** — Tags baked into files (IPTC/XMP), not locked in proprietary DB.
4. **Sandboxed** — Only user-defined folders. System dirs out of scope.

## Next Steps
- [ ] Scaffold Tauri + React project
- [ ] Set up Python backend skeleton
- [ ] Integrate llama.cpp sidecar
- [ ] Build HITL approval UI
- [ ] Implement file extraction pipeline
- [ ] Add face clustering pipeline
- [ ] Metadata injection via ExifTool

## Links
- Product Spec: `specs/product-spec.md`
- Agent Skills: `skills/engineering/`

## Agent Skills

### Issue tracker
Local markdown tracker under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels
Default canonical roles. See `docs/agents/triage-labels.md`.

### Domain docs
Single-context — `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
