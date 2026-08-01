"""
The Maid — Face Clustering (Slice 6B)
DBSCAN clustering of 128D ArcFace vectors into face groups.
SQLite storage for embeddings + cluster IDs.
Unknown_Person_N labels assigned sequentially.
"""

import sqlite3
import math
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import numpy as np

from .face_crypto import FaceEmbeddingCipher

# Default DBSCAN params (can be overridden via settings)
DEFAULT_EPS = 0.4        # cosine distance threshold (ArcFace embeddings are normalized)
DEFAULT_MIN_SAMPLES = 2  # minimum faces to form a cluster

# 128D ArcFace embedding vector
EMBEDDING_DIM = 128

# Schema version for migrations
DB_SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS embeddings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     TEXT NOT NULL,          -- 8-char hex (ADR 0009)
    file_path   TEXT NOT NULL,
    face_index  INTEGER NOT NULL,       -- which face in the file (0-based)
    embedding   BLOB NOT NULL,          -- 128D float32 vector (encrypted at rest)
    confidence  REAL DEFAULT 0.0,
    cluster_id  INTEGER,                -- NULL until clustered
    cluster_label TEXT,                 -- "Unknown_Person_1" etc
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_cluster ON embeddings(cluster_id);
CREATE INDEX IF NOT EXISTS idx_file ON embeddings(file_id);
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('schema_version', ?);
"""


def _db_path(db_path: Optional[str] = None) -> str:
    """Resolve database path. Default: ~/.the-maid/face-index.db per ADR 0006."""
    if db_path:
        return db_path
    home = Path.home()
    return str(home / ".the-maid" / "face-index.db")


def _cosine_distance_matrix(vectors: np.ndarray) -> np.ndarray:
    """Pairwise cosine distance for normalized embeddings (1 - dot product)."""
    # ArcFace normed_embeddings are L2-normalized, so dot product = cosine similarity
    return 1.0 - np.dot(vectors, vectors.T)


def _dbscan(eps: float, min_samples: int, dist_matrix: np.ndarray) -> List[int]:
    """
    Minimal DBSCAN on a precomputed distance matrix.
    Returns cluster labels: -1 = noise, 0+ = cluster ID.
    Avoids sklearn dependency — DBSCAN is ~40 lines on numpy.
    """
    n = dist_matrix.shape[0]
    if n == 0:
        return []
    if n == 1:
        # A single point's neighborhood is itself (distance 0), so it forms a
        # cluster when min_samples <= 1; otherwise it is noise.
        return [0] if min_samples <= 1 else [-1]

    labels = np.full(n, -1, dtype=int)  # -1 = unvisited/noise
    cluster_id = 0
    visited = np.zeros(n, dtype=bool)

    for i in range(n):
        if visited[i]:
            continue
        visited[i] = True

        # Find neighbors (include self via the zero diagonal)
        neighbors = np.where(dist_matrix[i] <= eps)[0]

        if len(neighbors) < min_samples:
            labels[i] = -1  # noise
            continue

        # Start new cluster
        labels[i] = cluster_id
        seed = list(neighbors)

        while seed:
            j = seed.pop(0)
            if labels[j] == -1:
                labels[j] = cluster_id
            if not visited[j]:
                visited[j] = True
                j_neighbors = np.where(dist_matrix[j] <= eps)[0]
                if len(j_neighbors) >= min_samples:
                    # Core point: extend seed with neighbors not already in seed
                    for nb in j_neighbors:
                        if nb not in seed:
                            seed.append(nb)
                else:
                    # Border point: still add its unvisited neighbors within eps so density-reachable
                    # points beyond the immediate core neighborhood get discovered.
                    for nb in j_neighbors:
                        if not visited[nb] and nb not in seed:
                            seed.append(nb)

        cluster_id += 1

    return labels.tolist()


def _is_finite(value: float) -> bool:
    """Return True if value is a finite real number."""
    return math.isfinite(value)


def _validate_embedding(embedding: List[float]) -> bool:
    """Return True if embedding has correct dimension and all finite values."""
    if len(embedding) != EMBEDDING_DIM:
        return False
    return all(_is_finite(v) for v in embedding)


def _centroid(vectors: np.ndarray) -> np.ndarray:
    """Compute L2-normalized mean centroid of a set of normalized vectors."""
    if len(vectors) == 0:
        return vectors
    mean = vectors.mean(axis=0)
    norm = np.linalg.norm(mean)
    if norm == 0:
        return mean
    return mean / norm


def _nearest_custom_label(
    new_vectors: np.ndarray,
    custom_centroids: List[Tuple[np.ndarray, str]],
    eps: float,
) -> Optional[str]:
    """
    Find the custom label whose previous centroid is closest to the new cluster's
    centroid, within eps (cosine distance). Returns None if no match.
    """
    if not custom_centroids:
        return None
    new_centroid = _centroid(new_vectors)
    best_label: Optional[str] = None
    best_dist = float("inf")
    for prev_centroid, label in custom_centroids:
        dist = 1.0 - float(np.dot(new_centroid, prev_centroid))
        if dist <= eps and dist < best_dist:
            best_dist = dist
            best_label = label
    return best_label


class FaceClusterer:
    """
    Stores face embeddings in SQLite and clusters them with DBSCAN.
    Assigns Unknown_Person_N labels to clusters.
    """

    def __init__(self, db_path: Optional[str] = None, eps: float = DEFAULT_EPS,
                 min_samples: int = DEFAULT_MIN_SAMPLES):
        self.db_path = _db_path(db_path)
        self.eps = eps
        self.min_samples = min_samples
        self._cipher: Optional[FaceEmbeddingCipher] = None
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if not exists; guard against unsupported future schemas."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        is_fresh = not Path(self.db_path).exists()
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(_SCHEMA_SQL)
            existing = conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            if existing and existing[0] is not None:
                try:
                    existing_version = int(existing[0])
                except ValueError:
                    existing_version = 0
                if existing_version > DB_SCHEMA_VERSION:
                    raise RuntimeError(
                        f"Database schema version {existing_version} is newer than "
                        f"supported version {DB_SCHEMA_VERSION}. Please upgrade the app."
                    )
            conn.execute("UPDATE schema_meta SET value = ? WHERE key = 'schema_version'",
                         (str(DB_SCHEMA_VERSION),))
            # Ensure cipher is initialized (creates salt if needed) before migration.
            self._cipher = FaceEmbeddingCipher(conn)
            self._migrate_plaintext_embeddings(conn)

        # Restrict DB file to owner only on Unix (P2 #26).
        if is_fresh and os.name == "posix":
            try:
                os.chmod(self.db_path, 0o600)
            except OSError:
                pass  # Best effort; network filesystems may reject chmod.

    def _migrate_plaintext_embeddings(self, conn) -> None:
        """One-time migration: encrypt any existing plaintext float32 blobs."""
        expected_len = EMBEDDING_DIM * 4  # 128 float32 values
        rows = conn.execute(
            "SELECT id, embedding FROM embeddings WHERE LENGTH(embedding) = ?",
            (expected_len,),
        ).fetchall()
        for row_id, blob in rows:
            encrypted = self._cipher.encrypt(bytes(blob))
            conn.execute(
                "UPDATE embeddings SET embedding = ? WHERE id = ?",
                (encrypted, row_id),
            )

    def store_embedding(self, file_id: str, file_path: str, face_index: int,
                        embedding: List[float], confidence: float = 0.0) -> int:
        """Store a single face embedding. Returns the row ID."""
        emb_arr = np.array(embedding, dtype=np.float32)
        if emb_arr.shape != (EMBEDDING_DIM,):
            raise ValueError(
                f"Embedding must be {EMBEDDING_DIM}D, got shape {emb_arr.shape}"
            )
        if not np.all(np.isfinite(emb_arr)):
            raise ValueError("Embedding contains non-finite values (NaN/Inf)")
        with sqlite3.connect(self.db_path) as conn:
            if self._cipher is None:
                self._cipher = FaceEmbeddingCipher(conn)
            encrypted = self._cipher.encrypt(emb_arr.tobytes())
            cur = conn.execute(
                "INSERT INTO embeddings (file_id, file_path, face_index, embedding, confidence) "
                "VALUES (?, ?, ?, ?, ?)",
                (file_id, file_path, face_index, encrypted, confidence)
            )
            return cur.lastrowid

    def store_embeddings_batch(self, faces: List[Dict[str, Any]]) -> int:
        """
        Store multiple face embeddings from scan results.
        faces: list of dicts with file_id, file_path, face_index, embedding, confidence.
        Invalid embeddings or malformed dicts are skipped silently so one bad face
        does not break a batch. Returns count stored.
        """
        count = 0
        with sqlite3.connect(self.db_path) as conn:
            for f in faces:
                try:
                    file_id = f["file_id"]
                    file_path = f["file_path"]
                    face_index = f["face_index"]
                    embedding = f["embedding"]
                except KeyError:
                    continue
                if file_id is None or file_path is None:
                    continue
                emb_arr = np.array(embedding, dtype=np.float32)
                if emb_arr.shape != (EMBEDDING_DIM,):
                    continue
                if not np.all(np.isfinite(emb_arr)):
                    continue
                confidence = f.get("confidence", 0.0)
                if isinstance(confidence, (int, float)) and math.isfinite(confidence):
                    confidence = float(confidence)
                else:
                    continue
                if self._cipher is None:
                    self._cipher = FaceEmbeddingCipher(conn)
                encrypted = self._cipher.encrypt(emb_arr.tobytes())
                conn.execute(
                    "INSERT INTO embeddings (file_id, file_path, face_index, embedding, confidence) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (file_id, file_path, face_index, encrypted, confidence)
                )
                count += 1
        return count

    def _decrypt_row_embedding(self, blob: bytes) -> np.ndarray:
        """Decrypt an embedding blob and return a float32 numpy array."""
        plaintext = self._cipher.decrypt(blob)
        return np.frombuffer(plaintext, dtype=np.float32)

    def get_all_embeddings(self) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
        """
        Fetch all embeddings from DB.
        Returns (vectors Nx128, metadata list) where metadata[i] corresponds to vectors[i].
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, file_id, file_path, face_index, embedding, confidence, cluster_id "
                "FROM embeddings ORDER BY id"
            ).fetchall()

        if not rows:
            return np.array([]), []

        if self._cipher is None:
            with sqlite3.connect(self.db_path) as conn:
                self._cipher = FaceEmbeddingCipher(conn)

        vectors = []
        metadata = []
        for row in rows:
            emb = self._decrypt_row_embedding(row[4])
            vectors.append(emb)
            metadata.append({
                "row_id": row[0],
                "file_id": row[1],
                "file_path": row[2],
                "face_index": row[3],
                "confidence": row[5],
                "cluster_id": row[6],
            })

        return np.array(vectors), metadata

    def cluster(self) -> Dict[str, Any]:
        """
        Run DBSCAN on all stored embeddings.
        Updates cluster_id and cluster_label in DB.
        Returns summary: {n_clusters, n_noise, labels: {row_id: cluster_label}}
        """
        vectors, metadata = self.get_all_embeddings()

        if len(vectors) == 0:
            return {"n_clusters": 0, "n_noise": 0, "labels": {}}

        if len(vectors) == 1:
            # Single face: cluster if eps allows, otherwise noise.
            # Since self-distance is zero, it always satisfies min_samples when min_samples == 1.
            if self.min_samples <= 1:
                cid = 0
                clabel = "Unknown_Person_1"
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        "UPDATE embeddings SET cluster_id = ?, cluster_label = ? WHERE id = ?",
                        (cid, clabel, metadata[0]["row_id"])
                    )
                return {"n_clusters": 1, "n_noise": 0, "labels": {metadata[0]["row_id"]: clabel}}
            # Single face = noise
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE embeddings SET cluster_id = -1, cluster_label = NULL WHERE id = ?",
                    (metadata[0]["row_id"],)
                )
            return {"n_clusters": 0, "n_noise": 1, "labels": {}}

        # Compute distance matrix
        dist = _cosine_distance_matrix(vectors)

        # Run DBSCAN
        raw_labels = _dbscan(self.eps, self.min_samples, dist)

        # Assign Unknown_Person_N labels to clusters.
        # Preserve already-named custom labels by matching new cluster centroids to
        # previous custom-labeled centroids (cosine distance <= eps). This is stable
        # across re-runs regardless of DBSCAN's raw label numbering.
        label_map: Dict[int, str] = {}

        # Build previous custom-labeled centroids from current DB before overwrite.
        custom_centroids: List[Tuple[np.ndarray, str]] = []
        if metadata:
            if self._cipher is None:
                with sqlite3.connect(self.db_path) as conn:
                    self._cipher = FaceEmbeddingCipher(conn)
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT id, cluster_id, cluster_label, embedding FROM embeddings"
                ).fetchall()
            prev_by_cluster: Dict[int, Dict[str, Any]] = {}
            for row_id, cid, clabel, emb_blob in rows:
                if cid is None or cid < 0:
                    continue
                if not clabel or clabel.startswith("Unknown_Person_"):
                    continue
                prev_by_cluster.setdefault(cid, {"label": clabel, "vectors": []})
                prev_by_cluster[cid]["vectors"].append(
                    self._decrypt_row_embedding(emb_blob)
                )
            for info in prev_by_cluster.values():
                if info["vectors"]:
                    custom_centroids.append(
                        (_centroid(np.array(info["vectors"])), info["label"])
                    )

        # Group vectors by new raw label so we can match centroids.
        new_cluster_vectors: Dict[int, List[np.ndarray]] = {}
        for i, label in enumerate(raw_labels):
            if label < 0:
                continue
            new_cluster_vectors.setdefault(label, []).append(vectors[i])

        for label in sorted(new_cluster_vectors.keys()):
            new_vecs = np.array(new_cluster_vectors[label])
            preserved = _nearest_custom_label(new_vecs, custom_centroids, self.eps)
            if preserved:
                label_map[label] = preserved
            else:
                # Next free Unknown_Person_N number.
                n = 1
                while f"Unknown_Person_{n}" in label_map.values():
                    n += 1
                label_map[label] = f"Unknown_Person_{n}"

        # Update DB
        labels_result = {}
        with sqlite3.connect(self.db_path) as conn:
            for i, meta in enumerate(metadata):
                cid = raw_labels[i]
                clabel = label_map.get(cid) if cid >= 0 else None
                conn.execute(
                    "UPDATE embeddings SET cluster_id = ?, cluster_label = ? WHERE id = ?",
                    (cid, clabel, meta["row_id"])
                )
                if cid >= 0:
                    labels_result[meta["row_id"]] = clabel

        n_clusters = len(label_map)
        n_noise = sum(1 for l in raw_labels if l < 0)

        return {
            "n_clusters": n_clusters,
            "n_noise": n_noise,
            "labels": labels_result,
        }

    def get_clusters(self) -> List[Dict[str, Any]]:
        """
        Return all clusters with their member faces.
        [{cluster_id, cluster_label, faces: [{file_id, file_path, face_index}]}]
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT cluster_id, cluster_label, file_id, file_path, face_index, confidence "
                "FROM embeddings WHERE cluster_id >= 0 ORDER BY cluster_id, id"
            ).fetchall()

        clusters: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            cid = row[0]
            if cid not in clusters:
                clusters[cid] = {
                    "cluster_id": cid,
                    "cluster_label": row[1],
                    "faces": [],
                }
            clusters[cid]["faces"].append({
                "file_id": row[2],
                "file_path": row[3],
                "face_index": row[4],
                "confidence": row[5],
            })

        return list(clusters.values())

    def get_clusters_for_ui(self) -> List[Dict[str, Any]]:
        """
        Return clusters formatted for the UI, including a representative face.
        Representative is the highest-confidence face; ties break by first seen.
        """
        clusters = self.get_clusters()
        ui_clusters: List[Dict[str, Any]] = []
        for c in clusters:
            faces = c["faces"]
            representative = max(
                faces,
                key=lambda f: (f.get("confidence", 0.0), -faces.index(f)),
            ) if faces else None
            ui_clusters.append({
                "cluster_id": c["cluster_id"],
                "cluster_label": c["cluster_label"],
                "representative": representative,
                "face_count": len(faces),
                "faces": faces,
            })
        return ui_clusters

    def rename_cluster(self, cluster_id: int, new_label: str) -> int:
        """
        Rename a cluster's label. Returns count of updated rows.
        (For Slice 6C: naming a cluster writes XMP tags to all photos.)
        """
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE embeddings SET cluster_label = ? WHERE cluster_id = ?",
                (new_label, cluster_id)
            )
            return cur.rowcount

    def clear(self) -> None:
        """Drop all embeddings (for re-scan)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM embeddings")


