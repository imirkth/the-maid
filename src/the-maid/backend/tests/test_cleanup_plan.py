"""Tests for CleanupPlan schema (ADR 0009) — validation, serialization, edge cases."""
import json
import pytest
from the_maid.cleanup_plan import (
    CleanupItem, CleanupPlan, SCHEMA_VERSION, generate_file_id,
    VALID_ACTIONS, FILE_ID_PATTERN,
)


# --- Fixtures ---

def make_item(**overrides) -> CleanupItem:
    defaults = dict(
        file_id="abc123ef",
        original_filename="test.txt",
        current_path="/home/user/Desktop/test.txt",
        proposed_action="move",
        proposed_path="/home/user/Documents/test.txt",
        proposed_tags=["work"],
        faces_detected=[],
        rationale="Moved to Documents",
        confidence=0.85,
    )
    defaults.update(overrides)
    return CleanupItem(**defaults)


def make_plan(items=None) -> CleanupPlan:
    return CleanupPlan(scan_timestamp="2026-07-25T10:00:00", items=items or [make_item()])


# --- CleanupItem validation ---

def test_valid_item_passes_validation():
    item = make_item()
    item.validate()  # should not raise


def test_invalid_file_id_rejected():
    item = make_item(file_id="short")
    with pytest.raises(ValueError, match="file_id must be 8-char hex"):
        item.validate()


def test_invalid_file_id_non_hex_rejected():
    item = make_item(file_id="xyz12345")  # not hex
    with pytest.raises(ValueError, match="file_id must be 8-char hex"):
        item.validate()


def test_invalid_action_rejected():
    item = make_item(proposed_action="compress")
    with pytest.raises(ValueError, match="proposed_action"):
        item.validate()


def test_confidence_below_zero_rejected():
    item = make_item(confidence=-0.1)
    with pytest.raises(ValueError, match="confidence"):
        item.validate()


def test_confidence_above_one_rejected():
    item = make_item(confidence=1.5)
    with pytest.raises(ValueError, match="confidence"):
        item.validate()


def test_confidence_boundary_zero_ok():
    item = make_item(confidence=0.0)
    item.validate()  # should not raise


def test_confidence_boundary_one_ok():
    item = make_item(confidence=1.0)
    item.validate()  # should not raise


def test_move_must_have_different_path():
    item = make_item(proposed_action="move", proposed_path="/home/user/Desktop/test.txt")
    with pytest.raises(ValueError, match="proposed_path must differ"):
        item.validate()


def test_tag_same_path_ok():
    item = make_item(proposed_action="tag", proposed_path=make_item().current_path)
    item.validate()  # should not raise


def test_delete_same_path_ok():
    item = make_item(proposed_action="delete", proposed_path=make_item().current_path)
    item.validate()  # should not raise


def test_empty_current_path_rejected():
    item = make_item(current_path="")
    with pytest.raises(ValueError, match="current_path is required"):
        item.validate()


def test_empty_proposed_path_rejected():
    item = make_item(proposed_path="")
    with pytest.raises(ValueError, match="proposed_path is required"):
        item.validate()


# --- Serialization ---

def test_item_to_dict_omits_none_user_edited_path():
    item = make_item()
    d = item.to_dict()
    assert "user_edited_path" not in d  # None omitted per ADR 0009


def test_item_to_dict_includes_user_edited_path_when_set():
    item = make_item(user_edited_path="/custom/path.txt")
    d = item.to_dict()
    assert d["user_edited_path"] == "/custom/path.txt"


def test_item_roundtrip_json():
    item = make_item()
    d = item.to_dict()
    restored = CleanupItem.from_dict(d)
    assert restored == item


def test_item_roundtrip_json_with_edited_path():
    item = make_item(user_edited_path="/edited.txt")
    d = item.to_dict()
    restored = CleanupItem.from_dict(d)
    assert restored.user_edited_path == "/edited.txt"


# --- CleanupPlan ---

def test_plan_validates_all_items():
    plan = make_plan([make_item(), make_item(file_id="deadbeef")])
    plan.validate()  # should not raise


def test_plan_rejects_duplicate_file_ids():
    plan = make_plan([make_item(file_id="abc123ef"), make_item(file_id="abc123ef")])
    with pytest.raises(ValueError, match="Duplicate file_id"):
        plan.validate()


def test_plan_rejects_wrong_schema_version():
    plan = CleanupPlan(schema_version="2.0.0", items=[make_item()])
    with pytest.raises(ValueError, match="schema_version"):
        plan.validate()


