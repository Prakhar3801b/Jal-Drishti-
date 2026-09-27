"""
Hyperlocal urban water-accumulation hotspots.

This is the part of the system aimed squarely at PS2's point that city-level weather
does not describe what happens at individual locations. A monitored city is divided
into a 16 x 16 grid of ~800 m cells (~13 x 13 km) and each cell gets:

  terrain (static, real data)
    elevation          Copernicus DEM GLO-90 via Open-Meteo, one sample per cell
    relative low-ness  where the cell sits in the city's own elevation range
    sink depth         how far the cell lies below the mean of its 8 neighbours
    flow accumulation  D8 routing on the grid: how many upslope cells drain into it
  urban form (static, OpenStreetMap)
    drains, streams, canals, major roads, rail, built-up land use -> urban intensity
    hospitals, schools, fire stations, road tunnels/underpasses -> exposure
  rain (dynamic, real data)
    hourly precipitation, 24 h back + 24 h ahead, sampled at a 3 x 3 grid over the
    city and bilinearly interpolated, so storms crossing the city are not smeared

and a simple, explainable ponding model runs hour by hour:

    runoff    = rain_rate x runoff_coefficient(urban) x (1 + upslope contribution)
    storage   = 0.85 x storage_prev + runoff - drainage_capacity(drains, urban)
    ponding   = storage x (1 + sink amplification)

It is deliberately a transparent bucket model, not a hydraulic simulation: there is
no sewer network data for Indian cities in the open. What it offers is ranking -
which streets fill first, and when - with every input shown. Uncertainty is carried
by re-running with rainfall at 60 % and 140 %, and by stating plainly that the DEM
(90 m) cannot see a 2 m underpass dip.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import math
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import numpy as np

from . import propagation, sources
from .config import CACHE_DIR as CACHE_ROOT, OPEN_METEO_ELEVATION, OPEN_METEO_FORECAST, TIMEZONE
from .engine import LOCATIONS_BY_ID
from .features import _now_index

log = logging.getLogger("jaldrishti.hotspots")

N = 16
STEP = 0.0072  # degrees, ~800 m
CACHE_DIR = CACHE_ROOT / "hotspots"
SEED_DIR = Path(__file__).resolve().parent / "data" / "hotspots"
OVERPASS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
UA = {"User-Agent": "JalDrishti-prototype/1.0 (flood research)"}
RAIN_TTL_S = 1800
_rain_cache: dict[str, tuple[float, dict]] = {}
# A first visit to an unseeded city waits this long for OpenStreetMap, then
# answers from terrain + rain alone while OSM keeps loading in the background.
OSM_BUDGET_S = 7.0
_partial: dict[str, dict] = {}
_osm_jobs: dict[str, asyncio.Task] = {}

PONDING_KNOTS = [(0.0, 0.0), (2.0, 15.0), (10.0, 40.0), (30.0, 65.0), (60.0, 85.0), (120.0, 100.0)]


def _pw(x: float, knots) -> float:
    if x <= knots[0][0]:
        return knots[0][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return knots[-1][1]


def _grid(lat: float, lon: float) -> list[tuple[float, float]]:
    return [
        (round(lat + (i - N / 2 + 0.5) * STEP, 5), round(lon + (j - N / 2 + 0.5) * STEP, 5))
        for i in range(N)
        for j in range(N)
    ]


# ------------------------------------------------------------------ static


async def _elevations(client: httpx.AsyncClient, pts: list[tuple[float, float]], retry_delay: float = 20.0) -> list[float]:
    out: list[float] = []
    for k in range(0, len(pts), 100):
        b = pts[k : k + 100]
        payload = await sources._get_json(
            client,
            OPEN_METEO_ELEVATION,
            {"latitude": ",".join(str(p[0]) for p in b), "longitude": ",".join(str(p[1]) for p in b)},
            tries=3,
            retry_delay=retry_delay,
        )
        out.extend(payload["elevation"])
    return out


async def _osm(client: httpx.AsyncClient, s: float, w: float, n: float, e: float) -> list[dict] | None:
    """
    OpenStreetMap features for the city box, as six small queries rather than one
    large one: public Overpass servers time out on the combined query for dense
    cities. Every part must succeed, otherwise the grid is marked OSM-less.
    """
    bbox = f"({s},{w},{n},{e})"
    parts = [
        f'way["waterway"~"^(drain|canal|river|stream|ditch)$"]{bbox};',
        f'nwr["amenity"~"^(hospital|school|fire_station)$"]{bbox};',
        f'way["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"]{bbox};',
        f'way["highway"]["tunnel"="yes"]{bbox};',
        f'way["railway"="rail"]{bbox};',
        f'way["landuse"~"^(residential|commercial|industrial|retail)$"]{bbox};',
    ]
    # Parts run concurrently, each starting on a different mirror, so no single
    # public server sees more than two queries from us at once.
    sem = asyncio.Semaphore(3)

    async def fetch(idx: int, part: str) -> list[dict] | None:
        q = f"[out:json][timeout:90];({part});out center tags;"
        mirrors = OVERPASS[idx % len(OVERPASS):] + OVERPASS[: idx % len(OVERPASS)]
        async with sem:
            for mirror in mirrors:
                try:
                    r = await client.post(mirror, data={"data": q}, timeout=110, headers=UA)
                    if r.status_code == 200:
                        return r.json().get("elements", [])
                    log.info("overpass %s HTTP %s", mirror, r.status_code)
                except Exception as exc:
                    log.info("overpass %s failed: %s", mirror, str(exc)[:80])
        return None

    results = await asyncio.gather(*(fetch(i, p) for i, p in enumerate(parts)))
    if any(r is None for r in results):
        return None
    return [el for r in results for el in r]


def _d8_accumulation(elev: list[float]) -> list[int]:
    """Classic D8: visit cells high to low, pass each cell's flow to its lowest neighbour."""
    acc = [1] * (N * N)
    order = sorted(range(N * N), key=lambda k: -elev[k])
    for k in order:
        i, j = divmod(k, N)
        best, drop = None, 0.0
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == dj == 0:
                    continue
                ii, jj = i + di, j + dj
                if 0 <= ii < N and 0 <= jj < N:
                    d = (elev[k] - elev[ii * N + jj]) / (1.414 if di and dj else 1.0)
                    if d > drop:
                        best, drop = ii * N + jj, d
        if best is not None:
            acc[best] += acc[k]
    return acc


