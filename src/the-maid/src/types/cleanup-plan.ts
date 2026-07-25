// The Maid — Cleanup Plan TypeScript types (mirrors backend cleanup_plan.py, ADR 0009)

export type ProposedAction = "move" | "copy" | "tag" | "delete" | "rename";

export interface CleanupItem {
  file_id: string;           // 8-char hex hash
  original_filename: string;
  current_path: string;     // absolute path at scan time
  proposed_action: ProposedAction;
  proposed_path: string;     // absolute destination
  proposed_tags: string[];   // IPTC/XMP tags
  faces_detected: string[];  // face cluster IDs, [] if none
  rationale: string;
  confidence: number;        // 0.0-1.0
  user_edited_path?: string; // ADR 0005: inline edit override
}

export interface CleanupPlan {
  schema_version: string;   // "1.0.0"
  scan_timestamp: string;    // ISO 8601
  items: CleanupItem[];
}

// Grouped view for batch approval UI
export type GroupedPlan = Record<ProposedAction, CleanupItem[]>;