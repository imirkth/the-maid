import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";

interface Props {
  onComplete: () => void;
}

// ponytail: model metadata — sizes for progress display. Real URLs added when bundling pipeline exists.
const MODELS = {
  text: { name: "Text LLM (always bundled)", size: 500, required: true },
  pdf: { name: "PDF OCR Model", size: 1000, optional: true },
  face: { name: "Face Recognition Model", size: 100, optional: true },
};

type DownloadState = "idle" | "downloading" | "done" | "skipped";

interface DownloadStatus {
  state: DownloadState;
  progress: number; // 0-100
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
    text: { state: "idle", progress: 0 },
    pdf: { state: "idle", progress: 0 },
    face: { state: "idle", progress: 0 },
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

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
        <button onClick={() => setStep(3)}>Next →</button>
      </div>
    </div>
  );

  // Step 3: Model download with progress
  const startDownload = (key: string, sizeMB: number) => {
    // ponytail: simulated download. Real download logic added when model bundling pipeline exists.
    setDownloads((prev) => ({ ...prev, [key]: { state: "downloading", progress: 0 } }));
    const interval = setInterval(() => {
      setDownloads((prev) => {
        const current = prev[key];
        if (current.state !== "downloading") {
          clearInterval(interval);
          return prev;
        }
        const next = Math.min(current.progress + Math.random() * 15 + 5, 100);
        if (next >= 100) {
          clearInterval(interval);
          return { ...prev, [key]: { state: "done", progress: 100 } };
        }
        return { ...prev, [key]: { state: "downloading", progress: next } };
      });
    }, 200);
  };

  const skipDownload = (key: string) => {
    setDownloads((prev) => ({ ...prev, [key]: { state: "skipped", progress: 0 } }));
  };

  const allDownloadsDone = () => {
    // Text model is always bundled — auto-done
    if (downloads.text.state === "idle") {
      setDownloads((prev) => ({ ...prev, text: { state: "done", progress: 100 } }));
    }
    const required = [
      { key: "text", needed: true },
      { key: "pdf", needed: features.pdf_ocr },
      { key: "face", needed: features.face_clustering },
    ];
    return required.every(({ key, needed }) => {
      if (!needed) return downloads[key]?.state === "skipped" || downloads[key]?.state === "done" || true;
      return downloads[key]?.state === "done";
    });
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
              <button onClick={() => startDownload("pdf", MODELS.pdf.size)} className="small">Download</button>
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
              <button onClick={() => startDownload("face", MODELS.face.size)} className="small">Download</button>
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
          disabled={!allDownloadsDone()}
        >
          {allDownloadsDone() ? "Next →" : "Waiting for downloads…"}
        </button>
      </div>
    </div>
  );

  // Step 4: Ready
  const handleComplete = async () => {
    setSaving(true);
    setError("");
    try {
      await invoke("complete_setup", {
        folders: selectedFolders,
        pdfOcr: features.pdf_ocr,
        faceClustering: features.face_clustering,
        generalFiles: features.general_files,
      });
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