async def build_static(location_id: str, use_seed: bool = True, budget_s: float | None = OSM_BUDGET_S) -> dict:
    """
    The city's static grid: disk cache, then bundled seed, then a live build.

    A live build fetches elevations (about a second) and OpenStreetMap (anything
    from seconds to minutes on public Overpass). With `budget_s` set, OSM gets
    that long; after that the grid is returned without it and OSM finishes in the
    background, so the next request gets the mapped version. `budget_s=None`
    waits for OSM (the seed builder).
    """
    loc = LOCATIONS_BY_ID[location_id]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{location_id}.json"
    if location_id in _partial:
        return _partial[location_id]
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        # A cache built while Overpass was down is retried at most once a day.
        if cached.get("osm_ok") or time.time() - cached.get("built_ts", 0) < 86400:
            return cached
    seed = SEED_DIR / f"{location_id}.json.gz"
    if use_seed and seed.exists():
        # Terrain and mapped drains change slowly: the bundled grid avoids ~256
        # elevation lookups and a heavy Overpass query on a fresh deployment.
        with gzip.open(seed, "rt", encoding="utf-8") as fh:
            static = json.load(fh)
        if static.get("osm_ok"):
            path.write_text(json.dumps(static), encoding="utf-8")
            return static

    pts = _grid(loc["lat"], loc["lon"])
    s, w = pts[0][0] - STEP / 2, pts[0][1] - STEP / 2
    n, e = pts[-1][0] + STEP / 2, pts[-1][1] + STEP / 2

    async def fetch_osm() -> list[dict] | None:
        async with httpx.AsyncClient(timeout=60, headers=UA) as osm_client:
            return await _osm(osm_client, s, w, n, e)

    job = _osm_jobs.get(location_id)
    if job is None:
        job = _osm_jobs[location_id] = asyncio.create_task(fetch_osm())
    async with httpx.AsyncClient(timeout=20, headers=UA) as client:
        # Someone is waiting on this page, so retry fast; the seed builder can wait.
        elev = await _elevations(client, pts, retry_delay=20.0 if budget_s is None else 1.5)

    if budget_s is not None and not job.done():
        await asyncio.wait({job}, timeout=budget_s)
    if job.done() or budget_s is None:
        osm = await job
        _osm_jobs.pop(location_id, None)
        static = _assemble(location_id, loc, pts, elev, osm)
        path.write_text(json.dumps(static, ensure_ascii=False), encoding="utf-8")
        return static

    # Over budget: answer now from terrain alone, finish OSM in the background.
    partial = _assemble(location_id, loc, pts, elev, None)
    partial["osm_pending"] = True
    _partial[location_id] = partial

    def finish(task: asyncio.Task) -> None:
        _osm_jobs.pop(location_id, None)
        _partial.pop(location_id, None)
        osm = None if task.cancelled() or task.exception() else task.result()
        full = _assemble(location_id, loc, pts, elev, osm)
        path.write_text(json.dumps(full, ensure_ascii=False), encoding="utf-8")
        log.info("hotspots %s: OpenStreetMap %s in background", location_id, "loaded" if osm is not None else "failed")

    job.add_done_callback(finish)
    return partial


