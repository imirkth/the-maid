# Recent Context

- **2026-07-26 evening**: Tester fix pass completed for all 5 Lightning donation bugs (#20–#24). Extracted `useDonation` hook as a testable seam, added regression tests, updated ADR 0011. TypeScript clean; 150 frontend tests pass; Rust verified via standalone harness (full `cargo test` blocked by missing GTK dev libs on host).
- **2026-07-25**: Completed bug review of Slice 4A/4B HITL Approval UI. Fixed 6 bugs including state-management leaks between simple/advanced mode, move toggle not suppressing `user_edited_path`, bucket/inline edits failing to promote `tag`/`delete` to `move`, and frontend/backend sandbox validation inconsistencies. Added regression tests (75 vitest, 96 pytest pass). Production build now succeeds. Findings posted to GitHub issue #7.
