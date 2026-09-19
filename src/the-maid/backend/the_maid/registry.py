"""
The Maid — Category Registry
Persistent memory of the category hierarchy across scans.
Grows over time as new categories/subcategories are discovered.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from difflib import SequenceMatcher

REGISTRY_PATH = os.path.expanduser("~/.the-maid/category_registry.json")


def _similarity(a: str, b: str) -> float:
    if a.lower() == b.lower():
        return 1.0
    a_l, b_l = a.lower(), b.lower()
    if a_l in b_l or b_l in a_l:
        return 0.85
    return SequenceMatcher(None, a_l, b_l).ratio()


class CategoryRegistry:
    """
    Persistent category tree registry.
    
    Structure:
    {
        "categories": {
            "Law": {
                "subcategories": ["Contract", "Tort", "Criminal"],
                "file_count": 15
            },
            "Cryptocurrency": {
                "subcategories": ["Wallets", "Trading", "Mining"],
                "file_count": 8
            }
        },
        "version": 1
    }
    """

    def __init__(self, path: str = REGISTRY_PATH):
        self.path = path
        self._data: Dict[str, Any] = {"categories": {}, "version": 1}
        self.load()

    def load(self):
        try:
            with open(self.path, "r") as f:
                self._data = json.load(f)
        except (OSError, json.JSONDecodeError):
            self._data = {"categories": {}, "version": 1}

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2)

    def get_categories(self) -> List[str]:
        return sorted(self._data.get("categories", {}).keys())

    def get_subcategories(self, category: str) -> List[str]:
        cat = self._find_category(category)
        if cat:
            return cat.get("subcategories", [])
        return []

    def _find_category(self, name: str) -> Optional[Dict[str, Any]]:
        cats = self._data.get("categories", {})
        # Exact match first
        if name in cats:
            return cats[name]
        # Fuzzy match
        for existing in cats:
            if _similarity(name, existing) >= 0.85:
                return cats[existing]
        return None

    def register(self, category: str, subcategory: str = "", file_count: int = 0):
        """Register a category/subcategory pair. Merges with existing if similar."""
        cats = self._data.setdefault("categories", {})
        
        # Find or create the category
        existing = self._find_category(category)
        if existing:
            # Use the existing name (merge)
            existing_name = next(k for k, v in cats.items() if v is existing)
            cat_obj = existing
        else:
            cats[category] = {"subcategories": [], "file_count": 0}
            existing_name = category
            cat_obj = cats[category]
        
        cat_obj["file_count"] = cat_obj.get("file_count", 0) + file_count
        
        if subcategory:
            subs = cat_obj.setdefault("subcategories", [])
            # Find or add subcategory (fuzzy)
            found = False
            for s in subs:
                if _similarity(subcategory, s) >= 0.85:
                    found = True
                    break
            if not found:
                subs.append(subcategory)
                subs.sort()
        
        self.save()

    def register_from_tree(self, tree: List[Dict[str, Any]]):
        """Register all categories/subcategories from a result tree."""
        for node in tree:
            cat = node.get("category", "Uncategorized")
            subs = node.get("subbuckets", [])
            sub_names = [s.get("subcategory", "") for s in subs if s.get("subcategory")]
            file_count = sum(len(s.get("files", [])) for s in subs)
            
            if sub_names:
                for sn in sub_names:
                    self.register(cat, sn, 0)
                self.register(cat, "", file_count)
            else:
                self.register(cat, "", file_count)

    def build_hint(self) -> str:
        """Build a hint string for the LLM prompt showing known hierarchy."""
        cats = self._data.get("categories", {})
        if not cats:
            return ""
        
        lines = []
        for cat_name, cat_data in sorted(cats.items(), key=lambda x: -x[1].get("file_count", 0)):
            subs = cat_data.get("subcategories", [])
            if subs:
                lines.append(f"  {cat_name} > {' | '.join(subs)}")
            else:
                lines.append(f"  {cat_name}")
        
        return "Known category hierarchy (reuse these when appropriate):\n" + "\n".join(lines)