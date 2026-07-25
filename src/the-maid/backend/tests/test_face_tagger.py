"""
Tests for face_tagger.py — XMP tag writing + cluster UI data.
"""

import pytest
import tempfile
import shutil
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

from the_maid.face_cluster import FaceClusterer
from the_maid.face_tagger import (
    rename_cluster_with_tags,
    get_clusters_for_ui,
    _exiftool_available,
    _write_xmp_tag,
    _clear_xmp_tag,
    _path_in_sandbox,
)
from tests.test_face_cluster import _make_embedding, _make_similar_embedding


# ─── Fixtures ───

@pytest.fixture
def temp_db():
    d = tempfile.mkdtemp(prefix="the-maid-tagger-test-")
    db_path = str(Path(d) / "face-index.db")
    yield db_path
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def clusterer_with_data(temp_db):
    """Clusterer with 2 clusters: 3 similar + 2 similar."""
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


# ─── ExifTool availability ───

class TestExifToolAvailability:
    def test_returns_bool(self):
        result = _exiftool_available()
        assert isinstance(result, bool)


# ─── XMP tag writing (mocked) ───

class TestXMPTagWriting:
    @patch("the_maid.face_tagger._exiftool_available", return_value=True)
    @patch("the_maid.face_tagger._file_exists", return_value=True)
    @patch("the_maid.face_tagger.subprocess.run")
    def test_write_xmp_tag_success(self, mock_run, mock_exists, mock_avail):
        mock_run.return_value = MagicMock(returncode=0)
        result = _write_xmp_tag("/fake/path.jpg", "PersonInImage", "Sarah")
        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "exiftool" in args
        assert "-XMP:PersonInImage=Sarah" in args
        assert "-overwrite_original" in args

    @patch("the_maid.face_tagger._exiftool_available", return_value=False)
    def test_write_xmp_tag_no_exiftool(self, mock_avail):
        result = _write_xmp_tag("/fake/path.jpg", "PersonInImage", "Sarah")
        assert result is False

    @patch("the_maid.face_tagger._exiftool_available", return_value=True)
    @patch("the_maid.face_tagger.subprocess.run")
    def test_write_xmp_tag_failure(self, mock_run, mock_avail):
        mock_run.return_value = MagicMock(returncode=1)
        result = _write_xmp_tag("/fake/path.jpg", "PersonInImage", "Sarah")
        assert result is False

    @patch("the_maid.face_tagger._exiftool_available", return_value=True)
    @patch("the_maid.face_tagger._file_exists", return_value=False)
    def test_write_xmp_tag_file_missing(self, mock_exists, mock_avail):
        result = _write_xmp_tag("/nonexistent.jpg", "PersonInImage", "Sarah")
        assert result is False

    @patch("the_maid.face_tagger._exiftool_available", return_value=True)
    @patch("the_maid.face_tagger.subprocess.run")
    def test_write_xmp_tag_timeout(self, mock_run, mock_avail):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="exiftool", timeout=30)
        result = _write_xmp_tag("/fake/path.jpg", "PersonInImage", "Sarah")
        assert result is False

    @patch("the_maid.face_tagger._exiftool_available", return_value=True)
    @patch("the_maid.face_tagger._file_exists", return_value=True)
    @patch("the_maid.face_tagger.subprocess.run")
    def test_clear_xmp_tag_success(self, mock_run, mock_exists, mock_avail):
        mock_run.return_value = MagicMock(returncode=0)
        result = _clear_xmp_tag("/fake/path.jpg")
        assert result is True
        args = mock_run.call_args[0][0]
        assert "-XMP:PersonInImage=" in args


# ─── rename_cluster_with_tags ───

