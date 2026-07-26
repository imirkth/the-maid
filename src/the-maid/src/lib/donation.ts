// The Maid — Lightning donation logic
// Pure functions for validation, polling, and formatting.

import QRCode from "qrcode";

export const MIN_DONATION_SATS = 1;
export const MAX_DONATION_SATS = 10_000_000;

export interface LightningInvoice {
  bolt11: string;
  payment_hash: string;
  amount_sats: number;
  expires_at?: string;
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

export async function generateInvoiceQrDataUrl(bolt11: string): Promise<string> {
  return QRCode.toDataURL(bolt11, { width: 256, margin: 2 });
}
