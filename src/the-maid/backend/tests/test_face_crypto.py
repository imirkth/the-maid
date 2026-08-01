"""
Tests for face embedding encryption at rest.
Verifies that encrypted blobs are not raw float32 bytes and that round-trip
storage/retrieval works. Encryption is now mandatory; the clusterer refuses to
initialize without cryptography.
"""

import sqlite3
import tempfile
import shutil
from pathlib import Path

import numpy as np
import pytest

from the_maid.face_crypto import FaceEmbeddingCipher, CRYPTO_AVAILABLE, _machine_id
from the_maid.face_cluster import FaceClusterer, EMBEDDING_DIM


def _make_embedding(seed: int = 0) -> np.ndarray:
    rng = np.random.RandomState(seed)
    v = rng.randn(EMBEDDING_DIM).astype(np.float32)
    v = v / np.linalg.norm(v)
    return v


@pytest.fixture
def conn():
    d = tempfile.mkdtemp(prefix="the-maid-crypto-test-")
    db_path = str(Path(d) / "face-index.db")
    with sqlite3.connect(db_path) as c:
        c.execute(
            "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        yield c
    shutil.rmtree(d, ignore_errors=True)


class TestCipherBasics:
    def test_machine_id_is_non_empty(self):
        mid = _machine_id()
        assert isinstance(mid, str)
        assert mid

    def test_cipher_initializes_with_salt(self, conn):
        if not CRYPTO_AVAILABLE:
            pytest.skip("cryptography not available")
        cipher = FaceEmbeddingCipher(conn)
        assert cipher._fernet is not None
        cur = conn.execute("SELECT value FROM schema_meta WHERE key = 'encryption_salt'")
        assert cur.fetchone() is not None

    def test_encrypt_produces_different_bytes(self, conn):
        if not CRYPTO_AVAILABLE:
            pytest.skip("cryptography not available")
        cipher = FaceEmbeddingCipher(conn)
        plaintext = b"hello world" * 50
        ciphertext = cipher.encrypt(plaintext)
        assert ciphertext != plaintext
        assert cipher.decrypt(ciphertext) == plaintext

    def test_decrypt_bad_ciphertext_raises(self, conn):
        if not CRYPTO_AVAILABLE:
            pytest.skip("cryptography not available")
        cipher = FaceEmbeddingCipher(conn)
        with pytest.raises(Exception):
            cipher.decrypt(b"not a fernet token")

    def test_reloaded_cipher_uses_same_salt(self, conn):
        if not CRYPTO_AVAILABLE:
            pytest.skip("cryptography not available")
        cipher1 = FaceEmbeddingCipher(conn)
        ct1 = cipher1.encrypt(b"secret")
        cipher2 = FaceEmbeddingCipher(conn)
        assert cipher2.decrypt(ct1) == b"secret"

    def test_missing_crypto_raises_on_cipher(self, conn, monkeypatch):
        if CRYPTO_AVAILABLE:
            monkeypatch.setattr("the_maid.face_crypto.CRYPTO_AVAILABLE", False)
        with pytest.raises(RuntimeError, match="cryptography is required"):
            FaceEmbeddingCipher(conn)


class TestFaceClusterEncryption:
    def test_encrypted_blob_not_raw_float32(self):
        if not CRYPTO_AVAILABLE:
            pytest.skip("cryptography not available")
        d = tempfile.mkdtemp(prefix="the-maid-cluster-crypto-test-")
        db_path = str(Path(d) / "face-index.db")
        try:
            clusterer = FaceClusterer(db_path=db_path)
            emb = _make_embedding(7)
            clusterer.store_embedding("f1", "/a.jpg", 0, emb.tolist())

            with sqlite3.connect(db_path) as c:
                blob = c.execute("SELECT embedding FROM embeddings").fetchone()[0]

            original_bytes = emb.tobytes()
            assert blob != original_bytes
            assert len(blob) != len(original_bytes)
            # Raw float32 parse should not recover the embedding.
            arr = np.frombuffer(blob, dtype=np.float32)
            assert len(arr) != EMBEDDING_DIM or not np.allclose(arr, emb, rtol=1e-5)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_round_trip_storage_and_retrieval(self):
        d = tempfile.mkdtemp(prefix="the-maid-cluster-crypto-test-")
        db_path = str(Path(d) / "face-index.db")
        try:
            clusterer = FaceClusterer(db_path=db_path)
            emb = _make_embedding(13)
            clusterer.store_embedding("f1", "/a.jpg", 0, emb.tolist())
            vectors, metadata = clusterer.get_all_embeddings()
            assert vectors.shape == (1, EMBEDDING_DIM)
            np.testing.assert_allclose(vectors[0], emb, rtol=1e-5)
            assert metadata[0]["file_id"] == "f1"
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_batch_storage_round_trip(self):
        d = tempfile.mkdtemp(prefix="the-maid-cluster-crypto-test-")
        db_path = str(Path(d) / "face-index.db")
        try:
            clusterer = FaceClusterer(db_path=db_path)
            faces = [
                {"file_id": "f1", "file_path": "/a.jpg", "face_index": 0,
                 "embedding": _make_embedding(1).tolist(), "confidence": 0.9},
                {"file_id": "f2", "file_path": "/b.jpg", "face_index": 0,
                 "embedding": _make_embedding(2).tolist(), "confidence": 0.8},
            ]
            clusterer.store_embeddings_batch(faces)
            vectors, metadata = clusterer.get_all_embeddings()
            assert vectors.shape == (2, EMBEDDING_DIM)
            assert {m["file_id"] for m in metadata} == {"f1", "f2"}
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_clustering_works_with_encrypted_embeddings(self):
        d = tempfile.mkdtemp(prefix="the-maid-cluster-crypto-test-")
        db_path = str(Path(d) / "face-index.db")
        try:
            clusterer = FaceClusterer(db_path=db_path, eps=0.4, min_samples=2)
            base = _make_embedding(42)
            for i in range(3):
                noise = np.random.RandomState(i).randn(EMBEDDING_DIM).astype(np.float32) * 0.001
                similar = base + noise
                similar = similar / np.linalg.norm(similar)
                clusterer.store_embedding(f"f{i}", f"/{i}.jpg", 0, similar.tolist())
            result = clusterer.cluster()
            assert result["n_clusters"] == 1
            assert result["n_noise"] == 0
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_db_file_permissions_restricted_on_unix(self):
        d = tempfile.mkdtemp(prefix="the-maid-cluster-crypto-test-")
        db_path = str(Path(d) / "face-index.db")
        try:
            import os
            clusterer = FaceClusterer(db_path=db_path)
            clusterer.store_embedding("f1", "/a.jpg", 0, _make_embedding(1).tolist())
            if os.name == "posix":
                mode = Path(db_path).stat().st_mode & 0o777
                assert mode == 0o600, f"expected 0o600, got 0o{mode:03o}"
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_plaintext_migration_to_encrypted(self):
        d = tempfile.mkdtemp(prefix="the-maid-cluster-crypto-test-")
        db_path = str(Path(d) / "face-index.db")
        try:
            # Create a legacy DB with the current schema and a plaintext embedding.
            with sqlite3.connect(db_path) as c:
                c.executescript("""
                    CREATE TABLE IF NOT EXISTS embeddings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        file_id TEXT NOT NULL,
                        file_path TEXT NOT NULL,
                        face_index INTEGER NOT NULL,
                        embedding BLOB NOT NULL,
                        confidence REAL DEFAULT 0.0,
                        cluster_id INTEGER,
                        cluster_label TEXT,
                        created_at TEXT DEFAULT (datetime('now'))
                    );
                    CREATE TABLE IF NOT EXISTS schema_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    );
                """)
                emb = _make_embedding(99)
                c.execute(
                    "INSERT INTO embeddings (file_id, file_path, face_index, embedding) "
                    "VALUES (?, ?, ?, ?)",
                    ("f1", "/a.jpg", 0, emb.tobytes()),
                )

            clusterer = FaceClusterer(db_path=db_path)
            vectors, _ = clusterer.get_all_embeddings()
            assert vectors.shape == (1, EMBEDDING_DIM)
            np.testing.assert_allclose(vectors[0], emb, rtol=1e-5)

            with sqlite3.connect(db_path) as c:
                blob = c.execute("SELECT embedding FROM embeddings").fetchone()[0]
                assert blob != emb.tobytes()
        finally:
            shutil.rmtree(d, ignore_errors=True)
