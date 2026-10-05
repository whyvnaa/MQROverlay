"""Zone maps exported by the MonkeyQuest knowledge base (scripts/export_overlay.py there) into data/."""

import json
from pathlib import Path

# in an installed copy (uvx) the data sits inside the package; in a clone it is the repo's data/ folder
_HERE = Path(__file__).resolve().parent
DATA = _HERE / "data" if (_HERE / "data" / "index.json").exists() else _HERE.parents[1] / "data"


def marker_matches(m: dict, query: str) -> bool:
    """query: lower case. Matches the marker's tooltip (enemy, NPC, portal target, ...) or anything it drops."""
    return query in m["tip"].lower() or any(query in d[0].lower() for d in m.get("drops", ()))


class GameData:
    def __init__(self, root: Path = DATA):
        self.root = root
        index = json.loads((root / "index.json").read_text(encoding="utf-8"))
        self.wiki = index["wiki"]
        self.categories = index["categories"]
        self.shapes = index["shapes"]
        self.zones = {z["name"].lower(): z for z in index["zones"]}
        self._loaded: dict[str, dict] = {}

    def zone(self, name: str | None) -> dict | None:
        """A zone's map by its level name (LV_CRS_Trail01, any case), or None if there is no map for it."""
        meta = self.zones.get((name or "").lower())
        if not meta:
            return None
        key = meta["name"].lower()
        if key not in self._loaded:
            self._loaded[key] = json.loads((self.root / "zones" / meta["file"]).read_text(encoding="utf-8"))
        return self._loaded[key]

    def search(self, query: str) -> list[tuple[dict, int]]:
        """Every zone with markers matching query (case-insensitive), most matches first: [(zone meta, count)]."""
        q = query.strip().lower()
        if not q:
            return []
        hits = []
        for meta in self.zones.values():
            n = sum(marker_matches(m, q) for m in self.zone(meta["name"])["markers"])
            if n:
                hits.append((meta, n))
        return sorted(hits, key=lambda h: (-h[1], h[0]["title"] or ""))

    def art(self, rel: str) -> Path:
        return self.root / "art" / rel
