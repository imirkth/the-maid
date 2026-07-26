// The Maid — Lightning donation logic
// Pure functions for validation, polling, formatting, and bolt11 parsing.

import QRCode from "qrcode";
import * as bolt11 from "bolt11";

export const MIN_DONATION_SATS = 1;
export const MAX_DONATION_SATS = 10_000_000;
export const DEFAULT_POLL_INTERVAL_MS = 5000;

export interface LightningInvoice {
  bolt11: string;
  payment_hash: string;
  amount_sats: number;
  verify_url: string;
  expires_at?: string;
}

// ponytail: ADR 0011 — verify response is status + settled + preimage, nothing else.
export interface VerifyResponse {
  status: string;
  settled?: boolean;
  preimage?: string | null;
}

export function validateDonationAmount(amount: number): { valid: boolean; error?: string } {
  if (!Number.isFinite(amount) || !Number.isInteger(amount)) {
    return { valid: false, error: "Amount must be a whole number" };
  }
  if (amount < MIN_DONATION_SATS) {
    return { valid: false, error: `Minimum donation is ${MIN_DONATION_SATS} sat` };
  }
  if (amount > MAX_DONATION_SATS) {
    return { valid: false, error: `Maximum donation is ${MAX_DONATION_SATS} sats` };
  }
  return { valid: true };
}

export function formatAmountSats(amount: number): string {
  return `${amount.toLocaleString()} sats`;
}

export function truncateInvoice(invoice: string, max = 40): string {
  if (invoice.length <= max) return invoice;
  return invoice.slice(0, max - 1) + "…";
}

export async function generateInvoiceQrDataUrl(bolt11Invoice: string): Promise<string> {
  return QRCode.toDataURL(bolt11Invoice, { width: 256, margin: 2 });
}

/**
 * Parse bolt11 invoice expiry as a Unix timestamp (seconds).
 * Returns null if parsing fails or no expiry tag present.
 */
export function parseBolt11Expiry(bolt11Invoice: string): number | null {
  try {
    const decoded = bolt11.decode(bolt11Invoice);
    if (decoded.timeExpireDate) {
      return decoded.timeExpireDate;
    }
    const expiryTag = decoded.tags.find((t) => t.tagName === "expire_time");
    if (expiryTag && typeof expiryTag.data === "number") {
      return decoded.timestamp + expiryTag.data;
    }
    return null;
  } catch {
    return null;
  }
}

export function isInvoiceExpired(expiryTimestampSeconds: number): boolean {
  return Math.floor(Date.now() / 1000) >= expiryTimestampSeconds;
}

/**
 * Determine payment settlement from LNURL-verify response.
 * Requires status OK, settled true, and a non-null preimage as proof.
 */
export function isPaymentSettled(response: VerifyResponse): boolean {
  return (
    response.status === "OK" &&
    response.settled === true &&
    response.preimage != null &&
    response.preimage.length > 0
  );
}

export function formatExpiryCountdown(expiryTimestampSeconds: number): string {
  const now = Math.floor(Date.now() / 1000);
  const remaining = expiryTimestampSeconds - now;
  if (remaining <= 0) return "Expired";
  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;
  return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
}
