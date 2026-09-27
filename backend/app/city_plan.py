"""
Street-level deployment: where inside a city the pumps and barricades go.

The national plan decides how many pumps and barricade sets a city gets; this
places them on the city's 800 m street grid (hotspots.py), using what that grid
knows per cell:

    flood weight   the ensemble's chance the cell floods (live rain), or, when live
                   rain is unavailable, its terrain susceptibility (labelled so)
    arrival        when water is expected in the cell (ensemble ETA)
    assets         named hospitals, schools and underpasses in the cell

Pumps: value = flood weight x (1 + 3 x hospitals + schools) x (0.5 + urban
intensity); a cell takes one pump, a second only where ponding is deep (>= 100 mm)
or two or more hospitals stand, at half value. Barricades: two sets for each named
underpass in a cell likely to flood, then one set per named road in the worst
cells. Units leave the district store at the city centre (0.5 h to load, ~20 km/h
through city traffic) and each placement says whether it beats the water.

For comparison, a terrain-only placement puts the same pumps on the most
susceptible cells regardless of what stands there; the plan reports how many
flood-prone hospitals and schools each approach covers.
"""

from __future__ import annotations

import math

from .travel import haversine_km

CITY_KMH = 20.0
LOAD_H = 0.5
DEEP_MM = 100.0
MIN_FLOOD_W = 0.2


def _n(v) -> int:
    return len(v) if isinstance(v, list) else int(v or 0)


