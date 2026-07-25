"""
Tests for FaceClusterer — DBSCAN clustering, SQLite storage, Unknown_Person_N labels.
No sklearn required (uses minimal numpy DBSCAN).
"""

import pytest
import tempfile
import shutil
import sqlite3
import numpy as np
from pathlib import Path
from typing import List

from the_maid.face_cluster import (
    FaceClusterer,
    cluster_faces_from_scan,
    _dbscan,
    _cosine_distance_matrix,
    DEFAULT_EPS,
    DEFAULT_MIN_SAMPLES,
)


# ─── Fixtures ───

@pytest.fixture
def temp_db():
    """Create a temp directory with a face-index.db."""
    d = tempfile.mkdtemp(prefix="the-maid-cluster-test-")
    db_path = str(Path(d) / "face-index.db")
    yield db_path
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def clusterer(temp_db):
    return FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)


def _make_embedding(seed: int = 0) -> List[float]:
    """Create a deterministic 128D normalized embedding."""
    rng = np.random.RandomState(seed)
    v = rng.randn(128).astype(np.float32)
    v = v / np.linalg.norm(v)  # L2 normalize
    return v.tolist()


def _make_similar_embedding(base: List[float], noise: float = 0.01) -> List[float]:
    """Create an embedding close to base with small noise."""
    v = np.array(base, dtype=np.float32)
    v = v + np.random.RandomState(42).randn(128).astype(np.float32) * noise
    v = v / np.linalg.norm(v)
    return v.tolist()


def _make_scan_results(n_images: int = 3, faces_per_image: int = 1,
                       embeddings_seed: int = 0) -> list:
    """Generate scan-like results with faces_detected."""
    rng = np.random.RandomState(embeddings_seed)
    results = []
    for i in range(n_images):
        faces = []
        for j in range(faces_per_image):
            v = rng.randn(128).astype(np.float32)
            v = v / np.linalg.norm(v)
            faces.append({
                "bbox": [0, 0, 50, 50],
                "confidence": 0.9,
                "embedding": v.tolist(),
            })
        results.append({
            "file_id": f"abc{i:05d}",
            "filename": f"photo{i}.jpg",
            "path": f"/tmp/photo{i}.jpg",
            "extension": ".jpg",
            "faces_detected": faces,
        })
    return results


# ─── DB Initialization ───

class TestDBInit:
    def test_creates_db_file(self, temp_db):
        clusterer = FaceClusterer(db_path=temp_db)
        assert Path(temp_db).exists()

    def test_schema_tables_exist(self, temp_db):
        clusterer = FaceClusterer(db_path=temp_db)
        with sqlite3.connect(temp_db) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        assert "embeddings" in tables
        assert "schema_meta" in tables

    def test_schema_version_stored(self, temp_db):
        clusterer = FaceClusterer(db_path=temp_db)
        with sqlite3.connect(temp_db) as conn:
            ver = conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
        assert ver is not None

    def test_default_db_path(self, temp_db):
        """Default path uses ~/.the-maid/face-index.db per ADR 0006."""
        from the_maid.face_cluster import _db_path
        path = _db_path(None)
        assert "face-index.db" in path
        assert ".the-maid" in path

    def test_idempotent_init(self, temp_db):
        """Initializing twice doesn't error."""
        FaceClusterer(db_path=temp_db)
        FaceClusterer(db_path=temp_db)

    def test_default_db_path_creates_parent_directory(self, monkeypatch):
        """Default path creates missing ~/.the-maid directory on first init."""
        import tempfile
        parent = tempfile.mkdtemp(prefix="the-maid-home-")
        monkeypatch.setenv("HOME", parent)
        clusterer = FaceClusterer()
        assert Path(parent, ".the-maid", "face-index.db").exists()
        clusterer.clear()

    def test_corrupt_db_raises_clear_error(self, temp_db):
        """A corrupt non-SQLite file should fail with a clear error when used as DB."""
        Path(temp_db).write_text("not a sqlite file")
        with pytest.raises(sqlite3.DatabaseError):
            FaceClusterer(db_path=temp_db)


# ─── Embedding Storage ───