def test_plan_to_json_contains_all_fields():
    plan = make_plan()
    j = json.loads(plan.to_json())
    assert j["schema_version"] == SCHEMA_VERSION
    assert j["scan_timestamp"] == "2026-07-25T10:00:00"
    assert len(j["items"]) == 1
    assert j["items"][0]["file_id"] == "abc123ef"


def test_plan_to_json_omits_none_user_edited_path():
    plan = make_plan()
    j = json.loads(plan.to_json())
    assert "user_edited_path" not in j["items"][0]


def test_plan_from_json_roundtrip():
    plan = make_plan([make_item(), make_item(file_id="deadbeef")])
    json_str = plan.to_json()
    restored = CleanupPlan.from_json(json_str)
    assert restored.schema_version == plan.schema_version
    assert restored.scan_timestamp == plan.scan_timestamp
    assert len(restored.items) == 2
    assert restored.items[0].file_id == "abc123ef"
    assert restored.items[1].file_id == "deadbeef"


def test_plan_empty_items_ok():
    plan = CleanupPlan(items=[])
    plan.validate()  # should not raise


def test_plan_grouped_by_action():
    plan = make_plan([
        make_item(file_id="abc123ef", proposed_action="move"),
        make_item(file_id="deadbeef", proposed_action="move"),
        make_item(file_id="cafe1234", proposed_action="tag"),
        make_item(file_id="babe5678", proposed_action="delete"),
    ])
    groups = plan.grouped_by_action()
    assert len(groups["move"]) == 2
    assert len(groups["tag"]) == 1
    assert len(groups["delete"]) == 1
    assert "copy" not in groups


def test_plan_approved_items_filter():
    plan = make_plan([
        make_item(file_id="abc123ef"),
        make_item(file_id="deadbeef"),
        make_item(file_id="cafe1234"),
    ])
    approved = plan.approved_items({"abc123ef", "cafe1234"})
    assert len(approved) == 2
    assert approved[0].file_id == "abc123ef"
    assert approved[1].file_id == "cafe1234"


# --- from_scan_results ---

def test_from_scan_results_creates_plan():
    scan_results = [
        {
            "file_id": "abc123ef",
            "filename": "test.txt",
            "path": "/home/user/Desktop/test.txt",
            "size_bytes": 100,
            "modified_time": "2026-07-25T10:00:00",
            "extension": ".txt",
            "mime_type": "text/plain",
        },
        {
            "file_id": "deadbeef",
            "filename": "photo.jpg",
            "path": "/home/user/Desktop/photo.jpg",
            "size_bytes": 5000,
            "modified_time": "2026-07-25T10:01:00",
            "extension": ".jpg",
            "mime_type": "image/jpeg",
        },
    ]
    plan = CleanupPlan.from_scan_results(scan_results, scan_timestamp="2026-07-25T10:00:00")
    assert len(plan.items) == 2
    assert plan.items[0].file_id == "abc123ef"
    assert plan.items[0].proposed_action == "tag"  # default least-invasive
    assert plan.items[0].proposed_path == "/home/user/Desktop/test.txt"  # same path for tag
    assert plan.items[0].faces_detected == []
    assert plan.items[0].confidence == 0.0
    assert plan.scan_timestamp == "2026-07-25T10:00:00"


# --- generate_file_id ---

def test_generate_file_id_is_8_hex_chars():
    fid = generate_file_id("/some/path/file.txt")
    assert len(fid) == 8
    assert FILE_ID_PATTERN.match(fid)


def test_generate_file_id_deterministic():
    path = "/home/user/Desktop/test.txt"
    assert generate_file_id(path) == generate_file_id(path)


def test_generate_file_id_different_paths_different_ids():
    id1 = generate_file_id("/path/a.txt")
    id2 = generate_file_id("/path/b.txt")
    assert id1 != id2


# --- All valid actions have items ---

def test_all_valid_actions_can_be_validated():
    for action in VALID_ACTIONS:
        if action in ("move", "copy", "rename"):
            item = make_item(proposed_action=action, proposed_path="/different/path.txt")
        else:
            item = make_item(proposed_action=action, proposed_path=make_item().current_path)
        item.validate()  # should not raise


# --- Empty lists per ADR 0009 (no nulls) ---

def test_empty_tags_and_faces_are_empty_lists_not_none():
    item = make_item(proposed_tags=[], faces_detected=[])
    d = item.to_dict()
    assert d["proposed_tags"] == []
    assert d["faces_detected"] == []


def test_plan_to_json_empty_lists_preserved():
    item = make_item(proposed_tags=[], faces_detected=[])
    plan = CleanupPlan(items=[item])
    j = json.loads(plan.to_json())
    assert j["items"][0]["proposed_tags"] == []
    assert j["items"][0]["faces_detected"] == []