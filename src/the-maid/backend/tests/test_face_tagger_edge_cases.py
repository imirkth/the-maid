"""
Edge-case and integration tests for face_tagger.py.
These use real file paths and real FaceClusterer state where possible,
mocking only ExifTool since it may not be installed in CI.
"""

import pytest
import tempfile
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from the_maid.face_cluster import FaceClusterer
from the_maid.face_tagger import (
    rename_cluster_with_tags,
    get_clusters_for_ui,
)
from tests.test_face_cluster import _make_embedding, _make_similar_embedding


@pytest.fixture
def temp_db():
    d = tempfile.mkdtemp(prefix="the-maid-tagger-edge-")
    db_path = str(Path(d) / "face-index.db")
    yield db_path
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def clusterer_with_data(temp_db):
    c = FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)
    base1 = _make_embedding(1)
    base2 = _make_embedding(99)
    for i in range(3):
        c.store_embedding(f"f{i}", f"/photos/a{i}.jpg", 0,
                          _make_similar_embedding(base1, noise=0.001))
    for i in range(2):
        c.store_embedding(f"g{i}", f"/photos/b{i}.jpg", 0,
                          _make_similar_embedding(base2, noise=0.001))
    c.cluster()
    return c


class TestRenameClusterEdgeCases:
    @patch("the_maid.face_tagger._write_xmp_tag", return_value=True)
    def test_renames_all_faces_in_cluster(self, mock_write, clusterer_with_data):
        result = rename_cluster_with_tags(clusterer_with_data, 0, "Sarah")
        assert result["renamed"] == 3
        assert result["tagged"] == 3
        assert result["skipped"] == 0
        written_paths = {c.args[0] for c in mock_write.call_args_list}
        assert written_paths == {"/photos/a0.jpg", "/photos/a1.jpg", "/photos/a2.jpg"}

    @patch("the_maid.face_tagger._write_xmp_tag", side_effect=[True, True, False])
    def test_partial_failure_counts_correctly(self, mock_write, clusterer_with_data):
        result = rename_cluster_with_tags(clusterer_with_data, 0, "Sarah")
        assert result["renamed"] == 3
        assert result["tagged"] == 2
        assert result["skipped"] == 1
        assert len(result["errors"]) == 1

    def test_missing_files_real_check(self, clusterer_with_data):
        with patch("the_maid.face_tagger._exiftool_available", return_value=True):
            result = rename_cluster_with_tags(clusterer_with_data, 0, "Sarah")
        assert result["renamed"] == 3
        assert result["tagged"] == 0
        assert result["skipped"] == 3
        assert all("File not found" in e or "exiftool failed" in e
                   for e in result["errors"])

    @patch("the_maid.face_tagger._write_xmp_tag", return_value=True)
    def test_rename_to_same_name_still_writes(self, mock_write, clusterer_with_data):
        clusters = clusterer_with_data.get_clusters()
        cluster_id = clusters[0]["cluster_id"]
        old_label = clusters[0]["cluster_label"]
        result = rename_cluster_with_tags(clusterer_with_data, cluster_id, old_label)
        assert result["renamed"] == 3
        assert result["tagged"] == 3

    @patch("the_maid.face_tagger._write_xmp_tag", return_value=True)
    def test_duplicate_names_allowed(self, mock_write, clusterer_with_data):
        rename_cluster_with_tags(clusterer_with_data, 0, "Sarah")
        result = rename_cluster_with_tags(clusterer_with_data, 1, "Sarah")
        assert result["renamed"] == 2
        assert result["tagged"] == 2

    @patch("the_maid.face_tagger._write_xmp_tag", return_value=True)
    def test_very_long_name_clamped(self, mock_write, clusterer_with_data):
        long_name = "A" * 1000
        result = rename_cluster_with_tags(clusterer_with_data, 0, long_name)
        assert result["renamed"] == 3
        assert result["tagged"] == 3
        written_values = {c.args[2] for c in mock_write.call_args_list}
        assert len(written_values) == 1
        assert len(next(iter(written_values))) == 100

    @patch("the_maid.face_tagger._write_xmp_tag", return_value=True)
    def test_special_characters_name(self, mock_write, clusterer_with_data):
        name = "Sarah-O'Connor 佐藤 🧹"
        result = rename_cluster_with_tags(clusterer_with_data, 0, name)
        assert result["renamed"] == 3
        assert result["tagged"] == 3

    def test_exiftool_missing_returns_error(self, clusterer_with_data):
        with patch("the_maid.face_tagger._exiftool_available", return_value=False):
            result = rename_cluster_with_tags(clusterer_with_data, 0, "Sarah")
        assert result["renamed"] == 3
        assert result["tagged"] == 0
        assert result["skipped"] == 3
        assert any("exiftool not installed" in e for e in result["errors"])

    @patch("the_maid.face_tagger._write_xmp_tag", return_value=True)
    def test_sandbox_rejects_outside_paths(self, mock_write, clusterer_with_data):
        result = rename_cluster_with_tags(
            clusterer_with_data, 0, "Sarah",
            sandbox_folders=["Desktop", "Pictures"]
        )
        assert result["renamed"] == 3
        assert result["tagged"] == 0
        assert result["skipped"] == 3
        assert any("sandbox" in e.lower() for e in result["errors"])

    @patch("the_maid.face_tagger._write_xmp_tag", return_value=True)
    def test_empty_label_rejected(self, mock_write, clusterer_with_data):
        result = rename_cluster_with_tags(clusterer_with_data, 0, "")
        assert result["renamed"] == 0
        assert result["tagged"] == 0
        assert result["skipped"] == 0
        assert any("empty" in e.lower() for e in result["errors"])


