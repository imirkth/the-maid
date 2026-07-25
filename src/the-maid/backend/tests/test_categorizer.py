"""Tests for rule-based file categorizer (LLM Routing Stub)."""
import pytest
from pathlib import Path
from the_maid.categorizer import categorize, DEFAULT_RULES, AMBIGUOUS_EXTENSIONS
from the_maid.cleanup_plan import CleanupPlan, CleanupItem


# --- Fixtures ---

def make_scan_result(filename="photo.jpg", path="/home/user/Desktop/photo.jpg", ext=".jpg"):
    return {
        "file_id": "abc123ef",
        "filename": filename,
        "path": path,
        "size_bytes": 5000,
        "modified_time": "2026-07-25T10:00:00",
        "extension": ext,
        "mime_type": "image/jpeg",
    }


def make_scan_results():
    files = [
        ("vacation.jpg", "/home/user/Desktop/vacation.jpg", ".jpg"),
        ("report.pdf", "/home/user/Desktop/report.pdf", ".pdf"),
        ("song.mp3", "/home/user/Desktop/song.mp3", ".mp3"),
        ("video.mp4", "/home/user/Desktop/video.mp4", ".mp4"),
        ("unknown.xyz", "/home/user/Desktop/unknown.xyz", ".xyz"),
        ("data.json", "/home/user/Desktop/data.json", ".json"),
    ]
    results = []
    for i, (name, path, ext) in enumerate(files):
        r = make_scan_result(name, path, ext)
        r["file_id"] = f"{i:08x}"  # unique 8-char hex (00000000, 00000001, ...)
        results.append(r)
    return results


CUSTOM_BUCKETS = [
    {"name": "Pictures", "path": "/home/user/Pictures"},
    {"name": "Documents", "path": "/home/user/Documents"},
    {"name": "Music", "path": "/home/user/Music"},
    {"name": "Videos", "path": "/home/user/Videos"},
    {"name": "Archives", "path": "/home/user/Archives"},
    {"name": "Code", "path": "/home/user/Code"},
]


# --- Basic categorization ---

def test_categorize_returns_cleanup_plan():
    results = [make_scan_result()]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    assert isinstance(plan, CleanupPlan)
    assert len(plan.items) == 1


def test_image_moved_to_pictures():
    results = [make_scan_result("photo.jpg", "/home/user/Desktop/photo.jpg", ".jpg")]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    item = plan.items[0]
    assert item.proposed_action == "move"
    assert item.proposed_path == "/home/user/Pictures/photo.jpg"
    assert "image" in item.proposed_tags
    assert item.confidence == 0.95
    assert "Pictures" in item.rationale


def test_pdf_moved_to_documents():
    results = [make_scan_result("report.pdf", "/home/user/Desktop/report.pdf", ".pdf")]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    item = plan.items[0]
    assert item.proposed_action == "move"
    assert item.proposed_path == "/home/user/Documents/report.pdf"
    assert "document" in item.proposed_tags
    assert item.confidence == 0.95


def test_mp3_moved_to_music():
    results = [make_scan_result("song.mp3", "/home/user/Desktop/song.mp3", ".mp3")]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    item = plan.items[0]
    assert item.proposed_path == "/home/user/Music/song.mp3"
    assert "audio" in item.proposed_tags


def test_mp4_moved_to_videos():
    results = [make_scan_result("clip.mp4", "/home/user/Desktop/clip.mp4", ".mp4")]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    item = plan.items[0]
    assert item.proposed_path == "/home/user/Videos/clip.mp4"


def test_zip_moved_to_archives():
    results = [make_scan_result("backup.zip", "/home/user/Desktop/backup.zip", ".zip")]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    item = plan.items[0]
    assert item.proposed_path == "/home/user/Archives/backup.zip"
    assert "archive" in item.proposed_tags


def test_py_moved_to_code():
    results = [make_scan_result("script.py", "/home/user/Desktop/script.py", ".py")]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    item = plan.items[0]
    assert item.proposed_path == "/home/user/Code/script.py"
    assert "python" in item.proposed_tags


# --- Unknown / ambiguous extensions ---

def test_unknown_extension_tag_only():
    results = [make_scan_result("mystery.xyz", "/home/user/Desktop/mystery.xyz", ".xyz")]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    item = plan.items[0]
    assert item.proposed_action == "tag"
    assert item.proposed_path == item.current_path  # no move
    assert item.confidence == 0.0
    assert "Unknown" in item.rationale


def test_no_extension_tag_only():
    results = [make_scan_result("README", "/home/user/Desktop/README", "")]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    item = plan.items[0]
    assert item.proposed_action == "tag"
    assert item.confidence == 0.0


def test_ambiguous_extension_lower_confidence():
    results = [make_scan_result("data.json", "/home/user/Desktop/data.json", ".json")]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    item = plan.items[0]
    assert item.confidence < 0.9  # ambiguous → lower confidence
    assert item.confidence == 0.60


def test_json_still_moved_to_code():
    results = [make_scan_result("data.json", "/home/user/Desktop/data.json", ".json")]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    item = plan.items[0]
    assert item.proposed_action == "move"
    assert item.proposed_path == "/home/user/Code/data.json"


