import { useState, useEffect, type ReactNode } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import PreferenceCheck from "./PreferenceCheck";
import TreeExplorer from "./TreeExplorer";
import Icon from "./Icon";
import { allFiles, buildFolderTree, findNode, fullPath, plural, type TreeCategory } from "../lib/tree";
import { recordFeedback, type TreeFeedback } from "../lib/feedback";

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

// Before/after structure comparison returned by the tree architect
interface StructureStats {
  folders: number;
  max_depth: number;
  loose_files: number;
  single_file_folders: number;
  top_level?: number;
}

interface TreeSummary {
  files?: number;
  before?: StructureStats;
  after?: StructureStats;
  to_sort?: number;
  kept_folders?: number;
  llm_named?: boolean;
}

interface CategorizeResponse {
  categories: TreeCategory[];
  total_files: number;
  total_categorized: number;
  summary?: TreeSummary;
}

interface TreeState {
  tree: TreeCategory[];
  approved_structure: boolean;
  total_files: number;
  total_categorized: number;
  summary?: TreeSummary;
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

function folderName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() || path;
}

const STEPS = ["Scan a folder", "Shape your tree", "Move your files"];

function Stepper({ step }: { step: number }) {
  return (
    <ol className="stepper" aria-label="Progress">
      {STEPS.map((label, i) => (
        <li key={label} className={i < step ? "done" : i === step ? "current" : ""} aria-current={i === step ? "step" : undefined}>
          <span className="step-dot">{i < step ? <Icon name="check" size={12} /> : i + 1}</span>
          <span className="step-label">{label}</span>
        </li>
      ))}
    </ol>
  );
}

function ProgressCard({ title, value, stats }: { title: ReactNode; value: number; stats: (string | false)[] }) {
  return (
    <div className="card progress-card">
      <div className="progress-card-head">
        <span className="spinner" aria-hidden="true" />
        <span>{title}</span>
        <span className="progress-pct">{Math.round(value)}%</span>
      </div>
      <div className="progress-bar"><div className="progress-fill" style={{ width: `${value}%` }} /></div>
      <div className="scan-progress-stats">{stats.filter(Boolean).map((s) => <span key={s as string}>{s}</span>)}</div>
    </div>
  );
}

