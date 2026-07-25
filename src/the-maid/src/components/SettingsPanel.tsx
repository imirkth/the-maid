import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";

interface Settings {
  sandbox_folders: string[];
  first_run: boolean;
  buckets: { id: string; name: string; path: string }[];
}

export default function SettingsPanel() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [newFolder, setNewFolder] = useState("");

  useEffect(() => {
    invoke<Settings>("get_settings").then(setSettings);
  }, []);

  const addFolder = () => {
    if (!newFolder.trim()) return;
    invoke<Settings>("add_sandbox_folder", { folder: newFolder.trim() }).then(setSettings);
    setNewFolder("");
  };

  const removeFolder = (folder: string) => {
    invoke<Settings>("remove_sandbox_folder", { folder }).then(setSettings);
  };

  if (!settings) return <p>Loading…</p>;

  return (
    <div className="settings-panel">
      <h2>⚙️ Settings</h2>

      <section>
        <h3>Sandbox Folders</h3>
        <p>Folders The Maid is allowed to scan and organize.</p>
        <ul className="folder-list">
          {settings.sandbox_folders.map((f) => (
            <li key={f}>
              {f}
              <button onClick={() => removeFolder(f)} className="btn-small">Remove</button>
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
      </section>

      <section>
        <h3>Support The Maid</h3>
        <p>The Maid is free with optional donation. No DRM, no telemetry.</p>
        <a href="https://github.com/imirkth/the-maid" target="_blank" rel="noreferrer">
          Support on GitHub →
        </a>
      </section>
    </div>
  );
}