import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

interface FileMeta {
  file_id: string;
  filename: string;
  path: string;
  size_bytes: number;
  modified_time: string;
  extension: string;
  mime_type: string;
}

interface ScanResponse {
  files: FileMeta[];
  errors: string[];
  count: number;
}

interface Settings {
  sandbox_folders: string[];
  first_run: boolean;
  setup_complete: boolean;
  buckets: { id: string; name: string; path: string }[];
}

export default function ScanView() {
  const [directory, setDirectory] = useState("");
  const [scanning, setScanning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [results, setResults] = useState<FileMeta[]>([]);
  const [error, setError] = useState("");
  const [backendReady, setBackendReady] = useState(false);
  const [scanned, setScanned] = useState(false);
  const [canScan, setCanScan] = useState(false);
  const [settings, setSettings] = useState<Settings | null>(null);

  useEffect(() => {
    // Load settings to check sandbox folders
    invoke<Settings>("get_settings")
      .then((s) => {
        setSettings(s);
        setCanScan(s.sandbox_folders.length > 0);
        if (s.sandbox_folders.length > 0 && !directory) {
          setDirectory(`${s.sandbox_folders[0]}`);
        }
      })
      .catch((e) => setError(String(e)));

    const unlistenReady = listen<boolean>("backend_ready", (e) => {
      setBackendReady(e.payload);
    });

    const unlistenProgress = listen<number>("scan_progress", (e) => {
      setProgress(e.payload * 100);
    });

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
    if (!directory || !canScan) return;
    setScanning(true);
    setProgress(0);
    setError("");
    setResults([]);
    setScanned(false);

    try {
      const resp: ScanResponse = await invoke("scan_directory", {
        request: { directory, max_files: 10000 },
      });
      setResults(resp.files);
      setScanned(true);
      if (resp.errors.length > 0) {
        setError(resp.errors.join("; "));
      }
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

  const scanDisabled = scanning || !directory || !backendReady || !canScan;

  return (
    <div className="scan-view">
      <h2>📁 Scan Directory</h2>

      {!canScan && (
        <p className="warning">⚠️ Complete the setup wizard and select at least one folder before scanning.</p>
      )}

      <div className="scan-input">
        {settings && settings.sandbox_folders.length > 0 && (
          <select
            value={directory}
            onChange={(e) => setDirectory(e.target.value)}
            disabled={scanning}
          >
            <option value="">Select a folder to scan…</option>
            {settings.sandbox_folders.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        )}
        <button onClick={handleScan} disabled={scanDisabled}>
          {scanning ? "Scanning…" : !backendReady ? "Waiting for backend…" : !canScan ? "No folders selected" : "Scan"}
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
          <p>I found {results.length} files to organize.</p>
          <button className="primary">Review Proposals →</button>
        </div>
      )}

      {results.length === 0 && scanned && !scanning && !error && (
        <p style={{ color: "#888", marginTop: "16px" }}>I found nothing to organize.</p>
      )}
    </div>
  );
}