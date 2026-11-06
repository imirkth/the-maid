"""
The Maid — learning from the user's tree edits.

Every edit the user makes to the draft tree is stored as a rule, and every
later build follows those rules:

- pin:     "these files belong in this folder". Renaming, accepting, merging
           or moving files into a folder pins it. Pinned files are placed
           there on every rebuild and are left out of clustering, so the rest
           of the tree re-sorts around them. Pinned folders also join the
           routing model, so new files can land in them.
- exclude: "leave these files alone". They are left out of the plan.
- rename:  a pinned folder's path changes (and the paths of the folders
           pinned below it).
- unpin:   forget a pin, so the builder decides again.

Rules are keyed by absolute file paths and saved to
~/.the-maid/tree_feedback.json.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

FEEDBACK_PATH = os.path.expanduser("~/.the-maid/tree_feedback.json")
ACTIONS = ("pin", "unpin", "exclude", "include", "rename", "reset")


def clean_folder_path(path: str) -> str:
    """'Work / Clients//Acme ' -> 'Work/Clients/Acme'; refuses '..' tricks."""
    parts = [" ".join(p.split()) for p in str(path or "").replace("\\", "/").split("/")]
    parts = [p[:60] for p in parts if p and p not in (".", "..")]
    return "/".join(parts)


def _abs(paths: Iterable[str]) -> List[str]:
    return [os.path.abspath(p) for p in paths if isinstance(p, str) and p.strip()]


@dataclass
class Feedback:
    pins: Dict[str, str] = field(default_factory=dict)      # abs file path -> "Cat/sub/path"
    excluded: List[str] = field(default_factory=list)       # abs file paths

    # -- queries ------------------------------------------------------------
    def pinned_path(self, file_path: str) -> Optional[str]:
        return self.pins.get(os.path.abspath(file_path)) if file_path else None

    def is_excluded(self, file_path: str) -> bool:
        return bool(file_path) and os.path.abspath(file_path) in set(self.excluded)

    def folders(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for f, folder in self.pins.items():
            out.setdefault(folder, []).append(f)
        return out

    # -- edits ----------------------------------------------------------------
    def apply(self, action: str, files: Iterable[str] = (), path: str = "", new_path: str = "") -> None:
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        files = _abs(files)
        if action == "reset":
            self.pins, self.excluded = {}, []
        elif action == "pin":
            folder = clean_folder_path(path)
            if not folder:
                raise ValueError("pin needs a folder path")
            for f in files:
                self.pins[f] = folder
            self.excluded = [x for x in self.excluded if x not in set(files)]
        elif action == "unpin":
            folder = clean_folder_path(path)
            for f in files:
                self.pins.pop(f, None)
            if folder and not files:   # unpin a whole folder
                self.pins = {f: p for f, p in self.pins.items() if p != folder}
        elif action == "exclude":
            for f in files:
                self.pins.pop(f, None)
                if f not in self.excluded:
                    self.excluded.append(f)
        elif action == "include":
            self.excluded = [x for x in self.excluded if x not in set(files)]
        elif action == "rename":
            old, new = clean_folder_path(path), clean_folder_path(new_path)
            if not old or not new:
                raise ValueError("rename needs path and new_path")
            for f, p in list(self.pins.items()):
                if p == old or p.startswith(old + "/"):
                    self.pins[f] = new + p[len(old):]
            for f in files:          # files in the renamed folder that were not pinned yet
                self.pins.setdefault(f, new)

    def file_moved(self, old: str, new: str) -> None:
        """Keep rules attached to a file after it is moved on disk."""
        old, new = os.path.abspath(old), os.path.abspath(new)
        if old in self.pins:
            self.pins[new] = self.pins.pop(old)
        self.excluded = [new if x == old else x for x in self.excluded]

    # -- persistence --------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {"version": 1, "pins": dict(self.pins), "excluded": list(self.excluded)}

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "Feedback":
        data = data or {}
        pins = data.get("pins") if isinstance(data.get("pins"), dict) else {}
        fb = cls()
        for f, p in pins.items():
            folder = clean_folder_path(p) if isinstance(p, str) else ""
            if isinstance(f, str) and f and folder:
                fb.pins[os.path.abspath(f)] = folder
        fb.excluded = _abs(data.get("excluded") or [] if isinstance(data.get("excluded"), list) else [])
        return fb


def load_feedback(path: str = FEEDBACK_PATH) -> Feedback:
    try:
        with open(path) as fh:
            return Feedback.from_dict(json.load(fh))
    except (OSError, json.JSONDecodeError):
        return Feedback()


def save_feedback(fb: Feedback, path: str = FEEDBACK_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(fb.to_dict(), fh, indent=2)
