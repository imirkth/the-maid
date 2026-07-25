// The Maid — Approval Logic (ADR 0005)
// Pure functions for grouping, approve/reject, filtering. Testable without React.

import type { CleanupItem, ProposedAction, GroupedPlan } from "../types/cleanup-plan";

// Group items by proposed_action for batch approval UI
export function groupByAction(items: CleanupItem[]): GroupedPlan {
  return items.reduce((groups, item) => {
    const action = item.proposed_action;
    if (!groups[action]) groups[action] = [];
    groups[action].push(item);
    return groups;
  }, {} as GroupedPlan);
}

// Toggle a single item's approval in a Set
export function toggleApproval(approved: Set<string>, fileId: string): Set<string> {
  const next = new Set(approved);
  if (next.has(fileId)) next.delete(fileId);
  else next.add(fileId);
  return next;
}

// Approve all items in a group
export function approveGroup(approved: Set<string>, items: CleanupItem[]): Set<string> {
  const next = new Set(approved);
  for (const item of items) next.add(item.file_id);
  return next;
}

// Reject all items in a group
export function rejectGroup(approved: Set<string>, items: CleanupItem[]): Set<string> {
  const next = new Set(approved);
  for (const item of items) next.delete(item.file_id);
  return next;
}

// Approve all items
export function approveAll(items: CleanupItem[]): Set<string> {
  return new Set(items.map((i) => i.file_id));
}

// Reject all items
export function rejectAll(): Set<string> {
  return new Set();
}

// Get approved items only
export function getApprovedItems(items: CleanupItem[], approved: Set<string>): CleanupItem[] {
  return items.filter((i) => approved.has(i.file_id));
}

// Apply user_edited_path override — returns effective destination path
export function effectivePath(item: CleanupItem): string {
  return item.user_edited_path ?? item.proposed_path;
}

// Confidence label
export function confidenceLabel(confidence: number): string {
  if (confidence >= 0.8) return "High";
  if (confidence >= 0.5) return "Medium";
  if (confidence > 0) return "Low";
  return "—";
}

// Action icons for UI
export const ACTION_ICONS: Record<ProposedAction, string> = {
  move: "📦",
  copy: "📄",
  tag: "🏷️",
  delete: "🗑️",
  rename: "✏️",
};

export const ACTION_LABELS: Record<ProposedAction, string> = {
  move: "Move",
  copy: "Copy",
  tag: "Tag",
  delete: "Delete",
  rename: "Rename",
};

// --- ADR 0005: Advanced approval (granular per-field toggles) ---

// Per-field approval state for advanced mode
export interface FieldApprovals {
  move: boolean;
  tags: boolean;
  faces: boolean;
}

// Per-item field approvals: file_id → {move, tags, faces}
export type ItemFieldApprovals = Record<string, FieldApprovals>;

// Default field approvals: all true (user approves everything by default)
export function defaultFieldApprovals(items: CleanupItem[]): ItemFieldApprovals {
  const result: ItemFieldApprovals = {};
  for (const item of items) {
    result[item.file_id] = { move: true, tags: true, faces: true };
  }
  return result;
}

// Toggle a single field (move/tags/faces) for an item
export function toggleField(
  state: ItemFieldApprovals,
  fileId: string,
  field: keyof FieldApprovals,
): ItemFieldApprovals {
  const current = state[fileId] ?? { move: true, tags: true, faces: true };
  return {
    ...state,
    [fileId]: { ...current, [field]: !current[field] },
  };
}

// Apply field approvals to produce final CleanupItems.
// If move is unchecked → change action to 'tag', keep current_path, AND clear
// user_edited_path so effectivePath() cannot resurrect a destination the user
// explicitly disabled.
export function applyFieldApprovals(
  item: CleanupItem,
  fields: FieldApprovals | undefined,
): CleanupItem {
  if (!fields) return item;
  const moveApproved = fields.move;
  return {
    ...item,
    proposed_tags: fields.tags ? item.proposed_tags : [],
    faces_detected: fields.faces ? item.faces_detected : [],
    proposed_action: moveApproved ? item.proposed_action : "tag",
    proposed_path: moveApproved ? item.proposed_path : item.current_path,
    // Clear the inline edit override when move is rejected; otherwise a stale
    // user_edited_path would win via effectivePath() and the file would still move.
    user_edited_path: moveApproved ? item.user_edited_path : undefined,
  };
}

