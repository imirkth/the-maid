# ADR 0008: Sandbox Enforcement — Hard Reject for Out-of-Scope Paths

## Status
Accepted

## Context
The Maid is sandboxed to user-defined folders (`~/Desktop`, `~/Downloads`, `~/Documents`, `~/Pictures`). System directories (`/bin`, `Program Files`, `System32`) are out of scope. Need to decide enforcement strategy when a user (or AI) attempts to target a forbidden path.

## Decision
**Hard reject** — any proposed move to a system directory or path outside the sandbox is immediately blocked with a clear error: "System directories are out of scope."

## Rationale
- **Privacy-first ethos:** The Maid is not a spyware. Allowing system access would violate the core trust proposition.
- **Security boundary:** A hard reject prevents accidental or malicious system compromise via the Approval UI or inline editor.
- **Simple user experience:** No ambiguous warnings or overrides — the boundary is absolute.

## Trade-offs
- **User flexibility:** Power users cannot manually override the sandbox, even intentionally.
- **Edge cases:** Network paths, mounted drives, or external storage may need explicit user approval to add to the sandbox.

## Consequences
- Rust backend validates all paths before Python orchestrator executes.
- Inline editor rejects out-of-scope paths in real-time.
- Error message is explicit: "System directories are out of scope."
- User can expand sandbox via Settings (add new allowed folders) but never system dirs.