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