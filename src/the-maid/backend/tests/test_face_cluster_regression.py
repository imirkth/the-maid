"""
Regression tests for Slice 6B bugs discovered during diagnosing-bugs pass.
Run with: python -m pytest tests/test_face_cluster_regression.py -v
"""

import pytest
import tempfile
import shutil
import sqlite3
import numpy as np
from pathlib import Path

from the_maid.face_cluster import (
    FaceClusterer,
    cluster_faces_from_scan,
    _dbscan,
    _cosine_distance_matrix,
    DEFAULT_EPS,
    DEFAULT_MIN_SAMPLES,
    EMBEDDING_DIM,
)


@pytest.fixture
def temp_db():
    d = tempfile.mkdtemp(prefix="the-maid-regression-test-")
    db_path = str(Path(d) / "face-index.db")
    yield db_path
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def clusterer(temp_db):
    return FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)


def _make_embedding(seed: int = 0) -> list:
    rng = np.random.RandomState(seed)
    v = rng.randn(128).astype(np.float32)
    v = v / np.linalg.norm(v)
    return v.tolist()


def _make_similar_embedding(base: list, noise: float = 0.001) -> list:
    v = np.array(base, dtype=np.float32)
    v = v + np.random.RandomState(seed=42).randn(128).astype(np.float32) * noise
    v = v / np.linalg.norm(v)
    return v.tolist()


# ─── Bug A: label preservation by raw DBSCAN label is unstable ───

class TestLabelPreservationStable:
    def test_renamed_label_follows_same_physical_cluster_after_reorder(self, temp_db):
        """
        If we add a new cluster so that DBSCAN raw label assignment changes,
        a renamed cluster should still keep its custom label on the same physical
        group of faces, not stick to whichever raw label number happened to match.
        """
        c = FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)

        base_a = _make_embedding(1)
        base_b = _make_embedding(99)
        # Cluster A (Alice)
        c.store_embedding("a1", "/a1.jpg", 0, base_a)
        c.store_embedding("a2", "/a2.jpg", 0, _make_similar_embedding(base_a))
        # Cluster B
        c.store_embedding("b1", "/b1.jpg", 0, base_b)
        c.store_embedding("b2", "/b2.jpg", 0, _make_similar_embedding(base_b))

        c.cluster()
        c.rename_cluster(0, "Alice")

        # Add a third cluster *before* A in point order so DBSCAN raw labels shift.
        base_c = _make_embedding(50)
        c.store_embedding("c1", "/c1.jpg", 0, base_c)
        c.store_embedding("c2", "/c2.jpg", 0, _make_similar_embedding(base_c))
        # And add another A face to keep the A cluster alive.
        c.store_embedding("a3", "/a3.jpg", 0, _make_similar_embedding(base_a))

        result = c.cluster()
        # Find the label for any A face.
        with sqlite3.connect(temp_db) as conn:
            a_labels = {row[0] for row in conn.execute(
                "SELECT cluster_label FROM embeddings WHERE file_id LIKE 'a%'"
            ).fetchall()}
        assert a_labels == {"Alice"}, f"A cluster lost Alice label: {a_labels}"
        assert "Alice" in result["labels"].values()

    def test_label_preserved_when_new_cluster_appears_before_old(self, temp_db):
        """
        Add a new cluster that DBSCAN labels 0 (because of point order), while the
        previously renamed cluster becomes label 1. The custom name must move with
        the old cluster's embeddings, not remain on raw label 0.
        """
        c = FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)

        base_old = _make_embedding(10)
        c.store_embedding("old1", "/old1.jpg", 0, base_old)
        c.store_embedding("old2", "/old2.jpg", 0, _make_similar_embedding(base_old))
        c.cluster()
        c.rename_cluster(0, "Grandma")

        # Now insert a new cluster *before* the old rows in id order.
        base_new = _make_embedding(20)
        c.store_embedding("new1", "/new1.jpg", 0, base_new)
        c.store_embedding("new2", "/new2.jpg", 0, _make_similar_embedding(base_new))
        # Insert another old-ish face to keep old cluster alive.
        c.store_embedding("old3", "/old3.jpg", 0, _make_similar_embedding(base_old))

        result = c.cluster()
        # Find which label old3 ended up in
        with sqlite3.connect(temp_db) as conn:
            old3_row = conn.execute(
                "SELECT cluster_id, cluster_label FROM embeddings WHERE file_id='old3'"
            ).fetchone()
        assert old3_row[1] == "Grandma", f"Old cluster lost name: {old3_row}"


# ─── Bug B/C: batch storage must tolerate malformed face dicts ───

