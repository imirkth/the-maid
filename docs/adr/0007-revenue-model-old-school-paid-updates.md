# ADR 0007: Revenue Model — Old-School Paid Updates

## Status
Accepted

## Context
One-time $30–$50 purchase. Need a sustainable update model.

## Decision
**Old-school desktop software model:**
- Buy the version you buy — one-time purchase, perpetual license for that version
- Bug fixes: free forever for purchased version
- New features/major versions: paid upgrade (new purchase)
- User decides whether to upgrade — no forced subscriptions

## Rationale
- Matches user expectations for desktop utilities
- Preserves "no subscription" positioning absolutely
- Bug fixes are a moral obligation — they shouldn't be monetized
- New features are new value — fair to charge for them
- Simple, honest pricing: "v1 = $40, v2 = $30 if you own v1"
- Avoids "optional support plan" complexity — simpler messaging

## Trade-offs
- No recurring revenue between major versions
- Need to save cash runway for development
- But: aligns with privacy-first, no-nonsense product ethos

## Consequences
- **Version definition:** Major versions are defined by **new features**, not semver. Any new feature set constitutes a new major version.
- **Upgrade pricing:** User pays the *difference* between what they originally paid and the new version's price. Example: paid $15 for v1, v2 costs $20 → upgrade is $5.
- **Bug fixes:** Free forever for purchased version.
- No telemetry means no "phoning home" for version checks — manual update notifications.
- Need a simple "Check for Updates" mechanism in-app.
