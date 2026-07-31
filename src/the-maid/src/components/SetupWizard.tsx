import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import {
  type FeatureFlags,
  type DownloadStatus,
  allDownloadsDone,
  canAdvanceFromStep2,
  buildSetupPayload,
} from "../lib/setup";

interface Props {
  onComplete: () => void;
}

// ponytail: model metadata — sizes for progress display. Real URLs handled by Rust download_model command.
const MODELS = {
  text: { name: "Text LLM (always bundled)", size: 500, required: true },
  pdf: { name: "PDF OCR Model", size: 1000, optional: true },
  face: { name: "Face Recognition Model", size: 100, optional: true },
};

type DownloadState = DownloadStatus["state"];

interface ModelDownloadProgress {
  model_id: string;
  downloaded_bytes: number;
  total_bytes: number;
  percent: number;
  complete: boolean;
  error: string | null;
}

export default function SetupWizard({ onComplete }: Props) {
  const [step, setStep] = useState(1);
  const [selectedFolders, setSelectedFolders] = useState<string[]>([
    "Desktop",
    "Downloads",
    "Documents",
    "Pictures",
  ]);
  const [features, setFeatures] = useState({
    pdf_ocr: false,
    face_clustering: false,
    general_files: true,
  });
  const [downloads, setDownloads] = useState<Record<string, DownloadStatus>>({
    text: { state: "done", progress: 100 },
    pdf: { state: "idle", progress: 0 },
    face: { state: "idle", progress: 0 },
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Listen for real download progress events from Rust backend
  useEffect(() => {
    const unlisten = listen<ModelDownloadProgress>("model_download_progress", (e) => {
      const p = e.payload;
      setDownloads((prev) => {
        if (p.error) {
          return { ...prev, [p.model_id]: { state: "idle", progress: 0 } };
        }
        if (p.complete) {
          return { ...prev, [p.model_id]: { state: "done", progress: 100 } };
        }
        return { ...prev, [p.model_id]: { state: "downloading", progress: p.percent } };
      });
    });
    return () => { unlisten.then((f) => f()); };
  }, []);

  const toggleFolder = (folder: string) => {
    setSelectedFolders((prev) =>
      prev.includes(folder) ? prev.filter((f) => f !== folder) : [...prev, folder]
    );
  };

  const totalSteps = 4;

  // Step 1: Welcome + folder selection
  const renderStep1 = () => (
    <div className="wizard-step">
      <h2>🧹 Welcome to The Maid</h2>
      <p>Your local, privacy-first file organizer.</p>
      <p>Choose which folders The Maid can access:</p>
      <div className="folder-grid">
        {["Desktop", "Downloads", "Documents", "Pictures", "Videos", "Music"].map((folder) => (
          <label key={folder} className="folder-checkbox">
            <input
              type="checkbox"
              checked={selectedFolders.includes(folder)}
              onChange={() => toggleFolder(folder)}
            />
            {folder}
          </label>
        ))}
      </div>
      <button onClick={() => setStep(2)} disabled={selectedFolders.length === 0}>
        Next →
      </button>
    </div>
  );

  // Step 2: Feature selection
  const renderStep2 = () => (
    <div className="wizard-step">
      <h2>🧩 Choose Features</h2>
      <p>Select which capabilities to install. You can change these later.</p>
      <div className="feature-grid">
        <label className={`feature-card ${features.general_files ? "selected" : ""}`}>
          <input
            type="checkbox"
            checked={features.general_files}
            onChange={(e) => setFeatures({ ...features, general_files: e.target.checked })}
          />
          <div className="feature-info">
            <strong>📁 General Files</strong>
            <p>Sort documents, images, videos, archives. Always recommended.</p>
            <span className="model-size">~500MB · bundled</span>
          </div>
        </label>
        <label className={`feature-card ${features.pdf_ocr ? "selected" : ""}`}>
          <input
            type="checkbox"
            checked={features.pdf_ocr}
            onChange={(e) => setFeatures({ ...features, pdf_ocr: e.target.checked })}
          />
          <div className="feature-info">
            <strong>📄 PDF OCR</strong>
            <p>Read text from scanned PDFs for smart categorization.</p>
            <span className="model-size">~1GB download</span>
          </div>
        </label>
        <label className={`feature-card ${features.face_clustering ? "selected" : ""}`}>
          <input
            type="checkbox"
            checked={features.face_clustering}
            onChange={(e) => setFeatures({ ...features, face_clustering: e.target.checked })}
          />
          <div className="feature-info">
            <strong>👤 Face Clustering</strong>
            <p>Group photos by person and name them. All offline.</p>
            <span className="model-size">~100MB download</span>
          </div>
        </label>
      </div>
      <div className="wizard-nav">
        <button onClick={() => setStep(1)}>← Back</button>
        <button onClick={() => setStep(3)} disabled={!canAdvanceFromStep2(features)}>
          Next →
        </button>
      </div>
    </div>
  );

  // Step 3: Model download with progress
  const startDownload = async (key: string) => {
    setDownloads((prev) => ({ ...prev, [key]: { state: "downloading", progress: 0 } }));
    try {
      await invoke("download_model", { modelId: key });
    } catch (err) {
      setDownloads((prev) => ({ ...prev, [key]: { state: "idle", progress: 0 } }));
      setError(`Download failed: ${err}`);
    }
  };

  const skipDownload = (key: string) => {
    setDownloads((prev) => ({ ...prev, [key]: { state: "skipped", progress: 0 } }));
  };

  const isDownloadComplete = () => {
    return allDownloadsDone(downloads, features);
  };

  const renderStep3 = () => (
    <div className="wizard-step">
      <h2>⬇️ Download Models</h2>
      <p>Fetching models for your selected features. Everything stays local.</p>

      <div className="download-list">
        {/* Text LLM — always bundled */}
        <div className="download-item">
          <div className="download-info">
            <strong>{MODELS.text.name}</strong>
            <span className="model-size">~{MODELS.text.size}MB · bundled</span>
          </div>
          <div className="download-status done">✓ Included</div>
        </div>

        {/* PDF OCR */}
        {features.pdf_ocr && (
          <div className="download-item">
            <div className="download-info">
              <strong>{MODELS.pdf.name}</strong>
              <span className="model-size">~{MODELS.pdf.size}MB</span>
            </div>
            {downloads.pdf.state === "idle" && (
              <button onClick={() => startDownload("pdf")} className="small">Download</button>
            )}
            {downloads.pdf.state === "downloading" && (
              <div className="download-progress">
                <div className="progress-bar slim">
                  <div className="progress-fill" style={{ width: `${downloads.pdf.progress}%` }} />
                </div>
                <span>{Math.round(downloads.pdf.progress)}%</span>
              </div>
            )}
            {downloads.pdf.state === "done" && <div className="download-status done">✓ Done</div>}
            {downloads.pdf.state === "skipped" && <div className="download-status skipped">Skipped</div>}
          </div>
        )}

        {/* Face clustering */}
        {features.face_clustering && (
          <div className="download-item">
            <div className="download-info">
              <strong>{MODELS.face.name}</strong>
              <span className="model-size">~{MODELS.face.size}MB</span>
            </div>
            {downloads.face.state === "idle" && (
              <button onClick={() => startDownload("face")} className="small">Download</button>
            )}
            {downloads.face.state === "downloading" && (
              <div className="download-progress">
                <div className="progress-bar slim">
                  <div className="progress-fill" style={{ width: `${downloads.face.progress}%` }} />
                </div>
                <span>{Math.round(downloads.face.progress)}%</span>
              </div>
            )}
            {downloads.face.state === "done" && <div className="download-status done">✓ Done</div>}
            {downloads.face.state === "skipped" && <div className="download-status skipped">Skipped</div>}
          </div>
        )}

        {/* Skip option for optional models */}
        {features.pdf_ocr && downloads.pdf.state === "idle" && (
          <button onClick={() => skipDownload("pdf")} className="small muted-btn">Skip PDF for now</button>
        )}
        {features.face_clustering && downloads.face.state === "idle" && (
          <button onClick={() => skipDownload("face")} className="small muted-btn">Skip Face for now</button>
        )}
      </div>

      <div className="wizard-nav">
        <button onClick={() => setStep(2)}>← Back</button>
        <button
          onClick={() => setStep(4)}
          disabled={!isDownloadComplete()}
        >
          {isDownloadComplete() ? "Next →" : "Waiting for downloads…"}
        </button>
      </div>
    </div>
  );

  // Step 4: Ready
  const handleComplete = async () => {
    setSaving(true);
    setError("");
    try {
      const payload = buildSetupPayload(selectedFolders, features);
      await invoke("complete_setup", payload);
      onComplete();
    } catch (err) {
      setError(String(err));
      setSaving(false);
    }
  };

  const renderStep4 = () => (
    <div className="wizard-step">
      <h2>🚀 Ready to Clean</h2>
      <p>The Maid will scan your selected folders and propose an organization plan.</p>
      <p><strong>Remember:</strong> Nothing moves until you approve it.</p>

      <div className="setup-summary">
        <h3>Setup Summary</h3>
        <p><strong>Folders:</strong> {selectedFolders.join(", ")}</p>
        <p><strong>Features:</strong> {[
          features.general_files && "General Files",
          features.pdf_ocr && "PDF OCR",
          features.face_clustering && "Face Clustering",
        ].filter(Boolean).join(", ") || "None"}</p>
      </div>

      {error && <div className="error">⚠️ {error}</div>}

      <div className="wizard-nav">
        <button onClick={() => setStep(3)} disabled={saving}>← Back</button>
        <button onClick={handleComplete} className="primary" disabled={saving}>
          {saving ? "Saving…" : "Start First Scan"}
        </button>
      </div>
    </div>
  );

  return (
    <div className="setup-wizard">
      <div className="progress-bar">
        <div className="progress-fill" style={{ width: `${(step / totalSteps) * 100}%` }} />
      </div>
      {step === 1 && renderStep1()}
      {step === 2 && renderStep2()}
      {step === 3 && renderStep3()}
      {step === 4 && renderStep4()}
    </div>
  );
}