class TestBatchStorageRobustness:
    def test_batch_skips_missing_embedding(self, clusterer):
        faces = [
            {"file_id": "good", "file_path": "/good.jpg", "face_index": 0,
             "embedding": _make_embedding(1), "confidence": 0.9},
            {"file_id": "bad", "file_path": "/bad.jpg", "face_index": 0,
             "confidence": 0.9},  # no embedding
        ]
        count = clusterer.store_embeddings_batch(faces)
        assert count == 1

    def test_batch_skips_missing_file_id(self, clusterer):
        faces = [
            {"file_id": "good", "file_path": "/good.jpg", "face_index": 0,
             "embedding": _make_embedding(1), "confidence": 0.9},
            {"file_path": "/bad.jpg", "face_index": 0,
             "embedding": _make_embedding(2), "confidence": 0.9},
        ]
        count = clusterer.store_embeddings_batch(faces)
        assert count == 1

    def test_batch_skips_non_finite_confidence(self, clusterer):
        faces = [
            {"file_id": "good", "file_path": "/good.jpg", "face_index": 0,
             "embedding": _make_embedding(1), "confidence": 0.9},
            {"file_id": "bad", "file_path": "/bad.jpg", "face_index": 0,
             "embedding": _make_embedding(2), "confidence": float("inf")},
            {"file_id": "bad2", "file_path": "/bad2.jpg", "face_index": 0,
             "embedding": _make_embedding(3), "confidence": float("nan")},
        ]
        count = clusterer.store_embeddings_batch(faces)
        assert count == 1

    def test_batch_stores_remaining_after_partial_failure(self, clusterer):
        faces = [
            {"file_id": "bad1", "file_path": "/bad1.jpg", "face_index": 0,
             "embedding": _make_embedding(1), "confidence": 0.9},
            {"file_id": None, "file_path": "/bad2.jpg", "face_index": 0,
             "embedding": _make_embedding(2), "confidence": 0.9},
            {"file_id": "good", "file_path": "/good.jpg", "face_index": 0,
             "embedding": _make_embedding(3), "confidence": 0.9},
        ]
        count = clusterer.store_embeddings_batch(faces)
        assert count == 2


# ─── Bug D: schema version should not downgrade unsupported future versions ───

class TestSchemaVersion:
    def test_schema_version_downgrade_detected(self, temp_db):
        FaceClusterer(db_path=temp_db)
        # Simulate future schema
        with sqlite3.connect(temp_db) as conn:
            conn.execute("UPDATE schema_meta SET value = '99' WHERE key='schema_version'")
        with pytest.raises(RuntimeError):
            FaceClusterer(db_path=temp_db)


# ─── Bug E: get_clusters_for_ui missing / representative face selection ───

class TestUIClusters:
    def test_get_clusters_for_ui_exists_and_returns_representative(self, temp_db):
        c = FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)
        base = _make_embedding(1)
        c.store_embedding("f1", "/f1.jpg", 0, base, confidence=0.7)
        c.store_embedding("f2", "/f2.jpg", 0, _make_similar_embedding(base), confidence=0.95)
        c.cluster()
        ui_clusters = c.get_clusters_for_ui()
        assert len(ui_clusters) == 1
        cluster = ui_clusters[0]
        assert "representative" in cluster
        rep = cluster["representative"]
        assert rep["file_id"] == "f2"  # highest confidence
        assert rep["confidence"] == 0.95

    def test_get_clusters_for_ui_empty(self, temp_db):
        c = FaceClusterer(db_path=temp_db)
        assert c.get_clusters_for_ui() == []


# ─── Deterministic Unknown_Person_N labels across re-runs ───

class TestDeterministicLabels:
    def test_unknown_labels_deterministic_across_runs(self, temp_db):
        c1 = FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)
        base_a = _make_embedding(1)
        base_b = _make_embedding(99)
        for i in range(2):
            c1.store_embedding(f"a{i}", f"/a{i}.jpg", 0, _make_similar_embedding(base_a))
            c1.store_embedding(f"b{i}", f"/b{i}.jpg", 0, _make_similar_embedding(base_b))
        r1 = c1.cluster()

        # New clusterer instance, same DB, re-run cluster
        c2 = FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)
        r2 = c2.cluster()
        assert r1["labels"] == r2["labels"]


# ─── DBSCAN edge: all-noise and single-cluster deterministic labels ───

class TestDBSCANEdgeCases:
    def test_all_noise_returns_empty_labels(self, temp_db):
        c = FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)
        for seed in [1, 50]:
            c.store_embedding(f"f{seed}", f"/{seed}.jpg", 0, _make_embedding(seed))
        result = c.cluster()
        assert result["n_clusters"] == 0
        assert result["n_noise"] == 2
        assert result["labels"] == {}

    def test_single_cluster_label_unknown_person_1(self, temp_db):
        c = FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)
        base = _make_embedding(1)
        for i in range(3):
            c.store_embedding(f"f{i}", f"/{i}.jpg", 0, base)
        result = c.cluster()
        assert result["n_clusters"] == 1
        assert set(result["labels"].values()) == {"Unknown_Person_1"}
