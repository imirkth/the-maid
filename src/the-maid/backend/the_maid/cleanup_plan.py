"""
The Maid — Cleanup Plan Schema (ADR 0009)
The contract between Python backend and Tauri frontend for HITL approval.
"""

import json
import hashlib
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

SCHEMA_VERSION = "1.0.0"

# Valid actions for cleanup plan items
VALID_ACTIONS = {"move", "copy", "tag", "delete", "rename"}

# file_id: 8-char hex (ADR 0009)
FILE_ID_PATTERN = re.compile(r"^[0-9a-f]{8}$")


@dataclass
class CleanupItem:
    """A single proposed file action. All fields required per ADR 0009."""
    file_id: str                        # 8-char hex hash of current_path
    original_filename: str
    current_path: str                   # absolute path at scan time
    proposed_action: str                # move | copy | tag | delete | rename
    proposed_path: str                  # absolute destination path (same as current_path for tag/delete)
    proposed_tags: List[str] = field(default_factory=list)   # IPTC/XMP tags to write
    faces_detected: List[str] = field(default_factory=list) # face cluster IDs, empty if none
    rationale: str = ""                 # LLM explanation for this proposal
    confidence: float = 0.0             # 0.0-1.0
    user_edited_path: Optional[str] = None  # ADR 0005: inline edit override

    def validate(self) -> None:
        """Validate this item. Raises ValueError on invalid data."""
        if not FILE_ID_PATTERN.match(self.file_id):
            raise ValueError(f"file_id must be 8-char hex, got: {self.file_id}")
        if self.proposed_action not in VALID_ACTIONS:
            raise ValueError(f"proposed_action must be one of {VALID_ACTIONS}, got: {self.proposed_action}")
        if not self.current_path:
            raise ValueError("current_path is required")
        if not self.proposed_path:
            raise ValueError("proposed_path is required")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be 0-1, got: {self.confidence}")
        # proposed_path required for move/copy/rename; for tag/delete it equals current_path
        if self.proposed_action in ("move", "copy", "rename") and self.proposed_path == self.current_path:
            raise ValueError(f"proposed_path must differ from current_path for {self.proposed_action}")

    def to_dict(self) -> dict:
        d = asdict(self)
        # ADR 0009: no nulls — omit user_edited_path if None
        if d["user_edited_path"] is None:
            d.pop("user_edited_path")
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CleanupItem":
        return cls(
            file_id=d["file_id"],
            original_filename=d["original_filename"],
            current_path=d["current_path"],
            proposed_action=d["proposed_action"],
            proposed_path=d["proposed_path"],
            proposed_tags=d.get("proposed_tags", []),
            faces_detected=d.get("faces_detected", []),
            rationale=d.get("rationale", ""),
            confidence=d.get("confidence", 0.0),
            user_edited_path=d.get("user_edited_path"),
        )


@dataclass
class CleanupPlan:
    """A full cleanup plan — grouped items for batch approval."""
    schema_version: str = SCHEMA_VERSION
    scan_timestamp: str = ""            # ISO 8601 when scan ran
    items: List[CleanupItem] = field(default_factory=list)

    def validate(self) -> None:
        """Validate all items and check for duplicate file_ids."""
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {SCHEMA_VERSION}, got {self.schema_version}")
        seen_ids = set()
        for item in self.items:
            item.validate()
            if item.file_id in seen_ids:
                raise ValueError(f"Duplicate file_id: {item.file_id}")
            seen_ids.add(item.file_id)

    def grouped_by_action(self) -> dict:
        """Group items by proposed_action for batch approval UI."""
        groups: dict[str, list[dict]] = {}
        for item in self.items:
            groups.setdefault(item.proposed_action, []).append(item.to_dict())
        return groups

    def approved_items(self, approved_file_ids: set[str]) -> List[CleanupItem]:
        """Return only items whose file_id is in the approved set."""
        return [item for item in self.items if item.file_id in approved_file_ids]

    def to_json(self) -> str:
        """Serialize to JSON for IPC."""
        return json.dumps({
            "schema_version": self.schema_version,
            "scan_timestamp": self.scan_timestamp,
            "items": [item.to_dict() for item in self.items],
        }, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "CleanupPlan":
        """Deserialize from JSON."""
        d = json.loads(json_str)
        return cls(
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            scan_timestamp=d.get("scan_timestamp", ""),
            items=[CleanupItem.from_dict(item) for item in d.get("items", [])],
        )

    @classmethod
    def from_scan_results(cls, scan_results: list[dict], scan_timestamp: str = "") -> "CleanupPlan":
        """
        Build a CleanupPlan from scanner output.
        Scanner returns metadata dicts; this wraps them as CleanupItems with default action 'tag'.
        """
        items = []
        for f in scan_results:
            items.append(CleanupItem(
                file_id=f["file_id"],
                original_filename=f["filename"],
                current_path=f["path"],
                proposed_action="tag",  # ponytail: default action is tag (least invasive)
                proposed_path=f["path"],  # same path for tag-only
                proposed_tags=[],
                faces_detected=[],
                rationale="Pending AI categorization",
                confidence=0.0,
            ))
        return cls(scan_timestamp=scan_timestamp, items=items)


def generate_file_id(current_path: str) -> str:
    """Generate 8-char hex file_id from path (ADR 0009)."""
    return hashlib.sha256(current_path.encode()).hexdigest()[:8]