# ADR 0009: Cleanup Plan JSON Schema — Short Hash IDs, Explicit Arrays, Absolute Paths

## Status
Accepted

## Context
The Cleanup Plan JSON payload is the contract between Python backend and Tauri frontend. Needs formal schema for validation, type safety, and future compatibility.

## Decision
**Schema rules:**
- `file_id`: 8-character hex string (short hash of `current_path`). Human-readable, unique within scan.
- All fields required — no optional fields except `user_edited_path` (ADR 0005 inline editing).
- `faces_detected`: always present, empty array `[]` if none — no nulls, no omissions.
- `proposed_path`: always absolute file path, resolved at generation time — not a bucket reference.

## Rationale
- **Short hash over UUID:** Easier for users to reference in logs, support, and UI lists. 8 chars = 4 billion combinations — collision risk within a single scan is negligible.
- **Explicit arrays:** Empty `[]` is unambiguous. Null vs omitted creates parser fragility.
- **Absolute paths:** Frontend doesn't need to resolve bucket references. Backend handles all path logic.

## Trade-offs
- **8-char limit:** Could theoretically collide in very large scans (100k+ files). Mitigated by including scan timestamp in hash salt.
- **No nulls:** Larger payloads for files with no faces/tags. Acceptable for simplicity.

## Consequences
- Python backend generates IDs with `hashlib.sha256(current_path.encode()).hexdigest()[:8]`.
- Frontend validates schema with strict required field checks.
- Schema version field added for future evolution: `"schema_version": "1.0.0"`.