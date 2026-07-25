import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { FaceClusterInfo, RenameResult } from "../types/face-cluster";

export default function FaceClusterView() {
  const [clusters, setClusters] = useState<FaceClusterInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editValue, setEditValue] = useState("");
  const [renameStatus, setRenameStatus] = useState<string | null>(null);

  const loadClusters = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await invoke<FaceClusterInfo[]>("get_face_clusters");
      setClusters(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadClusters(); }, [loadClusters]);

  const startEditing = (cluster: FaceClusterInfo) => {
    setEditingId(cluster.cluster_id);
    setEditValue(cluster.cluster_label.startsWith("Unknown_Person_") ? "" : cluster.cluster_label);
  };

  const cancelEditing = () => {
    setEditingId(null);
    setEditValue("");
  };

  const submitRename = async (clusterId: number) => {
    const name = editValue.trim();
    if (!name) return;
    setRenameStatus(null);
    try {
      const result = await invoke<RenameResult>("rename_face_cluster", {
        clusterId,
        newLabel: name,
      });
      setRenameStatus(
        `Renamed "${name}": ${result.tagged} tagged, ${result.skipped} skipped` +
        (result.errors.length ? `, ${result.errors.length} errors` : "")
      );
      setEditingId(null);
      setEditValue("");
      await loadClusters();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="face-cluster-view">
      <h2>👤 Face Clusters</h2>
      <p>Group photos by person. Name a cluster to tag all photos.</p>

      <div style={{ display: "flex", gap: "8px", marginBottom: "16px" }}>
        <button onClick={loadClusters} disabled={loading}>
          {loading ? "Loading..." : "Refresh"}
        </button>
        {renameStatus && <span style={{ fontSize: "13px", alignSelf: "center" }}>{renameStatus}</span>}
      </div>

      {error && <p style={{ color: "red" }}>{error}</p>}

      {clusters.length === 0 && !loading && (
        <p className="empty-state">No clusters found. Run a scan with face detection enabled.</p>
      )}

      <div className="clusters-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "16px" }}>
        {clusters.map((cluster) => (
          <div key={cluster.cluster_id} className="cluster-card"
               style={{ border: "1px solid #ddd", borderRadius: "8px", padding: "12px" }}>
            <div className="cluster-image"
                 style={{ width: "100%", height: "150px", background: "#f0f0f0",
                         display: "flex", alignItems: "center", justifyContent: "center",
                         marginBottom: "8px", borderRadius: "4px", overflow: "hidden" }}>
              {cluster.representative_path
                ? <img src={`file://${cluster.representative_path}`} alt="Face"
                       style={{ width: "100%", height: "100%", objectFit: "cover" }}
                       onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                : <span>No preview</span>}
            </div>
            <div className="cluster-info">
              <p style={{ margin: "4px 0", fontWeight: 500 }}>{cluster.cluster_label}</p>
              <p style={{ margin: "2px 0", fontSize: "13px", color: "#666" }}>
                {cluster.face_count} {cluster.face_count === 1 ? "photo" : "photos"}
              </p>
              {editingId === cluster.cluster_id ? (
                <div style={{ display: "flex", gap: "4px", marginTop: "4px" }}>
                  <input
                    type="text"
                    value={editValue}
                    placeholder="Type name..."
                    autoFocus
                    onChange={(e) => setEditValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") submitRename(cluster.cluster_id);
                      if (e.key === "Escape") cancelEditing();
                    }}
                    style={{ flex: 1, padding: "4px 8px" }}
                  />
                  <button onClick={() => submitRename(cluster.cluster_id)} disabled={!editValue.trim()}>
                    ✓
                  </button>
                  <button onClick={cancelEditing}>✕</button>
                </div>
              ) : (
                <button onClick={() => startEditing(cluster)}
                        style={{ marginTop: "4px", fontSize: "13px" }}>
                  {cluster.cluster_label.startsWith("Unknown_Person_") ? "Name this person" : "Rename"}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}