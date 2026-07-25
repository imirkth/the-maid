import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import SetupWizard from "./components/SetupWizard";
import ScanView from "./components/ScanView";
import ApprovalView from "./components/ApprovalView";
import BucketManager from "./components/BucketManager";
import FaceClusterView from "./components/FaceClusterView";
import "./styles.css";

type View = "setup" | "scan" | "approval" | "buckets" | "faces" | "settings";

function App() {
  const [currentView, setCurrentView] = useState<View>("setup");
  const [isFirstRun, setIsFirstRun] = useState(true);

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
        return <div className="coming-soon">Settings — coming soon</div>;
      default:
        return <ScanView />;
    }
  };

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
        </nav>
      )}
      <main className="content">{renderView()}</main>
    </div>
  );
}

export default App;
