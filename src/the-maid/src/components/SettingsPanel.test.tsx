// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import SettingsPanel from "./SettingsPanel";

const mockInvoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

vi.mock("@tauri-apps/plugin-shell", () => ({
  openUrl: vi.fn(),
}));

function mockBaseResponses() {
  mockInvoke
    .mockResolvedValueOnce({ sandbox_folders: ["Desktop"], setup_complete: true })
    .mockResolvedValueOnce([
      { id: "text", name: "Text", size_mb: 500, downloaded: true },
    ])
    .mockResolvedValueOnce("0.1.0");
}

async function openAboutSection() {
  render(<SettingsPanel />);
  await waitFor(() => expect(screen.getByText("⚙️ Settings")).toBeDefined());
  fireEvent.click(screen.getByText("ℹ️ About"));
  await waitFor(() =>
    expect(screen.getByText(/Lightning Donation/i)).toBeDefined()
  );
}

describe("SettingsPanel donation", () => {
  beforeEach(() => {
    mockInvoke.mockClear();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  it("ignores rapid double-click on Generate Invoice (Bug #20)", async () => {
    mockBaseResponses();
    let resolveInvoice: (v: unknown) => void;
    const invoicePromise = new Promise((resolve) => {
      resolveInvoice = resolve;
    });
    mockInvoke.mockResolvedValueOnce(invoicePromise);

    await openAboutSection();
    const button = screen.getByRole("button", { name: /Generate Invoice/i });

    fireEvent.click(button);
    fireEvent.click(button);

    expect(
      mockInvoke.mock.calls.filter((c) => c[0] === "create_lightning_invoice")
        .length
    ).toBe(1);

    resolveInvoice!({
      bolt11: "lnbc100u1test",
      payment_hash: "deadbeef",
      amount_sats: 1000,
      verify_url: "https://example.com/verify",
      expires_at: new Date(Date.now() + 60000).toISOString(),
    });

    await waitFor(() =>
      expect(
        mockInvoke.mock.calls.filter((c) => c[0] === "create_lightning_invoice")
          .length
      ).toBe(1)
    );

    vi.useRealTimers();
  });
});