def _assemble(location_id: str, loc: dict, pts: list[tuple[float, float]], elev: list, osm: list[dict] | None) -> dict:
    """Terrain metrics, OSM features and drainage parameters for every cell."""
    s, w = pts[0][0] - STEP / 2, pts[0][1] - STEP / 2
    n, e = pts[-1][0] + STEP / 2, pts[-1][1] + STEP / 2
    elev = [float(x if x is not None else 0.0) for x in elev]
    # The DEM reports open sea as 0 m. Sea cells are masked out: they would
    # otherwise rank as "the lowest ground in the city" in every coastal city.
    sea = [x <= 0.5 for x in elev]
    land = [x for x, is_sea in zip(elev, sea) if not is_sea] or elev

    # neighbourhood terrain metrics
    lo, hi = min(land), max(land)
    span = max(hi - lo, 1.0)
    acc = _d8_accumulation(elev)
    max_acc = max(acc)

    cells = []
    for k, (lat, lon) in enumerate(pts):
        i, j = divmod(k, N)
        neigh = [elev[ii * N + jj] for ii in range(i - 1, i + 2) for jj in range(j - 1, j + 2)
                 if (ii, jj) != (i, j) and 0 <= ii < N and 0 <= jj < N]
        mean_n = sum(neigh) / len(neigh)
        slope = max(abs(elev[k] - x) for x in neigh) / 800.0 * 100.0  # % grade to steepest neighbour
        cells.append(
            {
                "k": k, "i": i, "j": j, "lat": lat, "lon": lon, "sea": sea[k],
                "elev": round(elev[k], 1),
                # percentile rank among land cells, so a few hills cannot make
                # the whole city look "low"
                "rel_low": 0.0 if sea[k] else round(sum(1 for x in land if x > elev[k]) / len(land), 3),
                "sink_m": round(max(0.0, mean_n - elev[k]), 2),
                "slope_pct": round(slope, 2),
                "acc": acc[k],
                "acc_norm": round(math.log1p(acc[k]) / math.log1p(max_acc), 3),
                "drains": 0, "roads": 0, "rail": 0, "landuse": 0,
                "hospitals": [], "schools": [], "fire": [], "tunnels": [],
                "water_body": False,
            }
        )

    def cell_of(lat: float, lon: float) -> dict | None:
        i = int((lat - s) / STEP)
        j = int((lon - w) / STEP)
        if 0 <= i < N and 0 <= j < N:
            return cells[i * N + j]
        return None

    for el in osm or []:
        c = el.get("center") or ({"lat": el["lat"], "lon": el["lon"]} if "lat" in el else None)
        if not c:
            continue
        cell = cell_of(c["lat"], c["lon"])
        if not cell:
            continue
        tg = el.get("tags", {})
        name = tg.get("name") or tg.get("name:en")
        if "waterway" in tg:
            cell["drains"] += 1
            if tg["waterway"] in ("river", "canal"):
                cell["water_body"] = True
        elif tg.get("amenity") == "hospital":
            cell["hospitals"].append(name or "Hospital")
        elif tg.get("amenity") == "school":
            cell["schools"].append(name or "School")
        elif tg.get("amenity") == "fire_station":
            cell["fire"].append(name or "Fire station")
        elif tg.get("railway") == "rail":
            cell["rail"] += 1
        elif "landuse" in tg:
            cell["landuse"] += 1
        elif tg.get("tunnel") == "yes":
            cell["tunnels"].append(name or tg.get("ref") or "Road underpass")
        elif "highway" in tg:
            cell["roads"] += 1
            if name:
                cell.setdefault("road_names", [])
                if name not in cell["road_names"] and len(cell["road_names"]) < 3:
                    cell["road_names"].append(name)

    max_roads = max((c["roads"] for c in cells), default=1) or 1
    max_land = max((c["landuse"] for c in cells), default=1) or 1
    for c in cells:
        for key in ("hospitals", "schools", "fire", "tunnels"):
            c[key] = list(dict.fromkeys(c[key]))[:4]
        if osm is None:
            c["urban"] = 0.5  # unknown: assume mid-density rather than rural
        else:
            c["urban"] = round(min(1.0, 0.6 * c["roads"] / max_roads + 0.4 * c["landuse"] / max_land + 0.1 * min(c["rail"], 2)), 3)
        if c["sea"]:
            c.update(urban=0.0, susceptibility=0.0, capacity_mm_h=1e6, runoff_coeff=0.0)
            continue
        flat = math.exp(-c["slope_pct"] / 1.5)
        sink = min(c["sink_m"] / 4.0, 1.0)
        c["susceptibility"] = round(
            100 * (0.28 * c["rel_low"] + 0.20 * sink + 0.25 * c["acc_norm"] + 0.12 * flat + 0.15 * c["urban"]), 1
        )
        # drainage capacity (mm/h of runoff removed): formal drains help; dense
        # built-up land without mapped drains removes the least.
        base = 22.0 if c["drains"] else 12.0
        c["capacity_mm_h"] = round(base * (1.15 - 0.35 * c["urban"]) + (15.0 if c["water_body"] else 0.0), 1)
        c["runoff_coeff"] = round(0.30 + 0.55 * c["urban"], 2)

    static = {
        "location_id": location_id,
        "center": [loc["lat"], loc["lon"]],
        "n": N,
        "step_deg": STEP,
        "cell_m": 800,
        "bbox": [s, w, n, e],
        "elevation_range_m": [round(lo, 1), round(hi, 1)],
        "osm_ok": osm is not None,
        "osm_features": len(osm or []),
        "built_ts": time.time(),
        "cells": cells,
    }
    return static