class TestEmbeddingStorage:
    def test_store_single_embedding(self, clusterer, temp_db):
        emb = _make_embedding(42)
        row_id = clusterer.store_embedding("file1", "/path/to/file1.jpg", 0, emb, 0.95)
        assert row_id > 0

        with sqlite3.connect(temp_db) as conn:
            row = conn.execute(
                "SELECT file_id, file_path, face_index, confidence FROM embeddings WHERE id = ?",
                (row_id,)
            ).fetchone()
        assert row[0] == "file1"
        assert row[1] == "/path/to/file1.jpg"
        assert row[2] == 0
        assert row[3] == 0.95

    def test_store_batch(self, clusterer):
        faces = [
            {"file_id": "f1", "file_path": "/a.jpg", "face_index": 0,
             "embedding": _make_embedding(1), "confidence": 0.9},
            {"file_id": "f2", "file_path": "/b.jpg", "face_index": 0,
             "embedding": _make_embedding(2), "confidence": 0.8},
            {"file_id": "f1", "file_path": "/a.jpg", "face_index": 1,
             "embedding": _make_embedding(3), "confidence": 0.7},
        ]
        count = clusterer.store_embeddings_batch(faces)
        assert count == 3

    def test_store_empty_batch(self, clusterer):
        count = clusterer.store_embeddings_batch([])
        assert count == 0

    def test_embedding_stored_as_blob(self, clusterer, temp_db):
        emb = _make_embedding(99)
        clusterer.store_embedding("f1", "/a.jpg", 0, emb)
        with sqlite3.connect(temp_db) as conn:
            blob = conn.execute("SELECT embedding FROM embeddings").fetchone()[0]
        arr = np.frombuffer(blob, dtype=np.float32)
        assert len(arr) == 128
        np.testing.assert_allclose(arr, np.array(emb, dtype=np.float32), rtol=1e-5)

    def test_store_invalid_embedding_dimension(self, clusterer):
        """Embedding with wrong dimension should be rejected."""
        with pytest.raises(ValueError):
            clusterer.store_embedding("f1", "/a.jpg", 0, [0.1] * 64)

    def test_store_non_finite_embedding(self, clusterer):
        """Embedding with NaN/Inf should be rejected."""
        bad = [0.1] * 127 + [float("nan")]
        with pytest.raises(ValueError):
            clusterer.store_embedding("f1", "/a.jpg", 0, bad)

    def test_get_all_embeddings_empty(self, clusterer):
        vectors, metadata = clusterer.get_all_embeddings()
        assert len(vectors) == 0
        assert metadata == []

    def test_get_all_embeddings_populated(self, clusterer):
        emb1 = _make_embedding(1)
        emb2 = _make_embedding(2)
        clusterer.store_embedding("f1", "/a.jpg", 0, emb1)
        clusterer.store_embedding("f2", "/b.jpg", 0, emb2)

        vectors, metadata = clusterer.get_all_embeddings()
        assert vectors.shape == (2, 128)
        assert len(metadata) == 2
        assert metadata[0]["file_id"] == "f1"
        assert metadata[1]["file_id"] == "f2"


# ─── DBSCAN Implementation ───

