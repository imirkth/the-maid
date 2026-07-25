import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

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
  const [backendReady, setBackendReady] = useState(false);

  useEffect(() => {
    // Listen for backend_ready event
    const unlistenReady = listen<boolean>("backend_ready", (e) => {
      setBackendReady(e.payload);
    });

    // Listen for scan_progress events
    const unlistenProgress = listen<number>("scan_progress", (e) => {
      setProgress(e.payload * 100);
    });

    // Listen for scan_complete event
    const unlistenComplete = listen<unknown>("scan_complete", () => {
      setScanning(false);
      setProgress(100);
    });

    return () => {
      unlistenReady.then((f) => f());
      unlistenProgress.then((f) => f());
      unlistenComplete.then((f) => f());
    };
  }, []);

  const handleScan = async () => {
    if (!directory) return;
    setScanning(true);
    setProgress(0);
    setError("");
    setResults([]);

    try {
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

  const handlePing = async () => {
    try {
      await invoke("ping_backend");
    } catch (err) {
      setError(String(err));
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
        <button onClick={handleScan} disabled={scanning || !directory || !backendReady}>
          {scanning ? "Scanning..." : backendReady ? "Scan" : "Waiting for backend..."}
        </button>
        <button onClick={handlePing} disabled={!backendReady} style={{ marginLeft: "8px" }}>
          Health Check
        </button>
      </div>

      {scanning && (
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${progress}%` }} />
          <span className="progress-text">{Math.round(progress)}%</span>
        </div>
      )}

      {error && <div className="error">⚠️ {error}</div>}

      {results.length > 0 && (
        <div className="results-summary">
          <p>Found {results.length} files to organize.</p>
          <button className="primary">Review Proposals →</button>
        </div>
      )}

      {results.length === 0 && !scanning && !error && directory && backendReady && (
        <p style={{ color: "#888", marginTop: "16px" }}>I found nothing to organize.</p>
      )}
    </div>
  );
}