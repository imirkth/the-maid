// The Maid — tree model for the explorer.
// The backend stores the tree as categories whose children are either
// subfolders ({ name: "A/B/C", files: [...] }) or direct files. The explorer
// works on one nested node per folder; this file converts between the two and
// plans the edits (rename, move, remove) as calls to the existing /tree/* API.

export interface TreeFile {
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

export interface TreeChild {
  name?: string;
  count?: number;
  rationale?: string;
  files?: TreeFile[];
  file_id?: string;
  filename?: string;
  path?: string;
  proposed_path?: string;
  size_bytes?: number;
  confidence?: number;
  tags?: string[];
  approved?: boolean;
}

export interface TreeCategory {
  name: string;
  count: number;
  rationale?: string;
  children: TreeChild[];
}

export interface FolderNode {
  id: string;          // "<category>::<sub path>", sub path is "" for a top folder
  category: string;
  sub: string;         // path inside the category, e.g. "Photos/2023"
  name: string;        // last part of the path
  depth: number;       // 0 for a top folder
  files: TreeFile[];   // files directly in this folder
  children: FolderNode[];
  count: number;       // files in this folder and below
  rationale?: string;
  holding: boolean;    // "Uncategorized" / "To Sort": files there stay put
}

// Folders whose files are left where they are (nothing to approve)
export function isHoldingCategory(name: string): boolean {
  return name === "Uncategorized" || name === "To Sort";
}

export const nodeId = (category: string, sub = ""): string => `${category}::${sub}`;

export function joinPath(...parts: string[]): string {
  return parts.flatMap((p) => p.split("/")).filter(Boolean).join("/");
}

/** "Category/sub/path", the form the tree builder's feedback uses. */
export function fullPath(n: { category: string; sub: string }): string {
  return joinPath(n.category, n.sub);
}

export function parentSub(sub: string): string {
  const parts = sub.split("/").filter(Boolean);
  return parts.slice(0, -1).join("/");
}

/** Convert the backend tree into one node per folder. Empty folders are hidden. */
export function buildFolderTree(categories: TreeCategory[]): FolderNode[] {
  const roots = categories.map((cat) => {
    const holding = isHoldingCategory(cat.name);
    const root: FolderNode = {
      id: nodeId(cat.name), category: cat.name, sub: "", name: cat.name, depth: 0,
      files: [], children: [], count: 0, rationale: cat.rationale, holding,
    };
    const index = new Map<string, FolderNode>([["", root]]);
    const ensure = (sub: string): FolderNode => {
      const found = index.get(sub);
      if (found) return found;
      const parent = ensure(parentSub(sub));
      const parts = sub.split("/");
      const node: FolderNode = {
        id: nodeId(cat.name, sub), category: cat.name, sub, name: parts[parts.length - 1],
        depth: parts.length, files: [], children: [], count: 0, holding,
      };
      parent.children.push(node);
      index.set(sub, node);
      return node;
    };
    for (const child of cat.children ?? []) {
      if (child.files) {
        const sub = joinPath(child.name ?? "");
        const node = ensure(sub);
        // Same name twice (e.g. after a rename onto an existing folder): merge them
        node.files = node.files.concat(child.files);
        node.rationale = node.rationale ?? child.rationale ?? child.files[0]?.rationale;
      } else if (child.file_id) {
        root.files.push(child as TreeFile);
      }
    }
    return root;
  });

  const finish = (node: FolderNode): FolderNode | null => {
    const kids = node.children.map(finish).filter((n): n is FolderNode => n !== null);
    kids.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
    const count = node.files.length + kids.reduce((s, k) => s + k.count, 0);
    if (count === 0) return null;
    return { ...node, children: kids, count };
  };
  const result = roots.map(finish).filter((n): n is FolderNode => n !== null);
  // Real folders first (as the builder ordered them), holding folders last
  return [...result.filter((n) => !n.holding), ...result.filter((n) => n.holding)];
}

export function walk(nodes: FolderNode[], fn: (n: FolderNode) => void): void {
  for (const n of nodes) { fn(n); walk(n.children, fn); }
}

export function findNode(nodes: FolderNode[], id: string): FolderNode | undefined {
  let hit: FolderNode | undefined;
  walk(nodes, (n) => { if (!hit && n.id === id) hit = n; });
  return hit;
}

/** Ids of a node and all its ancestors, top first. */
export function pathToNode(nodes: FolderNode[], id: string): FolderNode[] {
  for (const n of nodes) {
    if (n.id === id) return [n];
    const below = pathToNode(n.children, id);
    if (below.length) return [n, ...below];
  }
  return [];
}

export function allFiles(node: FolderNode): TreeFile[] {
  const out: TreeFile[] = [...node.files];
  for (const c of node.children) out.push(...allFiles(c));
  return out;
}

/** The sub paths stored in the backend at or under this folder (they hold files). */
export function storedSubPaths(node: FolderNode): string[] {
  const out: string[] = [];
  walk([node], (n) => { if (n.sub && n.files.length > 0) out.push(n.sub); });
  return out;
}

/** Problem with a proposed folder name, or "" when it is fine. */
export function validateName(name: string): string {
  const v = name.trim();
  if (!v) return "A folder needs a name.";
  if (v.includes("/") || v.includes("\\")) return "Use a name without / or \\.";
  if (v === "." || v === "..") return "That name isn’t allowed.";
  if (/[<>:"|?*]/.test(v)) return "Avoid these characters: < > : \" | ? *";
  return "";
}

/** Whether the new name matches a sibling, so the rename would merge two folders. */
export function mergesWith(name: string, siblings: string[]): string | undefined {
  const v = name.trim().toLowerCase();
  return siblings.find((s) => s.toLowerCase() === v);
}

export type TreeCall = { cmd: string; args: Record<string, unknown> };

/** API calls that rename a folder. A nested folder is renamed by renaming
 *  every stored sub path under it, so no backend change is needed. */
export function planRename(node: FolderNode, newName: string, topNames: string[]): TreeCall[] {
  const name = newName.trim();
  if (!node.sub) {
    const existing = topNames.find((t) => t !== node.category && t.toLowerCase() === name.toLowerCase());
    if (existing) return [{ cmd: "merge_categories", args: { sourceName: node.category, targetName: existing } }];
    return [{ cmd: "edit_category", args: { oldName: node.category, newName: name, delete: false } }];
  }
  const newSub = joinPath(parentSub(node.sub), name);
  return storedSubPaths(node).map((p) => ({
    cmd: "edit_subcategory",
    args: { categoryName: node.category, oldSubname: p, newSubname: newSub + p.slice(node.sub.length), delete: false },
  }));
}

/** API calls that move a whole folder inside another folder. */
export function planMoveFolder(node: FolderNode, target: FolderNode): TreeCall[] {
  if (target.id === node.id || isInside(target, node)) return [];
  const base = joinPath(target.sub, node.name);
  const calls: TreeCall[] = [];
  walk([node], (n) => {
    if (n.files.length === 0) return;
    const rel = n.sub.slice(node.sub.length);
    calls.push({
      cmd: "bulk_move_files",
      args: { fileIds: n.files.map((f) => f.file_id), targetCategory: target.category, targetSubcategory: joinPath(base, rel) },
    });
  });
  return calls;
}

/** API calls that remove a folder. Its files go up one level; a top folder's
 *  files go to Uncategorized (the backend's existing behaviour). */
export function planRemove(node: FolderNode): TreeCall[] {
  if (!node.sub) return [{ cmd: "edit_category", args: { oldName: node.category, newName: null, delete: true } }];
  const ids = allFiles(node).map((f) => f.file_id);
  return [{ cmd: "bulk_move_files", args: { fileIds: ids, targetCategory: node.category, targetSubcategory: parentSub(node.sub) } }];
}

export function planMoveFiles(fileIds: string[], target: FolderNode): TreeCall[] {
  if (fileIds.length === 0) return [];
  return [{ cmd: "bulk_move_files", args: { fileIds, targetCategory: target.category, targetSubcategory: target.sub } }];
}

/** True when `node` is `ancestor` or sits somewhere below it. */
export function isInside(node: FolderNode, ancestor: FolderNode): boolean {
  if (node.category !== ancestor.category) return false;
  if (!ancestor.sub) return true;
  return node.sub === ancestor.sub || node.sub.startsWith(ancestor.sub + "/");
}

/** Folders matching a search (by folder or file name), with their ancestors, for filtering. */
export function matchingIds(nodes: FolderNode[], query: string): Set<string> | null {
  const q = query.trim().toLowerCase();
  if (!q) return null;
  const keep = new Set<string>();
  const visit = (n: FolderNode, trail: FolderNode[]): void => {
    const hit = n.name.toLowerCase().includes(q) || n.files.some((f) => f.filename.toLowerCase().includes(q));
    if (hit) [...trail, n].forEach((t) => keep.add(t.id));
    n.children.forEach((c) => visit(c, [...trail, n]));
  };
  nodes.forEach((n) => visit(n, []));
  return keep;
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export function plural(n: number, word: string): string {
  return `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;
}
