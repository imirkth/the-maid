import { describe, it, expect } from "vitest";
import {
  validateDonationAmount,
  formatAmountSats,
  truncateInvoice,
  generateInvoiceQrDataUrl,
  MIN_DONATION_SATS,
  MAX_DONATION_SATS,
} from "./donation";

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
