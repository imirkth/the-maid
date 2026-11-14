// The Maid — split a big scan into batches the tree builder can handle.
// Files are grouped by folder (top folders first; a folder too big for one
// batch is split by its own sub-folders), then small groups are packed
// together. Every batch keeps the scanned folder as its root, so all batches
// add to ONE tree for the whole drive.

export const MAX_BATCH_FILES = 15000;

export interface PathFile { path: string }

export interface FileBatch<T extends PathFile> {
  label: string;   // the folders it covers, for the progress line
  files: T[];
}

function relParts(path: string, root: string): string[] {
  const norm = (p: string) => p.replace(/\\/g, "/").replace(/\/+$/, "");
  const r = norm(root);
  const p = norm(path);
  const rel = r && p.startsWith(r + "/") ? p.slice(r.length + 1) : p;
  return rel.split("/").filter(Boolean);
}

interface Group<T> { name: string; files: T[] }

function groupsAt<T extends PathFile>(files: T[], root: string, depth: number, prefix: string, max: number): Group<T>[] {
  const byDir = new Map<string, T[]>();
  const loose: T[] = [];
  for (const f of files) {
    const parts = relParts(f.path, root);
    if (parts.length - 1 > depth) {
      const key = parts[depth];
      const list = byDir.get(key);
      if (list) list.push(f); else byDir.set(key, [f]);
    } else {
      loose.push(f);
    }
  }
  const out: Group<T>[] = [];
  for (const [name, list] of byDir) {
    const label = prefix ? `${prefix}/${name}` : name;
    if (list.length > max) out.push(...groupsAt(list, root, depth + 1, label, max));
    else out.push({ name: label, files: list });
  }
  if (loose.length) {
    // files sitting directly in a folder: chunk them if there are very many
    for (let i = 0; i < loose.length; i += max) {
      out.push({ name: prefix || "loose files", files: loose.slice(i, i + max) });
    }
  }
  return out;
}

export function splitIntoBatches<T extends PathFile>(files: T[], root: string, max = MAX_BATCH_FILES): FileBatch<T>[] {
  if (files.length <= max) return files.length ? [{ label: "", files }] : [];
  const groups = groupsAt(files, root, 0, "", max).sort((a, b) => b.files.length - a.files.length);
  // First-fit decreasing: fewer, fuller batches
  const batches: { names: string[]; files: T[] }[] = [];
  for (const g of groups) {
    const slot = batches.find((b) => b.files.length + g.files.length <= max);
    if (slot) { slot.names.push(g.name); slot.files.push(...g.files); }
    else batches.push({ names: [g.name], files: [...g.files] });
  }
  return batches.map((b) => ({
    label: b.names.length > 3 ? `${b.names.slice(0, 3).join(", ")} and ${b.names.length - 3} more` : b.names.join(", "),
    files: b.files,
  }));
}
