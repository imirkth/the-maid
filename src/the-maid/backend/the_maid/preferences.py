"""
The Maid — Personal tree preferences.

A small profile of how the user likes their files organised. It is asked once
(with previews built from the user's own files, see
``TreeArchitect.preview_choices``), saved to ~/.the-maid/preferences.json and
applied to every later tree build.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

PREFERENCES_PATH = os.path.expanduser("~/.the-maid/preferences.json")

# Inside each subject folder: "auto" (just by subject, split by file type only
# when a folder is big and mixed), "year", or "type".
INSIDE_TOPICS = ("auto", "year", "type")
# Photos and videos: by trip/event, or by year > month.
PHOTOS = ("events", "months")
# "detailed": up to 2 levels of subject folders; "shallow": one level.
DEPTH = ("detailed", "shallow")

MAX_AREAS = 8


def _clean_list(values: Any, limit: int) -> List[str]:
    if not isinstance(values, list):
        return []
    out: List[str] = []
    for v in values:
        if isinstance(v, str):
            v = " ".join(v.replace("/", " ").replace("\\", " ").split())[:40]
            if v and v.lower() not in {x.lower() for x in out}:
                out.append(v)
    return out[:limit]


@dataclass
class Preferences:
    inside_topics: str = "auto"
    photos: str = "events"
    depth: str = "detailed"
    areas: List[str] = field(default_factory=list)       # main top-level areas
    protected: List[str] = field(default_factory=list)   # absolute folders never touched
    answered: bool = False                                # user went through the check

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "Preferences":
        data = data or {}
        p = cls()
        if data.get("inside_topics") in INSIDE_TOPICS:
            p.inside_topics = data["inside_topics"]
        if data.get("photos") in PHOTOS:
            p.photos = data["photos"]
        if data.get("depth") in DEPTH:
            p.depth = data["depth"]
        p.areas = _clean_list(data.get("areas"), MAX_AREAS)
        protected = data.get("protected") if isinstance(data.get("protected"), list) else []
        p.protected = [os.path.abspath(x) for x in protected if isinstance(x, str) and x.strip()][:200]
        p.answered = bool(data.get("answered", False))
        return p

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def is_protected(self, path: str) -> bool:
        if not path or not self.protected:
            return False
        p = os.path.abspath(path)
        return any(p == root or p.startswith(root.rstrip(os.sep) + os.sep) for root in self.protected)


def load_preferences(path: str = PREFERENCES_PATH) -> Preferences:
    try:
        with open(path) as fh:
            return Preferences.from_dict(json.load(fh))
    except (OSError, json.JSONDecodeError):
        return Preferences()


def save_preferences(prefs: Preferences, path: str = PREFERENCES_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(prefs.to_dict(), fh, indent=2)
