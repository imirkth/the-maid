import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";

interface ScanResult {
  file_id: string;
  original_filename: string;
  current_path: string;
  proposed_path: string;
  proposed_tags: string[];
  faces_detected: string[];
  rationale: string;
}

export default function ScanView() {
  const [directory, setDirectory] = useState("");
  const [scanning, setScanning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [results, setResults] = useState<ScanResult[]>([]);
  const [error, setError] = useState("");

  const handleScan = async () => {
    if (!directory) return;
    setScanning(true);
    setError("");
    setResults([]);

    try {
      // TODO: This will call the Python backend via invoke
      const proposals: ScanResult[] = await invoke("scan_directory", {
        request: { directory, max_files: 10000 },
      });
      setResults(proposals);
    } catch (err) {
      setError(String(err));
    } finally {
      setScanning(false);
    }
  };

  return (
    <div className="scan-view">
      <h2>📁 Scan Directory</h2>
      <div className="scan-input">
        <input
          type="text"
          placeholder="Enter path (e.g., ~/Downloads)"
          value={directory}
          onChange={(e) => setDirectory(e.target.value)}
        />
        <button onClick={handleScan} disabled={scanning || !directory}>
          {scanning ? "Scanning..." : "Scan"}
        </button>
      </div>

      {scanning && (
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${progress}%` }} />
        </div>
      )}

      {error && <div className="error">⚠️ {error}</div>}

      {results.length > 0 && (
        <div className="results-summary">
          <p>Found {results.length} files to organize.</p>
          <button className="primary">Review Proposals →</button>
        </div>
      )}
    </div>
  );
}
