# ADR 0004: Folder Structure — Hybrid Setup Wizard + User-Approved Buckets

## Status
Accepted

## Context
The Maid needs a destination folder vocabulary for proposed moves. Users may have messy existing structures.

## Decision
**Hybrid Setup Wizard:**
1. First run: quick preview scan suggests 5–10 common folders based on file content
2. User accepts, edits, merges, or adds their own buckets in a setup wizard
3. Approved buckets become the fixed target vocabulary for all future scans
4. Approval UI maps files to these user-sanctioned buckets only — no arbitrary new folders

## Rationale
- Prevents folder sprawl (200 folders for 200 unique subjects)
- Gives user agency without requiring full manual setup
- The Maid feels smart but never creates structures the user didn't approve
- User can edit vocabulary anytime (add/remove/rename buckets)
- Matches "intelligent taxonomist" positioning — proposes, user approves structure

## Trade-offs
- More complex first-run UX than silent auto-organize
- Requires persistence of "approved bucket list"
- But: HITL is core principle anyway — this extends it to folder structure

## Consequences
- Need "Setup Wizard" as first-run experience
- Need "Bucket Manager" in settings for later edits
- JSON schema needs "user_defined_buckets" field
- Approval UI shows bucket selector for uncertain mappings