class TestGetClustersForUIEdgeCases:
    def test_representative_is_first_face(self, clusterer_with_data):
        result = get_clusters_for_ui(clusterer_with_data)
        for cluster in result:
            assert cluster["representative_path"] == cluster["faces"][0]["file_path"]

    def test_cluster_with_zero_faces_after_moves(self, temp_db):
        c = FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)
        base = _make_embedding(1)
        c.store_embedding("f1", str(Path.home() / "Desktop" / "photo1.jpg"), 0,
                          _make_similar_embedding(base, noise=0.001))
        c.store_embedding("f2", "/tmp/photo2.jpg", 0,
                          _make_similar_embedding(base, noise=0.001))
        c.cluster()
        result = get_clusters_for_ui(c, sandbox_folders=["Pictures"])
        assert result == []

    def test_sandbox_with_partial_members(self, temp_db):
        c = FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)
        base = _make_embedding(1)
        c.store_embedding("f1", str(Path.home() / "Desktop" / "photo1.jpg"), 0,
                          _make_similar_embedding(base, noise=0.001))
        c.store_embedding("f2", str(Path.home() / "Desktop" / "photo2.jpg"), 0,
                          _make_similar_embedding(base, noise=0.001))
        c.store_embedding("f3", "/tmp/photo3.jpg", 0,
                          _make_similar_embedding(base, noise=0.001))
        c.cluster()
        result = get_clusters_for_ui(c, sandbox_folders=["Desktop"])
        assert len(result) == 1
        assert result[0]["face_count"] == 2
        assert all("Desktop" in f["file_path"] for f in result[0]["faces"])

    def test_empty_clusterer(self, temp_db):
        c = FaceClusterer(db_path=temp_db)
        assert get_clusters_for_ui(c) == []

    def test_system_dir_paths_rejected(self, temp_db):
        c = FaceClusterer(db_path=temp_db, eps=0.4, min_samples=2)
        base = _make_embedding(1)
        c.store_embedding("f1", "/etc/passwd", 0, _make_similar_embedding(base, noise=0.001))
        c.store_embedding("f2", "/etc/hosts", 0, _make_similar_embedding(base, noise=0.001))
        c.cluster()
        result = get_clusters_for_ui(c)
        assert len(result) == 1
        result_filtered = get_clusters_for_ui(c, sandbox_folders=["Desktop"])
        assert result_filtered == []