def build(place: dict, hot: dict, static: dict | None, pool: dict, live_rain: bool) -> dict:
    """Assign `pool` = {"pump": n, "barricade": n} to the city's cells."""
    names = {c["k"]: c for c in (static or {}).get("cells", [])}
    cells = []
    for c in hot.get("cells", []):
        if c.get("sea"):
            continue
        s = names.get(c["k"], {})
        flood_w = float(c.get("prob_flood") or 0.0) if live_rain else (c.get("susceptibility") or 0) / 100.0 * 0.6
        dist = haversine_km(place["lat"], place["lon"], c["lat"], c["lon"]) * 1.3
        arrive = round(LOAD_H + dist / CITY_KMH, 1)
        eta = c.get("eta_h")
        roads = [r for r in (s.get("road_names") or []) if r]
        tunnels = [t for t in (c.get("tunnels") or s.get("tunnels") or []) if t]
        cells.append({
            "k": c["k"], "lat": c["lat"], "lon": c["lon"], "flood_w": round(flood_w, 3),
            "susceptibility": c.get("susceptibility"), "ponding_mm": c.get("peak_ponding_mm") or 0.0,
            "eta_h": eta, "arrive_h": arrive, "before_water": eta is None or arrive <= eta,
            "hospitals": c.get("hospitals") or [], "schools": c.get("schools") or [],
            "tunnels": tunnels, "roads": roads, "urban": c.get("urban") or 0.0,
            "label": (tunnels[0] if tunnels else roads[0] if roads else f"cell {c.get('i')},{c.get('j')}"),
        })

    def pump_value(c: dict) -> float:
        return c["flood_w"] * (1 + 3 * _n(c["hospitals"]) + _n(c["schools"])) * (0.5 + c["urban"])

    # ---- pumps: greedy on value with a half-value second unit is optimal here,
    # because each unit's worth depends only on its own cell.
    slots = []
    for c in cells:
        if c["flood_w"] < MIN_FLOOD_W and not (_n(c["hospitals"]) and c["flood_w"] >= MIN_FLOOD_W / 2):
            continue
        v = pump_value(c)
        slots.append((v, c, 1))
        if c["ponding_mm"] >= DEEP_MM or _n(c["hospitals"]) >= 2:
            slots.append((v * 0.5, c, 2))
    slots.sort(key=lambda t: -t[0])
    pumps: dict[int, int] = {}
    for v, c, _ in slots[: pool.get("pump", 0)]:
        pumps[c["k"]] = pumps.get(c["k"], 0) + 1

    # ---- barricades: underpasses first, then named roads in the worst cells
    bslots = []
    for c in sorted(cells, key=lambda c: -c["flood_w"]):
        if c["flood_w"] < MIN_FLOOD_W:
            continue
        for t in c["tunnels"]:
            bslots.append((2.0 * c["flood_w"], c, t, 2))
        for r in c["roads"][:2]:
            bslots.append((c["flood_w"], c, r, 1))
    bslots.sort(key=lambda t: -t[0])
    barricades: list[tuple[dict, str, int]] = []
    left = pool.get("barricade", 0)
    for _, c, what, sets in bslots:
        if left <= 0:
            break
        k = min(sets, left)
        barricades.append((c, what, k))
        left -= k

    by_k = {c["k"]: c for c in cells}
    out = []
    for k, n in sorted(pumps.items(), key=lambda kv: -pump_value(by_k[kv[0]])):
        c = by_k[k]
        facts = []
        if c["hospitals"]:
            facts.append(f"{_n(c['hospitals'])} hospital(s): {', '.join(c['hospitals'][:2])}")
        if c["schools"]:
            facts.append(f"{_n(c['schools'])} school(s)")
        out.append(_row(c, "pump", n, c["label"], facts))
    for c, what, n in barricades:
        out.append(_row(c, "barricade", n, what, ["underpass" if what in c["tunnels"] else "named road"]))

    # ---- terrain-only comparison: the same number of pump cells, chosen by
    # susceptibility alone, assets ignored
    prone = [c for c in cells if (c["susceptibility"] or 0) >= 60]
    terrain_pick = sorted(cells, key=lambda c: -(c["susceptibility"] or 0))[: len(pumps)]
    prone_h = sum(_n(c["hospitals"]) for c in prone)
    prone_s = sum(_n(c["schools"]) for c in prone)
    covered = lambda picks, key: sum(_n(c[key]) for c in picks if (c["susceptibility"] or 0) >= 60)  # noqa: E731
    ours_cells = [by_k[k] for k in pumps]
    quiet = not pumps and not barricades
    return {
        "place_id": place["id"],
        "live_rain": live_rain,
        "note_en": ("No street cell is expected to flood in the next 24 hours: the units stay at the district store, ready."
                    if quiet else None),
        "note_hi": ("अगले 24 घंटों में किसी गली सेल में बाढ़ अपेक्षित नहीं: इकाइयाँ ज़िला भंडार में तैयार रहेंगी।"
                    if quiet else None),
        "pool": pool,
        "assignments": out,
        "summary": {
            "pumps_placed": sum(pumps.values()),
            "barricades_placed": sum(n for _, _, n in barricades),
            "before_water": sum(1 for r in out if r["before_water"]),
            "cells_prone": len(prone),
            "prone_hospitals": prone_h,
            "prone_schools": prone_s,
            "hospitals_covered": covered(ours_cells, "hospitals"),
            "schools_covered": covered(ours_cells, "schools"),
            "terrain_only_hospitals_covered": covered(terrain_pick, "hospitals"),
            "terrain_only_schools_covered": covered(terrain_pick, "schools"),
            "underpasses_closed": sum(1 for c, what, _ in barricades if what in c["tunnels"]),
        },
        "method": {
            "flood_weight": "ensemble flood probability per cell" if live_rain else "terrain susceptibility (live rain unavailable)",
            "pump_value": "flood weight x (1 + 3 x hospitals + schools) x (0.5 + urban intensity)",
            "barricades": "2 sets per flood-prone underpass, then 1 per named road in the worst cells",
            "travel": f"{LOAD_H} h to load at the district store, ~{CITY_KMH:.0f} km/h through the city",
        },
    }


def _row(c: dict, rtype: str, n: int, label: str, facts: list[str]) -> dict:
    eta = c["eta_h"]
    timing_en = (
        f"arrives in ~{c['arrive_h']} h, before water expected in ~{eta:.0f} h" if eta is not None and c["before_water"]
        else f"arrives in ~{c['arrive_h']} h, after water expected in ~{eta:.0f} h" if eta is not None
        else f"arrives in ~{c['arrive_h']} h (no water forecast yet)"
    )
    timing_hi = f"~{c['arrive_h']} घंटे में पहुँच" + (f", पानी ~{eta:.0f} घंटे में" if eta is not None else "")
    w = f"{c['flood_w']:.0%}"
    return {
        "k": c["k"], "lat": c["lat"], "lon": c["lon"], "rtype": rtype, "count": n, "label": label,
        "flood_w": c["flood_w"], "eta_h": eta, "arrive_h": c["arrive_h"], "before_water": c["before_water"],
        "hospitals": c["hospitals"][:3], "schools": c["schools"][:3],
        "why_en": f"{label}: flood weight {w}" + (f"; {'; '.join(facts)}" if facts else "") + f"; {timing_en}.",
        "why_hi": f"{label}: बाढ़ भार {w}; {timing_hi}।",
    }