class TestDBSCAN:
    def test_empty_input(self):
        dist = np.array([]).reshape(0, 0)
        labels = _dbscan(0.4, 2, dist)
        assert labels == []

    def test_single_point_is_noise(self):
        dist = np.array([[0.0]])
        labels = _dbscan(0.4, 2, dist)
        assert labels == [-1]

    def test_single_point_min_samples_one_is_cluster(self):
        dist = np.array([[0.0]])
        labels = _dbscan(0.4, 1, dist)
        assert labels == [0]

    def test_density_reachability_assigns_border_points(self):
        """Border points reachable via other border points from a core point must join the cluster."""
        # 3x3 grid. eps=0.35, min_samples=3. Center, edges, and corners form a chain.
        # With min_samples=3 every point except the center has exactly 3 neighbors within eps
        # (itself + 2 edge neighbors), so edges/corners become core and the whole grid clusters.
        n = 9
        dist = np.full((n, n), 0.99)
        for i in range(3):
            for j in range(3):
                idx = i * 3 + j
                dist[idx, idx] = 0.0
                for di in (-1, 0, 1):
                    for dj in (-1, 0, 1):
                        if di == 0 and dj == 0:
                            continue
                        ni, nj = i + di, j + dj
                        if 0 <= ni < 3 and 0 <= nj < 3:
                            nidx = ni * 3 + nj
                            d = 0.3 if (di == 0 or dj == 0) else 0.45
                            dist[idx, nidx] = d
        labels = _dbscan(0.35, 3, dist)
        # All points should belong to a single cluster; none should be noise.
        assert len(set(labels)) == 1, labels
        assert all(l >= 0 for l in labels)

    def test_two_close_points_form_cluster(self):
        """Two points within eps should form a cluster (min_samples=2)."""
        dist = np.array([
            [0.0, 0.1],
            [0.1, 0.0],
        ])
        labels = _dbscan(eps=0.4, min_samples=2, dist_matrix=dist)
        assert labels[0] >= 0
        assert labels[1] >= 0
        assert labels[0] == labels[1]  # same cluster

    def test_two_far_points_are_noise(self):
        """Two points beyond eps should be noise."""
        dist = np.array([
            [0.0, 0.9],
            [0.9, 0.0],
        ])
        labels = _dbscan(eps=0.4, min_samples=2, dist_matrix=dist)
        assert labels[0] == -1
        assert labels[1] == -1

    def test_two_separate_clusters(self):
        """Two well-separated groups."""
        dist = np.array([
            [0.0, 0.1, 0.9, 0.9],
            [0.1, 0.0, 0.9, 0.9],
            [0.9, 0.9, 0.0, 0.1],
            [0.9, 0.9, 0.1, 0.0],
        ])
        labels = _dbscan(eps=0.4, min_samples=2, dist_matrix=dist)
        assert labels[0] == labels[1]
        assert labels[2] == labels[3]
        assert labels[0] != labels[2]

    def test_chain_of_close_points(self):
        """Points connected via a chain should cluster together."""
        n = 5
        dist = np.zeros((n, n))
        for i in range(n):
            for j in range(n):
                dist[i][j] = abs(i - j) * 0.2  # adjacent points within eps
        labels = _dbscan(eps=0.4, min_samples=2, dist_matrix=dist)
        cluster_labels = [l for l in labels if l >= 0]
        assert len(set(cluster_labels)) == 1  # one cluster
        assert len(cluster_labels) == n  # all in cluster

    def test_min_samples_3(self):
        """With min_samples=3, two close points are noise."""
        dist = np.array([
            [0.0, 0.1],
            [0.1, 0.0],
        ])
        labels = _dbscan(eps=0.4, min_samples=3, dist_matrix=dist)
        assert labels == [-1, -1]


class TestCosineDistance:
    def test_identical_vectors_zero_distance(self):
        v = np.array([_make_embedding(5)])
        dist = _cosine_distance_matrix(v)
        assert dist.shape == (1, 1)
        assert abs(dist[0][0]) < 1e-6

    def test_orthogonal_vectors_distance_one(self):
        v = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0],
        ], dtype=np.float32)
        dist = _cosine_distance_matrix(v)
        assert abs(dist[0][1] - 1.0) < 1e-6

    def test_similar_vectors_small_distance(self):
        v1 = np.array(_make_embedding(1), dtype=np.float32)
        v2 = v1 + 0.01 * np.random.RandomState(42).randn(128).astype(np.float32)
        v2 = v2 / np.linalg.norm(v2)
        dist = _cosine_distance_matrix(np.array([v1, v2]))
        assert dist[0][1] < 0.05  # very close


# ─── Clustering ───

