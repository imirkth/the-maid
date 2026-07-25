import { useState } from "react";

interface FaceCluster {
  id: string;
  representative_image: string;
  image_count: number;
  suggested_name: string;
}

export default function FaceClusterView() {
  const [clusters, setClusters] = useState<FaceCluster[]>([]);
  const [isScanning, setIsScanning] = useState(false);
  const [directory, setDirectory] = useState("~/Pictures");

  const scanFaces = async () => {
    setIsScanning(true);
    // TODO: Call cluster_faces
    setTimeout(() => setIsScanning(false), 2000);
  };

  const tagCluster = (id: string, name: string) => {
    // TODO: Call tag_face_cluster
    console.log("Tagging cluster", id, "as", name);
  };

  return (
    <div className="face-cluster-view">
      <h2>👤 Face Clustering</h2>
      <p>Group photos by person. No pre-training needed.</p>

      <div className="scan-input">
        <input
          type="text"
          value={directory}
          onChange={(e) => setDirectory(e.target.value)}
        />
        <button onClick={scanFaces} disabled={isScanning}>
          {isScanning ? "Scanning..." : "Scan for Faces"}
        </button>
      </div>

      {clusters.length === 0 && !isScanning && (
        <p className="empty-state">No clusters found. Scan a directory to start.</p>
      )}

      <div className="clusters-grid">
        {clusters.map((cluster) => (
          <div key={cluster.id} className="cluster-card">
            <div className="cluster-image">
              <img src={cluster.representative_image} alt="Face cluster" />
            </div>
            <div className="cluster-info">
              <p>{cluster.image_count} photos</p>
              <input
                type="text"
                placeholder="Who is this?"
                defaultValue={cluster.suggested_name}
                onBlur={(e) => tagCluster(cluster.id, e.target.value)}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