# ------------------------------------------------------------------ rainfall


RAIN_DISK_MAX_AGE_S = 24 * 3600


def _rain_disk(lid: str) -> Path:
    return CACHE_DIR / "rain" / f"{lid}.json"


async def _rain_field(lid: str) -> dict:
    """
    Hourly rain at a 3x3 lattice over the city (24 h back, 24 h ahead). Needs only
    the grid box, not the built grid, so it runs alongside build_static.

    The page must not fail because one weather call did: if the live fetch is
    refused (Open-Meteo rate limits busy servers), fall back in order to the last
    field saved on disk, the town's own series from the main refresh, and finally
    no rain at all - terrain ranking and design storms still work - with
    `source` saying which one the numbers came from.
    """
    cached = _rain_cache.get(lid)
    if cached and time.time() - cached[0] < RAIN_TTL_S:
        return cached[1]
    loc = LOCATIONS_BY_ID[lid]
    pts = _grid(loc["lat"], loc["lon"])
    s, w = pts[0][0] - STEP / 2, pts[0][1] - STEP / 2
    n, e = pts[-1][0] + STEP / 2, pts[-1][1] + STEP / 2
    lats = [s, (s + n) / 2, n]
    lons = [w, (w + e) / 2, e]
    pts = [(la, lo) for la in lats for lo in lons]
    try:
        async with httpx.AsyncClient(timeout=20, headers=UA) as client:
            # Through sources._get_json so a rate-limited server retries via the relay.
            # Short retries: a page is waiting.
            payload = await sources._get_json(
                client,
                OPEN_METEO_FORECAST,
                {
                    "latitude": ",".join(f"{p[0]:.4f}" for p in pts),
                    "longitude": ",".join(f"{p[1]:.4f}" for p in pts),
                    "hourly": "precipitation",
                    "past_days": 1,
                    "forecast_days": 2,
                    "timezone": TIMEZONE,
                },
                tries=3,
                retry_delay=1.5,
            )
    except Exception as exc:
        log.info("hotspots %s: live rain unavailable (%s), falling back", lid, str(exc)[:80])
        field = _rain_fallback(lid, lats, lons, cached)
        # Remember the fallback for a minute so each click during an outage does
        # not sit through the retries again.
        _rain_cache[lid] = (time.time() - RAIN_TTL_S + 60, field)
        return field
    payload = payload if isinstance(payload, list) else [payload]
    times = payload[0]["hourly"]["time"]
    series = [[v or 0.0 for v in item["hourly"]["precipitation"]] for item in payload]
    field = {"times": times, "lats": lats, "lons": lons, "series": series, "source": "live", "fetched_ts": time.time()}
    _rain_cache[lid] = (time.time(), field)
    try:
        _rain_disk(lid).parent.mkdir(parents=True, exist_ok=True)
        _rain_disk(lid).write_text(json.dumps(field), encoding="utf-8")
    except OSError:
        pass
    return field


