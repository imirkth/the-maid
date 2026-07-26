import { describe, it, expect } from "vitest";
import * as bolt11 from "bolt11";
import {
  validateDonationAmount,
  formatAmountSats,
  truncateInvoice,
  generateInvoiceQrDataUrl,
  parseBolt11Expiry,
  isInvoiceExpired,
  isPaymentSettled,
  formatExpiryCountdown,
  MIN_DONATION_SATS,
  MAX_DONATION_SATS,
} from "./donation";
import crypto from "crypto";

function makeTestInvoice(satoshis: number, expirySeconds: number): string {
  const payhash = crypto.randomBytes(32).toString("hex");
  const now = Math.floor(Date.now() / 1000);
  const encoded = bolt11.encode({
    satoshis,
    timestamp: now,
    tags: [
      { tagName: "payment_hash", data: payhash },
      { tagName: "description", data: "The Maid donation test" },
      { tagName: "expire_time", data: expirySeconds },
    ],
  });
  const priv = crypto.randomBytes(32).toString("hex");
  const signed = bolt11.sign(encoded, priv);
  return signed.paymentRequest;
}

describe("validateDonationAmount", () => {
  it("rejects zero", () => {
    const r = validateDonationAmount(0);
    expect(r.valid).toBe(false);
    expect(r.error).toContain("Minimum");
  });

  it("rejects negative", () => {
    const r = validateDonationAmount(-1);
    expect(r.valid).toBe(false);
  });

  it("rejects decimals", () => {
    const r = validateDonationAmount(100.5);
    expect(r.valid).toBe(false);
    expect(r.error).toContain("whole number");
  });

  it("rejects above max", () => {
    const r = validateDonationAmount(MAX_DONATION_SATS + 1);
    expect(r.valid).toBe(false);
    expect(r.error).toContain("Maximum");
  });

  it("accepts one sat", () => {
    const r = validateDonationAmount(MIN_DONATION_SATS);
    expect(r.valid).toBe(true);
  });

  it("accepts max", () => {
    const r = validateDonationAmount(MAX_DONATION_SATS);
    expect(r.valid).toBe(true);
  });

  it("accepts 1000 sats", () => {
    const r = validateDonationAmount(1000);
    expect(r.valid).toBe(true);
  });
});

describe("formatAmountSats", () => {
  it("formats with commas", () => {
    expect(formatAmountSats(1234567)).toBe("1,234,567 sats");
  });
});

describe("truncateInvoice", () => {
  it("returns short invoice unchanged", () => {
    expect(truncateInvoice("short")).toBe("short");
  });

  it("truncates long invoice", () => {
    const long = "a".repeat(200);
    expect(truncateInvoice(long, 20).length).toBe(20);
    expect(truncateInvoice(long, 20).endsWith("…")).toBe(true);
  });
});

describe("generateInvoiceQrDataUrl", () => {
  it("generates a data URL for an invoice", async () => {
    const url = await generateInvoiceQrDataUrl("lnbc100u1invoice");
    expect(url.startsWith("data:image/png;base64,")).toBe(true);
  });
});

describe("parseBolt11Expiry", () => {
  it("parses expiry from a generated invoice", () => {
    const invoice = makeTestInvoice(1000, 1800);
    const expiry = parseBolt11Expiry(invoice);
    expect(expiry).not.toBeNull();
    expect(expiry! > Math.floor(Date.now() / 1000)).toBe(true);
  });

  it("returns null for invalid invoice", () => {
    expect(parseBolt11Expiry("not-an-invoice")).toBeNull();
  });
});

describe("isInvoiceExpired", () => {
  it("returns true for past expiry", () => {
    expect(isInvoiceExpired(Math.floor(Date.now() / 1000) - 10)).toBe(true);
  });

  it("returns false for future expiry", () => {
    expect(isInvoiceExpired(Math.floor(Date.now() / 1000) + 600)).toBe(false);
  });
});

describe("isPaymentSettled", () => {
  it("returns true for OK + settled + preimage", () => {
    expect(
      isPaymentSettled({ status: "OK", settled: true, preimage: "abcdef" })
    ).toBe(true);
  });

  it("returns false if not settled", () => {
    expect(
      isPaymentSettled({ status: "OK", settled: false, preimage: null })
    ).toBe(false);
  });

  it("returns false if status is ERROR", () => {
    expect(
      isPaymentSettled({ status: "ERROR", settled: true, preimage: "abcdef" })
    ).toBe(false);
  });

  it("returns false if preimage is null", () => {
    expect(
      isPaymentSettled({ status: "OK", settled: true, preimage: null })
    ).toBe(false);
  });

  it("returns false if preimage is empty", () => {
    expect(
      isPaymentSettled({ status: "OK", settled: true, preimage: "" })
    ).toBe(false);
  });
});

describe("formatExpiryCountdown", () => {
  it("formats remaining time", () => {
    const expiry = Math.floor(Date.now() / 1000) + 125;
    expect(formatExpiryCountdown(expiry)).toMatch(/^2m 0\ds$/);
  });

  it("returns Expired for past expiry", () => {
    expect(formatExpiryCountdown(Math.floor(Date.now() / 1000) - 1)).toBe(
      "Expired"
    );
  });
});
