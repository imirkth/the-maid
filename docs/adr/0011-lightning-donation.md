# ADR 0011: Lightning Donation

## Status

Accepted

## Context

ADR 0010 established an honor-system license model with a voluntary donation fallback. The Maid needs a privacy-first way for users to donate Bitcoin without exposing the vendor to server management, activation infrastructure, or third-party payment telemetry.

After a `/grill-with-docs` design review, the following constraints were confirmed:

- Donations must route to the vendor's own wallet, not a user-configurable node.
- The app must not hold node credentials (macaroons, API keys).
- No telemetry or cloud payment processor metadata should leak donor information.
- UX should be minimal: user enters amount, gets a QR, pays from their wallet.
- The app should detect payment confirmation in-app, not require blind trust.

## Decision

Use **Alby** as the hosted Lightning wallet backend, accessed through its **LNURL-pay** URL, with payment verification via **LNURL-verify** (LUD-21).

The vendor's LNURL-pay URL is baked into the release binary at build time via the `MAID_DONATION_LNURL` environment variable. Users cannot change it.

### Flow

1. User navigates to **Settings → About → Lightning Donation**.
2. User enters an amount in satoshis (1 to 10,000,000).
3. Frontend invokes `create_lightning_invoice(amount_sats, memo)`.
4. Rust backend calls `GET <LNURL-pay URL>?amount=<millisats>`.
5. Alby returns a BOLT11 invoice (`pr`), a `verify` URL, and a valid `payment_hash`.
6. Frontend displays the invoice as a QR code and starts a 5-second poll loop.
7. Rust backend calls `GET <verify URL>` and checks the response.
8. Payment is confirmed when the verify response returns `status === "OK"`, `settled === true`, and a non-empty `preimage`.
9. Polling stops when the invoice expires, the user leaves the panel, payment is confirmed, or the verify response returns a terminal `status === "ERROR"` with a `reason`.
10. Invoice expiry is determined in this order:
    1. `expires_at` field from the LNURL-pay callback response (validated; malformed values disable automatic verification).
    2. Fallback: parse the BOLT11 invoice in the frontend with the `bolt11` library.
    3. If neither is available, polling continues until the user leaves the panel.

## Rationale

- **Alby** provides a hosted wallet with LNURL-pay support, eliminating the need for the vendor to self-host a public HTTPS endpoint or manage certificates/port forwarding.
- **LNURL-verify** gives cryptographic proof of payment (`preimage`) without requiring node credentials in the app.
- **Build-time URL** prevents users from redirecting donations to another wallet.
- **No API token** is required for the LNURL-pay/verify flow, keeping the app credential-free.

## Trade-offs

- **Custodial window**: funds sit in Alby until the vendor sweeps them to their own LND node. The vendor must establish a sweep schedule (daily/weekly) to minimize exposure.
- **Single point of failure**: if Alby is unavailable, donations cannot be generated.
- **Privacy**: Alby sees invoice amounts and donor IP metadata. This is acceptable because the alternative (Stripe/PayPal) has the same or worse privacy characteristics.
- **Verification requires preimage**: some LNURL providers may not return a preimage. In that case the app will never mark the donation as confirmed, even if paid.

## Consequences

- The Settings → About panel gains a **Lightning Donation** section with amount input, QR code, invoice copy, expiry countdown, and payment confirmation.
- A new Rust module `lightning` provides `create_lightning_invoice` and `verify_lightning_payment_cmd`.
- A new frontend module `lib/donation.ts` handles validation, QR generation, bolt11 expiry parsing, and settlement logic.
- The `bolt11` npm package is added for client-side invoice parsing.
- The `MAID_DONATION_LNURL` build-time variable must be set for release builds; otherwise invoice generation returns an error.

## Build configuration

```bash
MAID_DONATION_LNURL=https://getalby.com/.well-known/lnurlp/<username> \
  cargo tauri build
```

### Recommended Alby setup

1. Create an Alby account at https://getalby.com.
2. Enable your Lightning Address / LNURL-pay URL.
3. Copy the raw LNURL-pay URL (e.g. `https://getalby.com/.well-known/lnurlp/imirk`).
4. Set it as `MAID_DONATION_LNURL` in your release build pipeline.
5. Sweep donations from Alby to your LND node on a schedule (daily/weekly).

## Future considerations

- Add an optional webhook or serverless endpoint for real-time settlement notifications.
- Support direct LND REST as an advanced vendor option for fully non-custodial donations.
- Cache donation history locally so repeat donors see a thank-you state on reopening the app.
