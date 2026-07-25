import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import SetupWizard from "./components/SetupWizard";
import ScanView from "./components/ScanView";
import ApprovalView from "./components/ApprovalView";
import BucketManager from "./components/BucketManager";
import FaceClusterView from "./components/FaceClusterView";
import SettingsPanel from "./components/SettingsPanel";
import "./styles.css";

type View = "setup" | "scan" | "approval" | "buckets" | "faces" | "settings";

function App() {
  const [currentView, setCurrentView] = useState<View>("setup");
  const [isFirstRun, setIsFirstRun] = useState(true);
  const [backendReady, setBackendReady] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const unlisten = listen<boolean>("backend_ready", (e) => {
      setBackendReady(e.payload);
    });
    return () => { unlisten.then((f) => f()); };
  }, []);

  // Load settings on startup — determines if Setup Wizard should show
  useEffect(() => {
    invoke<{ first_run: boolean }>("get_settings")
      .then((s) => {
        setIsFirstRun(s.first_run);
        setLoaded(true);
      })
      .catch(() => setLoaded(true)); // defaults to first run
  }, []);

  const handleSetupComplete = () => {
    invoke("complete_first_run").catch(() => {});
    setIsFirstRun(false);
    setCurrentView("scan");
  };

  const renderView = () => {
    switch (currentView) {
      case "setup":
        return <SetupWizard onComplete={handleSetupComplete} />;
      case "scan":
        return <ScanView />;
      case "approval":
        return <ApprovalView />;
      case "buckets":
        return <BucketManager />;
      case "faces":
        return <FaceClusterView />;
      case "settings":
        return <SettingsPanel />;
      default:
        return <ScanView />;
    }
  };

  if (!loaded) {
    return <div className="app"><div className="content"><p>Loading…</p></div></div>;
  }

  return (
    <div className="app">
      {!isFirstRun && (
        <nav className="sidebar">
          <div className="logo">🧹 The Maid</div>
          <button onClick={() => setCurrentView("scan")} className={currentView === "scan" ? "active" : ""}>
            📁 Scan
          </button>
          <button onClick={() => setCurrentView("approval")} className={currentView === "approval" ? "active" : ""}>
            ✅ Approve
          </button>
          <button onClick={() => setCurrentView("buckets")} className={currentView === "buckets" ? "active" : ""}>
            📂 Buckets
          </button>
          <button onClick={() => setCurrentView("faces")} className={currentView === "faces" ? "active" : ""}>
            👤 Faces
          </button>
          <button onClick={() => setCurrentView("settings")} className={currentView === "settings" ? "active" : ""}>
            ⚙️ Settings
          </button>
          <div className="backend-status" style={{ marginTop: "auto", padding: "8px", fontSize: "12px" }}>
            {backendReady ? "🟢 Backend ready" : "🔴 Backend offline"}
          </div>
        </nav>
      )}
      <main className="content">{renderView()}</main>
    </div>
  );
}

export default App;