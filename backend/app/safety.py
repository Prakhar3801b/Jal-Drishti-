"""
Practical public-safety advice for an alert: which roads to avoid, safe water,
and what to do - in English and Hindi.

Roads and underpasses to avoid come from the city's street-level grid (the most
flood-prone 800 m cells that have a named road or an underpass). Only a grid that
is already built (bundled seed or cache) is read, so an alert never waits on a
fresh terrain/OpenStreetMap build; without one the advice is general.
"""

from __future__ import annotations

import gzip
import json

from .hotspots import CACHE_DIR, SEED_DIR

MAX_ROUTES = 3


_grids: dict[str, dict] = {}


def _static(location_id: str) -> dict | None:
    """A built grid, remembered once found (a city built later is picked up then)."""
    if location_id in _grids:
        return _grids[location_id]
    path = CACHE_DIR / f"{location_id}.json"
    seed = SEED_DIR / f"{location_id}.json.gz"
    try:
        if path.exists():
            grid = json.loads(path.read_text(encoding="utf-8"))
        elif seed.exists():
            with gzip.open(seed, "rt", encoding="utf-8") as fh:
                grid = json.load(fh)
        else:
            return None
    except (OSError, ValueError):
        return None
    _grids[location_id] = grid
    return grid


def routes_to_avoid(location_id: str) -> list[str]:
    """Underpasses first, then roads in the most flood-prone cells."""
    static = _static(location_id)
    if not static:
        return []
    cells = [c for c in static.get("cells", []) if not c.get("sea")]
    cells.sort(key=lambda c: -(c.get("susceptibility") or 0))
    out: list[str] = []
    for c in cells[:25]:
        for t in c.get("tunnels") or []:
            if t == "Road underpass":
                continue  # unnamed in OpenStreetMap: no use in a message
            label = t if "underpass" in t.lower() or "subway" in t.lower() else f"{t} (underpass)"
            if label not in out:
                out.append(label)
    for c in cells[:25]:
        for r in c.get("road_names") or []:
            if r not in out:
                out.append(r)
    return out[:MAX_ROUTES]


def advice(location_id: str | None, level: str, kind: str) -> dict:
    """Short, actionable steps for residents, most important first."""
    routes = routes_to_avoid(location_id) if location_id else []
    en: list[str] = []
    hi: list[str] = []
    if routes:
        en.append(f"Avoid these roads: {', '.join(routes)}.")
        hi.append(f"इन सड़कों से बचें: {', '.join(routes)}।")
    en.append("Do not walk or drive through flood water — 15 cm of moving water can knock you down, 60 cm can carry a car.")
    hi.append("बाढ़ के पानी में पैदल या वाहन से न जाएँ — 15 सेमी बहता पानी आपको गिरा सकता है, 60 सेमी कार बहा सकता है।")
    if kind in ("wave", "gauge"):
        en.append("Keep away from riverbanks, embankments and bridges over the river.")
        hi.append("नदी किनारों, तटबंधों और नदी पुलों से दूर रहें।")
    en.append("Drink only boiled or chlorinated water; flood water contaminates wells and taps.")
    hi.append("केवल उबला या क्लोरीन मिला पानी पिएँ; बाढ़ का पानी कुएँ व नल दूषित करता है।")
    if level == "red":
        en.append("If told to evacuate, move to higher ground or the nearest relief shelter at once.")
        hi.append("निकासी कहे जाने पर तुरंत ऊँचे स्थान या निकटतम राहत शिविर जाएँ।")
    en.append("Switch off electricity if water enters your home; keep documents, medicines and a charged phone in a waterproof bag.")
    hi.append("घर में पानी आए तो बिजली बंद करें; दस्तावेज़, दवाइयाँ और चार्ज फ़ोन जलरोधी थैले में रखें।")
    en.append("Emergency: 112 · NDMA 1078.")
    hi.append("आपात: 112 · NDMA 1078।")
    return {"routes": routes, "en": en, "hi": hi}
