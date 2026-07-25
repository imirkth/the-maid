# ADR 0006: Face Embeddings — Local SQLite Database

## Status
Accepted

## Context
The face clustering pipeline generates 128D vectors (mathematical face fingerprints). Need to decide where these live.

## Decision
Store face embeddings in a **local SQLite database** (`~/.the-maid/face-index.db`).

## Rationale
- Face embeddings are machine-readable fingerprints, not human-readable tags
- Writing raw vectors into image metadata risks leaking face data if images are shared
- The "metadata-first DAM" principle applies to searchable/user-facing tags (names, subjects, locations)
- Machine-facing index data (embeddings, vector clusters) is acceptable in a local database
- The data never leaves the user's machine — fully owned by the user

## Trade-offs
- Introduces a local database (but only for machine-facing data, not searchable metadata)
- Need migration strategy if schema changes
- But: human-readable names still get written to image metadata via ExifTool

## Consequences
- SQLite file lives in `~/.the-maid/` (configurable)
- Images get `XMP:PersonInImage` tags (human names) — searchable by OS
- Embeddings stay local, never travel with shared files
- Future scans read embeddings from SQLite to match known faces

## Future
Could revisit hashing approach if user wants portable face index across devices.
