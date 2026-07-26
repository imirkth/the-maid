import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-shell";
import {
  type Settings,
  type ModelStatus,
  type UpdateInfo,
  validateFolderName,
  folderExistsInList,
  formatStorageUsed,
  downloadedCount,
} from "../lib/settings";
import {
  type LightningInvoice,
  validateDonationAmount,
  formatAmountSats,
  truncateInvoice,
  generateInvoiceQrDataUrl,
  parseBolt11Expiry,
  isInvoiceExpired,
  isPaymentSettled,
  formatExpiryCountdown,
  DEFAULT_POLL_INTERVAL_MS,
} from "../lib/donation";

// ponytail: ADR 0010 — donation URL, no DRM
const DONATE_URL = "https://themaid.app/donate";

type Section = "folders" | "models" | "updates" | "about";

interface InvoiceWithQr extends LightningInvoice {
  qr_data_url?: string;
  expiry?: number; // Unix seconds
}


export default function SettingsPanel() {
  const [section, setSection] = useState<Section>("folders");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [models, setModels] = useState<ModelStatus[]>([]);
  const [newFolder, setNewFolder] = useState("");
  const [folderError, setFolderError] = useState("");
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [updateChecking, setUpdateChecking] = useState(false);
  const [updateError, setUpdateError] = useState("");
  const [appVersion, setAppVersion] = useState("0.1.0");

  // Lightning donation state
  const [donationAmount, setDonationAmount] = useState(1000);
  const [invoice, setInvoice] = useState<InvoiceWithQr | null>(null);
  const [donationLoading, setDonationLoading] = useState(false);
  const [donationError, setDonationError] = useState("");
  const [paid, setPaid] = useState(false);
  const [countdown, setCountdown] = useState("");

  useEffect(() => {
    invoke<Settings>("get_settings").then(setSettings);
    invoke<ModelStatus[]>("get_model_status").then(setModels);
    invoke<string>("get_app_version").then(setAppVersion);
  }, []);

  const refreshSettings = () => invoke<Settings>("get_settings").then(setSettings);

  const addFolder = () => {
    const trimmed = newFolder.trim();
    const validation = validateFolderName(trimmed);
    if (!validation.valid) {
      setFolderError(validation.error || "Invalid folder");
      return;
    }
    if (settings && folderExistsInList(trimmed, settings.sandbox_folders)) {
      setFolderError("Folder already in list");
      return;
    }
    setFolderError("");
    invoke<Settings>("add_sandbox_folder", { folder: trimmed })
      .then(setSettings)
      .catch((e) => setFolderError(String(e)));
    setNewFolder("");
  };

  const removeFolder = (folder: string) => {
    invoke<Settings>("remove_sandbox_folder", { folder })
      .then(setSettings)
      .catch((e) => setFolderError(String(e)));
  };

  const checkForUpdates = () => {
    setUpdateChecking(true);
    setUpdateError("");
    invoke<UpdateInfo>("check_updates")
      .then((info) => {
        setUpdateInfo(info);
        setUpdateChecking(false);
      })
      .catch((e) => {
        setUpdateError(String(e));
        setUpdateChecking(false);
      });
  };

  const createInvoice = async () => {
    setInvoice(null);
    setPaid(false);
    setDonationError("");
    setCountdown("");
    const validation = validateDonationAmount(donationAmount);
    if (!validation.valid) {
      setDonationError(validation.error || "Invalid amount");
      return;
    }
    setDonationLoading(true);
    try {
      const result = await invoke<LightningInvoice>("create_lightning_invoice", {
        amount_sats: donationAmount,
        memo: "Support The Maid",
      });
      const qr_data_url = await generateInvoiceQrDataUrl(result.bolt11);
      const expiry = result.expires_at
        ? Math.floor(new Date(result.expires_at).getTime() / 1000)
        : parseBolt11Expiry(result.bolt11) ?? undefined;
      setInvoice({ ...result, qr_data_url, expiry });
    } catch (e) {
      setDonationError(String(e));
    } finally {
      setDonationLoading(false);
    }
  };

  // Poll LNURL-verify endpoint every 5s until paid or expired.
  useEffect(() => {
    if (!invoice?.verify_url || paid) return;

    const poll = async () => {
      try {
        const status = await invoke<{
          status: string;
          settled?: boolean;
          preimage?: string | null;
        }>("verify_lightning_payment_cmd", {
          verify_url: invoice.verify_url,
        });
        if (isPaymentSettled(status)) {
          setPaid(true);
        }
      } catch (e) {
        // Swallow polling errors; keep trying until expiry.
        console.error("Donation verify poll failed:", e);
      }
    };

    const timer = setInterval(poll, DEFAULT_POLL_INTERVAL_MS);
    // immediate first poll
    poll();

    return () => clearInterval(timer);
  }, [invoice?.verify_url, paid]);

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

  const copyInvoice = () => {
    if (invoice?.bolt11) {
      navigator.clipboard.writeText(invoice.bolt11);
    }
  };

  const openDonate = () => {
    openUrl(DONATE_URL);
  };

  if (!settings) return <p>Loading…</p>;

  return (
    <div className="settings-panel">
      <h2>⚙️ Settings</h2>

      <div className="settings-tabs">
        <button
          className={section === "folders" ? "active" : ""}
          onClick={() => setSection("folders")}
        >📁 Folders</button>
        <button
          className={section === "models" ? "active" : ""}
          onClick={() => setSection("models")}
        >🧩 Models</button>
        <button
          className={section === "updates" ? "active" : ""}
          onClick={() => setSection("updates")}
        >🔄 Updates</button>
        <button
          className={section === "about" ? "active" : ""}
          onClick={() => setSection("about")}
        >ℹ️ About</button>
      </div>

      {section === "folders" && (
        <section>
          <h3>Sandbox Folders</h3>
          <p>Folders The Maid is allowed to scan and organize.</p>
          <ul className="folder-list">
            {settings.sandbox_folders.map((f) => (
              <li key={f} className="folder-list-item">
                <span>{f}</span>
                <button onClick={() => removeFolder(f)} className="btn-small danger">Remove</button>
              </li>
            ))}
          </ul>
          <div className="add-folder">
            <input
              value={newFolder}
              onChange={(e) => setNewFolder(e.target.value)}
              placeholder="Folder name (e.g. Desktop)"
              onKeyDown={(e) => e.key === "Enter" && addFolder()}
            />
            <button onClick={addFolder}>Add</button>
          </div>
          {folderError && <div className="error">⚠️ {folderError}</div>}
        </section>
      )}

      {section === "models" && (
        <section>
          <h3>Model Downloads</h3>
          <p>
            {downloadedCount(models)} of {models.length} models downloaded ·
            {" "}{formatStorageUsed(models)} storage used
          </p>
          <div className="model-list">
            {models.map((m) => (
              <div key={m.id} className="model-item">
                <div className="model-info">
                  <strong>{m.name}</strong>
                  <span className="model-size">~{m.size_mb} MB</span>
                </div>
                <div className={m.downloaded ? "model-status done" : "model-status idle"}>
                  {m.downloaded ? "✓ Downloaded" : "Not downloaded"}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {section === "updates" && (
        <section>
          <h3>Check for Updates</h3>
          <p>Current version: <strong>v{appVersion}</strong></p>
          <p>Bug fixes are always free. Major versions are a paid upgrade.</p>
          <button onClick={checkForUpdates} disabled={updateChecking}>
            {updateChecking ? "Checking…" : "Check for Updates"}
          </button>

          {updateError && (
            <div className="error">⚠️ {updateError}</div>
          )}

          {updateInfo && !updateError && (
            <div className="update-info">
              <p>Latest version: <strong>v{updateInfo.latest_version}</strong></p>
              {updateInfo.update_available ? (
                <div>
                  <p className="update-available">✨ A new version is available!</p>
                  {updateInfo.upgrade_price != null && (
                    <p>Upgrade price: ${updateInfo.upgrade_price.toFixed(2)}</p>
                  )}
                  {updateInfo.release_notes && (
                    <div className="release-notes">
                      <h4>Release Notes</h4>
                      <p>{updateInfo.release_notes}</p>
                    </div>
                  )}
                </div>
              ) : (
                <p className="up-to-date">✓ You're up to date!</p>
              )}
            </div>
          )}
        </section>
      )}

      {section === "about" && (
        <section>
          <h3>About The Maid</h3>
          <p>Version: v{appVersion}</p>
          <p>Local-first AI file organizer. Your files never leave your machine.</p>

          <div className="about-section">
            <h4>Lightning Donation</h4>
            <p>Pay with Bitcoin Lightning. No processor, no tracking.</p>

            <div className="donation-form">
              <label>Amount (sats)</label>
              <input
                type="number"
                min={1}
                step={1}
                value={donationAmount}
                onChange={(e) => setDonationAmount(Number(e.target.value))}
                disabled={donationLoading || paid}
              />
              <button onClick={createInvoice} disabled={donationLoading || paid}>
                {donationLoading ? "Creating…" : paid ? "Paid ✓" : "Generate Invoice"}
              </button>
            </div>

            {donationError && <div className="error">⚠️ {donationError}</div>}

            {invoice && !paid && (
              <div className="donation-invoice">
                <p>Pay {formatAmountSats(invoice.amount_sats)}</p>
                {countdown && <p className="donation-expiry">Expires in {countdown}</p>}
                {invoice.qr_data_url && (
                  <img
                    src={invoice.qr_data_url}
                    alt="Lightning invoice QR"
                    className="donation-qr"
                  />
                )}
                <pre className="donation-bolt11">{truncateInvoice(invoice.bolt11, 60)}</pre>
                <button onClick={copyInvoice}>Copy Invoice</button>
              </div>
            )}

            {paid && (
              <div className="donation-thank-you">
                <p>✨ Thank you for supporting The Maid!</p>
                <p>Payment confirmed.</p>
              </div>
            )}
          </div>

          <div className="about-section">
            <h4>Support The Maid</h4>
            <p>
              The Maid is made by one person. No DRM, no telemetry, no subscription.
              If you find it useful, consider supporting:
            </p>
            <button onClick={openDonate} className="donate-btn">
              💝 Support The Maid
            </button>
          </div>

          <div className="about-section">
            <h4>Pricing</h4>
            <p>One-time purchase: $30–$50. No subscription.</p>
            <p>Bug fixes: free forever for your version.</p>
            <p>Major version upgrades: paid upgrade (price difference).</p>
          </div>

          <div className="about-section">
            <h4>Privacy</h4>
            <p>✓ All processing is local</p>
            <p>✓ Zero cloud uploads</p>
            <p>✓ No telemetry or tracking</p>
            <p>✓ Metadata stays in your files (IPTC/XMP)</p>
          </div>
        </section>
      )}
    </div>
  );
}