// Build the final list of proposals to execute, honoring simple/advanced mode.
// In simple mode field approvals are ignored (all dimensions approved), matching
// the all-or-nothing UI contract. In advanced mode stored per-field toggles apply.
export function buildFinalProposals(
  items: CleanupItem[],
  approved: Set<string>,
  fieldApprovals: ItemFieldApprovals,
  advancedMode: boolean,
): CleanupItem[] {
  return getApprovedItems(items, approved).map((item) => {
    const fields = advancedMode ? fieldApprovals[item.file_id] : { move: true, tags: true, faces: true };
    return applyFieldApprovals(item, fields);
  });
}

// --- Bucket selector (reassign file to different bucket) ---

export interface BucketOption {
  id: string;
  name: string;
  path: string;
}

// Reassign a file to a different bucket — updates proposed_path and promotes
// tag/delete to move so the reassignment is actually executed.
export function reassignBucket(
  item: CleanupItem,
  bucket: BucketOption,
): CleanupItem {
  const base = bucket.path.replace(/\\/g, "/").replace(/\/$/, "");
  const filename = item.original_filename;
  const newPath = `${base}/${filename}`;
  const needsPromotion = item.proposed_action === "tag" || item.proposed_action === "delete";
  return {
    ...item,
    proposed_action: needsPromotion ? "move" : item.proposed_action,
    proposed_path: newPath,
    user_edited_path: newPath,
    rationale: `Reassigned to ${bucket.name}: ${item.rationale}`,
  };
}

// --- Sandbox validation for edited paths ---

// System directories that are always rejected
const SYSTEM_DIRS = [
  "/bin", "/sbin", "/usr", "/etc", "/var", "/opt", "/lib", "/lib64",
  "/boot", "/dev", "/proc", "/sys", "/run", "/srv", "/root",
  "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
  "C:\\ProgramData",
];

function isSystemDir(normalized: string): boolean {
  const n = normalized.replace(/\\/g, "/");
  for (const sysDir of SYSTEM_DIRS) {
    const sys = sysDir.replace(/\\/g, "/");
    if (n === sys || n.startsWith(`${sys}/`)) {
      return true;
    }
  }
  return false;
}

function resolveAgainstHome(path: string, home: string | undefined): string {
  if (!home) return path.replace(/\\/g, "/");
  let p = path.replace(/\\/g, "/");
  if (p.startsWith("~/")) {
    p = `${home}/${p.slice(2)}`;
  } else if (p === "~") {
    p = home;
  }
  // Collapse trivial .. and . to match backend resolve() semantics as closely
  // as a browser-side validator can. We do not follow symlinks here.
  const parts = p.split("/").filter((part) => part !== ".");
  const stack: string[] = [];
  for (const part of parts) {
    if (part === "..") {
      stack.pop();
    } else {
      stack.push(part);
    }
  }
  return stack.join("/") || "/";
}

// Validate an edited path against sandbox folders.
// `home` is optional; when provided relative sandbox names are resolved against it,
// matching the backend's Path.home() / folder containment.
export function validateEditedPath(
  path: string,
  sandboxFolders: string[],
  home?: string,
): { valid: boolean; error?: string } {
  if (!path || path.trim().length === 0) {
    return { valid: false, error: "Path cannot be empty" };
  }
  const normalized = resolveAgainstHome(path.trim(), home);

  if (isSystemDir(normalized)) {
    return { valid: false, error: `System directories are out of scope: '${path}'` };
  }

  // If no sandbox folders, just reject system paths
  if (sandboxFolders.length === 0) {
    return { valid: true };
  }

  // Sandbox containment: support both absolute paths and relative folder names.
  // Absolute folders require proper prefix containment. Relative folder names are
  // resolved against home when home is known; otherwise they require the path to
  // start with that folder name (no escape via .. or unrelated prefix).
  for (const folder of sandboxFolders) {
    const f = folder.replace(/\\/g, "/").replace(/\/$/, "");
    if (f.startsWith("/") || /^[A-Za-z]:/.test(f)) {
      // Absolute sandbox folder: require normalized path to be folder or inside it
      if (normalized === f || normalized.startsWith(`${f}/`)) {
        return { valid: true };
      }
    } else {
      // Relative folder name: resolve against home if available
      if (home) {
        const resolved = `${home}/${f}`;
        if (normalized === resolved || normalized.startsWith(`${resolved}/`)) {
          return { valid: true };
        }
      } else {
        // Best-effort: path must begin with this folder component
        if (normalized === f || normalized.startsWith(`${f}/`)) {
          return { valid: true };
        }
      }
    }
  }
  return { valid: false, error: `Path '${path}' is outside the sandbox. Allowed: ${sandboxFolders.join(", ")}` };
}