# --- Missing bucket handling ---

def test_rule_exists_but_no_bucket_configured():
    """If a rule matches but the bucket isn't in the buckets list, fall back to tag-only."""
    partial_buckets = [
        {"name": "Documents", "path": "/home/user/Documents"},
        # No Pictures bucket
    ]
    results = [make_scan_result("photo.jpg", "/home/user/Desktop/photo.jpg", ".jpg")]
    plan = categorize(results, buckets=partial_buckets)
    item = plan.items[0]
    assert item.proposed_action == "tag"
    assert "No bucket configured" in item.rationale


# --- Default buckets (None) ---

def test_default_buckets_used_when_none():
    results = [make_scan_result("photo.jpg", "/home/user/Desktop/photo.jpg", ".jpg")]
    plan = categorize(results, buckets=None)
    item = plan.items[0]
    assert item.proposed_action == "move"
    # Default Pictures bucket is ~/Pictures
    assert "Pictures" in item.proposed_path
    assert "photo.jpg" in item.proposed_path


# --- Empty scan results ---

def test_empty_scan_results():
    plan = categorize([], buckets=CUSTOM_BUCKETS)
    assert isinstance(plan, CleanupPlan)
    assert len(plan.items) == 0


# --- Multiple files ---

def test_multiple_files_different_buckets():
    results = make_scan_results()
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    assert len(plan.items) == 6

    # Each file should have correct action
    actions = {item.original_filename: item.proposed_action for item in plan.items}
    assert actions["vacation.jpg"] == "move"
    assert actions["report.pdf"] == "move"
    assert actions["song.mp3"] == "move"
    assert actions["video.mp4"] == "move"
    assert actions["unknown.xyz"] == "tag"
    assert actions["data.json"] == "move"


def test_all_items_have_valid_file_ids():
    results = make_scan_results()
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    for item in plan.items:
        assert len(item.file_id) == 8
        assert all(c in "0123456789abcdef" for c in item.file_id)


def test_all_items_have_rationale():
    results = make_scan_results()
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    for item in plan.items:
        assert item.rationale  # non-empty


def test_all_items_have_faces_detected_empty():
    results = make_scan_results()
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    for item in plan.items:
        assert item.faces_detected == []  # ADR 0009: empty list, not null


# --- Schema compliance ---

def test_plan_validates_successfully():
    results = make_scan_results()
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    plan.validate()  # should not raise


def test_plan_serializes_to_json():
    results = make_scan_results()
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    json_str = plan.to_json()
    assert '"schema_version"' in json_str
    assert '"items"' in json_str


def test_plan_grouped_by_action():
    results = make_scan_results()
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    groups = plan.grouped_by_action()
    assert "move" in groups
    assert "tag" in groups
    assert len(groups["move"]) == 5  # jpg, pdf, mp3, mp4, json
    assert len(groups["tag"]) == 1   # unknown.xyz


# --- Custom rules ---

def test_custom_rules_override_defaults():
    custom_rules = {
        ".jpg": {"bucket": "Photos", "tags": ["image", "photo"], "confidence": 0.99, "rationale": "Custom: photo to Photos"},
    }
    custom_buckets = [{"name": "Photos", "path": "/home/user/Photos"}]
    results = [make_scan_result("photo.jpg", "/home/user/Desktop/photo.jpg", ".jpg")]
    plan = categorize(results, buckets=custom_buckets, rules=custom_rules)
    item = plan.items[0]
    assert item.proposed_path == "/home/user/Photos/photo.jpg"
    assert item.confidence == 0.99
    assert "Custom" in item.rationale


# --- Case insensitivity ---

def test_uppercase_extension_matched():
    results = [make_scan_result("PHOTO.JPG", "/home/user/Desktop/PHOTO.JPG", ".jpg")]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    item = plan.items[0]
    assert item.proposed_action == "move"
    assert item.proposed_path == "/home/user/Pictures/PHOTO.JPG"


def test_mixed_case_extension_matched():
    results = [make_scan_result("Photo.JpG", "/home/user/Desktop/Photo.JpG", ".jpg")]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    item = plan.items[0]
    assert item.proposed_action == "move"


# --- Filename preservation ---

def test_filename_preserved_in_proposed_path():
    results = [make_scan_result("My Vacation (2024).jpg", "/home/user/Desktop/My Vacation (2024).jpg", ".jpg")]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    item = plan.items[0]
    assert "My Vacation (2024).jpg" in item.proposed_path
    assert item.original_filename == "My Vacation (2024).jpg"


def test_filename_with_spaces_preserved():
    results = [make_scan_result("hello world.txt", "/home/user/Desktop/hello world.txt", ".txt")]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    item = plan.items[0]
    assert "hello world.txt" in item.proposed_path


def test_filename_with_unicode_preserved():
    results = [make_scan_result("café résumé.pdf", "/home/user/Desktop/café résumé.pdf", ".pdf")]
    plan = categorize(results, buckets=CUSTOM_BUCKETS)
    item = plan.items[0]
    assert "café résumé.pdf" in item.proposed_path