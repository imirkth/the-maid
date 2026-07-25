# ADR 0010: Licensing — Honor System with Donation Fallback

## Status
Accepted

## Context
One-time $30–$50 purchase. Need license enforcement without server infrastructure or telemetry.

## Decision
**No DRM. No server. Honor system + voluntary donation.**

## Rationale
- **No server management:** Owner explicitly does not want to run or maintain activation servers.
- **Privacy-first alignment:** Any server connection (even one-time activation) contradicts "zero telemetry" positioning.
- **Piracy is inevitable:** All DRM is eventually broken. Accepting this upfront avoids wasting energy on unwinnable battles.
- **Donation model:** Users who pirated and love the product may voluntarily pay. "Pay what you want" button in-app links to Stripe/PayPal.

## Trade-offs
- **Revenue leakage:** Some users will share keys or redistribute the binary. Estimated 20–40% of potential sales.
- **No upgrade tracking:** Cannot distinguish paid vs unpaid users for upgrade pricing.
- **Social pressure:** May need prominent "This software is made by one person — consider paying" messaging.

## Consequences
- Purchase flow: simple Stripe checkout → download link → no key required.
- "Enter license key" screen removed entirely.
- Settings include "Support The Maid" → donation page.
- Upgrade announcements go to all users regardless of payment status.

## Future
If revenue leakage becomes critical, revisit with a lightweight server (e.g., Gumroad/LemonSqueezy handles activation).