import { useState, useEffect, useCallback } from "react";
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

// ponytail: collect all file_ids from a subcategory's files array
function subcategoryFileIds(cat: TreeCategory, subName: string): string[] {
  const child = cat.children.find(c => c.name === subName && c.files);
  return child?.files?.map(f => f.file_id) ?? [];
}

// ponytail: collect all file_ids in a category (subs + direct files)
function categoryFileIds(cat: TreeCategory): string[] {
  const ids: string[] = [];
  for (const child of cat.children) {
    if (child.files) {
      for (const f of child.files) ids.push(f.file_id);
    } else if (child.file_id) {
      ids.push(child.file_id);
    }
  }
  return ids;
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
  const [editingSub, setEditingSub] = useState<string | null>(null); // "cat::sub"
  const [editSubValue, setEditSubValue] = useState("");
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set());
  const [movingFileId, setMovingFileId] = useState<string | null>(null);
  const [moveTargetCat, setMoveTargetCat] = useState("");
  const [moveTargetSub, setMoveTargetSub] = useState("");
  const [executing, setExecuting] = useState(false);
  const [executeResults, setExecuteResults] = useState<string | null>(null);

  // Accept/refuse state — track per-category and per-subcategory
  const [acceptedCats, setAcceptedCats] = useState<Set<string>>(new Set());
  const [refusedCats, setRefusedCats] = useState<Set<string>>(new Set());
  const [acceptedSubs, setAcceptedSubs] = useState<Set<string>>(new Set()); // "cat::sub"
  const [refusedSubs, setRefusedSubs] = useState<Set<string>>(new Set()); // "cat::sub"

  // Bulk move bar
  const [bulkMoveCat, setBulkMoveCat] = useState("");
  const [bulkMoveSub, setBulkMoveSub] = useState("");

  // Merge dropdown
  const [mergingCat, setMergingCat] = useState<string | null>(null);

  const updateTree = useCallback((updated: { tree: TreeCategory[] }) => {
    setTree(prev => prev ? { ...prev, tree: updated.tree } : null);
  }, []);

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

    const unlistenReady = listen<boolean>("backend_ready", (e) => setBackendReady(e.payload));
    invoke("ping_backend").then(() => setBackendReady(true)).catch(() => {});

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
    setProgress(0); setScanCount(0); setScanMax(0); setScanElapsed(0); setScanEta(0);
    setError(""); setResults([]); setScanned(false);
    try {
      const resp: ScanResponse = await invoke("scan_directory", { request: { directory, max_files: 1000 } });
      setResults(resp.files);
      setScanned(true);
      if (resp.errors.length > 0) setError(resp.errors.join("; "));
    } catch (err) { setError(String(err)); }
    finally { setScanning(false); }
  };

  const handleCategorize = async () => {
    if (results.length === 0) return;
    setCategorizing(true); setCategorizeProgress(0); setCatFilesDone(0);
    setCatFilesTotal(results.length); setCatBatch(0); setCatTotalBatches(0);
    setCatElapsed(0); setCatEta(0); setError("");
    try {
      const resp: CategorizeResponse = await invoke("categorize_files", { files: results, directory });
      const merged = await invoke<TreeState>("merge_tree", {
        categories: resp.categories, totalFiles: resp.total_files, totalCategorized: resp.total_categorized,
      });
      setTree(merged);
      const initial = new Set<string>();
      (merged.tree || []).slice(0, 3).forEach((c) => initial.add(c.name));
      setExpandedCats(initial);
    } catch (err) { setError(String(err)); }
    finally { setCategorizing(false); }
  };

  const toggleCat = (name: string) => {
    setExpandedCats((prev) => { const n = new Set(prev); n.has(name) ? n.delete(name) : n.add(name); return n; });
  };
  const toggleSub = (key: string) => {
    setExpandedSubs((prev) => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });
  };

  // --- Category edit ---
  const startRenameCat = (name: string) => { setEditingCat(name); setEditCatValue(name); };
  const submitRenameCat = async () => {
    if (!editingCat || !editCatValue.trim()) return;
    try { const u = await invoke<{ tree: TreeCategory[] }>("edit_category", { oldName: editingCat, newName: editCatValue.trim(), delete: false }); updateTree(u); }
    catch (e) { setError(String(e)); }
    setEditingCat(null);
  };
  const deleteCat = async (name: string) => {
    if (!confirm(`Delete category "${name}"? Files will move to Uncategorized.`)) return;
    try { const u = await invoke<{ tree: TreeCategory[] }>("edit_category", { oldName: name, newName: null, delete: true }); updateTree(u); }
    catch (e) { setError(String(e)); }
  };

  // --- Subcategory edit ---
  const startRenameSub = (catName: string, subName: string) => {
    setEditingSub(`${catName}::${subName}`); setEditSubValue(subName);
  };
  const submitRenameSub = async (catName: string, oldSub: string) => {
    if (!editSubValue.trim()) return;
    try { const u = await invoke<{ tree: TreeCategory[] }>("edit_subcategory", { categoryName: catName, oldSubname: oldSub, newSubname: editSubValue.trim(), delete: false }); updateTree(u); }
    catch (e) { setError(String(e)); }
    setEditingSub(null);
  };
  const deleteSub = async (catName: string, subName: string) => {
    if (!confirm(`Delete subfolder "${subName}"? Files will move to parent category.`)) return;
    try { const u = await invoke<{ tree: TreeCategory[] }>("edit_subcategory", { categoryName: catName, oldSubname: subName, newSubname: null, delete: true }); updateTree(u); }
    catch (e) { setError(String(e)); }
  };

  // --- Merge categories ---
  const submitMerge = async (source: string, target: string) => {
    if (source === target) return;
    if (!confirm(`Merge "${source}" into "${target}"? All files will move to ${target}.`)) return;
    try { const u = await invoke<{ tree: TreeCategory[] }>("merge_categories", { sourceName: source, targetName: target }); updateTree(u); }
    catch (e) { setError(String(e)); }
    setMergingCat(null);
  };

  // --- Accept / Refuse ---
  const acceptCat = (name: string) => {
    setAcceptedCats(prev => { const n = new Set(prev); n.add(name); return n; });
    setRefusedCats(prev => { const n = new Set(prev); n.delete(name); return n; });
  };
  const refuseCat = (name: string) => {
    setRefusedCats(prev => { const n = new Set(prev); n.add(name); return n; });
    setAcceptedCats(prev => { const n = new Set(prev); n.delete(name); return n; });
  };
  const acceptSub = (key: string) => {
    setAcceptedSubs(prev => { const n = new Set(prev); n.add(key); return n; });
    setRefusedSubs(prev => { const n = new Set(prev); n.delete(key); return n; });
  };
  const refuseSub = (key: string) => {
    setRefusedSubs(prev => { const n = new Set(prev); n.add(key); return n; });
    setAcceptedSubs(prev => { const n = new Set(prev); n.delete(key); return n; });
  };

  // All categories must have a decision before approving
  const allCatsDecided = hasTree ? tree!.tree.every(c =>
    c.name === "Uncategorized" || acceptedCats.has(c.name) || refusedCats.has(c.name)
  ) : false;

  // --- Approve structure (move refused to Uncategorized first) ---
  const approveStructure = async () => {
    // Move files from refused subcategories to Uncategorized
    for (const subKey of refusedSubs) {
      const [catName, subName] = subKey.split("::");
      const cat = tree?.tree.find(c => c.name === catName);
      if (!cat) continue;
      const ids = subcategoryFileIds(cat, subName);
      if (ids.length > 0) {
        try { await invoke("bulk_move_files", { fileIds: ids, targetCategory: "Uncategorized", targetSubcategory: "" }); }
        catch (e) { setError(String(e)); }
      }
    }
    // Move files from refused categories to Uncategorized
    for (const catName of refusedCats) {
      const cat = tree?.tree.find(c => c.name === catName);
      if (!cat) continue;
      const ids = categoryFileIds(cat);
      if (ids.length > 0) {
        try { await invoke("bulk_move_files", { fileIds: ids, targetCategory: "Uncategorized", targetSubcategory: "" }); }
        catch (e) { setError(String(e)); }
      }
    }
    try {
      await invoke("approve_tree_structure");
      setTree(prev => prev ? { ...prev, approved_structure: true } : null);
    } catch (e) { setError(String(e)); }
  };

  // --- File selection ---
  const toggleFileSelection = (fileId: string) => {
    setSelectedFileIds((prev) => { const n = new Set(prev); n.has(fileId) ? n.delete(fileId) : n.add(fileId); return n; });
  };
  const selectAllInSub = (cat: TreeCategory, subName: string) => {
    const ids = subcategoryFileIds(cat, subName);
    const allSelected = ids.every(id => selectedFileIds.has(id));
    setSelectedFileIds(prev => {
      const n = new Set(prev);
      if (allSelected) { ids.forEach(id => n.delete(id)); }
      else { ids.forEach(id => n.add(id)); }
      return n;
    });
  };

  // --- Single file move ---
  const submitMoveFile = async () => {
    if (!movingFileId || !moveTargetCat) return;
    try { const u = await invoke<{ tree: TreeCategory[] }>("move_file_in_tree", { fileId: movingFileId, targetCategory: moveTargetCat, targetSubcategory: moveTargetSub }); updateTree(u); }
    catch (e) { setError(String(e)); }
    setMovingFileId(null); setMoveTargetCat(""); setMoveTargetSub("");
  };

  // --- Bulk move ---
  const submitBulkMove = async () => {
    if (selectedFileIds.size === 0 || !bulkMoveCat) return;
    try {
      const u = await invoke<{ tree: TreeCategory[] }>("bulk_move_files", {
        fileIds: Array.from(selectedFileIds), targetCategory: bulkMoveCat, targetSubcategory: bulkMoveSub,
      });
      updateTree(u);
      setSelectedFileIds(new Set());
      setBulkMoveCat(""); setBulkMoveSub("");
    } catch (e) { setError(String(e)); }
  };

  // --- Execute moves on disk ---
  const handleExecuteMoves = async () => {
    if (selectedFileIds.size === 0) return;
    if (!confirm(`Move ${selectedFileIds.size} files on disk? This is irreversible (uses trash for conflicts).`)) return;
    setExecuting(true); setError("");
    try {
      const result = await invoke<{ results: Array<{ file_id: string; status: string; detail?: string }> }>("execute_tree_moves", { approvedFileIds: Array.from(selectedFileIds) });
      const moved = result.results.filter((r) => r.status === "moved").length;
      const errors = result.results.filter((r) => r.status === "error");
      setExecuteResults(`Moved ${moved} files. ${errors.length > 0 ? `${errors.length} errors.` : ""}`);
      setSelectedFileIds(new Set());
    } catch (err) { setError(String(err)); }
    finally { setExecuting(false); }
  };

  const scanDisabled = scanning || !directory || !backendReady || !canScan;
  const hasTree = tree && tree.tree && tree.tree.length > 0;
  const allCategoryNames = hasTree ? tree!.tree.map(c => c.name).filter(n => n !== "Uncategorized") : [];

  // --- Render helpers ---
  const catStateClass = (name: string): string => {
    if (name === "Uncategorized") return "";
    if (acceptedCats.has(name)) return " tree-accepted";
    if (refusedCats.has(name)) return " tree-refused";
    return " tree-pending";
  };
  const subStateClass = (key: string): string => {
    if (acceptedSubs.has(key)) return " tree-accepted";
    if (refusedSubs.has(key)) return " tree-refused";
    return " tree-pending";
  };

  // File row render — shared between subcategory files and direct children
  const renderFile = (f: TreeFile, catName: string) => {
    const isDirect = !movingFileId || movingFileId === f.file_id;
    return (
      <div key={f.file_id} className="content-tree-file">
        {tree!.approved_structure && (
          <input type="checkbox" checked={selectedFileIds.has(f.file_id)} onChange={() => toggleFileSelection(f.file_id)} />
        )}
        <span className="content-tree-file-icon">📄</span>
        <span className="content-tree-file-name">{f.filename}</span>
        <span className="content-tree-file-size">{formatSize(f.size_bytes)}</span>
        {f.path && <span className="content-tree-file-path">📍 {shortPath(f.path)}</span>}
        {f.proposed_path && <span className="content-tree-file-proposed">→ {f.proposed_path}</span>}
        {f.confidence > 0 && (
          <span className={`confidence ${confidenceClass(f.confidence)}`}>{Math.round(f.confidence * 100)}%</span>
        )}
        {tree!.approved_structure && (
          <button className="file-move-btn" onClick={() => { setMovingFileId(f.file_id); setMoveTargetCat(catName); setMoveTargetSub(""); }}>↗</button>
        )}
        {movingFileId === f.file_id && (
          <div className="move-file-popup">
            <select value={moveTargetCat} onChange={(e) => setMoveTargetCat(e.target.value)}>
              <option value="">Select category…</option>
              {allCategoryNames.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
            <input type="text" placeholder="Sub (optional)" value={moveTargetSub} onChange={(e) => setMoveTargetSub(e.target.value)} />
            <button onClick={submitMoveFile} disabled={!moveTargetCat}>✓</button>
            <button onClick={() => setMovingFileId(null)}>✕</button>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="scan-view">
      <h2>📁 Scan Directory</h2>

      {!canScan && <p className="warning">⚠️ Complete the setup wizard and select at least one folder before scanning.</p>}

      <div className="scan-input">
        {settings && settings.sandbox_folders.length > 0 && (
          <select value={directory} onChange={(e) => setDirectory(e.target.value)} disabled={scanning}>
            <option value="">Select a folder to scan…</option>
            {settings.sandbox_folders.map((f) => <option key={f} value={f}>{f.split('/').pop() || f}</option>)}
          </select>
        )}
        <button onClick={handleScan} disabled={scanDisabled}>
          {scanning ? "Scanning…" : !backendReady ? "Waiting for backend…" : !canScan ? "No folders selected" : "Scan"}
        </button>
      </div>

      {scanning && (
        <div className="scan-progress-panel">
          <div className="progress-bar"><div className="progress-fill" style={{ width: `${progress}%` }} /><span className="progress-text">{Math.round(progress)}%</span></div>
          <div className="scan-progress-stats">
            <span>📄 {scanCount.toLocaleString()} files scanned</span>
            {scanEta > 0 && <span>⏱ ~{formatDuration(scanEta)} remaining</span>}
            {scanElapsed > 0 && <span>🕐 {formatDuration(scanElapsed)} elapsed</span>}
          </div>
        </div>
      )}

      {error && <div className="error">⚠️ {error}</div>}

      {results.length > 0 && !categorizing && (
        <div className="scan-results">
          <p className="scan-summary">Found <strong>{results.length}</strong> new files to categorize</p>
          <button className="primary" onClick={handleCategorize} style={{ marginTop: "12px" }}>🧠 Categorize with AI</button>
        </div>
      )}

      {categorizing && (
        <div className="scan-progress-panel">
          <p className="scan-summary">Analyzing content of <strong>{results.length.toLocaleString()}</strong> files…</p>
          <div className="progress-bar"><div className="progress-fill" style={{ width: `${categorizeProgress}%` }} /><span className="progress-text">{Math.round(categorizeProgress)}%</span></div>
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
              <>
                <button className="primary" onClick={approveStructure} disabled={!allCatsDecided} style={{ marginLeft: "12px" }} title={allCatsDecided ? "" : "Accept or refuse all categories first"}>
                  ✓ Approve Tree Structure
                </button>
                {!allCatsDecided && <span className="muted" style={{ marginLeft: 8 }}>Review all categories first</span>}
              </>
            ) : (
              <div className="approval-actions">
                <span className="file-selection-info">{selectedFileIds.size} files selected</span>
                <button className="primary" onClick={handleExecuteMoves} disabled={selectedFileIds.size === 0 || executing} style={{ marginLeft: "12px" }}>
                  {executing ? "Moving…" : "📦 Move Files on Disk"}
                </button>
              </div>
            )}
          </div>

          {executeResults && <p className="scan-summary" style={{ color: "#4ade80" }}>{executeResults}</p>}

          {/* Bulk move bar — visible when files are selected after approval */}
          {tree!.approved_structure && selectedFileIds.size > 0 && (
            <div className="bulk-move-bar">
              <span>Move {selectedFileIds.size} files to:</span>
              <select value={bulkMoveCat} onChange={(e) => setBulkMoveCat(e.target.value)}>
                <option value="">Select category…</option>
                {allCategoryNames.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              <input type="text" placeholder="Sub (optional)" value={bulkMoveSub} onChange={(e) => setBulkMoveSub(e.target.value)} />
              <button onClick={submitBulkMove} disabled={!bulkMoveCat}>Move</button>
              <button onClick={() => setSelectedFileIds(new Set())}>Clear</button>
            </div>
          )}

          <div className="content-tree">
            {tree!.tree.map((cat) => {
              const expanded = expandedCats.has(cat.name);
              const isUncategorized = cat.name === "Uncategorized";
              const isAccepted = acceptedCats.has(cat.name);
              const isRefused = refusedCats.has(cat.name);
              return (
                <div key={cat.name} className={`content-tree-category${catStateClass(cat.name)}`}>
                  <div className="content-tree-category-header" onClick={() => toggleCat(cat.name)}>
                    <span className="content-tree-toggle">{expanded ? "−" : "+"}</span>
                    <span className="content-tree-icon">{isUncategorized ? "❓" : "📁"}</span>
                    {editingCat === cat.name ? (
                      <input type="text" value={editCatValue} autoFocus onClick={(e) => e.stopPropagation()}
                        onChange={(e) => setEditCatValue(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") submitRenameCat(); if (e.key === "Escape") setEditingCat(null); }}
                        style={{ flex: 1, padding: "2px 6px" }} />
                    ) : (
                      <span className="content-tree-name" onDoubleClick={(e) => { e.stopPropagation(); if (!isUncategorized) startRenameCat(cat.name); }}>
                        {cat.name}
                      </span>
                    )}
                    <span className="content-tree-count">{cat.count} {cat.count === 1 ? "file" : "files"}</span>

                    {/* Accept / Refuse buttons — pre-approval */}
                    {!isUncategorized && !tree!.approved_structure && (
                      <>
                        <button className={`cat-accept-btn${isAccepted ? " active" : ""}`} onClick={(e) => { e.stopPropagation(); acceptCat(cat.name); }} title="Accept">✓</button>
                        <button className={`cat-refuse-btn${isRefused ? " active" : ""}`} onClick={(e) => { e.stopPropagation(); refuseCat(cat.name); }} title="Refuse">✕</button>
                      </>
                    )}

                    {/* Edit buttons */}
                    {!isUncategorized && tree!.approved_structure && (
                      <button className="cat-edit-btn" onClick={(e) => { e.stopPropagation(); deleteCat(cat.name); }} title="Delete category">🗑</button>
                    )}
                    {!isUncategorized && !tree!.approved_structure && (
                      <>
                        <button className="cat-edit-btn" onClick={(e) => { e.stopPropagation(); startRenameCat(cat.name); }} title="Rename">✏</button>
                        <button className="cat-edit-btn" onClick={(e) => { e.stopPropagation(); setMergingCat(mergingCat === cat.name ? null : cat.name); }} title="Merge into…">🔀</button>
                        <button className="cat-edit-btn" onClick={(e) => { e.stopPropagation(); deleteCat(cat.name); }} title="Delete">🗑</button>
                      </>
                    )}

                    {/* Merge dropdown */}
                    {mergingCat === cat.name && (
                      <div className="merge-popup" onClick={(e) => e.stopPropagation()}>
                        <span>Merge into:</span>
                        <select defaultValue="" onChange={(e) => { if (e.target.value) submitMerge(cat.name, e.target.value); }}>
                          <option value="" disabled>Choose target…</option>
                          {allCategoryNames.filter(n => n !== cat.name).map((n) => <option key={n} value={n}>{n}</option>)}
                        </select>
                        <button onClick={() => setMergingCat(null)}>✕</button>
                      </div>
                    )}
                  </div>

                  {expanded && (
                    <div className="content-tree-children">
                      {cat.children.map((child, idx) => {
                        if (child.name && child.files) {
                          const subKey = `${cat.name}::${child.name}`;
                          const subExpanded = expandedSubs.has(subKey);
                          const subAccepted = acceptedSubs.has(subKey);
                          const subRefused = refusedSubs.has(subKey);
                          const subIds = child.files.map(f => f.file_id);
                          const allSubSelected = subIds.length > 0 && subIds.every(id => selectedFileIds.has(id));
                          return (
                            <div key={idx} className={`content-tree-subcategory${subStateClass(subKey)}`}>
                              <div className="content-tree-subcategory-header" onClick={() => toggleSub(subKey)}>
                                <span className="content-tree-toggle">{subExpanded ? "−" : "+"}</span>
                                <span className="content-tree-icon">📂</span>
                                {editingSub === subKey ? (
                                  <input type="text" value={editSubValue} autoFocus onClick={(e) => e.stopPropagation()}
                                    onChange={(e) => setEditSubValue(e.target.value)}
                                    onKeyDown={(e) => { if (e.key === "Enter") submitRenameSub(cat.name, child.name!); if (e.key === "Escape") setEditingSub(null); }}
                                    style={{ flex: 1, padding: "2px 6px" }} />
                                ) : (
                                  <span className="content-tree-name" onDoubleClick={(e) => { e.stopPropagation(); startRenameSub(cat.name, child.name!); }}>
                                    {child.name}
                                  </span>
                                )}
                                <span className="content-tree-count">{child.count} {child.count === 1 ? "file" : "files"}</span>

                                {/* Select-all checkbox — after approval */}
                                {tree!.approved_structure && (
                                  <input type="checkbox" checked={allSubSelected} onClick={(e) => e.stopPropagation()} onChange={() => selectAllInSub(cat, child.name!)} title="Select all" />
                                )}

                                {/* Accept / Refuse — pre-approval */}
                                {!tree!.approved_structure && (
                                  <>
                                    <button className={`cat-accept-btn${subAccepted ? " active" : ""}`} onClick={(e) => { e.stopPropagation(); acceptSub(subKey); }} title="Accept">✓</button>
                                    <button className={`cat-refuse-btn${subRefused ? " active" : ""}`} onClick={(e) => { e.stopPropagation(); refuseSub(subKey); }} title="Refuse">✕</button>
                                  </>
                                )}

                                {/* Edit buttons */}
                                {!tree!.approved_structure && (
                                  <>
                                    <button className="cat-edit-btn" onClick={(e) => { e.stopPropagation(); startRenameSub(cat.name, child.name!); }} title="Rename">✏</button>
                                    <button className="cat-edit-btn" onClick={(e) => { e.stopPropagation(); deleteSub(cat.name, child.name!); }} title="Delete">🗑</button>
                                  </>
                                )}
                              </div>
                              {subExpanded && (
                                <div className="content-tree-files">
                                  {child.files.map((f) => renderFile(f, cat.name))}
                                </div>
                              )}
                            </div>
                          );
                        } else {
                          // Direct file child
                          const f = child as unknown as TreeFile;
                          return <div key={idx}>{renderFile(f, cat.name)}</div>;
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