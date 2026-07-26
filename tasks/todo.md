# Task: Lightning Donation (Slice 7 extension)

Goal: Add self-hosted Lightning node donation flow so the user can plug in their own node backend. Use TDD.

## Checklist
- [x] Plan Lightning donation architecture (LNURL-pay first, generic config field).
- [x] Add `lightning_node_url` to Rust `Settings` + frontend `Settings` interface.
- [x] Write failing Rust tests for `create_lightning_invoice` (mock server / test fixtures).
- [x] Write failing frontend tests for donation logic + UI state.
- [x] Implement Rust `create_lightning_invoice` command with LNURL-pay callback flow.
- [x] Implement frontend donation panel: amount input, invoice, QR, status polling.
- [x] Wire new command in `lib.rs` and expose to frontend.
- [x] Run frontend tests; run Rust tests if deps available (note if not).
- [x] Update ADR 0010 to mention Lightning option.
- [ ] Commit and post update.

## Notes
- No external payment processor. User's own node.
- Keep amount validation sane (1..10_000_000 sats).
- QR generated from bolt11 invoice string.
- Privacy-first: no telemetry, no third-party APIs.
