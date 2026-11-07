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

const STEPS = ["Find your files", "Shape your tree", "Move your files"];

interface Batch { directory: string; files: FileMeta[] }

function listNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

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
  const [batches, setBatches] = useState<Batch[]>([]); // new files, per scanned folder
  const [phaseLabel, setPhaseLabel] = useState("");   // which folder is being looked at
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

  const results = batches.flatMap((b) => b.files);
  const folders = settings?.sandbox_folders ?? [];

  // Build the tree folder by folder, so each folder is tidied in place
  const buildTree = async (todo: Batch[]) => {
    const work = todo.filter((b) => b.files.length > 0);
    if (work.length === 0) return;
    const total = work.reduce((n, b) => n + b.files.length, 0);
    setCategorizing(true); setCategorizeProgress(0); setCatFilesDone(0);
    setCatFilesTotal(total); setCatBatch(0); setCatTotalBatches(0);
    setCatElapsed(0); setCatEta(0); setError("");
    try {
      let merged: TreeState | null = null;
      for (const [i, b] of work.entries()) {
        setPhaseLabel(work.length > 1 ? `${folderName(b.directory)} (${i + 1} of ${work.length})` : folderName(b.directory));
        const resp: CategorizeResponse = await invoke("categorize_files", { files: b.files, directory: b.directory });
        merged = await invoke<TreeState>("merge_tree", {
          categories: resp.categories, totalFiles: resp.total_files, totalCategorized: resp.total_categorized,
        });
      }
      if (merged) { setTree(merged); setTreeKey((k) => k + 1); }
      setBatches([]);
    } catch (err) { setError(String(err)); }
    finally { setCategorizing(false); setPhaseLabel(""); }
  };

  // The one button: look through the chosen folders, then build the tree straight away
  const tidy = async (targets: string[]) => {
    if (targets.length === 0 || !canScan) return;
    setScanning(true); setError(""); setBatches([]); setScanned(false); setExecuteResults(null);
    const found: Batch[] = [];
    const errors: string[] = [];
    try {
      for (const [i, dir] of targets.entries()) {
        setDirectory(dir);
        setPhaseLabel(targets.length > 1 ? `${folderName(dir)} (${i + 1} of ${targets.length})` : folderName(dir));
        setProgress(0); setScanCount(0); setScanElapsed(0); setScanEta(0);
        try {
          const resp: ScanResponse = await invoke("scan_directory", { request: { directory: dir, max_files: 10000 } });
          found.push({ directory: dir, files: resp.files });
          errors.push(...resp.errors);
        } catch (err) { errors.push(`${folderName(dir)}: ${String(err)}`); }
      }
    } finally { setScanning(false); setPhaseLabel(""); }
    setScanned(true);
    if (errors.length > 0) setError(errors.join("; "));
    setBatches(found);
    if (found.some((b) => b.files.length > 0)) {
      if (prefsAnswered) await buildTree(found);
      else setShowPrefCheck(true); // asked once, before the very first tree
    }
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

  const names = folders.map(folderName);
  const tidyLabel = scanning ? "Looking…" : categorizing ? "Sorting…" : !backendReady ? "Starting up…" : "Tidy my computer";
  // Advanced: tidy just one of the folders
  const oneFolder = folders.length > 1 && (
    <details className="one-folder">
      <summary>Only tidy one folder</summary>
      <div className="one-folder-row">
        <label className="folder-picker">
          <Icon name="folder" size={16} />
          <select value={directory} onChange={(e) => setDirectory(e.target.value)} disabled={busy} aria-label="Folder to tidy">
            {folders.map((f) => <option key={f} value={f}>{folderName(f)}</option>)}
          </select>
        </label>
        <button type="button" className="secondary" onClick={() => tidy([directory])} disabled={scanDisabled}>Tidy this folder</button>
      </div>
    </details>
  );

  return (
    <div className="scan-view">
      <header className="page-head">
        <div>
          <h2>Organize</h2>
          <p className="page-sub">I look at your files, propose a tidy folder tree, and you shape it. Nothing moves on disk until you say so.</p>
        </div>
        {hasTree && (
          <div className="page-head-actions">
            <button type="button" className="secondary" onClick={() => tidy(folders)} disabled={scanDisabled}
              title={`Look for new files in ${listNames(names)}`}>
              <Icon name="refresh" size={14} /> {busy ? tidyLabel : "Check for new files"}
            </button>
          </div>
        )}
      </header>

      <Stepper step={step} />

      {!canScan && settings && (
        <div className="notice warn"><Icon name="info" size={16} /> Pick at least one folder in the setup wizard or Settings before tidying.</div>
      )}
      {error && (
        <div className="notice error" role="alert">
          <Icon name="info" size={16} /> <span>{error}</span>
          <button type="button" className="icon-btn" aria-label="Dismiss" onClick={() => setError("")}><Icon name="x" size={12} /></button>
        </div>
      )}

      {/* Step 1: one button */}
      {!hasTree && !busy && !showPrefCheck && results.length === 0 && (
        <div className="card hero-card">
          {names.length > 0 && (
            <div className="hero-folders" aria-hidden="true">
              {names.map((n, i) => (
                <div key={n} className="hero-folder" style={{ zIndex: names.length - i }}>
                  <span className="hero-folder-tab">{n}</span>
                </div>
              ))}
            </div>
          )}
          <h3>{names.length > 0 ? `Sort ${listNames(names)} into one tidy tree` : "Sort your files into one tidy tree"}</h3>
          <p className="muted">I read your files on this computer, suggest where each one belongs, and wait for your approval before anything moves</p>
          <button type="button" className="primary hero-button" onClick={() => tidy(folders)} disabled={scanDisabled}>
            {tidyLabel}
          </button>
          {scanned && !error && <p className="muted hero-note">Everything is already in its place. Nothing new to sort.</p>}
          {oneFolder && <div className="hero-links">{oneFolder}</div>}
        </div>
      )}

      {scanning && (
        <ProgressCard title={<>Looking through <strong>{phaseLabel || folderName(directory)}</strong></>} value={progress}
          stats={[
            `${scanCount.toLocaleString()} files found`,
            scanEta > 0 && `about ${formatDuration(scanEta)} left`,
            scanElapsed > 0 && `${formatDuration(scanElapsed)} so far`,
          ]} />
      )}

      {/* Only shown if building was cancelled or failed: lets you pick it up again */}
      {results.length > 0 && !busy && !showPrefCheck && (
        <div className="card found-card">
          <div>
            <h3>Found {plural(results.length, "new file")}</h3>
            <p className="muted">Ready to sort into your tree</p>
          </div>
          <div className="found-actions">
            <button type="button" className="ghost" onClick={() => setShowPrefCheck(true)}>My preferences</button>
            <button type="button" className="primary" onClick={() => (prefsAnswered ? buildTree(batches) : setShowPrefCheck(true))}>
              Sort them
            </button>
          </div>
        </div>
      )}

      {results.length > 0 && !categorizing && showPrefCheck && (
        <PreferenceCheck files={results}
          directory={[...batches].sort((a, b) => b.files.length - a.files.length)[0]?.directory ?? directory}
          onCancel={() => setShowPrefCheck(false)}
          onDone={() => { setShowPrefCheck(false); setPrefsAnswered(true); buildTree(batches); }} />
      )}

      {categorizing && (
        <ProgressCard title={<>Sorting {plural(results.length, "file")}{phaseLabel && <> in <strong>{phaseLabel}</strong></>}</>} value={categorizeProgress}
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

          {summary?.after && (() => {
            const before = summary.before;
            const after = summary.after!;
            const fig = (n: number, label: string, was?: number) => (
              <span className="fig">
                <span className="fig-num">{n.toLocaleString()}</span>
                <span className="fig-label">{label}</span>
                {was !== undefined && <span className="fig-was">was {was.toLocaleString()}</span>}
              </span>
            );
            const notes = [
              `${plural(tree!.total_categorized, "file")} sorted`,
              (summary.kept_folders ?? 0) > 0 && `${summary.kept_folders} of your own folders kept`,
              (summary.to_sort ?? 0) > 0 && `${summary.to_sort} waiting in To Sort`,
            ].filter(Boolean);
            return (
              <div className="compare">
                <div className="compare-figs">
                  {fig(after.top_level ?? 0, "main folders")}
                  {fig(after.folders, "folders in all", before?.folders)}
                  {fig(after.max_depth, "levels deep", before?.max_depth)}
                  {before && before.loose_files > 0 && fig(after.loose_files, "loose files", before.loose_files)}
                </div>
                <p className="compare-note">{notes.join(" · ")}</p>
              </div>
            );
          })()}

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
