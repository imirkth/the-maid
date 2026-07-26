import { useState, useEffect, useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  type LightningInvoice,
  validateDonationAmount,
  generateInvoiceQrDataUrl,
  parseBolt11Expiry,
  isInvoiceExpired,
  isPaymentSettled,
  formatExpiryCountdown,
  DEFAULT_POLL_INTERVAL_MS,
} from "../lib/donation";

export interface InvoiceWithQr extends LightningInvoice {
  qr_data_url?: string;
  expiry?: number;
}

export interface UseDonationReturn {
  donationAmount: number;
  setDonationAmount: (amount: number) => void;
  invoice: InvoiceWithQr | null;
  donationLoading: boolean;
  donationError: string;
  paid: boolean;
  countdown: string;
  createInvoice: () => Promise<void>;
  copyInvoice: () => Promise<void>;
}

export function useDonation(): UseDonationReturn {
  const [donationAmount, setDonationAmount] = useState(1000);
  const [invoice, setInvoice] = useState<InvoiceWithQr | null>(null);
  const [donationLoading, setDonationLoading] = useState(false);
  const [donationError, setDonationError] = useState("");
  const [paid, setPaid] = useState(false);
  const [countdown, setCountdown] = useState("");
  const [terminal, setTerminal] = useState(false);
  const creatingRef = useRef(false);

  const createInvoice = useCallback(async () => {
    if (creatingRef.current) return;
    creatingRef.current = true;
    setInvoice(null);
    setPaid(false);
    setDonationError("");
    setCountdown("");
    setTerminal(false);
    const validation = validateDonationAmount(donationAmount);
    if (!validation.valid) {
      setDonationError(validation.error || "Invalid amount");
      creatingRef.current = false;
      return;
    }
    setDonationLoading(true);
    try {
      const result = await invoke<LightningInvoice>("create_lightning_invoice", {
        amount_sats: donationAmount,
        memo: "Support The Maid",
      });
      const qr_data_url = await generateInvoiceQrDataUrl(result.bolt11);

      let expiry: number | undefined;
      let expiryError: string | undefined;
      if (result.expires_at) {
        const parsed = Math.floor(new Date(result.expires_at).getTime() / 1000);
        if (Number.isFinite(parsed)) {
          expiry = parsed;
        } else {
          expiryError =
            "Invoice expiry is invalid; automatic payment verification is disabled.";
        }
      }
      if (expiry === undefined && !expiryError) {
        expiry = parseBolt11Expiry(result.bolt11) ?? undefined;
      }

      setInvoice({ ...result, qr_data_url, expiry });
      if (expiryError) {
        setDonationError(expiryError);
        setTerminal(true);
      }
    } catch (e) {
      setDonationError(String(e));
    } finally {
      setDonationLoading(false);
      creatingRef.current = false;
    }
  }, [donationAmount]);

  // Poll LNURL-verify endpoint every 5s until paid, terminal, or expired.
  useEffect(() => {
    if (!invoice?.verify_url || paid || terminal) return;
    if (invoice.expiry !== undefined && isInvoiceExpired(invoice.expiry)) return;

    const poll = async () => {
      try {
        const status = await invoke<{
          status: string;
          settled?: boolean;
          preimage?: string | null;
          reason?: string;
        }>("verify_lightning_payment_cmd", {
          verify_url: invoice.verify_url,
        });
        if (!status) return;
        if (status.reason) {
          setDonationError(status.reason);
          setTerminal(true);
          return;
        }
        if (isPaymentSettled(status)) {
          setPaid(true);
        }
      } catch (e) {
        // Swallow polling errors; keep trying until expiry or terminal.
        console.error("Donation verify poll failed:", e);
      }
    };

    const timer = setInterval(poll, DEFAULT_POLL_INTERVAL_MS);
    poll();

    return () => clearInterval(timer);
  }, [invoice, paid, terminal]);

  // Update expiry countdown every second.
  useEffect(() => {
    if (!invoice?.expiry || paid) {
      setCountdown("");
      return;
    }
    const update = () => {
      if (isInvoiceExpired(invoice.expiry!)) {
        setCountdown("Expired");
      } else {
        setCountdown(formatExpiryCountdown(invoice.expiry!));
      }
    };
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [invoice?.expiry, paid]);

  const copyInvoice = useCallback(async () => {
    if (!invoice?.bolt11) return;
    try {
      await navigator.clipboard.writeText(invoice.bolt11);
    } catch (e) {
      setDonationError(
        "Clipboard access denied. Copy the invoice manually from the QR code or text below."
      );
    }
  }, [invoice]);

  return {
    donationAmount,
    setDonationAmount,
    invoice,
    donationLoading,
    donationError,
    paid,
    countdown,
    createInvoice,
    copyInvoice,
  };
}