class TestRenameClusterWithTags:
    @patch("the_maid.face_tagger._write_xmp_tag", return_value=True)
    def test_rename_updates_label_and_tags(self, mock_write, clusterer_with_data):
        result = rename_cluster_with_tags(clusterer_with_data, 0, "Sarah")
        assert result["renamed"] == 3  # 3 faces in cluster 0
        assert result["tagged"] == 3
        assert result["skipped"] == 0
        assert result["errors"] == []
        # Verify label updated in DB
        clusters = clusterer_with_data.get_clusters()
        assert clusters[0]["cluster_label"] == "Sarah"

    @patch("the_maid.face_tagger._write_xmp_tag", return_value=False)
    def test_rename_tag_failure(self, mock_write, clusterer_with_data):
        result = rename_cluster_with_tags(clusterer_with_data, 0, "Sarah")
        assert result["renamed"] == 3
        assert result["tagged"] == 0
        assert result["skipped"] == 3
        assert len(result["errors"]) > 0

    @patch("the_maid.face_tagger._write_xmp_tag", return_value=True)
    def test_rename_nonexistent_cluster(self, mock_write, clusterer_with_data):
        result = rename_cluster_with_tags(clusterer_with_data, 999, "Ghost")
        assert result["renamed"] == 0
        assert result["tagged"] == 0
        assert "Cluster not found" in result["errors"]

    @patch("the_maid.face_tagger._write_xmp_tag", return_value=True)
    def test_rename_with_sandbox_filter(self, mock_write, clusterer_with_data):
        # All paths are /photos/* which is outside default sandbox
        result = rename_cluster_with_tags(
            clusterer_with_data, 0, "Sarah",
            sandbox_folders=["Desktop", "Pictures"]
        )
        assert result["renamed"] == 3  # label still updates in DB
        assert result["tagged"] == 0   # but no XMP writes (outside sandbox)
        assert result["skipped"] == 3
        assert any("sandbox" in e for e in result["errors"])

    @patch("the_maid.face_tagger._write_xmp_tag", return_value=True)
    def test_rename_partial_sandbox(self, mock_write, clusterer_with_data, temp_db):
        """Add two faces in Desktop (cluster) and rename with sandbox filter."""
        base = _make_embedding(55)
        clusterer_with_data.store_embedding(
            "h0", str(Path.home() / "Desktop" / "photo1.jpg"),
            0, base
        )
        clusterer_with_data.store_embedding(
            "h1", str(Path.home() / "Desktop" / "photo2.jpg"),
            0, _make_similar_embedding(base, noise=0.001)
        )
        clusterer_with_data.cluster()
        clusters = clusterer_with_data.get_clusters()
        desk_cluster = [c for c in clusters
                        if any("Desktop" in f["file_path"] for f in c["faces"])]
        if desk_cluster:
            result = rename_cluster_with_tags(
                clusterer_with_data, desk_cluster[0]["cluster_id"], "Bob",
                sandbox_folders=["Desktop"]
            )
            assert result["tagged"] >= 1

    @patch("the_maid.face_tagger._write_xmp_tag", return_value=True)
    def test_rename_empty_label(self, mock_write, clusterer_with_data):
        """Empty label is rejected by the tagger before any DB update."""
        result = rename_cluster_with_tags(clusterer_with_data, 0, "")
        assert result["renamed"] == 0
        assert result["tagged"] == 0
        assert result["skipped"] == 0
        assert any("empty" in e.lower() for e in result["errors"])


# ─── get_clusters_for_ui ───

class TestGetClustersForUI:
    def test_returns_cluster_info(self, clusterer_with_data):
        result = get_clusters_for_ui(clusterer_with_data)
        assert len(result) == 2  # 2 clusters
        assert "cluster_id" in result[0]
        assert "cluster_label" in result[0]
        assert "face_count" in result[0]
        assert "representative_path" in result[0]
        assert "faces" in result[0]

    def test_face_count_correct(self, clusterer_with_data):
        result = get_clusters_for_ui(clusterer_with_data)
        counts = [r["face_count"] for r in result]
        assert 3 in counts  # cluster with 3 faces
        assert 2 in counts  # cluster with 2 faces

    def test_representative_path_is_first_face(self, clusterer_with_data):
        result = get_clusters_for_ui(clusterer_with_data)
        for cluster in result:
            assert cluster["representative_path"] == cluster["faces"][0]["file_path"]

    def test_sandbox_filter_excludes(self, clusterer_with_data):
        """Paths outside sandbox are filtered out."""
        result = get_clusters_for_ui(
            clusterer_with_data,
            sandbox_folders=["Desktop"]
        )
        # All test paths are /photos/* which is outside Desktop
        assert result == []

    def test_sandbox_filter_includes(self, clusterer_with_data, temp_db):
        """Add two faces in Desktop (so they cluster) and check they appear."""
        base = _make_embedding(55)
        clusterer_with_data.store_embedding(
            "h0", str(Path.home() / "Desktop" / "photo1.jpg"),
            0, base
        )
        clusterer_with_data.store_embedding(
            "h1", str(Path.home() / "Desktop" / "photo2.jpg"),
            0, _make_similar_embedding(base, noise=0.001)
        )
        clusterer_with_data.cluster()
        result = get_clusters_for_ui(
            clusterer_with_data,
            sandbox_folders=["Desktop"]
        )
        assert len(result) >= 1
        assert all("Desktop" in f["file_path"] for r in result for f in r["faces"])

    def test_empty_clusterer(self, temp_db):
        c = FaceClusterer(db_path=temp_db)
        result = get_clusters_for_ui(c)
        assert result == []


# ─── _path_in_sandbox ───

class TestPathInSandbox:
    def test_in_sandbox(self):
        assert _path_in_sandbox(str(Path.home() / "Desktop" / "file.jpg"), ["Desktop"])

    def test_outside_sandbox(self):
        assert not _path_in_sandbox("/tmp/random/file.jpg", ["Desktop"])

    def test_system_dir(self):
        assert not _path_in_sandbox("/etc/passwd", ["Desktop"])

    def test_no_sandbox_folders(self):
        """No sandbox list = non-system paths allowed."""
        assert _path_in_sandbox("/tmp/random/file.jpg", None)
        assert not _path_in_sandbox("/etc/passwd", None)