def _rain_fallback(lid: str, lats: list[float], lons: list[float], cached: tuple[float, dict] | None) -> dict:
    if cached:
        prev = cached[1]
        return {**prev, "source": "cached" if prev.get("source") == "live" else prev.get("source")}
    try:
        disk = json.loads(_rain_disk(lid).read_text(encoding="utf-8"))
        if time.time() - disk.get("fetched_ts", 0) < RAIN_DISK_MAX_AGE_S:
            return {**disk, "source": "cached"}
    except (OSError, ValueError):
        pass

    from .engine import engine

    hourly = (engine.raw.get(lid, ({}, {}))[0] or {}).get("hourly") or {}
    if hourly.get("time") and hourly.get("precipitation"):
        # The main refresh has the town-centre series: no spatial detail, but real rain.
        one = [v or 0.0 for v in hourly["precipitation"]]
        return {"times": hourly["time"], "lats": lats, "lons": lons, "series": [one] * 9, "source": "town"}

    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    times = [(now + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(-24, 48)]
    return {"times": times, "lats": lats, "lons": lons, "series": [[0.0] * len(times)] * 9, "source": "none"}


def _bilinear(field: dict, lat: float, lon: float, h: int) -> float:
    lats, lons, ser = field["lats"], field["lons"], field["series"]
    fy = min(max((lat - lats[0]) / (lats[2] - lats[0]) * 2, 0.0), 2.0)
    fx = min(max((lon - lons[0]) / (lons[2] - lons[0]) * 2, 0.0), 2.0)
    y0, x0 = min(int(fy), 1), min(int(fx), 1)
    ty, tx = fy - y0, fx - x0
    v = lambda yy, xx: ser[yy * 3 + xx][h]
    top = v(y0, x0) * (1 - tx) + v(y0, x0 + 1) * tx
    bot = v(y0 + 1, x0) * (1 - tx) + v(y0 + 1, x0 + 1) * tx
    return top * (1 - ty) + bot * ty


# ------------------------------------------------------------------ dynamics


ACTIONS = {
    "tunnel": ("Close or barricade the underpass and divert traffic", "अंडरपास बंद कर यातायात मोड़ें"),
    "hospital": ("Keep an access route to the hospital clear; alert its emergency desk", "अस्पताल तक पहुँच मार्ग खुला रखें; आपात विभाग को सूचित करें"),
    "school": ("Advise the school on closure / early dismissal", "स्कूल को बंद या जल्दी छुट्टी की सलाह दें"),
    "no_drain": ("Pre-position portable dewatering pumps", "पोर्टेबल जल-निकासी पंप तैनात करें"),
    "drain": ("Clear drain inlets and culverts before the rain peak", "वर्षा चरम से पहले नालियों व पुलियों की सफाई करें"),
    "sink": ("Warn residents of the low-lying pocket; ready sandbags", "निचले इलाके के निवासियों को चेताएँ; रेत की बोरियाँ तैयार रखें"),
}


async def hotspots(location_id: str, capacity_scale: float = 1.0, scenario_mm_h: float | None = None, scenario_hours: int = 3) -> dict:
    static, field = await asyncio.gather(build_static(location_id), _rain_field(location_id))
    cells = static["cells"]
    times = field["times"]
    now_i = _now_index(times, None)
    h_from, h_to = max(0, now_i - 24), min(len(times) - 1, now_i + 24)
    hours = list(range(h_from, h_to + 1))

    if scenario_mm_h:
        # A design storm starting next hour, on top of nothing else - the planner's
        # "what happens at 50 mm/h for 3 hours" question.
        rain_at = lambda c, h: scenario_mm_h if now_i < h <= now_i + scenario_hours else 0.0
    else:
        rain_at = lambda c, h: _bilinear(field, c["lat"], c["lon"], h)

    now_pos = hours.index(now_i)
    future = range(now_pos, len(hours))
    rain = np.array([[rain_at(c, h) for c in cells] for h in hours], dtype=float)
    sim = propagation.simulate(
        cells,
        rain,
        now_pos,
        capacity_scale,
        seed_key=f"{location_id}|{capacity_scale}|{scenario_mm_h}|{times[now_i]}",
        design_storm=bool(scenario_mm_h),
    )
    mid = np.round(sim["mid"]["pond"], 1).tolist()
    risk_by_hour = [[round(_pw(p, PONDING_KNOTS)) for p in row] for row in mid]

    # per-cell peak over the next 24 h, its ensemble band, and how water reaches it
    for c, st in zip(cells, sim["cells"]):
        k = c["k"]
        peak_pos = max(future, key=lambda t: mid[t][k])
        c["peak_ponding_mm"] = mid[peak_pos][k]
        c["peak_low_mm"] = st["peak_p10_mm"]
        c["peak_high_mm"] = st["peak_p90_mm"]
        c["peak_hour"] = times[hours[peak_pos]]
        c["peak_risk"] = round(_pw(mid[peak_pos][k], PONDING_KNOTS))
        c["now_risk"] = risk_by_hour[now_pos][k]
        c.update(st)
        exposure = min(1.0, 0.5 * c["urban"] + 0.25 * bool(c["hospitals"]) + 0.15 * bool(c["schools"]) + 0.25 * bool(c["tunnels"]))
        c["exposure"] = round(exposure, 2)
        # Priority blends where water will collect with what it would hit. The
        # static susceptibility keeps dry-day rankings meaningful for pre-monsoon
        # preparation work.
        c["priority"] = round((0.7 * c["peak_risk"] + 0.3 * c["susceptibility"]) * (0.5 + 0.5 * exposure), 1)

    ranked = sorted((c for c in cells if not c["sea"]), key=lambda c: -c["priority"])[:12]
    priorities = []
    for rank, c in enumerate(ranked, start=1):
        acts = []
        if c["tunnels"]:
            acts.append("tunnel")
        if c["hospitals"]:
            acts.append("hospital")
        if c["schools"] and c["peak_risk"] >= 40:
            acts.append("school")
        acts.append("drain" if c["drains"] else "no_drain")
        if c["sink_m"] >= 1.0:
            acts.append("sink")
        label = (c.get("road_names") or c["tunnels"] or c["hospitals"] or [None])[0]
        priorities.append(
            {
                "rank": rank,
                "k": c["k"],
                "lat": c["lat"],
                "lon": c["lon"],
                "label": label or f"Cell {c['i']}-{c['j']}",
                "priority": c["priority"],
                "peak_risk": c["peak_risk"],
                "peak_ponding_mm": c["peak_ponding_mm"],
                "band_mm": [c["peak_low_mm"], c["peak_high_mm"]],
                "peak_hour": c["peak_hour"],
                "susceptibility": c["susceptibility"],
                "why": _why(c),
                "facilities": {"hospitals": c["hospitals"], "schools": c["schools"], "tunnels": c["tunnels"], "fire": c["fire"]},
                "actions_en": [ACTIONS[a][0] for a in acts],
                "actions_hi": [ACTIONS[a][1] for a in acts],
            }
        )

    next_affected, affected_now = _propagation_lists(cells, sim["cells"], now_pos, hours, times)

    timeline = []
    for t, h in enumerate(hours):
        city_rain = sum(_bilinear(field, c["lat"], c["lon"], h) for c in cells[:: N + 1]) / len(cells[:: N + 1]) if not scenario_mm_h else rain_at(None, h)
        timeline.append(
            {
                "time": times[h],
                "is_forecast": h > now_i,
                "rain_mm_h": round(city_rain, 2),
                "cells_elevated": sum(1 for v in risk_by_hour[t] if v >= 40),
                "land_cells": sum(1 for c in cells if not c["sea"]),
                "cells_high": sum(1 for v in risk_by_hour[t] if v >= 65),
                "max_ponding_mm": max(mid[t]),
                "cells_flooded": sum(1 for v in mid[t] if v >= propagation.FLOOD_MM),
                "cells_flooded_band": sim["flooded_count_band"][t],
            }
        )

    peak_rain = max((x["rain_mm_h"] for x in timeline if x["is_forecast"]), default=0.0)
    confidence = _confidence(static, peak_rain, scenario_mm_h is not None, field.get("source", "live"))
    weak = sum(1 for c in cells if not c["sea"] and c["prob_flood"] > 0 and c["evidence"] == "weak")
    if weak:
        confidence["reasons"].append(
            f"Propagation evidence is weak for {weak} cell{'s' if weak > 1 else ''}: ensemble runs disagree on whether or when water reaches them"
        )

    return {
        "location": {k: LOCATIONS_BY_ID[location_id].get(k) for k in ("id", "name", "name_hi", "state", "lat", "lon", "population")},
        "grid": {k: static[k] for k in ("n", "step_deg", "cell_m", "bbox", "elevation_range_m", "osm_ok", "osm_features")}
        | {"osm_pending": bool(static.get("osm_pending"))},
        "hours": [times[h] for h in hours],
        "now_index": now_pos,
        "risk_by_hour": risk_by_hour,
        "cells": [
            {k: c[k] for k in ("k", "i", "j", "lat", "lon", "sea", "elev", "sink_m", "acc", "urban", "susceptibility",
                               "capacity_mm_h", "drains", "peak_risk", "now_risk", "peak_ponding_mm",
                               "peak_low_mm", "peak_high_mm", "peak_hour", "priority", "hospitals", "schools", "tunnels",
                               "prob_flood", "eta_h", "inflow_share", "driver", "source_k", "downstream_k", "flooded_now",
                               "evidence", "evidence_reasons")}
            for c in cells
        ],
        "propagation": {
            "flood_mm": propagation.FLOOD_MM,
            "members": sim["members"],
            "outflow_by_hour": np.round(sim["mid"]["out"], 1).tolist(),
            "next_affected": next_affected,
            "affected_now": affected_now,
        },
        "priorities": priorities,
        "timeline": timeline,
        "scenario": {"mm_h": scenario_mm_h, "hours": scenario_hours} if scenario_mm_h else None,
        "rain_source": field.get("source", "live"),
        "capacity_scale": capacity_scale,
        "confidence": confidence,
        "method": {
            "en": (
                "800 m grid. Terrain from Copernicus DEM (90 m) with D8 flow accumulation and sink depth; "
                "urban intensity, drains and critical facilities from OpenStreetMap; hourly rain from a 3x3 "
                "Open-Meteo lattice. The grid is a flow graph: each hour a cell gains rain runoff and water "
                "spilled by upslope neighbours, loses drainage capacity, and spills what it cannot hold to its "
                "lower neighbours (split by slope), so flooding propagates cell to cell. A 20-run ensemble "
                "perturbs rain amount and timing, drain capacity and terrain (+/-1.5 m) to give each cell a "
                "flood probability, an arrival-time range and an evidence rating."
            ),
            "hi": (
                "800 मीटर ग्रिड। कोपरनिकस DEM से ऊँचाई, जल-प्रवाह संचय व गड्ढे; ओपनस्ट्रीटमैप से शहरी घनत्व, नालियाँ व "
                "महत्वपूर्ण सुविधाएँ; 3x3 बिंदुओं से प्रति घंटा वर्षा। ग्रिड एक प्रवाह नेटवर्क है: हर घंटे कोशिका को वर्षा व ऊपरी "
                "कोशिकाओं से बहकर आया पानी मिलता है, नाली क्षमता जितना निकलता है, और अतिरिक्त पानी ढलान से निचली कोशिकाओं "
                "में जाता है — इस तरह बाढ़ आगे फैलती है। 20 रन का समूह वर्षा, समय, नाली क्षमता व भूभाग बदलकर हर कोशिका "
                "की बाढ़ संभावना, पहुँचने का समय और साक्ष्य स्तर देता है।"
            ),
        },
    }


def _cell_label(c: dict) -> str:
    return (c.get("road_names") or c["tunnels"] or c["hospitals"] or [None])[0] or f"Cell {c['i']}-{c['j']}"


def _propagation_lists(cells: list[dict], stats: list[dict], now_pos: int, hours: list[int], times: list[str]) -> tuple[list[dict], list[dict]]:
    """
    Cells likely to be hit next (dry now, flooded in the forecast window), ranked
    by when, and the cells already affected - each with where its water comes from.
    """
    def entry(c: dict) -> dict:
        eta = c["eta_h"]
        src = c["source_k"]
        when = None
        if eta:
            when = times[hours[min(now_pos + eta["p50"], len(hours) - 1)]]
        return {
            "k": c["k"],
            "lat": c["lat"],
            "lon": c["lon"],
            "label": _cell_label(c),
            "prob": c["prob_flood"],
            "eta_h": eta,
            "eta_time": when,
            "driver": c["driver"],
            "inflow_share": c["inflow_share"],
            "source": {"k": src, "label": _cell_label(cells[src])} if src is not None else None,
            "path": [{"k": k, "label": _cell_label(cells[k])} for k in propagation.chain(stats, c["k"])],
            "peak_mm": c["peak_ponding_mm"],
            "band_mm": [c["peak_low_mm"], c["peak_high_mm"]],
            "evidence": c["evidence"],
            "evidence_reasons": c["evidence_reasons"],
            "facilities": {"hospitals": c["hospitals"], "schools": c["schools"], "tunnels": c["tunnels"]},
        }

    land = [c for c in cells if not c["sea"]]
    upcoming = [c for c in land if not c["flooded_now"] and c["prob_flood"] >= 0.25 and c["eta_h"]]
    upcoming.sort(key=lambda c: (c["eta_h"]["p50"], -c["prob_flood"]))
    now = sorted((c for c in land if c["flooded_now"]), key=lambda c: -c["now_risk"])
    return [entry(c) for c in upcoming[:15]], [entry(c) for c in now[:10]]


def _why(c: dict) -> list[str]:
    out = []
    if c["rel_low"] >= 0.8:
        out.append(f"lower than {c['rel_low'] * 100:.0f}% of the city")
    if c["sink_m"] >= 1.0:
        out.append(f"sits {c['sink_m']} m below surrounding cells")
    if c["acc"] >= 12:
        out.append(f"{c['acc']} upslope cells drain into it")
    if not c["drains"] and c["urban"] >= 0.4:
        out.append("built-up with no mapped drain")
    if c["tunnels"]:
        out.append("contains a road underpass")
    if c["peak_ponding_mm"] >= 10:
        out.append(f"~{c['peak_ponding_mm']:.0f} mm of ponding expected at peak")
    return out or ["moderate terrain and drainage exposure"]


RAIN_SOURCE_NOTE = {
    "cached": (-0.1, "Weather service busy: using this city's last fetched rain forecast"),
    "town": (-0.15, "Weather service busy: using the town-centre rain series, without spread across the city"),
    "none": (-0.3, "Live rain unavailable (weather service busy): ranking is by terrain only; design-storm scenarios still work"),
}


def _confidence(static: dict, peak_rain: float, scenario: bool, rain_source: str = "live") -> dict:
    value, reasons = 0.7, []
    reasons.append("Terrain from a 90 m DEM: street-scale dips such as underpasses are below its resolution")
    value -= 0.1
    if static["osm_ok"]:
        reasons.append(f"{static['osm_features']} OpenStreetMap features describe drains, roads and facilities")
    else:
        value -= 0.2
        reasons.append(
            "OpenStreetMap drains and roads still loading: urban intensity assumed for now; reload in a minute for the mapped version"
            if static.get("osm_pending")
            else "OpenStreetMap unavailable: urban intensity and drains assumed, not mapped"
        )
    if scenario:
        reasons.append("Design-storm scenario: rainfall is an input, not a forecast")
    elif rain_source in RAIN_SOURCE_NOTE:
        delta, note = RAIN_SOURCE_NOTE[rain_source]
        value += delta
        reasons.insert(0, note)
    elif peak_rain < 2:
        value += 0.1
        reasons.append("Little rain forecast in the next 24 h, so a low-risk reading is robust")
    else:
        reasons.append("Rain forecast at ~11 km resolution interpolated across the city")
    value = max(0.1, min(1.0, value))
    level = "high" if value >= 0.7 else "medium" if value >= 0.45 else "low"
    return {"value": round(value, 2), "level": level, "reasons": reasons}
