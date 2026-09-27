"""
River network status: CWC gauges placed along India's rivers.

For each river line (Natural Earth, clipped to India) this module:

  1. attaches every catalogued CWC gauge within GAUGE_SNAP_KM of the line and
     measures its chainage (km along the line),
  2. orients the line upstream -> downstream using the gauges' own danger levels,
     which are reduced levels in metres above mean sea level and therefore fall
     downstream (Ballia 57.6 m -> Patna 48.6 m -> Farakka 22.3 m on the Ganga).
     With fewer than two datum points the direction is reported as unknown and
     the UI does not animate flow rather than guess,
  3. splits the line at the gauges into reaches, each coloured by the worse
     status of the gauges bounding it. Beyond the first and last gauge a reach
     is "unmonitored" - it is never painted safe just because nothing measures it.

A per-river longitudinal profile (level minus danger mark, upstream to downstream)
is returned too: it shows where along a river the flood wave currently sits.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache

from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import substring

from .config import DATA_DIR
from .official import official

log = logging.getLogger("jaldrishti.rivers")

RIVERS_PATH = DATA_DIR / "india_rivers.geojson"
GAUGE_SNAP_KM = 8.0
KM_PER_DEG = 111.0
EXTEND_KM = 25.0  # how far a gauge's status is carried past the first/last gauge

STATUS_RANK = {"DANGER": 3, "WARNING": 2, "NORMAL": 1, "UNMONITORED": 0}


@lru_cache(maxsize=1)
def _rivers() -> list[dict]:
    if not RIVERS_PATH.exists():
        return []
    gj = json.loads(RIVERS_PATH.read_text(encoding="utf-8"))
    out = []
    for f in gj["features"]:
        geom = shape(f["geometry"])
        parts = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
        out.append({**f["properties"], "parts": parts})
    return out


def _worse(a: str, b: str) -> str:
    return a if STATUS_RANK[a] >= STATUS_RANK[b] else b


def network_status() -> dict:
    rivers = _rivers()
    gauges = [official.station_status(code) for code in official.catalog]

    # Assign each gauge to the single nearest river part within the snap radius.
    assigned: dict[tuple[int, int], list[dict]] = {}
    for g in gauges:
        pt = Point(g["lon"], g["lat"])
        best, best_d = None, GAUGE_SNAP_KM / KM_PER_DEG
        for ri, r in enumerate(rivers):
            for pi, part in enumerate(r["parts"]):
                d = part.distance(pt)
                if d < best_d:
                    best, best_d = (ri, pi), d
        if best:
            part = rivers[best[0]]["parts"][best[1]]
            assigned.setdefault(best, []).append(
                {**g, "chainage_deg": part.project(pt), "offset_km": round(best_d * KM_PER_DEG, 1)}
            )

    features, summaries = [], []
    for ri, r in enumerate(rivers):
        river_counts = {"DANGER": 0, "WARNING": 0, "NORMAL": 0}
        profile = []
        oriented_any = False
        for pi, part in enumerate(r["parts"]):
            gs = sorted(assigned.get((ri, pi), []), key=lambda x: x["chainage_deg"])

            # Orientation: danger levels are metres above MSL and fall downstream.
            datum = [(x["chainage_deg"], x["danger_level"]) for x in gs if x.get("danger_level")]
            direction = "unknown"
            if len(datum) >= 2:
                n = len(datum)
                mx = sum(c for c, _ in datum) / n
                my = sum(v for _, v in datum) / n
                cov = sum((c - mx) * (v - my) for c, v in datum)
                if cov > 0:  # datum rises along the line -> line is drawn downstream->upstream
                    part = LineString(list(part.coords)[::-1])
                    L = part.length
                    for x in gs:
                        x["chainage_deg"] = L - x["chainage_deg"]
                    gs.reverse()
                direction = "downstream"
                oriented_any = True

            L = part.length
            ext = EXTEND_KM / KM_PER_DEG
            cuts: list[tuple[float, float, str]] = []
            if not gs:
                cuts.append((0.0, L, "UNMONITORED"))
            else:
                first, last = gs[0], gs[-1]
                if first["chainage_deg"] > 0:
                    a = max(0.0, first["chainage_deg"] - ext)
                    if a > 0:
                        cuts.append((0.0, a, "UNMONITORED"))
                    cuts.append((a, first["chainage_deg"], first["status"]))
                for x, y in zip(gs, gs[1:]):
                    cuts.append((x["chainage_deg"], y["chainage_deg"], _worse(x["status"], y["status"])))
                if last["chainage_deg"] < L:
                    b = min(L, last["chainage_deg"] + ext)
                    cuts.append((last["chainage_deg"], b, last["status"]))
                    if b < L:
                        cuts.append((b, L, "UNMONITORED"))

            for a, b, status in cuts:
                if b - a < 1e-4:
                    continue
                seg = substring(part, a, b)
                if seg.is_empty or seg.geom_type != "LineString":
                    continue
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "river": r["name"],
                            "river_hi": r["name_hi"],
                            "status": status,
                            "direction": direction,
                        },
                        "geometry": mapping(seg),
                    }
                )

            for x in gs:
                river_counts[x["status"]] = river_counts.get(x["status"], 0) + 1
                vs = x.get("above_danger_m")
                # A reading tens of metres off its own danger mark is a datum
                # mismatch in the source (gauge zero vs mean sea level), not a flood.
                datum_suspect = vs is not None and abs(vs) > 25
                if x.get("danger_level") is not None and not datum_suspect:
                    profile.append(
                        {
                            "code": x["code"],
                            "name": x["name"],
                            "state": x.get("state"),
                            "part": pi,
                            "chainage_km": round(x["chainage_deg"] * KM_PER_DEG),
                            "status": x["status"],
                            "level_m": x.get("level_m"),
                            "danger_level": x["danger_level"],
                            "warning_level": x.get("warning_level"),
                            "vs_danger_m": x.get("above_danger_m"),
                            "trend": x.get("trend"),
                        }
                    )

        worst = "DANGER" if river_counts["DANGER"] else "WARNING" if river_counts["WARNING"] else "NORMAL" if river_counts["NORMAL"] else "UNMONITORED"
        profile.sort(key=lambda p: (p["part"], p["chainage_km"]))
        summaries.append(
            {
                "name": r["name"],
                "name_hi": r["name_hi"],
                "status": worst,
                "gauges": sum(river_counts.values()),
                "counts": river_counts,
                "direction_known": oriented_any,
                "profile": profile,
            }
        )

    summaries.sort(key=lambda s: (-STATUS_RANK[s["status"]], -s["counts"]["DANGER"], -s["counts"]["WARNING"], -s["gauges"]))
    return {
        "fetched_at": official.fetched_at,
        "gauges_on_rivers": sum(s["gauges"] for s in summaries),
        "rivers": summaries,
        "reaches": {"type": "FeatureCollection", "features": features},
        "method": (
            "CWC gauges within 8 km of a Natural Earth river line are placed by chainage; "
            "reaches between gauges take the worse status of the two; flow direction is "
            "inferred from gauge danger levels (m above MSL), which fall downstream."
        ),
    }


# ------------------------------------------------------ downstream propagation

# A flood wave on a large Indian river typically travels 2.5-7 km/h (roughly
# 0.7-2 m/s); the spread is wide because reach slope, channel shape, embankment
# breaches and dam releases all change it. The range is reported, not a point.
CELERITY_KMH = (7.0, 4.0, 2.5)  # fast, typical, slow -> p10, p50, p90 arrival
TOWN_SNAP_KM = 15.0
LOCAL_GAUGE_KM = 5.0  # a gauge this close is the town's own gauge, not upstream
MAX_UPSTREAM_KM = 600.0
LONG_REACH_KM = 250.0

_placed_cache: dict = {"key": None, "parts": []}


def _placed_parts() -> list[dict]:
    """
    River parts oriented upstream -> downstream with their gauges' chainage in km.
    Geometry and danger marks are static, so this is computed once per catalogue.
    """
    key = len(official.catalog)
    if _placed_cache["key"] == key:
        return _placed_cache["parts"]
    rivers = _rivers()
    assigned: dict[tuple[int, int], list[dict]] = {}
    for code, g in official.catalog.items():
        if g.get("lat") is None or g.get("lon") is None:
            continue
        pt = Point(g["lon"], g["lat"])
        best, best_d = None, GAUGE_SNAP_KM / KM_PER_DEG
        for ri, r in enumerate(rivers):
            for pi, part in enumerate(r["parts"]):
                d = part.distance(pt)
                if d < best_d:
                    best, best_d = (ri, pi), d
        if best:
            part = rivers[best[0]]["parts"][best[1]]
            assigned.setdefault(best, []).append({"code": code, "ch": part.project(pt), "danger": g.get("danger_level")})

    parts = []
    for (ri, pi), gs in assigned.items():
        line = rivers[ri]["parts"][pi]
        datum = [(x["ch"], x["danger"]) for x in gs if x.get("danger")]
        if len(datum) < 2:
            continue  # direction unknown: never guess which way a wave travels
        n = len(datum)
        mx = sum(c for c, _ in datum) / n
        my = sum(v for _, v in datum) / n
        if sum((c - mx) * (v - my) for c, v in datum) > 0:
            line = LineString(list(line.coords)[::-1])
            for x in gs:
                x["ch"] = line.length - x["ch"]
        parts.append(
            {
                "river": rivers[ri]["name"],
                "river_hi": rivers[ri]["name_hi"],
                "line": line,
                "gauges": sorted(({"code": x["code"], "ch_km": x["ch"] * KM_PER_DEG} for x in gs), key=lambda x: x["ch_km"]),
            }
        )
    _placed_cache.update(key=key, parts=parts)
    return parts


def upstream_threats(lat: float, lon: float, limit: int = 5) -> list[dict]:
    """
    Gauges upstream of a place on the same river that are above warning, at
    danger, or rising close to danger - with when their water could arrive and
    how much to trust that. Empty when the place is not on a monitored river.
    """
    pt = Point(lon, lat)
    out = []
    for part in _placed_parts():
        off_km = part["line"].distance(pt) * KM_PER_DEG
        if off_km > TOWN_SNAP_KM:
            continue
        town_km = part["line"].project(pt) * KM_PER_DEG
        for g in part["gauges"]:
            dist = town_km - g["ch_km"]
            if dist < LOCAL_GAUGE_KM or dist > MAX_UPSTREAM_KM:
                continue
            st = official.station_status(g["code"])
            above = st.get("above_danger_m")
            if above is not None and abs(above) > 25:
                continue  # datum mismatch in the source, not a reading
            trend = (st.get("trend") or "").upper()
            rising_near = trend == "RISING" and above is not None and above > -1.0
            if st["status"] not in ("DANGER", "WARNING") and not rising_near:
                continue
            reasons = []
            if trend == "FALLING":
                reasons.append("the gauge is falling: the peak may already be passing")
            if dist > LONG_REACH_KM:
                reasons.append(f"{dist:.0f} km is a long reach: the wave flattens and tributaries or dams can change it")
            if off_km > GAUGE_SNAP_KM:
                reasons.append(f"the town sits {off_km:.0f} km from the mapped river line")
            if st["status"] != "DANGER" and not rising_near:
                reasons.append("the gauge is above warning, not danger")
            evidence = "weak" if trend == "FALLING" or dist > LONG_REACH_KM or len(reasons) >= 2 else "moderate" if reasons else "strong"
            out.append(
                {
                    "code": g["code"],
                    "name": st.get("name"),
                    "state": st.get("state"),
                    "river": part["river"],
                    "river_hi": part["river_hi"],
                    "status": st["status"],
                    "trend": trend or None,
                    "level_m": st.get("level_m"),
                    "above_danger_m": above,
                    "distance_km": round(dist),
                    "eta_h": {k: round(dist / v) for k, v in zip(("p10", "p50", "p90"), CELERITY_KMH)},
                    "evidence": evidence,
                    "evidence_reasons": reasons,
                }
            )
    # One entry per gauge (a river split into parts can see it twice), soonest first.
    seen, uniq = set(), []
    for t in sorted(out, key=lambda t: (t["eta_h"]["p50"], -STATUS_RANK[t["status"]])):
        if t["code"] not in seen:
            seen.add(t["code"])
            uniq.append(t)
    return uniq[:limit]


_path_cache: dict = {"ts": 0.0, "rows": []}
# Rebuilt after every 15-minute gauge sweep (main._gauge_loop); the TTL is only
# a fallback if a sweep fails.
PATH_TTL_S = 1200


def towns_in_path() -> list[dict]:
    """Every monitored town with a flood wave coming down its river, soonest first."""
    import time

    from .engine import LOCATIONS

    if time.time() - _path_cache["ts"] < PATH_TTL_S:
        return _path_cache["rows"]
    rows = []
    for loc in LOCATIONS:
        threats = upstream_threats(loc["lat"], loc["lon"], limit=3)
        if threats:
            rows.append(
                {
                    "id": loc["id"],
                    "name": loc["name"],
                    "name_hi": loc.get("name_hi"),
                    "state": loc["state"],
                    "threats": threats,
                }
            )
    rows.sort(key=lambda r: r["threats"][0]["eta_h"]["p50"])
    _path_cache.update(ts=time.time(), rows=rows)
    return rows
