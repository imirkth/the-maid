// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useDonation } from "./useDonation";

const mockInvoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

describe("useDonation", () => {
  beforeEach(() => {
    mockInvoke.mockClear();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("ignores concurrent createInvoice calls (Bug #20)", async () => {
    let resolveInvoice: (v: unknown) => void;
    const invoicePromise = new Promise((resolve) => {
      resolveInvoice = resolve;
    });
    mockInvoke.mockResolvedValueOnce(invoicePromise);

    const { result } = renderHook(() => useDonation());

    await act(async () => {
      result.current.createInvoice();
      result.current.createInvoice();
    });

    expect(
      mockInvoke.mock.calls.filter((c) => c[0] === "create_lightning_invoice").length
    ).toBe(1);

    await act(async () => {
      resolveInvoice({
        bolt11: "lnbc100u1test",
        payment_hash: "deadbeef",
        amount_sats: 1000,
        verify_url: "https://example.com/verify",
        expires_at: new Date(Date.now() + 60000).toISOString(),
      });
    });

    await waitFor(() =>
      expect(
        mockInvoke.mock.calls.filter((c) => c[0] === "create_lightning_invoice").length
      ).toBe(1)
    );
  });

  it("surfaces clipboard errors when copying invoice (Bug #21)", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("Denied"));
    Object.assign(navigator, { clipboard: { writeText } });

    mockInvoke.mockResolvedValueOnce({
      bolt11: "lnbc100u1test",
      payment_hash: "deadbeef",
      amount_sats: 1000,
      verify_url: "https://example.com/verify",
      expires_at: new Date(Date.now() + 60000).toISOString(),
    });

    const { result } = renderHook(() => useDonation());

    await act(async () => {
      await result.current.createInvoice();
    });

    await act(async () => {
      await result.current.copyInvoice();
    });

    expect(result.current.donationError).toContain("Clipboard");
  });

  it("stops polling and surfaces terminal LNURL errors (Bug #24 frontend)", async () => {
    mockInvoke.mockResolvedValueOnce({
      bolt11: "lnbc100u1test",
      payment_hash: "deadbeef",
      amount_sats: 1000,
      verify_url: "https://example.com/verify",
      expires_at: new Date(Date.now() + 60000).toISOString(),
    });
    mockInvoke.mockResolvedValueOnce({
      status: "ERROR",
      settled: false,
      preimage: null,
      reason: "Invoice expired",
    });

    const { result } = renderHook(() => useDonation());

    await act(async () => {
      await result.current.createInvoice();
    });

    // Wait for immediate poll and error handling.
    await waitFor(() =>
      expect(result.current.donationError).toContain("Invoice expired")
    );

    // Advance past poll interval; no more verify calls should happen.
    await act(async () => {
      vi.advanceTimersByTime(15000);
    });

    expect(
      mockInvoke.mock.calls.filter((c) => c[0] === "verify_lightning_payment_cmd").length
    ).toBe(1);
  });

  it("stops polling when expires_at is malformed (Bug #22)", async () => {
    mockInvoke.mockResolvedValueOnce({
      bolt11: "lnbc100u1test",
      payment_hash: "deadbeef",
      amount_sats: 1000,
      verify_url: "https://example.com/verify",
      expires_at: "not-a-date",
    });
    mockInvoke.mockResolvedValue({ settled: false });

    const { result } = renderHook(() => useDonation());

    await act(async () => {
      await result.current.createInvoice();
    });

    // No bolt11 expiry in this fake invoice, so expiry should be undefined.
    expect(result.current.invoice?.expiry).toBeUndefined();

    // Advance well past the poll interval.
    await act(async () => {
      vi.advanceTimersByTime(15000);
    });

    expect(
      mockInvoke.mock.calls.filter((c) => c[0] === "verify_lightning_payment_cmd").length
    ).toBe(0);
  });
});