export default function ScanView() {
  const [directory, setDirectory] = useState("");
  const [scanning, setScanning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [scanCount, setScanCount] = useState(0);
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

  // Preference check: asked before the first build, re-openable any time
  const [showPrefCheck, setShowPrefCheck] = useState(false);
  const [prefsAnswered, setPrefsAnswered] = useState(false);

  // Persistent tree state
  const [tree, setTree] = useState<TreeState | null>(null);
  const [treeKey, setTreeKey] = useState(0); // remounts the explorer for a freshly built tree
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [selectedFileIds, setSelectedFileIds] = useState<Set<string>>(new Set());
  const [approving, setApproving] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [executeResults, setExecuteResults] = useState<string | null>(null);

  useEffect(() => {
    invoke<Settings>("get_settings")
      .then((s) => {
        setSettings(s);
        setCanScan(s.sandbox_folders.length > 0);
        if (s.sandbox_folders.length > 0) setDirectory((d) => d || s.sandbox_folders[0]);
      })
      .catch((e) => setError(String(e)));

    invoke<TreeState>("get_tree")
      .then((t) => { if (t?.tree && t.tree.length > 0) setTree(t); })
      .catch(() => {});

    const unlistenReady = listen<boolean>("backend_ready", (e) => setBackendReady(e.payload));
    invoke("ping_backend").then(() => setBackendReady(true)).catch(() => {});
    invoke<{ answered?: boolean }>("get_preferences")
      .then((p) => setPrefsAnswered(!!p?.answered))
      .catch(() => {});

    const unlistenProgress = listen<ScanProgress>("scan_progress", (e) => {
      const p = e.payload;
      setProgress(p.progress * 100);
      setScanCount(p.count);
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
    setProgress(0); setScanCount(0); setScanElapsed(0); setScanEta(0);
    setError(""); setResults([]); setScanned(false); setExecuteResults(null);
    try {
      const resp: ScanResponse = await invoke("scan_directory", { request: { directory, max_files: 10000 } });
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
      setTreeKey((k) => k + 1);
      setResults([]);
    } catch (err) { setError(String(err)); }
    finally { setCategorizing(false); }
  };

  const toggleExcluded = (id: string) => {
    const node = tree ? findNode(buildFolderTree(tree.tree), id) : undefined;
    const wasOff = excluded.has(id);
    setExcluded((prev) => { const n = new Set(prev); wasOff ? n.delete(id) : n.add(id); return n; });
    if (node) void recordFeedback([{ action: wasOff ? "include" : "exclude", file_ids: allFiles(node).map((f) => f.file_id) }]);
  };

  // Approve: files in folders switched off go to Uncategorized (they stay where they are)
  const approveStructure = async () => {
    if (!tree) return;
    setApproving(true); setError("");
    try {
      const nodes = buildFolderTree(tree.tree);
      const ids = new Set<string>();
      for (const id of excluded) {
        const node = findNode(nodes, id);
        if (node) allFiles(node).forEach((f) => ids.add(f.file_id));
      }
      let latest = tree.tree;
      if (ids.size > 0) {
        const res = await invoke<{ tree: TreeCategory[] }>("bulk_move_files", {
          fileIds: [...ids], targetCategory: "Uncategorized", targetSubcategory: "",
        });
        if (res?.tree) latest = res.tree;
      }
      await invoke("approve_tree_structure");
      // Approving accepts every folder that is in use: the builder keeps them next time
      const accepted: TreeFeedback[] = buildFolderTree(latest)
        .filter((n) => !n.holding)
        .map((n) => ({ action: "pin", path: fullPath(n) }));
      void recordFeedback(accepted);
      setTree((prev) => (prev ? { ...prev, tree: latest, approved_structure: true } : null));
      setExcluded(new Set());
      // Start with every file that will move already picked
      const movable = new Set<string>();
      for (const n of buildFolderTree(latest)) if (!n.holding) allFiles(n).forEach((f) => movable.add(f.file_id));
      setSelectedFileIds(movable);
    } catch (e) { setError(String(e)); }
    finally { setApproving(false); }
  };

  const handleExecuteMoves = async () => {
    if (selectedFileIds.size === 0) return;
    if (!confirm(`Move ${plural(selectedFileIds.size, "file")} into the new folders on disk? Nothing is overwritten: name clashes get a (2) suffix.`)) return;
    setExecuting(true); setError("");
    try {
      const result = await invoke<{ results: Array<{ file_id: string; status: string; detail?: string }> }>("execute_tree_moves", { approvedFileIds: Array.from(selectedFileIds) });
      const moved = result.results.filter((r) => r.status === "moved").length;
      const errors = result.results.filter((r) => r.status === "error");
      setExecuteResults(`Moved ${plural(moved, "file")}.${errors.length > 0 ? ` ${plural(errors.length, "file")} couldn’t be moved.` : ""}`);
      setSelectedFileIds(new Set());
    } catch (err) { setError(String(err)); }
    finally { setExecuting(false); }
  };

  const handleClearTree = async () => {
    if (!confirm("Throw away this proposed tree and start over? Your files on disk are not touched.")) return;
    setError("");
    try {
      await invoke("clear_tree");
      setTree(null);
      setExcluded(new Set());
      setSelectedFileIds(new Set());
      setExecuteResults(null);
    } catch (err) { setError(String(err)); }
  };

  const hasTree = !!tree && tree.tree.length > 0;
  const approved = !!tree?.approved_structure;
  const step = !hasTree ? 0 : approved ? 2 : 1;
  const scanDisabled = scanning || categorizing || !directory || !backendReady || !canScan;
  const busy = scanning || categorizing;
  const summary = tree?.summary;

  const folderPicker = settings && settings.sandbox_folders.length > 0 && (
    <label className="folder-picker">
      <Icon name="folder" size={16} />
      <select value={directory} onChange={(e) => setDirectory(e.target.value)} disabled={busy} aria-label="Folder to scan">
        {settings.sandbox_folders.map((f) => <option key={f} value={f}>{folderName(f)}</option>)}
      </select>
    </label>
  );
  const scanLabel = scanning ? "Scanning…" : !backendReady ? "Starting up…" : hasTree ? "Scan for new files" : "Scan folder";

  return (
    <div className="scan-view">
      <header className="page-head">
        <div>
          <h2>Organize</h2>
          <p className="page-sub">I look at your files, propose a tidy folder tree, and you shape it. Nothing moves on disk until you say so.</p>
        </div>
        {hasTree && (
          <div className="page-head-actions">
            {folderPicker}
            <button type="button" className="secondary" onClick={handleScan} disabled={scanDisabled}>
              <Icon name="refresh" size={14} /> {scanLabel}
            </button>
          </div>
        )}
      </header>

      <Stepper step={step} />

      {!canScan && settings && (
        <div className="notice warn"><Icon name="info" size={16} /> Pick at least one folder in the setup wizard or Settings before scanning.</div>
      )}
      {error && (
        <div className="notice error" role="alert">
          <Icon name="info" size={16} /> <span>{error}</span>
          <button type="button" className="icon-btn" aria-label="Dismiss" onClick={() => setError("")}><Icon name="x" size={12} /></button>
        </div>
      )}

      {/* Step 1: pick a folder and scan */}
      {!hasTree && !busy && results.length === 0 && (
        <div className="card hero-card">
          <span className="hero-icon"><Icon name="broom" size={28} /></span>
          <h3>Which folder should I tidy?</h3>
          <p className="muted">I read file names and contents on this computer only. You’ll see the proposed tree before anything changes.</p>
          <div className="hero-actions">
            {folderPicker}
            <button type="button" className="primary" onClick={handleScan} disabled={scanDisabled}>
              <Icon name="scan" size={16} /> {scanLabel}
            </button>
          </div>
          {scanned && !error && <p className="muted">Everything here is already in the tree. Nothing new to sort.</p>}
        </div>
      )}

      {scanning && (
        <ProgressCard title={<>Scanning <strong>{folderName(directory)}</strong></>} value={progress}
          stats={[
            `${scanCount.toLocaleString()} files found`,
            scanEta > 0 && `about ${formatDuration(scanEta)} left`,
            scanElapsed > 0 && `${formatDuration(scanElapsed)} so far`,
          ]} />
      )}

      {results.length > 0 && !categorizing && !showPrefCheck && (
        <div className="card found-card">
          <div>
            <h3>Found {plural(results.length, "new file")}</h3>
            <p className="muted">Next I’ll read them and design a folder tree that fits.{!prefsAnswered && " First, a few quick choices about how you like things arranged."}</p>
          </div>
          <div className="found-actions">
            {prefsAnswered && (
              <button type="button" className="ghost" onClick={() => setShowPrefCheck(true)}><Icon name="settings" size={14} /> My preferences</button>
            )}
            <button type="button" className="primary" onClick={() => (prefsAnswered ? handleCategorize() : setShowPrefCheck(true))}>
              <Icon name="sparkles" size={16} /> {prefsAnswered ? "Build my tree" : "Continue"}
            </button>
          </div>
        </div>
      )}

      {results.length > 0 && !categorizing && showPrefCheck && (
        <PreferenceCheck files={results} directory={directory}
          onCancel={() => setShowPrefCheck(false)}
          onDone={() => { setShowPrefCheck(false); setPrefsAnswered(true); handleCategorize(); }} />
      )}

      {categorizing && (
        <ProgressCard title={<>Reading {plural(results.length, "file")} and designing your tree</>} value={categorizeProgress}
          stats={[
            catFilesDone > 0 && `${catFilesDone.toLocaleString()} / ${catFilesTotal.toLocaleString()} files`,
            catTotalBatches > 1 && `batch ${catBatch} of ${catTotalBatches}`,
            catEta > 0 && `about ${formatDuration(catEta)} left`,
            catElapsed > 0 && `${formatDuration(catElapsed)} so far`,
          ]} />
      )}

      {/* Steps 2 and 3: the tree */}
      {hasTree && (
        <section className="tree-section">
          <div className="tree-bar">
            <div className="tree-bar-text">
              {approved ? (
                <>
                  <h3>Pick the files to move</h3>
                  <p className="muted">Your tree is approved. Choose files on the right, then move them. Files in Uncategorized and To Sort stay put.</p>
                </>
              ) : (
                <>
                  <h3>Here’s the tree I suggest</h3>
                  <p className="muted">Rename anything, drag files between folders, or switch off folders you don’t want. When it looks right, approve it.</p>
                </>
              )}
            </div>
            <div className="tree-bar-actions">
              {!approved && (
                <>
                  <button type="button" className="ghost" onClick={handleClearTree}>Start over</button>
                  <button type="button" className="primary" onClick={approveStructure} disabled={approving}>
                    <Icon name="check" size={16} /> {approving ? "Approving…" : "Approve this tree"}
                  </button>
                </>
              )}
            </div>
          </div>

          {summary?.after && (
            <div className="stats">
              <div className="stat"><span className="stat-num">{tree!.total_categorized.toLocaleString()}</span><span className="stat-label">files sorted</span></div>
              <div className="stat"><span className="stat-num">{summary.after.top_level ?? "–"}</span><span className="stat-label">main folders</span></div>
              <div className="stat">
                <span className="stat-num">{summary.after.folders}</span>
                <span className="stat-label">folders{summary.before ? ` (was ${summary.before.folders})` : ""}</span>
              </div>
              <div className="stat">
                <span className="stat-num">{summary.after.max_depth}</span>
                <span className="stat-label">levels deep{summary.before ? ` (was ${summary.before.max_depth})` : ""}</span>
              </div>
              {(summary.kept_folders ?? 0) > 0 && (
                <div className="stat"><span className="stat-num">{summary.kept_folders}</span><span className="stat-label">of your folders kept</span></div>
              )}
              {(summary.to_sort ?? 0) > 0 && (
                <div className="stat"><span className="stat-num">{summary.to_sort}</span><span className="stat-label">waiting in To Sort</span></div>
              )}
            </div>
          )}

          {executeResults && <div className="notice success"><Icon name="check" size={16} /> {executeResults}</div>}
          {!approved && excluded.size > 0 && (
            <div className="notice"><Icon name="eyeOff" size={16} /> {plural(excluded.size, "folder")} switched off. Their files will stay where they are.</div>
          )}

          <TreeExplorer key={treeKey} tree={tree!.tree} approved={approved}
            excluded={excluded} onToggleExcluded={toggleExcluded}
            selectedFiles={selectedFileIds} onSelectFiles={setSelectedFileIds}
            onTreeChange={(t) => setTree((prev) => (prev ? { ...prev, tree: t } : null))}
            onError={setError} />

          {approved && (
            <div className="action-bar">
              <span><strong>{plural(selectedFileIds.size, "file")}</strong> selected</span>
              {selectedFileIds.size > 0 && <button type="button" className="link-btn" onClick={() => setSelectedFileIds(new Set())}>Clear</button>}
              <span className="spacer" />
              <button type="button" className="ghost" onClick={handleClearTree}>Start over</button>
              <button type="button" className="primary" onClick={handleExecuteMoves} disabled={selectedFileIds.size === 0 || executing}>
                <Icon name="arrowRight" size={16} /> {executing ? "Moving…" : "Move files on disk"}
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