def cluster_faces_from_scan(
    scan_results: List[Dict[str, Any]],
    clusterer: Optional[FaceClusterer] = None,
    enabled: bool = True,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Post-detection clustering pass. Takes scan results with faces_detected,
    stores embeddings in SQLite, runs DBSCAN, returns cluster summary.

    Args:
        scan_results: Output from detect_faces_for_scan (with faces_detected populated)
        clusterer: FaceClusterer instance. If None, creates default.
        enabled: If False, skips clustering.
        db_path: Override DB path for testing.

    Returns: {n_clusters, n_noise, labels: {file_id: [cluster_labels]}}
    """
    if not enabled:
        return {"n_clusters": 0, "n_noise": 0, "labels": {}}

    if clusterer is None:
        clusterer = FaceClusterer(db_path=db_path)

    # Collect all faces with embeddings from scan results
    faces_to_store = []
    for f in scan_results:
        for idx, face in enumerate(f.get("faces_detected", [])):
            if "embedding" in face:
                faces_to_store.append({
                    "file_id": f["file_id"],
                    "file_path": f["path"],
                    "face_index": idx,
                    "embedding": face["embedding"],
                    "confidence": face.get("confidence", 0.0),
                })

    if not faces_to_store:
        return {"n_clusters": 0, "n_noise": 0, "labels": {}}

    # Store embeddings
    clusterer.store_embeddings_batch(faces_to_store)

    # Run clustering
    cluster_result = clusterer.cluster()

    # Build file-level label map: {file_id: [cluster_labels]}
    clusters = clusterer.get_clusters()
    file_labels: Dict[str, List[str]] = {}
    for c in clusters:
        for face in c["faces"]:
            fid = face["file_id"]
            if fid not in file_labels:
                file_labels[fid] = []
            if c["cluster_label"]:
                file_labels[fid].append(c["cluster_label"])

    # Mutate scan_results: add cluster labels to faces_detected
    for f in scan_results:
        labels = file_labels.get(f["file_id"], [])
        for idx, face in enumerate(f.get("faces_detected", [])):
            if idx < len(labels):
                face["cluster_label"] = labels[idx]
            else:
                face.setdefault("cluster_label", None)

    return {
        "n_clusters": cluster_result["n_clusters"],
        "n_noise": cluster_result["n_noise"],
        "labels": file_labels,
    }
