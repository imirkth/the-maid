// The Maid — tree explorer: folders on the left, the open folder's contents on
// the right (like a file manager). Rename in place, drag files or folders onto
// a folder to move them, and switch off folders you don't want.
import { useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent, type ReactElement } from "react";
import { invoke } from "@tauri-apps/api/core";
import Icon, { fileKind } from "./Icon";
import { recordFeedback, type TreeFeedback } from "../lib/feedback";
import {
  allFiles, buildFolderTree, fullPath, joinPath, findNode, formatSize, isInside, matchingIds, mergesWith, nodeId,
  pathToNode, planMoveFiles, planMoveFolder, planRemove, planRename, plural, validateName, walk,
  type FolderNode, type TreeCall, type TreeCategory, type TreeFile,
} from "../lib/tree";

interface Props {
  tree: TreeCategory[];
  approved: boolean;                      // structure approved: files can be picked for moving on disk
  excluded: Set<string>;                  // folder ids switched off before approval
  onToggleExcluded: (id: string) => void;
  selectedFiles: Set<string>;
  onSelectFiles: (ids: Set<string>) => void;
  onTreeChange: (tree: TreeCategory[]) => void;
  onError: (message: string) => void;
}

const FILES_MIME = "application/x-maid-files";
const FOLDER_MIME = "application/x-maid-folder";

function confidenceLabel(c: number): { cls: string; text: string } {
  if (c >= 0.75) return { cls: "high", text: "Confident" };
  if (c >= 0.5) return { cls: "medium", text: "Fairly sure" };
  if (c > 0) return { cls: "low", text: "Unsure" };
  return { cls: "none", text: "" };
}

function shortPath(fullPath: string): string {
  const parts = fullPath.split(/[\\/]/).filter(Boolean);
  if (parts.length <= 1) return fullPath;
  const dirs = parts.slice(0, -1);
  return dirs.length <= 2 ? dirs.join("/") : "…/" + dirs.slice(-2).join("/");
}

function folderLabel(n: FolderNode): string {
  return n.sub ? `${n.category} / ${n.sub.split("/").join(" / ")}` : n.category;
}

// --- Inline rename field -------------------------------------------------

