// The Maid — tells the tree builder about the user's edits so the next
// rebuild keeps them ("learn from my edits"). Best effort: an edit never
// fails because feedback could not be recorded (e.g. an older backend).
import { invoke } from "@tauri-apps/api/core";

export interface TreeFeedback {
  action: "pin" | "unpin" | "rename" | "exclude" | "include" | "reset";
  path?: string;       // "Category/sub/path"
  new_path?: string;
  file_ids?: string[];
}

export async function recordFeedback(items: TreeFeedback[]): Promise<void> {
  for (const feedback of items) {
    try { await invoke("record_tree_feedback", { feedback }); }
    catch { /* not available or rejected: the edit itself already succeeded */ }
  }
}
