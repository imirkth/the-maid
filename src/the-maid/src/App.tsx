import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import SetupWizard from "./components/SetupWizard";
import ScanView from "./components/ScanView";
import ApprovalView from "./components/ApprovalView";
import BucketManager from "./components/BucketManager";
import FaceClusterView from "./components/FaceClusterView";
import SettingsPanel from "./components/SettingsPanel";
import Icon, { type IconName } from "./components/Icon";
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
    // The ready event can fire before this screen listens, so also ask directly
    invoke("ping_backend").then(() => setBackendReady(true)).catch(() => {});
    return () => { unlisten.then((f) => f()); };
  }, []);

  // Load settings on startup — determines if Setup Wizard should show
  useEffect(() => {
    invoke<{ first_run: boolean; setup_complete: boolean }>("get_settings")
      .then((s) => {
        const firstRun = s.first_run || !s.setup_complete;
        setIsFirstRun(firstRun);
        if (!firstRun) setCurrentView("scan");
        setLoaded(true);
      })
      .catch(() => setLoaded(true)); // defaults to first run
  }, []);

  const handleSetupComplete = () => {
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
    return <div className="app"><div className="content app-loading"><span className="spinner" /> Loading…</div></div>;
  }

  const nav: { view: View; label: string; icon: IconName; hint: string }[] = [
    { view: "scan", label: "Organize", icon: "broom", hint: "Scan a folder and shape its tree" },
    { view: "approval", label: "Review", icon: "listCheck", hint: "Approve suggested moves" },
    { view: "buckets", label: "Buckets", icon: "inbox", hint: "Your destination folders" },
    { view: "faces", label: "Faces", icon: "users", hint: "Group photos by person" },
    { view: "settings", label: "Settings", icon: "settings", hint: "Folders, models and about" },
  ];

  return (
    <div className="app">
      {!isFirstRun && (
        <nav className="sidebar" aria-label="Main">
          <div className="logo"><span className="logo-mark"><Icon name="broom" size={18} /></span> The Maid</div>
          {nav.map((n) => (
            <button key={n.view} type="button" title={n.hint} onClick={() => setCurrentView(n.view)}
              className={currentView === n.view ? "active" : ""} aria-current={currentView === n.view ? "page" : undefined}>
              <Icon name={n.icon} size={17} /> {n.label}
            </button>
          ))}
          <div className={`backend-status${backendReady ? " ready" : ""}`} title={backendReady ? "The local engine is running" : "The local engine is starting or stopped"}>
            <span className="status-dot" /> {backendReady ? "Ready" : "Starting…"}
          </div>
        </nav>
      )}
      <main className="content">{renderView()}</main>
    </div>
  );
}

export default App;