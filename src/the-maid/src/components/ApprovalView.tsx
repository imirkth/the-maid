import { useState } from "react";

interface FileProposal {
  file_id: string;
  original_filename: string;
  current_path: string;
  proposed_path: string;
  proposed_tags: string[];
  faces_detected: string[];
  rationale: string;
}

export default function ApprovalView() {
  const [proposals, setProposals] = useState<FileProposal[]>([]);
  const [approvedIds, setApprovedIds] = useState<Set<string>>(new Set());
  const [advancedMode, setAdvancedMode] = useState(false);
  const [editingPath, setEditingPath] = useState<string | null>(null);

  const toggleApproval = (id: string) => {
    setApprovedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const approveAll = () => {
    setApprovedIds(new Set(proposals.map((p) => p.file_id)));
  };

  const rejectAll = () => {
    setApprovedIds(new Set());
  };

  const handleApprove = async () => {
    // TODO: Call approve_and_clean with approvedIds
    console.log("Approving:", Array.from(approvedIds));
  };

  return (
    <div className="approval-view">
      <div className="approval-header">
        <h2>✅ Review & Approve</h2>
        <div className="approval-controls">
          <label>
            <input
              type="checkbox"
              checked={advancedMode}
              onChange={(e) => setAdvancedMode(e.target.checked)}
            />
            Advanced Mode
          </label>
          <button onClick={approveAll}>Approve All</button>
          <button onClick={rejectAll}>Reject All</button>
        </div>
      </div>

      <div className="approval-stats">
        {approvedIds.size} of {proposals.length} approved
      </div>

      <div className="proposals-list">
        {proposals.length === 0 && (
          <p className="empty-state">No proposals yet. Run a scan first.</p>
        )}

        {proposals.map((p) => (
          <div key={p.file_id} className={`proposal-card ${approvedIds.has(p.file_id) ? "approved" : ""}`}>
            <div className="proposal-header">
              <input
                type="checkbox"
                checked={approvedIds.has(p.file_id)}
                onChange={() => toggleApproval(p.file_id)}
              />
              <span className="filename">{p.original_filename}</span>
            </div>

            <div className="proposal-paths">
              <div>From: <code>{p.current_path}</code></div>
              <div>→ To: <code>{p.proposed_path}</code></div>
            </div>

            <div className="proposal-tags">
              {p.proposed_tags.map((tag) => (
                <span key={tag} className="tag">{tag}</span>
              ))}
            </div>

            <p className="rationale">💡 {p.rationale}</p>
          </div>
        ))}
      </div>

      {proposals.length > 0 && (
        <button className="primary approve-button" onClick={handleApprove}>
          Approve & Clean ({approvedIds.size} files)
        </button>
      )}
    </div>
  );
}
