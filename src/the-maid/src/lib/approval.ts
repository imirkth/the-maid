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

// Apply field approvals to produce final CleanupItems
// If move is unchecked → drop proposed_path (tag-only)
// If tags is unchecked → clear proposed_tags
// If faces is unchecked → clear faces_detected
export function applyFieldApprovals(
  item: CleanupItem,
  fields: FieldApprovals | undefined,
): CleanupItem {
  if (!fields) return item;
  return {
    ...item,
    proposed_tags: fields.tags ? item.proposed_tags : [],
    faces_detected: fields.faces ? item.faces_detected : [],
    // ponytail: if move unchecked, change action to 'tag' and keep current path
    proposed_action: fields.move ? item.proposed_action : "tag",
    proposed_path: fields.move ? item.proposed_path : item.current_path,
  };
}

// --- Bucket selector (reassign file to different bucket) ---

export interface BucketOption {
  id: string;
  name: string;
  path: string;
}

// Reassign a file to a different bucket — updates proposed_path
export function reassignBucket(
  item: CleanupItem,
  bucket: BucketOption,
): CleanupItem {
  const filename = item.original_filename;
  return {
    ...item,
    proposed_path: `${bucket.path}/${filename}`,
    user_edited_path: `${bucket.path}/${filename}`,
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

// Validate an edited path against sandbox folders
export function validateEditedPath(
  path: string,
  sandboxFolders: string[],
): { valid: boolean; error?: string } {
  if (!path || path.trim().length === 0) {
    return { valid: false, error: "Path cannot be empty" };
  }
  const normalized = path.replace(/\\/g, "/");
  for (const sysDir of SYSTEM_DIRS) {
    if (normalized.startsWith(sysDir.replace(/\\/g, "/"))) {
      return { valid: false, error: `System directories are out of scope: '${path}'` };
    }
  }
  // If no sandbox folders, just reject system paths
  if (sandboxFolders.length === 0) {
    return { valid: true };
  }
  // Check containment — path must be absolute or within a sandbox folder
  // ponytail: accept both absolute paths and relative-to-home paths
  const home = (typeof window !== "undefined" ? "" : ""); // frontend doesn't know HOME, so just check suffix
  for (const folder of sandboxFolders) {
    // Accept paths that end with /folder or contain /folder/
    if (normalized.includes(`/${folder}/`) || normalized.endsWith(`/${folder}`) || normalized === folder) {
      return { valid: true };
    }
  }
  // If path looks absolute and doesn't match any sandbox folder, reject
  if (normalized.startsWith("/") || normalized.match(/^[A-Z]:\\\\/i)) {
    return { valid: false, error: `Path '${path}' is outside the sandbox. Allowed: ${sandboxFolders.join(", ")}` };
  }
  // Relative path — assume ok (frontend can't fully validate)
  return { valid: true };
}