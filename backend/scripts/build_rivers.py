"""
Build the India river network layer used by the Rivers page.

Source: Natural Earth 1:10m "rivers_lake_centerlines" (public domain), clipped to
India's boundary (+15 km so border rivers keep their Indian reach), with names
normalised to the forms used by CWC and Indian readers (Ganges -> Ganga,
Godävari -> Godavari, Tista -> Teesta ...).

Writes the same file to the backend (gauge assignment) and the frontend (drawing):
    backend/app/data/india_rivers.geojson
    frontend/public/geo/india-rivers.geojson

    python backend/scripts/build_rivers.py path/to/ne_10m_rivers_lake_centerlines.geojson
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from shapely.geometry import MultiLineString, mapping, shape
from shapely.ops import linemerge, unary_union

ROOT = Path(__file__).resolve().parents[2]
STATES = ROOT / "frontend" / "public" / "geo" / "india-states.geojson"
OUTS = [ROOT / "backend" / "app" / "data" / "india_rivers.geojson", ROOT / "frontend" / "public" / "geo" / "india-rivers.geojson"]

NAMES = {
    "Ganges": ("Ganga", "गंगा"),
    "Yamuna": ("Yamuna", "यमुना"),
    "Brahmaputra": ("Brahmaputra", "ब्रह्मपुत्र"),
    "Dihang": ("Siang (Brahmaputra)", "सियांग"),
    "Luhit": ("Lohit", "लोहित"),
    "Godävari": ("Godavari", "गोदावरी"),
    "Krishna": ("Krishna", "कृष्णा"),
    "Narmada": ("Narmada", "नर्मदा"),
    "Mahäna Nadï": ("Mahanadi", "महानदी"),
    "Cauvery": ("Kaveri", "कावेरी"),
    "Kolidam": ("Kollidam", "कोल्लिडम"),
    "Chambal": ("Chambal", "चंबल"),
    "Betwa": ("Betwa", "बेतवा"),
    "Son": ("Son", "सोन"),
    "Gandak": ("Gandak", "गंडक"),
    "Ghäghara": ("Ghaghara", "घाघरा"),
    "Sapt": ("Kosi (Sapt Kosi)", "कोसी"),
    "Tista": ("Teesta", "तीस्ता"),
    "Tapi": ("Tapi", "तापी"),
    "Mahi": ("Mahi", "माही"),
    "Sabarmati": ("Sabarmati", "साबरमती"),
    "Bhima": ("Bhima", "भीमा"),
    "Tungabhadra": ("Tungabhadra", "तुंगभद्रा"),
    "Penner": ("Pennar", "पेन्नार"),
    "Palar": ("Palar", "पालार"),
    "Wainganga": ("Wainganga", "वैनगंगा"),
    "Indravati": ("Indravati", "इंद्रावती"),
    "Brahmani": ("Brahmani", "ब्राह्मणी"),
    "Sankh": ("Sankh", "शंख"),
    "Tel": ("Tel", "तेल"),
    "Banas": ("Banas", "बनास"),
    "Indus": ("Indus", "सिंधु"),
    "Jhelum": ("Jhelum", "झेलम"),
    "Chenab": ("Chenab", "चिनाब"),
    "Ravi": ("Ravi", "रावी"),
    "Beas": ("Beas", "ब्यास"),
    "Sutlej": ("Sutlej", "सतलुज"),
    "Parbati": ("Parbati", "पार्वती"),
    "Balak": ("Balak", "बालक"),
    "Dam": ("Damodar", "दामोदर"),
}


def main(src: str) -> None:
    states = json.loads(STATES.read_text(encoding="utf-8"))
    india = unary_union([shape(f["geometry"]).buffer(0) for f in states["features"]]).buffer(0.14)

    raw = json.loads(Path(src).read_text(encoding="utf-8"))
    parts = defaultdict(list)
    weight = defaultdict(float)
    for f in raw["features"]:
        props = f["properties"]
        name = props.get("name_en") or props.get("name")
        if name not in NAMES:
            continue
        g = shape(f["geometry"])
        if not g.intersects(india):
            continue
        clipped = g.intersection(india)
        if clipped.is_empty:
            continue
        lines = [clipped] if clipped.geom_type == "LineString" else [x for x in getattr(clipped, "geoms", []) if x.geom_type == "LineString"]
        parts[name].extend(lines)
        weight[name] = max(weight[name], float(props.get("strokeweig") or 1.0))

    features = []
    for name, lines in parts.items():
        merged = linemerge(MultiLineString(lines))
        merged = merged.simplify(0.004, preserve_topology=False)
        geoms = [merged] if merged.geom_type == "LineString" else list(merged.geoms)
        geoms = [g for g in geoms if g.length > 0.05]  # drop sub-5 km slivers from clipping
        if not geoms:
            continue
        en, hi = NAMES[name]
        features.append(
            {
                "type": "Feature",
                "properties": {"name": en, "name_hi": hi, "source_name": name, "weight": round(weight[name], 2)},
                "geometry": mapping(MultiLineString(geoms)),
            }
        )

    features.sort(key=lambda f: -f["properties"]["weight"])
    out = {
        "type": "FeatureCollection",
        "source": "Natural Earth 1:10m rivers_lake_centerlines (public domain), clipped to India",
        "features": features,
    }
    for path in OUTS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(features)} rivers -> {OUTS[0].stat().st_size // 1024} KB")
    print(", ".join(f["properties"]["name"] for f in features))


if __name__ == "__main__":
    main(sys.argv[1])