class TestClustering:
    def test_empty_db_clusters(self, clusterer):
        result = clusterer.cluster()
        assert result["n_clusters"] == 0
        assert result["n_noise"] == 0

    def test_single_face_is_noise(self, clusterer):
        clusterer.store_embedding("f1", "/a.jpg", 0, _make_embedding(1))
        result = clusterer.cluster()
        assert result["n_clusters"] == 0
        assert result["n_noise"] == 1

    def test_two_similar_faces_cluster(self, clusterer):
        """Two similar embeddings should form one cluster."""
        base = _make_embedding(42)
        similar = _make_similar_embedding(base, noise=0.001)
        clusterer.store_embedding("f1", "/a.jpg", 0, base)
        clusterer.store_embedding("f2", "/b.jpg", 0, similar)
        result = clusterer.cluster()
        assert result["n_clusters"] == 1
        assert result["n_noise"] == 0

    def test_two_different_faces_are_noise(self, clusterer):
        """Very different embeddings should be noise with min_samples=2."""
        clusterer.store_embedding("f1", "/a.jpg", 0, _make_embedding(1))
        clusterer.store_embedding("f2", "/b.jpg", 0, _make_embedding(99))
        result = clusterer.cluster()
        assert result["n_clusters"] == 0
        assert result["n_noise"] == 2

    def test_unknown_person_labels_sequential(self, clusterer):
        """Clusters get Unknown_Person_1, Unknown_Person_2, etc."""
        # Create two distinct clusters
        base1 = _make_embedding(1)
        base2 = _make_embedding(99)
        for i in range(3):
            clusterer.store_embedding(f"f{i}", f"/a{i}.jpg", 0,
                                      _make_similar_embedding(base1, noise=0.001))
        for i in range(3):
            clusterer.store_embedding(f"g{i}", f"/b{i}.jpg", 0,
                                      _make_similar_embedding(base2, noise=0.001))
        result = clusterer.cluster()
        assert result["n_clusters"] == 2
        labels = set(result["labels"].values())
        assert "Unknown_Person_1" in labels
        assert "Unknown_Person_2" in labels

    def test_unknown_person_labels_after_rename(self, clusterer):
        """Renamed clusters keep their name; new unknown clusters use smallest free number."""
        base1 = _make_embedding(1)
        base2 = _make_embedding(99)
        for i in range(2):
            clusterer.store_embedding(f"f{i}", f"/a{i}.jpg", 0,
                                      _make_similar_embedding(base1, noise=0.001))
        for i in range(2):
            clusterer.store_embedding(f"g{i}", f"/b{i}.jpg", 0,
                                      _make_similar_embedding(base2, noise=0.001))
        clusterer.cluster()
        clusterer.rename_cluster(0, "Sarah")
        # Add a brand new cluster after a rename
        base3 = _make_embedding(50)
        for i in range(2):
            clusterer.store_embedding(f"h{i}", f"/c{i}.jpg", 0,
                                      _make_similar_embedding(base3, noise=0.001))
        result = clusterer.cluster()
        labels = set(result["labels"].values())
        # Previously cluster 0 was renamed to Sarah, so it should remain Sarah
        assert "Sarah" in labels
        # The remaining unnamed clusters should use sequential unknown numbers
        assert "Unknown_Person_1" in labels
        assert "Unknown_Person_2" in labels

    def test_cluster_label_format(self, clusterer):
        """Labels follow Unknown_Person_N format."""
        base = _make_embedding(1)
        clusterer.store_embedding("f1", "/a.jpg", 0, base)
        clusterer.store_embedding("f2", "/b.jpg", 0, _make_similar_embedding(base, noise=0.001))
        result = clusterer.cluster()
        assert "Unknown_Person_1" in result["labels"].values()

    def test_get_clusters_returns_structure(self, clusterer):
        """get_clusters returns structured cluster data."""
        base = _make_embedding(1)
        clusterer.store_embedding("f1", "/a.jpg", 0, base)
        clusterer.store_embedding("f2", "/b.jpg", 0, _make_similar_embedding(base, noise=0.001))
        clusterer.cluster()

        clusters = clusterer.get_clusters()
        assert len(clusters) == 1
        assert clusters[0]["cluster_id"] >= 0
        assert "Unknown_Person" in clusters[0]["cluster_label"]
        assert len(clusters[0]["faces"]) == 2

    def test_get_clusters_empty(self, clusterer):
        clusters = clusterer.get_clusters()
        assert clusters == []

    def test_rename_cluster_preserves_label_ordering(self, clusterer):
        """Renaming cluster 2 should not change numbering of other unknown clusters."""
        base1 = _make_embedding(1)
        base2 = _make_embedding(99)
        # cluster 0
        clusterer.store_embedding("f1", "/a.jpg", 0, base1)
        clusterer.store_embedding("f2", "/b.jpg", 0, _make_similar_embedding(base1, noise=0.001))
        # cluster 1
        clusterer.store_embedding("f3", "/c.jpg", 0, base2)
        clusterer.store_embedding("f4", "/d.jpg", 0, _make_similar_embedding(base2, noise=0.001))
        clusterer.cluster()
        clusterer.rename_cluster(1, "Sarah")

        # Cluster 0 should remain Unknown_Person_1, cluster 1 now Sarah
        with sqlite3.connect(clusterer.db_path) as conn:
            rows = conn.execute(
                "SELECT cluster_id, cluster_label FROM embeddings WHERE cluster_id >= 0 ORDER BY cluster_id"
            ).fetchall()
        assert rows[0] == (0, "Unknown_Person_1")
        assert rows[1] == (0, "Unknown_Person_1")
        assert rows[2] == (1, "Sarah")
        assert rows[3] == (1, "Sarah")

    def test_rename_cluster_nonexistent(self, clusterer):
        """Renaming a nonexistent cluster returns zero updates."""
        count = clusterer.rename_cluster(999, "Nobody")
        assert count == 0

    def test_clear(self, clusterer):
        """clear removes all embeddings."""
        clusterer.store_embedding("f1", "/a.jpg", 0, _make_embedding(1))
        clusterer.clear()
        vectors, _ = clusterer.get_all_embeddings()
        assert len(vectors) == 0

    def test_recluster_after_adding(self, clusterer):
        """Adding new embeddings and re-clustering works."""
        base = _make_embedding(1)
        clusterer.store_embedding("f1", "/a.jpg", 0, base)
        clusterer.store_embedding("f2", "/b.jpg", 0, _make_similar_embedding(base, noise=0.001))
        r1 = clusterer.cluster()
        assert r1["n_clusters"] == 1

        # Add a new different face
        clusterer.store_embedding("f3", "/c.jpg", 0, _make_embedding(77))
        r2 = clusterer.cluster()
        # The new face is noise (single, different from cluster)
        assert r2["n_noise"] >= 1

    def test_recluster_renames_existing_labels(self, clusterer):
        """Reclustering should reset old cluster labels so new numbering is consistent."""
        base = _make_embedding(1)
        clusterer.store_embedding("f1", "/a.jpg", 0, base)
        clusterer.store_embedding("f2", "/b.jpg", 0, _make_similar_embedding(base, noise=0.001))
        r1 = clusterer.cluster()
        old_label = list(r1["labels"].values())[0]

        # Add another face similar enough to merge into the same cluster (3 points now)
        clusterer.store_embedding("f3", "/c.jpg", 0, _make_similar_embedding(base, noise=0.001))
        r2 = clusterer.cluster()
        assert r2["n_clusters"] == 1
        new_label = list(r2["labels"].values())[0]
        # Label numbering may be reset; all rows should share one current label
        with sqlite3.connect(clusterer.db_path) as conn:
            labels = {row[0] for row in conn.execute("SELECT DISTINCT cluster_label FROM embeddings WHERE cluster_id >= 0").fetchall()}
        assert len(labels) == 1

    def test_configurable_eps(self, temp_db):
        """Higher eps clusters more aggressively."""
        base = _make_embedding(1)
        different = _make_embedding(50)
        # With eps=0.4, these are likely noise
        c_strict = FaceClusterer(db_path=temp_db, eps=0.3, min_samples=2)
        c_strict.store_embedding("f1", "/a.jpg", 0, base)
        c_strict.store_embedding("f2", "/b.jpg", 0, different)
        r_strict = c_strict.cluster()

        c_loose = FaceClusterer(db_path=temp_db, eps=2.0, min_samples=2)
        c_loose.clear()
        c_loose.store_embedding("f1", "/a.jpg", 0, base)
        c_loose.store_embedding("f2", "/b.jpg", 0, different)
        r_loose = c_loose.cluster()

        assert r_loose["n_clusters"] >= r_strict["n_clusters"]

    def test_eps_too_large_one_cluster(self, temp_db):
        """Eps very large should merge all faces into a single cluster."""
        c = FaceClusterer(db_path=temp_db, eps=5.0, min_samples=2)
        for seed in [1, 50, 99, 200]:
            c.store_embedding(f"f{seed}", f"/{seed}.jpg", 0, _make_embedding(seed))
        r = c.cluster()
        assert r["n_clusters"] == 1
        assert r["n_noise"] == 0

    def test_eps_too_small_all_noise(self, temp_db):
        """Eps tiny should mark all faces as noise."""
        c = FaceClusterer(db_path=temp_db, eps=1e-6, min_samples=2)
        base = _make_embedding(1)
        c.store_embedding("f1", "/a.jpg", 0, base)
        c.store_embedding("f2", "/b.jpg", 0, _make_similar_embedding(base, noise=0.001))
        r = c.cluster()
        assert r["n_clusters"] == 0
        assert r["n_noise"] == 2

    def test_min_samples_one_cluster(self, temp_db):
        """min_samples=1 makes any point a cluster core point."""
        c = FaceClusterer(db_path=temp_db, eps=0.4, min_samples=1)
        c.store_embedding("f1", "/a.jpg", 0, _make_embedding(1))
        r = c.cluster()
        assert r["n_clusters"] == 1
        assert r["n_noise"] == 0

    def test_all_same_person_cluster(self, temp_db):
        """Many slightly different faces of one person cluster together."""
        c = FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)
        base = _make_embedding(1)
        for i in range(10):
            c.store_embedding(f"f{i}", f"/{i}.jpg", 0,
                              _make_similar_embedding(base, noise=0.01))
        r = c.cluster()
        assert r["n_clusters"] == 1
        assert r["n_noise"] == 0

    def test_all_different_people_noise(self, temp_db):
        """Many orthogonal-ish faces should remain noise with min_samples=2."""
        c = FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)
        for i in range(10):
            c.store_embedding(f"f{i}", f"/{i}.jpg", 0, _make_embedding(i * 7))
        r = c.cluster()
        assert r["n_clusters"] == 0
        assert r["n_noise"] == 10

    def test_duplicate_embeddings_cluster(self, temp_db):
        """Identical embeddings should be one cluster."""
        c = FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)
        emb = _make_embedding(1)
        for i in range(3):
            c.store_embedding(f"f{i}", f"/{i}.jpg", 0, emb)
        r = c.cluster()
        assert r["n_clusters"] == 1
        assert r["n_noise"] == 0


