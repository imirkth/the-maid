# Slice 4A/4B Approval UI Bug Review — Completed

## Summary

Reviewed the Approval UI slice (4A/4B) per ADR 0005. Built a red-capable feedback loop with regression tests, reproduced 6 real bugs, fixed them, and added regression coverage. Full test suites pass (75 vitest, 96 pytest). Production build now succeeds.

## Bugs Found & Fixed

| # | Severity | File(s) | Bug | Fix |
|---|----------|---------|-----|-----|
| 1 | **High** | `approval.ts`, `ApprovalView.tsx` | Unchecking **Move** in advanced mode did not prevent execution when `user_edited_path` was set — `effectivePath()` still returned the edited destination. | `applyFieldApprovals()` now clears `user_edited_path` when `move` is false. `buildFinalProposals()` honors simple vs. advanced mode. |
| 2 | **High** | `approval.ts`, `ApprovalView.tsx` | In simple mode, stale advanced per-field toggles still affected execution, breaking the all-or-nothing contract. | Added `buildFinalProposals()` which uses default all-true fields when `advancedMode` is off. |
| 3 | **Medium** | `approval.ts`, `ApprovalView.tsx` | Reassigning a tag-only item to a bucket left `proposed_action` as `tag`, so the file would not move. | `reassignBucket()` now promotes `tag`/`delete` to `move`; inline edit path does the same. |
| 4 | **Medium** | `approval.ts`, `ApprovalView.tsx` | Frontend path validation accepted relative escapes (`Desktop/../Documents`) and unrelated components (`/tmp/Desktop/file.txt`) as valid. | Rewrote `validateEditedPath()` to resolve `~`, collapse `..`, resolve relative sandbox names against home, and require proper prefix containment. `homeDir()` loaded once in the component. |
| 5 | **Medium** | `sandbox.py`, `approval.ts` | System-directory check used naive prefix match, so `/bingo`, `/usrfake`, etc. were misclassified as system paths. | Changed prefix check to exact match or trailing `/` in both Python and TypeScript validators. |
| 6 | **Low** | `ApprovalView.tsx` | Path edit trigger was a non-keyboard-accessible `<code>` element; main checkbox lacked label association; bucket selector had no label. | Wrapped checkbox in `<label>`, added `role="button"`, `tabIndex`, keyboard handlers, `aria-live`/`role="alert"`, and labeled bucket `<select>`. |
| 7 | **Low** | `index.html` | Vite build failed because asset paths pointed to `/src/*` while Vite root is `src/`. | Corrected to `/styles.css` and `/main.tsx`. |

## Verification

- `npm test` (vitest): 75 passed
- `PYTHONPATH=. pytest` (backend): 96 passed
- `npm run build`: production build succeeds

## Regression Tests Added

- `src/the-maid/src/lib/approval-advanced.test.ts`: 11 new tests covering `user_edited_path` clearing, bucket action promotion, false-positive system prefixes, relative sandbox escapes, `~` expansion, and `buildFinalProposals` simple/advanced behavior.
- `src/the-maid/backend/tests/test_sandbox.py`: 2 new tests for system-prefix false positives.

## Note

All changes committed to the current branch.
