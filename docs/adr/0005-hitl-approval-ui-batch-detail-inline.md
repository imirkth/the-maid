# ADR 0005: HITL Approval UI — Batch + Detail + Inline Editing

## Status
Accepted

## Context
The HITL approval UI needs to balance speed (simple) with control (granular). Users will encounter misclassified files.

## Decision
**Three-tier approval UI:**

1. **Default (Simple):** One checkbox per file. Approve/reject the entire proposal (move + tags + faces).
2. **Advanced Toggle:** Expands rows to show granular controls — approve/reject: move, individual tags, face names per file.
3. **Inline Editing:** Click any proposed path to edit/reallocate manually. User can type a new destination or select from existing buckets.

## Rationale
- 80% case: fast batch approval with simple checkboxes
- 20% case: granular control for edge cases and corrections
- Inline editing handles the "almost right but wrong folder" case without rejecting the whole proposal
- Extends HITL principle: AI proposes, user has final say on every dimension

## UI States
- Simple: `[✓] IMG_9921.JPG → Pictures/Bali-22/IMG_9921.JPG`
- Advanced: `[✓] Move [✓] Tags [ ] Faces`
- Editing: click path → inline text input or dropdown picker

## Trade-offs
- More UI complexity to implement
- Need to validate edited paths (sandbox guardrails still apply)
- But: reduces friction significantly vs. reject-and-rescan workflow

## Consequences
- Approval UI needs three rendering modes
- JSON schema needs `user_edited_path` override field
- Backend must validate edited paths against sandbox boundaries
