"""
Road travel times between resource depots and monitored places.

Real drive times come from OSRM's table service over the OpenStreetMap road
network (router.project-osrm.org). The whole depot x place matrix is fetched in
chunks the public server accepts, paced to its usage policy, and cached on disk
for a week: roads do not change between scoring runs.

Until the matrix is built, or for any pair OSRM cannot route (an island, a road
gap), a straight-line estimate is used instead - distance x 1.4 road factor at
45 km/h - and every such pair is flagged `estimated` so the plan says so rather
than presenting a guess as a route. A pair with no road at all (Andaman, Lakshadweep
from the mainland) is `no_road`: those places need air or sea lift, which the
planner does not model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time

import httpx

from .config import CACHE_DIR

log = logging.getLogger("jaldrishti.travel")

OSRM_TABLE = "https://router.project-osrm.org/table/v1/driving/"
CACHE_PATH = CACHE_DIR / "travel_matrix.json"
CACHE_TTL_S = 7 * 24 * 3600
SRC_CHUNK, DST_CHUNK = 25, 50  # 75 coordinates per request, under the public server's table limit
PACE_S = 1.2  # the public demo server asks for about one request a second
ROAD_FACTOR = 1.4  # straight line -> road distance, typical for Indian highways
FALLBACK_KMH = 45.0

_matrix: dict[str, dict] = {}  # "src|dst" -> {"h": hours or None, "km": km or None}
_meta: dict = {"source": "estimate", "built_at": None, "pairs": 0, "building": False}


def _key(src: dict, dst: dict) -> str:
    return f"{src['id']}|{dst['id']}"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _load_cache() -> None:
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    _matrix.clear()
    _matrix.update(data.get("pairs", {}))
    _meta.update({"source": "osrm", "built_at": data.get("built_at"), "pairs": len(_matrix)})


def status() -> dict:
    return dict(_meta)


def leg(src: dict, dst: dict) -> dict:
    """Drive time for one depot -> place pair: hours, km, and how it was obtained."""
    if src["id"] == dst["id"] or (abs(src["lat"] - dst["lat"]) < 1e-4 and abs(src["lon"] - dst["lon"]) < 1e-4):
        return {"h": 0.0, "km": 0.0, "basis": "same_place"}
    got = _matrix.get(_key(src, dst))
    if got is not None:
        if got["h"] is None:
            return {"h": None, "km": None, "basis": "no_road"}
        return {"h": got["h"], "km": got["km"], "basis": "road"}
    km = haversine_km(src["lat"], src["lon"], dst["lat"], dst["lon"]) * ROAD_FACTOR
    return {"h": round(km / FALLBACK_KMH, 2), "km": round(km, 1), "basis": "estimated"}


async def build(sources: list[dict], destinations: list[dict], force: bool = False) -> None:
    """Fetch the OSRM matrix for every source x destination pair (cached a week)."""
    if not _matrix:
        _load_cache()
    fresh = _meta.get("built_at") and time.time() - float(_meta["built_at"]) < CACHE_TTL_S
    missing = [(s, d) for s in sources for d in destinations if s["id"] != d["id"] and _key(s, d) not in _matrix]
    if fresh and not missing and not force:
        return
    if _meta["building"]:
        return
    _meta["building"] = True
    pairs: dict[str, dict] = {}
    try:
        async with httpx.AsyncClient(headers={"User-Agent": "JalDrishti-planning (research prototype)"}, timeout=40) as client:
            for i in range(0, len(sources), SRC_CHUNK):
                srcs = sources[i : i + SRC_CHUNK]
                for j in range(0, len(destinations), DST_CHUNK):
                    dsts = destinations[j : j + DST_CHUNK]
                    coords = ";".join(f"{p['lon']:.5f},{p['lat']:.5f}" for p in srcs + dsts)
                    url = (
                        f"{OSRM_TABLE}{coords}?sources={';'.join(str(k) for k in range(len(srcs)))}"
                        f"&destinations={';'.join(str(len(srcs) + k) for k in range(len(dsts)))}"
                        "&annotations=duration,distance"
                    )
                    r = await client.get(url)
                    r.raise_for_status()
                    body = r.json()
                    if body.get("code") != "Ok":
                        raise RuntimeError(f"OSRM answered {body.get('code')}")
                    for a, s in enumerate(srcs):
                        for b, d in enumerate(dsts):
                            dur = body["durations"][a][b]
                            dist = body["distances"][a][b]
                            # OSRM snaps each point to the nearest road; a null or a
                            # snap far from the point means there is no road link.
                            pairs[_key(s, d)] = (
                                {"h": None, "km": None}
                                if dur is None
                                else {"h": round(dur / 3600.0, 2), "km": round(dist / 1000.0, 1)}
                            )
                    await asyncio.sleep(PACE_S)
        _matrix.update(pairs)
        now = time.time()
        _meta.update({"source": "osrm", "built_at": now, "pairs": len(_matrix)})
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps({"built_at": now, "pairs": _matrix}), encoding="utf-8")
        log.info("travel matrix: %d road pairs from OSRM", len(pairs))
    except Exception as exc:
        log.warning("OSRM travel matrix unavailable, using straight-line estimates: %s", exc)
    finally:
        _meta["building"] = False


_load_cache()