# ─── Scan Integration ───

class TestScanIntegration:
    def test_cluster_faces_from_scan_empty(self, temp_db):
        results = cluster_faces_from_scan([], db_path=temp_db)
        assert results["n_clusters"] == 0
        assert results["n_noise"] == 0

    def test_cluster_faces_from_scan_disabled(self, temp_db):
        scan = _make_scan_results(n_images=3)
        results = cluster_faces_from_scan(scan, enabled=False, db_path=temp_db)
        assert results["n_clusters"] == 0

    def test_cluster_faces_from_scan_no_faces(self, temp_db):
        """Scan results with empty faces_detected should produce no clusters."""
        scan = [{"file_id": "f1", "path": "/a.jpg", "faces_detected": []}]
        results = cluster_faces_from_scan(scan, db_path=temp_db)
        assert results["n_clusters"] == 0
        assert results["n_noise"] == 0

    def test_cluster_faces_from_scan_with_faces(self, temp_db):
        """Scan results with similar faces should cluster."""
        base = _make_embedding(42)
        similar = _make_similar_embedding(base, noise=0.001)
        scan = [
            {"file_id": "f1", "filename": "a.jpg", "path": "/a.jpg",
             "extension": ".jpg",
             "faces_detected": [{"bbox": [0, 0, 50, 50], "confidence": 0.9, "embedding": base}]},
            {"file_id": "f2", "filename": "b.jpg", "path": "/b.jpg",
             "extension": ".jpg",
             "faces_detected": [{"bbox": [0, 0, 50, 50], "confidence": 0.9, "embedding": similar}]},
        ]
        results = cluster_faces_from_scan(scan, db_path=temp_db)
        assert results["n_clusters"] == 1
        assert "f1" in results["labels"]
        assert "f2" in results["labels"]

    def test_cluster_adds_label_to_faces_detected(self, temp_db):
        """After clustering, faces_detected items get cluster_label."""
        base = _make_embedding(42)
        similar = _make_similar_embedding(base, noise=0.001)
        scan = [
            {"file_id": "f1", "filename": "a.jpg", "path": "/a.jpg",
             "extension": ".jpg",
             "faces_detected": [{"bbox": [0, 0, 50, 50], "confidence": 0.9, "embedding": base}]},
            {"file_id": "f2", "filename": "b.jpg", "path": "/b.jpg",
             "extension": ".jpg",
             "faces_detected": [{"bbox": [0, 0, 50, 50], "confidence": 0.9, "embedding": similar}]},
        ]
        cluster_faces_from_scan(scan, db_path=temp_db)
        assert scan[0]["faces_detected"][0]["cluster_label"] == "Unknown_Person_1"
        assert scan[1]["faces_detected"][0]["cluster_label"] == "Unknown_Person_1"

    def test_cluster_label_indexed_by_face_index(self, temp_db):
        """Multiple faces per image should map labels by face_index, not position."""
        base1 = _make_embedding(1)
        base2 = _make_embedding(99)
        # Add third face that is similar to base1 (so base1 cluster has 2 members)
        similar1 = _make_similar_embedding(base1, noise=0.001)
        scan = [
            {"file_id": "f1", "filename": "group.jpg", "path": "/group.jpg",
             "extension": ".jpg",
             "faces_detected": [
                 {"bbox": [0, 0, 50, 50], "confidence": 0.9, "embedding": base1},
                 {"bbox": [60, 60, 120, 120], "confidence": 0.85, "embedding": base2},
             ]},
            {"file_id": "f2", "filename": "solo.jpg", "path": "/solo.jpg",
             "extension": ".jpg",
             "faces_detected": [
                 {"bbox": [0, 0, 50, 50], "confidence": 0.9, "embedding": similar1},
             ]},
        ]
        cluster_faces_from_scan(scan, db_path=temp_db)
        # f1 face 0 (base1) is in Unknown_Person_1, face 1 (base2) is noise
        assert scan[0]["faces_detected"][0]["cluster_label"] == "Unknown_Person_1"
        assert scan[0]["faces_detected"][1].get("cluster_label") is None
        # f2 face 0 (similar1) is also in Unknown_Person_1
        assert scan[1]["faces_detected"][0]["cluster_label"] == "Unknown_Person_1"

    def test_cluster_preserves_scan_fields(self, temp_db):
        """Clustering should not remove existing scan metadata."""
        base = _make_embedding(42)
        scan = [
            {"file_id": "f1", "filename": "a.jpg", "path": "/a.jpg",
             "extension": ".jpg", "size_bytes": 100,
             "faces_detected": [{"bbox": [0, 0, 50, 50], "confidence": 0.9, "embedding": base}]},
        ]
        cluster_faces_from_scan(scan, db_path=temp_db)
        assert scan[0]["file_id"] == "f1"
        assert scan[0]["filename"] == "a.jpg"
        assert scan[0]["size_bytes"] == 100

    def test_multiple_faces_per_image(self, temp_db):
        """Multiple faces in the same image can be in different clusters."""
        base1 = _make_embedding(1)
        base2 = _make_embedding(99)
        scan = [
            {"file_id": "f1", "filename": "group.jpg", "path": "/group.jpg",
             "extension": ".jpg",
             "faces_detected": [
                 {"bbox": [0, 0, 50, 50], "confidence": 0.9, "embedding": base1},
                 {"bbox": [60, 60, 120, 120], "confidence": 0.85, "embedding": base2},
             ]},
            {"file_id": "f2", "filename": "solo.jpg", "path": "/solo.jpg",
             "extension": ".jpg",
             "faces_detected": [
                 {"bbox": [0, 0, 50, 50], "confidence": 0.9,
                  "embedding": _make_similar_embedding(base1, noise=0.001)},
             ]},
        ]
        results = cluster_faces_from_scan(scan, db_path=temp_db)
        assert results["n_clusters"] >= 1
        # f1 has two faces, possibly in different clusters
        assert "f1" in results["labels"]
        assert "f2" in results["labels"]

    def test_no_embedding_skipped(self, temp_db):
        """Faces without embedding field are skipped gracefully."""
        scan = [
            {"file_id": "f1", "path": "/a.jpg",
             "faces_detected": [{"bbox": [0, 0, 50, 50], "confidence": 0.9}]},
        ]
        results = cluster_faces_from_scan(scan, db_path=temp_db)
        assert results["n_clusters"] == 0
        assert results["n_noise"] == 0