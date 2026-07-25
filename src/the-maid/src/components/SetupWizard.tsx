import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";

interface Props {
  onComplete: () => void;
}

export default function SetupWizard({ onComplete }: Props) {
  const [step, setStep] = useState(1);
  const [selectedFolders, setSelectedFolders] = useState<string[]>([
    "Desktop",
    "Downloads",
    "Documents",
    "Pictures",
  ]);
  const [buckets, setBuckets] = useState([
    { id: "1", name: "Desktop", path: "~/Desktop" },
    { id: "2", name: "Documents", path: "~/Documents" },
    { id: "3", name: "Pictures", path: "~/Pictures" },
    { id: "4", name: "Downloads", path: "~/Downloads" },
  ]);

  const toggleFolder = (folder: string) => {
    setSelectedFolders((prev) =>
      prev.includes(folder) ? prev.filter((f) => f !== folder) : [...prev, folder]
    );
  };

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

  const renderStep2 = () => (
    <div className="wizard-step">
      <h2>📂 Default Buckets</h2>
      <p>These are your approved destination folders. You can add more later.</p>
      <ul className="bucket-list">
        {buckets.map((b) => (
          <li key={b.id}>
            <strong>{b.name}</strong> → {b.path}
          </li>
        ))}
      </ul>
      <div className="wizard-nav">
        <button onClick={() => setStep(1)}>← Back</button>
        <button onClick={() => setStep(3)}>Next →</button>
      </div>
    </div>
  );

  const renderStep3 = () => (
    <div className="wizard-step">
      <h2>🚀 Ready to Clean</h2>
      <p>The Maid will scan your selected folders and propose an organization plan.</p>
      <p><strong>Remember:</strong> Nothing moves until you approve it.</p>
      <div className="wizard-nav">
        <button onClick={() => setStep(2)}>← Back</button>
        <button onClick={onComplete} className="primary">Start First Scan</button>
      </div>
    </div>
  );

  return (
    <div className="setup-wizard">
      <div className="progress-bar">
        <div className="progress-fill" style={{ width: `${(step / 3) * 100}%` }} />
      </div>
      {step === 1 && renderStep1()}
      {step === 2 && renderStep2()}
      {step === 3 && renderStep3()}
    </div>
  );
}
