"""
Full pipeline integration test: detection → clustering → naming → XMP tag write.
Uses mocked FaceDetector to avoid needing insightface/models.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

from the_maid.face_cluster import cluster_faces_from_scan
from the_maid.face_tagger import rename_cluster_with_tags, get_clusters_for_ui
from the_maid.face_cluster import FaceClusterer
from test_face_cluster import _make_embedding, _make_similar_embedding


@pytest.fixture
def temp_db():
    d = tempfile.mkdtemp(prefix="the-maid-face-pipeline-")
    db_path = str(Path(d) / "face-index.db")
    yield db_path
    shutil.rmtree(d, ignore_errors=True)


def _make_scan_results(paths_and_embeddings):
    results = []
    for i, (path, embeddings) in enumerate(paths_and_embeddings):
        ext = Path(path).suffix.lower()
        faces = [
            {"bbox": [0, 0, 50, 50], "confidence": 0.9, "embedding": emb}
            for emb in embeddings
        ]
        results.append({
            "file_id": f"fid{i:05d}",
            "filename": Path(path).name,
            "path": path,
            "extension": ext,
            "size_bytes": 100,
            "faces_detected": faces,
        })
    return results


class TestFullPipeline:
    def test_detect_cluster_rename_pipeline(self, temp_db):
        base = _make_embedding(1)
        other = _make_embedding(99)
        paths_and_embs = [
            ("/tmp/pipeline/photo1.jpg", [base]),
            ("/tmp/pipeline/photo2.jpg", [_make_similar_embedding(base, noise=0.001)]),
            ("/tmp/pipeline/photo3.jpg", [other]),
        ]
        scan = _make_scan_results(paths_and_embs)

        cluster_result = cluster_faces_from_scan(scan, db_path=temp_db)
        assert cluster_result["n_clusters"] == 1
        assert "fid00000" in cluster_result["labels"]
        assert "fid00001" in cluster_result["labels"]
        assert "fid00002" not in cluster_result["labels"]

        clusterer = FaceClusterer(db_path=temp_db)
        clusters = get_clusters_for_ui(clusterer)
        assert len(clusters) == 1
        cluster_id = clusters[0]["cluster_id"]
        assert clusters[0]["face_count"] == 2

        with patch("the_maid.face_tagger._write_xmp_tag", return_value=True) as mock_write:
            result = rename_cluster_with_tags(clusterer, cluster_id, "Sarah")
            assert result["renamed"] == 2
            assert result["tagged"] == 2
            assert result["skipped"] == 0
            written = {c.args[0] for c in mock_write.call_args_list}
            assert written == {"/tmp/pipeline/photo1.jpg", "/tmp/pipeline/photo2.jpg"}
            for c in mock_write.call_args_list:
                assert c.args[2] == "Sarah"

    def test_pipeline_with_faces_per_image(self, temp_db):
        base1 = _make_embedding(1)
        base2 = _make_embedding(99)
        similar1 = _make_similar_embedding(base1, noise=0.001)
        paths_and_embs = [
            ("/tmp/pipeline/group.jpg", [base1, base2]),
            ("/tmp/pipeline/solo.jpg", [similar1]),
        ]
        scan = _make_scan_results(paths_and_embs)
        cluster_result = cluster_faces_from_scan(scan, db_path=temp_db)
        assert cluster_result["n_clusters"] == 1
        assert "fid00000" in cluster_result["labels"]
        assert "fid00001" in cluster_result["labels"]

        clusterer = FaceClusterer(db_path=temp_db)
        clusters = get_clusters_for_ui(clusterer)
        assert len(clusters) == 1
        cluster_id = clusters[0]["cluster_id"]

        with patch("the_maid.face_tagger._write_xmp_tag", return_value=True) as mock_write:
            result = rename_cluster_with_tags(clusterer, cluster_id, "Mom")
            assert result["renamed"] == 2
            assert result["tagged"] == 2
            written = {c.args[0] for c in mock_write.call_args_list}
            assert "/tmp/pipeline/group.jpg" in written
            assert "/tmp/pipeline/solo.jpg" in written

    def test_pipeline_recluster_after_rename_preserves_name(self, temp_db):
        base = _make_embedding(1)
        paths_and_embs = [
            ("/tmp/pipeline/photo1.jpg", [base]),
            ("/tmp/pipeline/photo2.jpg", [_make_similar_embedding(base, noise=0.001)]),
        ]
        scan = _make_scan_results(paths_and_embs)
        cluster_faces_from_scan(scan, db_path=temp_db)

        clusterer = FaceClusterer(db_path=temp_db)
        clusters = get_clusters_for_ui(clusterer)
        cluster_id = clusters[0]["cluster_id"]

        with patch("the_maid.face_tagger._write_xmp_tag", return_value=True):
            rename_cluster_with_tags(clusterer, cluster_id, "Dad")

        clusterer.cluster()
        clusters_after = get_clusters_for_ui(clusterer)
        assert len(clusters_after) == 1
        assert clusters_after[0]["cluster_label"] == "Dad"
