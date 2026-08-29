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

// Content tree types
interface TreeFile {
  file_id: string;
  filename: string;
  path: string;
  proposed_path?: string;
  size_bytes: number;
  rationale: string;
  confidence: number;
  tags: string[];
  approved?: boolean;
}

interface TreeChild {
  name?: string;
  count?: number;
  files?: TreeFile[];
  file_id?: string;
  filename?: string;
  path?: string;
  proposed_path?: string;
  size_bytes?: number;
  rationale?: string;
  confidence?: number;
  tags?: string[];
  approved?: boolean;
}

interface TreeCategory {
  name: string;
  count: number;
  children: TreeChild[];
}

interface CategorizeResponse {
  categories: TreeCategory[];
  total_files: number;
  total_categorized: number;
}

interface TreeState {
  tree: TreeCategory[];
  approved_structure: boolean;
  total_files: number;
  total_categorized: number;
}

function shortPath(fullPath: string): string {
  const parts = fullPath.split('/');
  if (parts.length <= 3) return fullPath;
  return '…/' + parts.slice(-2).join('/');
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

interface ScanProgress {
  count: number;
  max_files: number;
  progress: number;
  elapsed_seconds: number;
  eta_seconds: number;
}

interface CategorizeProgress {
  progress: number;
  batch: number;
  total_batches: number;
  files_done: number;
  files_total: number;
  elapsed_seconds: number;
  eta_seconds: number;
}

function formatDuration(seconds: number): string {
  if (seconds < 1) return "0s";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

function confidenceClass(c: number): string {
  if (c >= 0.75) return "confidence-high";
  if (c >= 0.5) return "confidence-medium";
  if (c > 0) return "confidence-low";
  return "confidence-none";
}

export default function ScanView() {
  const [directory, setDirectory] = useState("");
  const [scanning, setScanning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [scanCount, setScanCount] = useState(0);
  const [scanMax, setScanMax] = useState(0);
  const [scanElapsed, setScanElapsed] = useState(0);
  const [scanEta, setScanEta] = useState(0);
  const [results, setResults] = useState<FileMeta[]>([]);
  const [error, setError] = useState("");
  const [backendReady, setBackendReady] = useState(false);
  const [scanned, setScanned] = useState(false);
  const [canScan, setCanScan] = useState(false);
  const [settings, setSettings] = useState<Settings | null>(null);

  // Categorization state
  const [categorizing, setCategorizing] = useState(false);
  const [categorizeProgress, setCategorizeProgress] = useState(0);
  const [catFilesDone, setCatFilesDone] = useState(0);
  const [catFilesTotal, setCatFilesTotal] = useState(0);
  const [catBatch, setCatBatch] = useState(0);
  const [catTotalBatches, setCatTotalBatches] = useState(0);
  const [catElapsed, setCatElapsed] = useState(0);
  const [catEta, setCatEta] = useState(0);

  // Persistent tree state
  const [tree, setTree] = useState<TreeState | null>(null);
  const [expandedCats, setExpandedCats] = useState<Set<string>>(new Set());
  const [expandedSubs, setExpandedSubs] = useState<Set<string>>(new Set());

  // Tree editing state
  const [editingCat, setEditingCat] = useState<string | null>(null);
  const [editCatValue, setEditCatValue] = useState("");
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set());
  const [movingFileId, setMovingFileId] = useState<string | null>(null);
  const [moveTargetCat, setMoveTargetCat] = useState("");
  const [moveTargetSub, setMoveTargetSub] = useState("");
  const [executing, setExecuting] = useState(false);
  const [executeResults, setExecuteResults] = useState<string | null>(null);

  useEffect(() => {
    invoke<Settings>("get_settings")
      .then((s) => {
        setSettings(s);
        setCanScan(s.sandbox_folders.length > 0);
        if (s.sandbox_folders.length > 0 && !directory) {
          setDirectory(`${s.sandbox_folders[0]}`);
        }
      })
      .catch((e) => setError(String(e)));

    // Load persistent tree on startup
    invoke<TreeState>("get_tree")
      .then((t) => {
        if (t.tree && t.tree.length > 0) {
          setTree(t);
          const initial = new Set<string>();
          t.tree.slice(0, 3).forEach((c) => initial.add(c.name));
          setExpandedCats(initial);
        }
      })
      .catch(() => {});

    const unlistenReady = listen<boolean>("backend_ready", (e) => {
      setBackendReady(e.payload);
    });
    invoke("ping_backend")
      .then(() => setBackendReady(true))
      .catch(() => {});

    const unlistenProgress = listen<ScanProgress>("scan_progress", (e) => {
      const p = e.payload;
      setProgress(p.progress * 100);
      setScanCount(p.count);
      setScanMax(p.max_files);
      setScanElapsed(p.elapsed_seconds);
      setScanEta(p.eta_seconds);
    });

    const unlistenComplete = listen<{ count: number; elapsed_seconds: number }>("scan_complete", (e) => {
      setScanning(false);
      setProgress(100);
      setScanElapsed(e.payload?.elapsed_seconds ?? 0);
      setScanEta(0);
    });

    const unlistenCatProgress = listen<CategorizeProgress>("categorize_progress", (e) => {
      const p = e.payload;
      setCategorizeProgress(p.progress * 100);
      setCatFilesDone(p.files_done ?? 0);
      setCatFilesTotal(p.files_total ?? 0);
      setCatBatch(p.batch ?? 0);
      setCatTotalBatches(p.total_batches ?? 0);
      setCatElapsed(p.elapsed_seconds ?? 0);
      setCatEta(p.eta_seconds ?? 0);
    });

    const unlistenCatComplete = listen<{ total: number; elapsed_seconds: number }>("categorize_complete", (e) => {
      setCategorizing(false);
      setCategorizeProgress(100);
      setCatEta(0);
      if (e.payload?.elapsed_seconds) setCatElapsed(e.payload.elapsed_seconds);
    });

    return () => {
      unlistenReady.then((f) => f());
      unlistenProgress.then((f) => f());
      unlistenComplete.then((f) => f());
      unlistenCatProgress.then((f) => f());
      unlistenCatComplete.then((f) => f());
    };
  }, []);

  const handleScan = async () => {
    if (!directory || !canScan) return;
    setScanning(true);
    setProgress(0);
    setScanCount(0);
    setScanMax(0);
    setScanElapsed(0);
    setScanEta(0);
    setError("");
    setResults([]);
    setScanned(false);
    // Don't clear tree — it's persistent now

    try {
      const resp: ScanResponse = await invoke("scan_directory", {
        request: { directory, max_files: 1000 },
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

  const handleCategorize = async () => {
    if (results.length === 0) return;
    setCategorizing(true);
    setCategorizeProgress(0);
    setCatFilesDone(0);
    setCatFilesTotal(results.length);
    setCatBatch(0);
    setCatTotalBatches(0);
    setCatElapsed(0);
    setCatEta(0);
    setError("");
    // Don't clear existing tree — merge into it

    try {
      const resp: CategorizeResponse = await invoke("categorize_files", {
        files: results,
        directory,
      });
      // Merge new results into persistent tree
      const merged = await invoke<TreeState>("merge_tree", {
        categories: resp.categories,
        totalFiles: resp.total_files,
        totalCategorized: resp.total_categorized,
      });
      setTree(merged);
      const initial = new Set<string>();
      (merged.tree || []).slice(0, 3).forEach((c) => initial.add(c.name));
      setExpandedCats(initial);
    } catch (err) {
      setError(String(err));
    } finally {
      setCategorizing(false);
    }
  };

  const toggleCat = (name: string) => {
    setExpandedCats((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const toggleSub = (key: string) => {
    setExpandedSubs((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const startRenameCat = (name: string) => {
    setEditingCat(name);
    setEditCatValue(name);
  };

  const submitRenameCat = async () => {
    if (!editingCat || !editCatValue.trim()) return;
    try {
      const updated = await invoke<{ tree: TreeCategory[] }>("edit_category", {
        oldName: editingCat,
        newName: editCatValue.trim(),
        delete: false,
      });
      setTree(prev => prev ? { ...prev, tree: updated.tree } : null);
    } catch (err) {
      setError(String(err));
    }
    setEditingCat(null);
  };

  const deleteCat = async (name: string) => {
    if (!confirm(`Delete category "${name}"? Files will move to Uncategorized.`)) return;
    try {
      const updated = await invoke<{ tree: TreeCategory[] }>("edit_category", {
        oldName: name,
        newName: null,
        delete: true,
      });
      setTree(prev => prev ? { ...prev, tree: updated.tree } : null);
    } catch (err) {
      setError(String(err));
    }
  };

  const approveStructure = async () => {
    try {
      await invoke("approve_tree_structure");
      setTree(prev => prev ? { ...prev, approved_structure: true } : null);
    } catch (err) {
      setError(String(err));
    }
  };

  const toggleFileSelection = (fileId: string) => {
    setSelectedFileIds((prev) => {
      const next = new Set(prev);
      if (next.has(fileId)) next.delete(fileId);
      else next.add(fileId);
      return next;
    });
  };

  const submitMoveFile = async () => {
    if (!movingFileId || !moveTargetCat) return;
    try {
      const updated = await invoke<{ tree: TreeCategory[] }>("move_file_in_tree", {
        fileId: movingFileId,
        targetCategory: moveTargetCat,
        targetSubcategory: moveTargetSub,
      });
      setTree(prev => prev ? { ...prev, tree: updated.tree } : null);
    } catch (err) {
      setError(String(err));
    }
    setMovingFileId(null);
    setMoveTargetCat("");
    setMoveTargetSub("");
  };

  const handleExecuteMoves = async () => {
    if (selectedFileIds.size === 0) return;
    if (!confirm(`Move ${selectedFileIds.size} files on disk? This is irreversible (uses trash for conflicts).`)) return;
    setExecuting(true);
    setError("");
    try {
      const result = await invoke<{ results: Array<{ file_id: string; status: string; detail?: string }> }>("execute_tree_moves", {
        approvedFileIds: Array.from(selectedFileIds),
      });
      const moved = result.results.filter((r) => r.status === "moved").length;
      const errors = result.results.filter((r) => r.status === "error");
      setExecuteResults(`Moved ${moved} files. ${errors.length > 0 ? `${errors.length} errors.` : ""}`);
      // Clear selection
      setSelectedFileIds(new Set());
    } catch (err) {
      setError(String(err));
    } finally {
      setExecuting(false);
    }
  };

  const scanDisabled = scanning || !directory || !backendReady || !canScan;
  const hasTree = tree && tree.tree && tree.tree.length > 0;
  const allCategoryNames = hasTree ? tree!.tree.map(c => c.name) : [];

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
              <option key={f} value={f}>{f.split('/').pop() || f}</option>
            ))}
          </select>
        )}
        <button onClick={handleScan} disabled={scanDisabled}>
          {scanning ? "Scanning…" : !backendReady ? "Waiting for backend…" : !canScan ? "No folders selected" : "Scan"}
        </button>
      </div>

      {scanning && (
        <div className="scan-progress-panel">
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${progress}%` }} />
            <span className="progress-text">{Math.round(progress)}%</span>
          </div>
          <div className="scan-progress-stats">
            <span>📄 {scanCount.toLocaleString()} files scanned</span>
            {scanEta > 0 && <span>⏱ ~{formatDuration(scanEta)} remaining</span>}
            {scanElapsed > 0 && <span>🕐 {formatDuration(scanElapsed)} elapsed</span>}
          </div>
        </div>
      )}

      {error && <div className="error">⚠️ {error}</div>}

      {/* Scan results — show Categorize button */}
      {results.length > 0 && !categorizing && (
        <div className="scan-results">
          <p className="scan-summary">
            Found <strong>{results.length}</strong> new files to categorize
          </p>
          <button className="primary" onClick={handleCategorize} style={{ marginTop: "12px" }}>
            🧠 Categorize with AI
          </button>
        </div>
      )}

      {/* Categorization progress */}
      {categorizing && (
        <div className="scan-progress-panel">
          <p className="scan-summary">
            Analyzing content of <strong>{results.length.toLocaleString()}</strong> files…
          </p>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${categorizeProgress}%` }} />
            <span className="progress-text">{Math.round(categorizeProgress)}%</span>
          </div>
          <div className="scan-progress-stats">
            {catFilesDone > 0 && <span>📄 {catFilesDone.toLocaleString()} / {catFilesTotal.toLocaleString()} files</span>}
            {catTotalBatches > 1 && <span>📦 Batch {catBatch} / {catTotalBatches}</span>}
            {catEta > 0 && <span>⏱ ~{formatDuration(catEta)} remaining</span>}
            {catElapsed > 0 && <span>🕐 {formatDuration(catElapsed)} elapsed</span>}
          </div>
        </div>
      )}

      {/* Persistent Tree Display */}
      {hasTree && (
        <div className="scan-results">
          <div className="tree-header">
            <p className="scan-summary">
              <strong>{tree!.total_categorized}</strong> of <strong>{tree!.total_files}</strong> files categorized
              {tree!.approved_structure && <span className="badge-approved"> ✓ Tree approved</span>}
            </p>
            {!tree!.approved_structure ? (
              <button className="primary" onClick={approveStructure} style={{ marginLeft: "12px" }}>
                ✓ Approve Tree Structure
              </button>
            ) : (
              <div className="approval-actions">
                <span className="file-selection-info">{selectedFileIds.size} files selected</span>
                <button
                  className="primary"
                  onClick={handleExecuteMoves}
                  disabled={selectedFileIds.size === 0 || executing}
                  style={{ marginLeft: "12px" }}
                >
                  {executing ? "Moving…" : "📦 Approve & Move Files"}
                </button>
              </div>
            )}
          </div>

          {executeResults && <p className="scan-summary" style={{ color: "#4ade80" }}>{executeResults}</p>}

          <div className="content-tree">
            {tree!.tree.map((cat) => {
              const expanded = expandedCats.has(cat.name);
              const isUncategorized = cat.name === "Uncategorized";
              return (
                <div key={cat.name} className="content-tree-category">
                  <div className="content-tree-category-header" onClick={() => toggleCat(cat.name)}>
                    <span className="content-tree-toggle">{expanded ? "−" : "+"}</span>
                    <span className="content-tree-icon">{isUncategorized ? "❓" : "📁"}</span>
                    {editingCat === cat.name ? (
                      <input
                        type="text"
                        value={editCatValue}
                        autoFocus
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => setEditCatValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") submitRenameCat();
                          if (e.key === "Escape") setEditingCat(null);
                        }}
                        style={{ flex: 1, padding: "2px 6px" }}
                      />
                    ) : (
                      <span className="content-tree-name" onDoubleClick={(e) => { e.stopPropagation(); startRenameCat(cat.name); }}>
                        {cat.name}
                      </span>
                    )}
                    <span className="content-tree-count">{cat.count} {cat.count === 1 ? "file" : "files"}</span>
                    {!isUncategorized && tree!.approved_structure && (
                      <button
                        className="cat-edit-btn"
                        onClick={(e) => { e.stopPropagation(); deleteCat(cat.name); }}
                        title="Delete category"
                      >🗑</button>
                    )}
                    {!isUncategorized && !tree!.approved_structure && (
                      <button
                        className="cat-edit-btn"
                        onClick={(e) => { e.stopPropagation(); startRenameCat(cat.name); }}
                        title="Rename"
                      >✏</button>
                    )}
                  </div>
                  {expanded && (
                    <div className="content-tree-children">
                      {cat.children.map((child, idx) => {
                        if (child.name && child.files) {
                          const subKey = `${cat.name}::${child.name}`;
                          const subExpanded = expandedSubs.has(subKey);
                          return (
                            <div key={idx} className="content-tree-subcategory">
                              <div className="content-tree-subcategory-header" onClick={() => toggleSub(subKey)}>
                                <span className="content-tree-toggle">{subExpanded ? "−" : "+"}</span>
                                <span className="content-tree-icon">📂</span>
                                <span className="content-tree-name">{child.name}</span>
                                <span className="content-tree-count">{child.count} {child.count === 1 ? "file" : "files"}</span>
                              </div>
                              {subExpanded && (
                                <div className="content-tree-files">
                                  {child.files.map((f) => (
                                    <div key={f.file_id} className="content-tree-file">
                                      {tree!.approved_structure && (
                                        <input
                                          type="checkbox"
                                          checked={selectedFileIds.has(f.file_id)}
                                          onChange={() => toggleFileSelection(f.file_id)}
                                        />
                                      )}
                                      <span className="content-tree-file-icon">📄</span>
                                      <span className="content-tree-file-name">{f.filename}</span>
                                      <span className="content-tree-file-size">{formatSize(f.size_bytes)}</span>
                                      {f.path && (
                                        <span className="content-tree-file-path">📍 {shortPath(f.path)}</span>
                                      )}
                                      {f.proposed_path && (
                                        <span className="content-tree-file-proposed">→ {f.proposed_path}</span>
                                      )}
                                      {f.rationale && (
                                        <span className="content-tree-file-rationale">— {f.rationale}</span>
                                      )}
                                      {f.confidence > 0 && (
                                        <span className={`confidence ${confidenceClass(f.confidence)}`}>
                                          {Math.round(f.confidence * 100)}%
                                        </span>
                                      )}
                                      {tree!.approved_structure && (
                                        <button
                                          className="file-move-btn"
                                          onClick={() => { setMovingFileId(f.file_id); setMoveTargetCat(""); setMoveTargetSub(""); }}
                                        >↗</button>
                                      )}
                                      {movingFileId === f.file_id && (
                                        <div className="move-file-popup">
                                          <select value={moveTargetCat} onChange={(e) => setMoveTargetCat(e.target.value)}>
                                            <option value="">Select category…</option>
                                            {allCategoryNames.map((n) => <option key={n} value={n}>{n}</option>)}
                                          </select>
                                          <input
                                            type="text"
                                            placeholder="Subcategory (optional)"
                                            value={moveTargetSub}
                                            onChange={(e) => setMoveTargetSub(e.target.value)}
                                          />
                                          <button onClick={submitMoveFile} disabled={!moveTargetCat}>✓</button>
                                          <button onClick={() => setMovingFileId(null)}>✕</button>
                                        </div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        } else {
                          const f = child as unknown as TreeFile;
                          return (
                            <div key={idx} className="content-tree-file">
                              {tree!.approved_structure && (
                                <input
                                  type="checkbox"
                                  checked={selectedFileIds.has(f.file_id)}
                                  onChange={() => toggleFileSelection(f.file_id)}
                                />
                              )}
                              <span className="content-tree-file-icon">📄</span>
                              <span className="content-tree-file-name">{f.filename}</span>
                              <span className="content-tree-file-size">{formatSize(f.size_bytes)}</span>
                              {f.path && (
                                <span className="content-tree-file-path">📍 {shortPath(f.path)}</span>
                              )}
                              {f.proposed_path && (
                                <span className="content-tree-file-proposed">→ {f.proposed_path}</span>
                              )}
                              {f.rationale && (
                                <span className="content-tree-file-rationale">— {f.rationale}</span>
                              )}
                              {f.confidence > 0 && (
                                <span className={`confidence ${confidenceClass(f.confidence)}`}>
                                  {Math.round(f.confidence * 100)}%
                                </span>
                              )}
                              {tree!.approved_structure && (
                                <button
                                  className="file-move-btn"
                                  onClick={() => { setMovingFileId(f.file_id); setMoveTargetCat(""); setMoveTargetSub(""); }}
                                >↗</button>
                              )}
                              {movingFileId === f.file_id && (
                                <div className="move-file-popup">
                                  <select value={moveTargetCat} onChange={(e) => setMoveTargetCat(e.target.value)}>
                                    <option value="">Select category…</option>
                                    {allCategoryNames.map((n) => <option key={n} value={n}>{n}</option>)}
                                  </select>
                                  <input
                                    type="text"
                                    placeholder="Subcategory (optional)"
                                    value={moveTargetSub}
                                    onChange={(e) => setMoveTargetSub(e.target.value)}
                                  />
                                  <button onClick={submitMoveFile} disabled={!moveTargetCat}>✓</button>
                                  <button onClick={() => setMovingFileId(null)}>✕</button>
                                </div>
                              )}
                            </div>
                          );
                        }
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {results.length === 0 && scanned && !scanning && !error && !categorizing && !hasTree && (
        <p style={{ color: "#888", marginTop: "16px" }}>I found nothing to organize.</p>
      )}
    </div>
  );
}