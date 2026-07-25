// The Maid — Approval View (ADR 0005: Batch + Detail + Inline Editing)
// Slice 4B: Advanced Approval UI — granular toggles, bucket selector, sandbox validation
import { useState, useEffect, useCallback, useMemo } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { homeDir } from "@tauri-apps/api/path";
import type { CleanupItem, CleanupPlan, ProposedAction } from "../types/cleanup-plan";
import {
  groupByAction,
  toggleApproval,
  approveGroup,
  rejectGroup,
  approveAll,
  rejectAll,
  effectivePath,
  confidenceLabel,
  ACTION_ICONS,
  ACTION_LABELS,
  defaultFieldApprovals,
  toggleField,
  buildFinalProposals,
  reassignBucket,
  validateEditedPath,
  type ItemFieldApprovals,
  type BucketOption,
} from "../lib/approval";

interface Settings {
  sandbox_folders: string[];
  first_run: boolean;
  buckets: { id: string; name: string; path: string }[];
}

export default function ApprovalView() {
  const [plan, setPlan] = useState<CleanupPlan | null>(null);
  const [approved, setApproved] = useState<Set<string>>(new Set());
  const [advancedMode, setAdvancedMode] = useState(false);
  const [fieldApprovals, setFieldApprovals] = useState<ItemFieldApprovals>({});
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [editError, setEditError] = useState("");
  const [buckets, setBuckets] = useState<BucketOption[]>([]);
  const [sandboxFolders, setSandboxFolders] = useState<string[]>([]);
  const [home, setHome] = useState<string>("");
  const [executing, setExecuting] = useState(false);
  const [message, setMessage] = useState("");

  // Listen for cleanup plan from backend
  useEffect(() => {
    const unlisten = listen<CleanupPlan>("cleanup_plan_ready", (e) => {
      setPlan(e.payload);
      setApproved(new Set());
      setFieldApprovals(defaultFieldApprovals(e.payload.items));
      setMessage("");
    });
    return () => { unlisten.then((f) => f()); };
  }, []);

  // ponytail: try loading existing plan on mount (for dev without event)
  useEffect(() => {
    invoke<CleanupPlan>("get_cleanup_plan").catch(() => {});
    // Load settings for buckets + sandbox folders + home
    invoke<Settings>("get_settings")
      .then((s) => {
        setSandboxFolders(s.sandbox_folders);
        setBuckets(s.buckets.map((b) => ({ id: b.id, name: b.name, path: b.path })));
      })
      .catch(() => {});
    homeDir()
      .then((h) => setHome(h.replace(/\\/g, "/").replace(/\/$/, "")))
      .catch(() => {});
  }, []);

  const items = plan?.items ?? [];
  const grouped = useMemo(() => groupByAction(items), [items]);
  const approvedCount = approved.size;

  const handleExecute = useCallback(async () => {
    if (!plan) return;
    const finalItems = buildFinalProposals(items, approved, fieldApprovals, advancedMode);
    if (finalItems.length === 0) return;
    setExecuting(true);
    setMessage("");
    try {
      const result = await invoke<string>("approve_and_clean", {
        request: {
          proposals: finalItems.map((i) => ({
            file_id: i.file_id,
            original_filename: i.original_filename,
            current_path: i.current_path,
            proposed_path: effectivePath(i),
            proposed_tags: i.proposed_tags,
            faces_detected: i.faces_detected,
            rationale: i.rationale,
          })),
          approved_ids: Array.from(approved),
        },
      });
      setMessage(result);
      setApproved(new Set());
      setFieldApprovals({});
    } catch (err) {
      setMessage(`Error: ${err}`);
    } finally {
      setExecuting(false);
    }
  }, [plan, items, approved, fieldApprovals, advancedMode]);

  const startEdit = useCallback((item: CleanupItem) => {
    setEditingId(item.file_id);
    setEditValue(effectivePath(item));
    setEditError("");
  }, []);

  const saveEdit = useCallback(() => {
    if (!plan || !editingId) return;
    // Validate edited path against sandbox
    const validation = validateEditedPath(editValue, sandboxFolders, home);
    if (!validation.valid) {
      setEditError(validation.error ?? "Invalid path");
      return;
    }
    setPlan((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        items: prev.items.map((i) => {
          if (i.file_id !== editingId) return i;
          const needsPromotion = i.proposed_action === "tag" || i.proposed_action === "delete";
          return {
            ...i,
            proposed_action: needsPromotion ? "move" : i.proposed_action,
            user_edited_path: editValue,
          };
        }),
      };
    });
    setEditingId(null);
    setEditValue("");
    setEditError("");
  }, [editValue, editingId, home, plan, sandboxFolders]);

  const cancelEdit = useCallback(() => {
    setEditingId(null);
    setEditValue("");
    setEditError("");
  }, []);

  const handleReassign = useCallback((item: CleanupItem, bucket: BucketOption) => {
    if (!plan) return;
    const updated = reassignBucket(item, bucket);
    setPlan((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        items: prev.items.map((i) => (i.file_id === item.file_id ? updated : i)),
      };
    });
  }, [plan]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent, action: () => void) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      action();
    }
  }, []);

  // Empty state
  if (!plan || items.length === 0) {
    return (
      <div className="approval-view">
        <h2>✅ Review & Approve</h2>
        <p className="empty-state">No proposals yet. Run a scan first.</p>
      </div>
    );
  }

  return (
    <div className="approval-view">
      <div className="approval-header">
        <h2>✅ Review & Approve</h2>
        <div className="approval-controls">
          <label className="advanced-toggle">
            <input
              type="checkbox"
              checked={advancedMode}
              onChange={(e) => setAdvancedMode(e.target.checked)}
            />
            Advanced
          </label>
          <button onClick={() => setApproved(approveAll(items))}>Approve All</button>
          <button onClick={() => setApproved(rejectAll())}>Reject All</button>
        </div>
      </div>

      <div className="approval-stats" aria-live="polite">
        {approvedCount} of {items.length} approved
      </div>

      {/* Grouped sections per action type */}
      {(Object.keys(grouped) as ProposedAction[]).map((action) => {
        const groupItems = grouped[action] ?? [];
        const groupApproved = groupItems.filter((i) => approved.has(i.file_id)).length;

        return (
          <div key={action} className="action-group">
            <div className="action-group-header">
              <h3>
                {ACTION_ICONS[action]} {ACTION_LABELS[action]} ({groupItems.length})
              </h3>
              <div className="group-controls">
                <button
                  className="small"
                  onClick={() => setApproved(approveGroup(approved, groupItems))}
                >
                  Approve Group
                </button>
                <button
                  className="small"
                  onClick={() => setApproved(rejectGroup(approved, groupItems))}
                >
                  Reject Group
                </button>
                <span className="group-stats">{groupApproved}/{groupItems.length}</span>
              </div>
            </div>

            {groupItems.map((item) => (
              <div
                key={item.file_id}
                className={`proposal-card ${approved.has(item.file_id) ? "approved" : ""}`}
              >
                <div className="proposal-header">
                  <label className="proposal-checkbox-label">
                    <input
                      type="checkbox"
                      checked={approved.has(item.file_id)}
                      onChange={() => setApproved(toggleApproval(approved, item.file_id))}
                    />
                    <span className="filename">{item.original_filename}</span>
                  </label>
                  <span className={`confidence confidence-${confidenceLabel(item.confidence).toLowerCase()}`}>
                    {confidenceLabel(item.confidence)}
                  </span>
                </div>

                <div className="proposal-paths">
                  <div>From: <code>{item.current_path}</code></div>
                  {editingId === item.file_id ? (
                    <div className="inline-edit">
                      <span>→ To: </span>
                      <input
                        type="text"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onKeyDown={(e) => handleKeyDown(e, saveEdit)}
                        autoFocus
                        aria-invalid={!!editError}
                        aria-describedby={editError ? "edit-error" : undefined}
                      />
                      <button className="small" onClick={saveEdit}>Save</button>
                      <button className="small" onClick={cancelEdit}>Cancel</button>
                      {editError && (
                        <span id="edit-error" className="edit-error" role="alert">
                          ⚠️ {editError}
                        </span>
                      )}
                    </div>
                  ) : (
                    <div>
                      → To:{" "}
                      <code
                        className={item.user_edited_path ? "edited-path" : ""}
                        onClick={() => startEdit(item)}
                        onKeyDown={(e) => handleKeyDown(e, () => startEdit(item))}
                        role="button"
                        tabIndex={0}
                        title="Click to edit destination"
                        style={{ cursor: "pointer" }}
                      >
                        {effectivePath(item)}
                      </code>
                      {item.user_edited_path && <span className="edited-badge"> (edited)</span>}
                    </div>
                  )}
                </div>

                {/* Advanced mode: granular controls + bucket selector */}
                {advancedMode && (
                  <div className="advanced-controls">
                    {/* Granular checkboxes per ADR 0005 */}
                    <div className="granular-toggles">
                      <label className="field-toggle">
                        <input
                          type="checkbox"
                          checked={fieldApprovals[item.file_id]?.move ?? true}
                          onChange={() => setFieldApprovals(toggleField(fieldApprovals, item.file_id, "move"))}
                        />
                        Move
                      </label>
                      <label className="field-toggle">
                        <input
                          type="checkbox"
                          checked={fieldApprovals[item.file_id]?.tags ?? true}
                          onChange={() => setFieldApprovals(toggleField(fieldApprovals, item.file_id, "tags"))}
                        />
                        Tags
                      </label>
                      {item.faces_detected.length > 0 && (
                        <label className="field-toggle">
                          <input
                            type="checkbox"
                            checked={fieldApprovals[item.file_id]?.faces ?? true}
                            onChange={() => setFieldApprovals(toggleField(fieldApprovals, item.file_id, "faces"))}
                          />
                          Faces
                        </label>
                      )}
                    </div>

                    {/* Tags display */}
                    <div className="tags-row">
                      <span className="advanced-label">Tags:</span>
                      {item.proposed_tags.map((tag) => (
                        <span key={tag} className="tag">{tag}</span>
                      ))}
                      {item.proposed_tags.length === 0 && <span className="muted">none</span>}
                    </div>

                    {/* Faces display */}
                    {item.faces_detected.length > 0 && (
                      <div className="faces-row">
                        <span className="advanced-label">Faces:</span>
                        {item.faces_detected.map((f) => (
                          <span key={f} className="tag">{f}</span>
                        ))}
                      </div>
                    )}

                    {/* Bucket selector dropdown for reallocation */}
                    {buckets.length > 0 && (
                      <div className="bucket-selector">
                        <label>
                          <span className="advanced-label">Reassign to:</span>
                          <select
                            defaultValue=""
                            onChange={(e) => {
                              const bucket = buckets.find((b) => b.id === e.target.value);
                              if (bucket) handleReassign(item, bucket);
                              e.target.value = "";
                            }}
                          >
                            <option value="" disabled>Choose bucket…</option>
                            {buckets.map((b) => (
                              <option key={b.id} value={b.id}>{b.name}</option>
                            ))}
                          </select>
                        </label>
                      </div>
                    )}
                  </div>
                )}

                <p className="rationale">💡 {item.rationale}</p>
              </div>
            ))}
          </div>
        );
      })}

      {message && <div className={message.startsWith("Error") ? "error" : "success-msg"} role="status">{message}</div>}

      <button
        className="primary approve-button"
        onClick={handleExecute}
        disabled={executing || approvedCount === 0}
      >
        {executing ? "Executing…" : `Execute (${approvedCount} files)`}
      </button>
    </div>
  );
}