function RenameField({ initial, siblings, onCommit, onCancel, large = false }: {
  initial: string; siblings: string[]; large?: boolean;
  onCommit: (name: string) => void; onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const ref = useRef<HTMLInputElement>(null);
  const done = useRef(false);
  useEffect(() => { ref.current?.focus(); ref.current?.select(); }, []);
  const problem = validateName(value);
  const merge = value.trim() !== initial ? mergesWith(value, siblings.filter((s) => s !== initial)) : undefined;

  const commit = () => {
    if (done.current) return;
    if (problem || value.trim() === initial) { done.current = true; onCancel(); return; }
    done.current = true;
    onCommit(value.trim());
  };

  return (
    <span className={`rename-field${large ? " large" : ""}`} onClick={(e) => e.stopPropagation()}>
      <input ref={ref} type="text" value={value} aria-label="Folder name" aria-invalid={!!problem}
        onChange={(e) => setValue(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Enter") commit();
          if (e.key === "Escape") { done.current = true; onCancel(); }
        }} />
      {(problem || merge) && (
        <span className={`rename-hint${problem ? " bad" : ""}`} role="status">
          {problem || `Joins the existing “${merge}” folder`}
        </span>
      )}
    </span>
  );
}

// --- Explorer --------------------------------------------------------------

export default function TreeExplorer({
  tree, approved, excluded, onToggleExcluded, selectedFiles, onSelectFiles, onTreeChange, onError,
}: Props) {
  const nodes = useMemo(() => buildFolderTree(tree), [tree]);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(nodes.slice(0, 3).map((n) => n.id)));
  const [currentId, setCurrentId] = useState<string>(() => nodes[0]?.id ?? "");
  // Where a rename is happening: in the tree row, or in the big title on the right
  const [renaming, setRenaming] = useState<{ id: string; where: "tree" | "pane" } | null>(null);
  const renamingId = renaming?.id ?? null;
  const startRename = (id: string, where: "tree" | "pane" = "tree") => setRenaming({ id, where });
  const stopRename = () => setRenaming(null);
  const [query, setQuery] = useState("");
  const [dropId, setDropId] = useState<string | null>(null);
  const [movingFile, setMovingFile] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const treeRef = useRef<HTMLDivElement>(null);

  const current = findNode(nodes, currentId) ?? nodes[0];
  const matches = useMemo(() => matchingIds(nodes, query), [nodes, query]);
  const topNames = nodes.map((n) => n.category);
  const allFolders = useMemo(() => { const out: FolderNode[] = []; walk(nodes, (n) => out.push(n)); return out; }, [nodes]);

  const isExcluded = (n: FolderNode): boolean =>
    pathToNode(nodes, n.id).some((a) => excluded.has(a.id));

  // Visible rows in order, for keyboard navigation
  const visibleRows = useMemo(() => {
    const out: FolderNode[] = [];
    const add = (list: FolderNode[]) => list.forEach((n) => {
      if (matches && !matches.has(n.id)) return;
      out.push(n);
      if (matches || expanded.has(n.id)) add(n.children);
    });
    add(nodes);
    return out;
  }, [nodes, expanded, matches]);

  const open = (id: string) => {
    setCurrentId(id);
    // Make sure the opened folder is visible in the tree
    setExpanded((prev) => {
      const next = new Set(prev);
      pathToNode(nodes, id).slice(0, -1).forEach((a) => next.add(a.id));
      return next;
    });
  };

  const toggle = (id: string) => setExpanded((prev) => {
    const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next;
  });

  // Every edit goes through here, so a future "learn from my edits" call has one home.
  const run = async (calls: TreeCall[], after?: (t: TreeCategory[]) => void, feedback: TreeFeedback[] = []) => {
    if (calls.length === 0) return;
    setBusy(true);
    try {
      let latest: TreeCategory[] | null = null;
      for (const c of calls) {
        const res = await invoke<{ tree: TreeCategory[] }>(c.cmd, c.args);
        if (res?.tree) latest = res.tree;
      }
      if (latest) { onTreeChange(latest); after?.(latest); }
      void recordFeedback(feedback);
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const siblingsOf = (n: FolderNode): string[] => {
    if (!n.sub) return topNames;
    const parent = pathToNode(nodes, n.id).slice(-2, -1)[0];
    return parent ? parent.children.map((c) => c.name) : [];
  };

  const rename = (n: FolderNode, name: string) => {
    stopRename();
    const merging = !n.sub && topNames.find((t) => t !== n.category && t.toLowerCase() === name.toLowerCase());
    const newId = n.sub
      ? nodeId(n.category, [...n.sub.split("/").slice(0, -1), name].join("/"))
      : nodeId(merging || name);
    const wasOpen = current && isInside(current, n);
    const newPath = n.sub ? joinPath(n.category, n.sub.split("/").slice(0, -1).join("/"), name) : (merging || name);
    run(planRename(n, name, topNames), () => {
      setExpanded((prev) => new Set([...prev, newId]));
      if (wasOpen) setCurrentId(newId);
    }, [{ action: "rename", path: fullPath(n), new_path: newPath }]);
  };

  const remove = (n: FolderNode) => {
    const where = n.sub ? "its parent folder" : "Uncategorized";
    if (!confirm(`Remove the folder “${n.name}”? Its ${plural(n.count, "file")} go to ${where}. Nothing on disk changes.`)) return;
    const parentId = pathToNode(nodes, n.id).slice(-2, -1)[0]?.id;
    run(planRemove(n), () => { if (current && isInside(current, n)) setCurrentId(parentId ?? ""); },
      [{ action: "unpin", path: fullPath(n) }]);
  };

  const moveFiles = (ids: string[], target: FolderNode) =>
    run(planMoveFiles(ids, target), undefined, [{ action: "pin", path: fullPath(target), file_ids: ids }]);

  const moveFolder = (n: FolderNode, target: FolderNode) => {
    const calls = planMoveFolder(n, target);
    if (calls.length === 0) return;
    const newSub = [target.sub, n.name].filter(Boolean).join("/");
    run(calls, () => open(nodeId(target.category, newSub)),
      [{ action: "rename", path: fullPath(n), new_path: joinPath(fullPath(target), n.name) }]);
  };

  // --- Drag and drop ---
  const dragFiles = (e: DragEvent, f: TreeFile) => {
    const ids = approved && selectedFiles.has(f.file_id) ? [...selectedFiles] : [f.file_id];
    e.dataTransfer.setData(FILES_MIME, JSON.stringify(ids));
    e.dataTransfer.effectAllowed = "move";
  };
  const dragFolder = (e: DragEvent, n: FolderNode) => {
    if (n.holding) { e.preventDefault(); return; }
    e.dataTransfer.setData(FOLDER_MIME, n.id);
    e.dataTransfer.effectAllowed = "move";
  };
  const dropProps = (target: FolderNode) => ({
    onDragOver: (e: DragEvent) => {
      const types = e.dataTransfer.types;
      if (!types.includes(FILES_MIME) && !types.includes(FOLDER_MIME)) return;
      e.preventDefault();
      if (dropId !== target.id) setDropId(target.id);
    },
    onDragLeave: () => setDropId((d) => (d === target.id ? null : d)),
    onDrop: (e: DragEvent) => {
      e.preventDefault(); e.stopPropagation();
      setDropId(null);
      const files = e.dataTransfer.getData(FILES_MIME);
      if (files) { moveFiles(JSON.parse(files), target); return; }
      const folder = findNode(nodes, e.dataTransfer.getData(FOLDER_MIME));
      if (folder && !isInside(target, folder)) moveFolder(folder, target);
    },
  });

  // --- Keyboard navigation on the folder tree ---
  const onTreeKey = (e: KeyboardEvent) => {
    if (renamingId || !current) return;
    const i = visibleRows.findIndex((r) => r.id === current.id);
    const go = (n?: FolderNode) => { if (n) { e.preventDefault(); setCurrentId(n.id); } };
    switch (e.key) {
      case "ArrowDown": go(visibleRows[i + 1]); break;
      case "ArrowUp": go(visibleRows[i - 1]); break;
      case "ArrowRight":
        if (current.children.length && !expanded.has(current.id)) { e.preventDefault(); toggle(current.id); }
        else go(current.children[0]);
        break;
      case "ArrowLeft":
        if (expanded.has(current.id) && current.children.length) { e.preventDefault(); toggle(current.id); }
        else go(pathToNode(nodes, current.id).slice(-2, -1)[0]);
        break;
      case "F2": case "Enter":
        if (!current.holding) { e.preventDefault(); startRename(current.id); }
        break;
    }
  };

  useEffect(() => {
    const rows = treeRef.current?.querySelectorAll<HTMLElement>("[data-id]") ?? [];
    Array.from(rows).find((r) => r.dataset.id === currentId)?.scrollIntoView?.({ block: "nearest" });
  }, [currentId]);

  // --- Rendering ---
  const renderRow = (n: FolderNode): ReactElement | null => {
    if (matches && !matches.has(n.id)) return null;
    const isOpen = matches ? true : expanded.has(n.id);
    const off = isExcluded(n);
    const selected = current?.id === n.id;
    return (
      <div key={n.id} role="none">
        <div role="treeitem" data-id={n.id} aria-selected={selected} aria-expanded={n.children.length ? isOpen : undefined}
          className={`tree-row${selected ? " selected" : ""}${off ? " off" : ""}${dropId === n.id ? " drop" : ""}${n.holding ? " holding" : ""}`}
          style={{ paddingLeft: 8 + n.depth * 18 }}
          draggable={!n.holding && renamingId !== n.id}
          onDragStart={(e) => dragFolder(e, n)}
          onClick={() => setCurrentId(n.id)}
          onDoubleClick={() => { if (!n.holding) startRename(n.id); }}
          {...dropProps(n)}>
          <button type="button" className={`tree-chevron${n.children.length ? "" : " empty"}`} tabIndex={-1}
            aria-label={isOpen ? "Collapse" : "Expand"}
            onClick={(e) => { e.stopPropagation(); if (n.children.length) toggle(n.id); }}>
            {n.children.length > 0 && <Icon name={isOpen ? "chevronDown" : "chevronRight"} size={16} />}
          </button>
          <Icon name={n.holding ? "inbox" : isOpen && n.children.length ? "folderOpen" : "folder"} size={16}
            className={`tree-folder-icon depth-${Math.min(n.depth, 3)}`} />
          {renaming?.id === n.id && renaming.where === "tree" ? (
            <RenameField initial={n.name} siblings={siblingsOf(n)}
              onCommit={(name) => rename(n, name)} onCancel={() => stopRename()} />
          ) : (
            <span className="tree-name" title={n.holding ? "Files here stay where they are" : "Double-click to rename"}>{n.name}</span>
          )}
          <span className="tree-count">{n.count.toLocaleString()}</span>
          {!n.holding && renamingId !== n.id && (
            <span className="tree-row-actions">
              <button type="button" className="icon-btn" title="Rename (F2)" aria-label={`Rename ${n.name}`}
                onClick={(e) => { e.stopPropagation(); startRename(n.id); }}><Icon name="pencil" size={16} /></button>
              {!approved && (
                <button type="button" className="icon-btn" aria-label={excluded.has(n.id) ? `Use ${n.name}` : `Don't use ${n.name}`}
                  title={excluded.has(n.id) ? "Use this folder again" : "Don't use this folder (its files stay where they are)"}
                  onClick={(e) => { e.stopPropagation(); onToggleExcluded(n.id); }}>
                  <Icon name={excluded.has(n.id) ? "eye" : "eyeOff"} size={16} />
                </button>
              )}
            </span>
          )}
        </div>
        {isOpen && n.children.length > 0 && <div role="group">{n.children.map(renderRow)}</div>}
      </div>
    );
  };

  const renderFile = (f: TreeFile) => {
    const { icon, kind } = fileKind(f.filename);
    const conf = confidenceLabel(f.confidence);
    const checked = selectedFiles.has(f.file_id);
    return (
      <div key={f.file_id} className={`file-row${checked ? " checked" : ""}`} draggable onDragStart={(e) => dragFiles(e, f)}
        title={f.rationale || undefined}>
        {approved && (
          <input type="checkbox" className="file-check" checked={checked} aria-label={`Select ${f.filename}`}
            onChange={() => { const s = new Set(selectedFiles); checked ? s.delete(f.file_id) : s.add(f.file_id); onSelectFiles(s); }} />
        )}
        <span className={`file-icon kind-${kind}`}><Icon name={icon} size={16} /></span>
        <span className="file-main">
          <span className="file-title">{f.filename}</span>
          {f.path && <span className="file-from">from {shortPath(f.path)}</span>}
        </span>
        {conf.text && <span className={`conf-pill ${conf.cls}`} title={`${Math.round(f.confidence * 100)}% sure`}>{conf.text}</span>}
        <span className="file-size">{formatSize(f.size_bytes)}</span>
        {movingFile === f.file_id ? (
          <select autoFocus className="move-select" defaultValue="" aria-label="Move to folder"
            onBlur={() => setMovingFile(null)}
            onChange={(e) => {
              const target = findNode(nodes, e.target.value);
              setMovingFile(null);
              if (target) moveFiles([f.file_id], target);
            }}>
            <option value="" disabled>Move to…</option>
            {allFolders.filter((n) => n.id !== current?.id).map((n) => <option key={n.id} value={n.id}>{folderLabel(n)}</option>)}
          </select>
        ) : (
          <button type="button" className="icon-btn file-move" title="Move to another folder" aria-label={`Move ${f.filename}`}
            onClick={() => setMovingFile(f.file_id)}><Icon name="move" size={16} /></button>
        )}
      </div>
    );
  };

  if (nodes.length === 0) {
    return <div className="explorer-empty">The tree is empty.</div>;
  }

  const crumbs = current ? pathToNode(nodes, current.id) : [];
  const currentAll = current ? allFiles(current).map((f) => f.file_id) : [];
  const allChecked = currentAll.length > 0 && currentAll.every((id) => selectedFiles.has(id));
  const currentOff = current ? isExcluded(current) : false;

  return (
    <div className={`explorer${busy ? " busy" : ""}`}>
      <aside className="explorer-side">
        <div className="explorer-toolbar">
          <label className="search-box">
            <Icon name="search" size={16} />
            <input type="text" placeholder="Find a folder or file" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search the tree" />
            {query && <button type="button" className="icon-btn" aria-label="Clear search" onClick={() => setQuery("")}><Icon name="x" size={12} /></button>}
          </label>
          <button type="button" className="icon-btn" title="Expand all" aria-label="Expand all"
            onClick={() => { const all = new Set<string>(); walk(nodes, (n) => { if (n.children.length) all.add(n.id); }); setExpanded(all); }}>
            <Icon name="expand" size={16} />
          </button>
          <button type="button" className="icon-btn" title="Collapse all" aria-label="Collapse all" onClick={() => setExpanded(new Set())}>
            <Icon name="collapse" size={16} />
          </button>
        </div>
        <div className="tree-list" role="tree" aria-label="Proposed folders" tabIndex={0} ref={treeRef} onKeyDown={onTreeKey}>
          {nodes.map(renderRow)}
          {matches && matches.size === 0 && <p className="muted tree-nomatch">Nothing matches “{query}”.</p>}
        </div>
        <p className="explorer-tip">
          <Icon name="info" size={16} /> Double-click a name to rename it. Drag files or folders onto a folder to move them.
        </p>
      </aside>

      {current && (
        <section className={`explorer-pane${currentOff ? " off" : ""}`} {...dropProps(current)}>
          <nav className="crumbs" aria-label="Folder path">
            {crumbs.map((c, i) => (
              <span key={c.id} className="crumb-wrap">
                {i > 0 && <Icon name="chevronRight" size={12} className="crumb-sep" />}
                <button type="button" className={`crumb${i === crumbs.length - 1 ? " here" : ""}${dropId === c.id ? " drop" : ""}`}
                  onClick={() => open(c.id)} {...dropProps(c)}>{c.name}</button>
              </span>
            ))}
          </nav>

          {/* The open folder, drawn as a manila folder holding its contents */}
          <div className={`folder-sheet${current.holding ? " holding" : ""}`}>
          <header className="folder-head">
            <div className="folder-tab">
              {current.holding && <Icon name="inbox" size={16} />}
              {renaming?.id === current.id && renaming.where === "pane" ? (
                <RenameField large initial={current.name} siblings={siblingsOf(current)}
                  onCommit={(name) => rename(current, name)} onCancel={() => stopRename()} />
              ) : (
                <h3 onDoubleClick={() => { if (!current.holding) startRename(current.id, "pane"); }}
                  title={current.holding ? undefined : "Double-click to rename"}>{current.name}</h3>
              )}
            </div>
            <div className="folder-front">
              <span className="pane-sub">
                {plural(current.count, "file")}
                {current.children.length > 0 && <> · {plural(current.children.length, "folder")}</>}
                {currentOff && <> · not used, files stay where they are</>}
              </span>
              {!current.holding && (
                <div className="pane-actions">
                  <button type="button" className="ghost" onClick={() => startRename(current.id, "pane")}><Icon name="pencil" size={16} /> Rename</button>
                  {!approved && (
                    <button type="button" className="ghost" onClick={() => onToggleExcluded(current.id)}>
                      <Icon name={excluded.has(current.id) ? "eye" : "eyeOff"} size={16} /> {excluded.has(current.id) ? "Use folder" : "Don’t use"}
                    </button>
                  )}
                  <button type="button" className="ghost danger" onClick={() => remove(current)} aria-label={`Remove ${current.name}`}>
                    <Icon name="trash" size={16} /> Remove
                  </button>
                </div>
              )}
            </div>
          </header>
          <div className="folder-body">

          {current.holding && (
            <p className="pane-why">These files didn’t have enough to go on. They stay where they are unless you drag them into a folder.</p>
          )}
          {!current.holding && current.rationale && (
            <p className="pane-why">{current.rationale}</p>
          )}

          {current.children.length > 0 && (
            <div className="tiles">
              {current.children.map((c) => (
                <button type="button" key={c.id} className={`tile${dropId === c.id ? " drop" : ""}${isExcluded(c) ? " off" : ""}`}
                  draggable onDragStart={(e) => dragFolder(e, c)}
                  onClick={() => open(c.id)} {...dropProps(c)}>
                  <span className="tile-name">{c.name}</span>
                  <span className="tile-count">{plural(c.count, "file")}</span>
                </button>
              ))}
            </div>
          )}

          {current.files.length > 0 && (
            <div className="file-list">
              <div className="file-list-head">
                <span>{current.children.length > 0 ? "Files in this folder" : "Files"}</span>
                {approved && currentAll.length > 0 && (
                  <button type="button" className="link-btn" onClick={() => {
                    const s = new Set(selectedFiles);
                    currentAll.forEach((id) => (allChecked ? s.delete(id) : s.add(id)));
                    onSelectFiles(s);
                  }}>{allChecked ? "Unselect all" : `Select all ${currentAll.length}`}</button>
                )}
              </div>
              {current.files.map(renderFile)}
            </div>
          )}

          {current.files.length === 0 && current.children.length === 0 && (
            <p className="muted">This folder is empty.</p>
          )}
          {approved && current.files.length === 0 && currentAll.length > 0 && (
            <button type="button" className="link-btn" onClick={() => {
              const s = new Set(selectedFiles);
              currentAll.forEach((id) => (allChecked ? s.delete(id) : s.add(id)));
              onSelectFiles(s);
            }}>{allChecked ? "Unselect all files below" : `Select all ${currentAll.length} files below`}</button>
          )}
          </div>
          </div>
        </section>
      )}
    </div>
  );
}
