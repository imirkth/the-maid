# Task: Lightning Donation (Slice 7 extension) — DONE

Confirmed design from /grill-with-docs session:
- Backend: Alby LNURL-pay URL baked in via MAID_DONATION_LNURL.
- User flow: amount → QR → pay externally.
- App polls Alby LNURL-verify URL every 5s until invoice expiry.
- Paid when status=OK, settled=true, preimage non-null.
- Expiry: from verify response expires_at, else bolt11 parsing in frontend.

Implemented and committed.