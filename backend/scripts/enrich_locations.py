"""
Build-time enrichment of the monitored location set.

Everything this script writes into locations.enriched.json is DERIVED FROM REAL DATA,
not hand-authored:

  * elevation_m       Open-Meteo Elevation API (Copernicus DEM GLO-90)
  * slope_deg         finite-difference slope from a 5-point DEM stencil (+-0.02 deg)
  * drainage_density  total OSM waterway length / disc area, km per km^2 (Overpass)
  * dist_to_water_km  great-circle distance to the nearest OSM river / water body
  * waterbody_area_km2 area of OSM water polygons within the disc
  * glofas_lat/lon    the GloFAS 5 km cell near the town with the largest river
                      discharge, i.e. the main channel the settlement sits on.
                      Querying the town centroid directly often lands on a hillslope
                      cell carrying ~10 m3/s, which badly understates a location on
                      the Ganga or Brahmaputra. Snapping fixes that.

Run once (or whenever locations.json changes):

    python backend/scripts/enrich_locations.py                # all three stages
    python backend/scripts/enrich_locations.py --only snap     # redo one stage

Stages merge into the existing locations.enriched.json, so a stage that fails
half-way can be retried on its own without discarding the other two.

It is deliberately slow and polite. Open-Meteo bills one *coordinate* as one call
against a per-minute budget, and Overpass is a donated service - we are guests on
both, so every loop here is rate limited and backs off on 429.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import httpx

DATA = Path(__file__).resolve().parent.parent / "app" / "data"
SRC = DATA / "locations.json"
OUT = DATA / "locations.enriched.json"

ELEVATION_API = "https://api.open-meteo.com/v1/elevation"
FLOOD_API = "https://flood-api.open-meteo.com/v1/flood"
# Overpass is a donated service and the main instance returns 504/429 under load.
# Trying the mirrors in turn is the difference between 37 of 41 locations enriched
# and all 41.
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

DEM_OFFSET = 0.02          # ~2.2 km stencil arm for the slope estimate
SNAP_STEP = 0.05           # GloFAS grid is ~0.05 deg, so probe on that pitch
SNAP_RING = 2              # +-2 cells => 5x5 probe window (~+-11 km)
OSM_RADIUS_M = 8000        # drainage-density disc
CHUNK = 90                 # Open-Meteo accepts ~100 coordinate pairs per call

# Open-Meteo's free tier counts every coordinate in a batch as a separate call
# against a per-minute budget. Staying near 400 coords/min keeps us clear of 429s
# while still finishing the whole snap pass in a couple of minutes.
COORDS_PER_MIN = 400
RETRY_429_SLEEP = 65


def short_err(exc: Exception, limit: int = 160) -> str:
    """Open-Meteo echoes the whole request URL back in errors; keep logs readable."""
    text = str(exc).split(" for url")[0]
    return text[:limit]


def get_with_backoff(client: httpx.Client, url: str, params: dict, tries: int = 4, timeout: int = 120):
    """GET that treats 429 as 'wait for the next minute bucket', not as failure."""
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            r = client.get(url, params=params, timeout=timeout)
            if r.status_code == 429:
                raise httpx.HTTPStatusError("429 Too Many Requests", request=r.request, response=r)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as exc:
            last = exc
            if exc.response is not None and exc.response.status_code == 429 and attempt < tries:
                print(f"    rate limited, waiting {RETRY_429_SLEEP}s (attempt {attempt}/{tries})")
                time.sleep(RETRY_429_SLEEP)
                continue
            raise
        except Exception as exc:
            last = exc
            if attempt < tries:
                time.sleep(3 * attempt)
                continue
            raise
    raise last if last else RuntimeError("unreachable")


def haversine_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = p2 - p1
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


# --------------------------------------------------------------------------- DEM


def fetch_elevations(client: httpx.Client, coords: list[tuple[float, float]]) -> list[float | None]:
    """Batch-resolve DEM elevation for a list of (lat, lon)."""
    out: list[float | None] = []
    for batch in chunked(coords, CHUNK):
        params = {
            "latitude": ",".join(f"{la:.4f}" for la, _ in batch),
            "longitude": ",".join(f"{lo:.4f}" for _, lo in batch),
        }
        payload = get_with_backoff(client, ELEVATION_API, params, timeout=60)
        elev = payload.get("elevation") or []
        elev = list(elev) + [None] * (len(batch) - len(elev))
        out.extend(elev)
        time.sleep(60.0 * len(batch) / COORDS_PER_MIN)
    return out


def dem_stencil(lat: float, lon: float) -> list[tuple[float, float]]:
    d = DEM_OFFSET
    return [(lat, lon), (lat + d, lon), (lat - d, lon), (lat, lon + d), (lat, lon - d)]


def slope_from_stencil(elev: list[float | None], lat: float) -> tuple[float | None, float | None]:
    """Return (elevation_m, slope_deg) from a centre/N/S/E/W elevation stencil."""
    c, n, s, e, w = elev
    if c is None:
        return None, None
    dy_m = DEM_OFFSET * 111_320 * 2          # N-S separation of the two arms
    dx_m = DEM_OFFSET * 111_320 * 2 * math.cos(math.radians(lat))
    gy = ((n - s) / dy_m) if (n is not None and s is not None and dy_m) else 0.0
    gx = ((e - w) / dx_m) if (e is not None and w is not None and dx_m) else 0.0
    slope = math.degrees(math.atan(math.hypot(gx, gy)))
    return round(float(c), 1), round(slope, 3)


# ------------------------------------------------------------------ GloFAS snap


def snap_to_channel(client: httpx.Client, locs: list[dict]) -> dict[str, dict]:
    """
    Probe a 7x7 GloFAS grid window around each location and keep the cell with the
    highest long-run mean discharge. That cell is the main river channel.
    """
    probes: list[tuple[str, float, float]] = []
    for loc in locs:
        for i in range(-SNAP_RING, SNAP_RING + 1):
            for j in range(-SNAP_RING, SNAP_RING + 1):
                probes.append(
                    (loc["id"], round(loc["lat"] + i * SNAP_STEP, 4), round(loc["lon"] + j * SNAP_STEP, 4))
                )

    best: dict[str, dict] = {}
    total = len(probes)
    for k, batch in enumerate(chunked(probes, CHUNK), start=1):
        params = {
            "latitude": ",".join(f"{la}" for _, la, _ in batch),
            "longitude": ",".join(f"{lo}" for _, _, lo in batch),
            "daily": "river_discharge_mean",
            "past_days": 7,
            "forecast_days": 1,
        }
        try:
            payload = get_with_backoff(client, FLOOD_API, params)
        except Exception as exc:  # pragma: no cover - network best effort
            print(f"  ! snap batch {k} failed: {short_err(exc)}", file=sys.stderr)
            continue

        if isinstance(payload, dict):
            payload = [payload]
        for (loc_id, la, lo), item in zip(batch, payload):
            series = (item.get("daily") or {}).get("river_discharge_mean") or []
            vals = [v for v in series if v is not None]
            if not vals:
                continue
            mean = sum(vals) / len(vals)
            cur = best.get(loc_id)
            if cur is None or mean > cur["discharge_mean"]:
                best[loc_id] = {
                    "glofas_lat": la,
                    "glofas_lon": lo,
                    "discharge_mean": round(mean, 2),
                }
        done = min(k * CHUNK, total)
        print(f"  snap {done}/{total} probes")
        time.sleep(60.0 * len(batch) / COORDS_PER_MIN)
    return best


# ------------------------------------------------------------------- Overpass


OVERPASS_QL = """
[out:json][timeout:90];
(
  way["waterway"~"^(river|stream|canal|drain|ditch)$"](around:{radius},{lat},{lon});
  way["natural"="water"](around:{radius},{lat},{lon});
  relation["natural"="water"](around:{radius},{lat},{lon});
);
out geom;
"""


def polyline_km(geom: list[dict]) -> float:
    total = 0.0
    for a, b in zip(geom, geom[1:]):
        total += haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
    return total


def ring_area_km2(geom: list[dict]) -> float:
    """Shoelace area of a closed ring, projected locally to km."""
    if len(geom) < 4:
        return 0.0
    lat0 = sum(p["lat"] for p in geom) / len(geom)
    kx = 111.320 * math.cos(math.radians(lat0))
    ky = 110.574
    pts = [((p["lon"]) * kx, (p["lat"]) * ky) for p in geom]
    s = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def fetch_hydrology(client: httpx.Client, lat: float, lon: float) -> dict:
    q = OVERPASS_QL.format(radius=OSM_RADIUS_M, lat=lat, lon=lon)

    elements = None
    last: Exception | None = None
    for mirror in OVERPASS_MIRRORS:
        try:
            r = client.post(mirror, data={"data": q}, timeout=180)
            r.raise_for_status()
            elements = r.json().get("elements", [])
            break
        except Exception as exc:
            last = exc
            time.sleep(2.0)
    if elements is None:
        raise RuntimeError(f"all Overpass mirrors failed; last: {short_err(last or RuntimeError('?'))}")

    waterway_km = 0.0
    river_km = 0.0
    water_area = 0.0
    nearest = float("inf")
    nearest_name = None
    counts: dict[str, int] = {}

    for el in elements:
        geom = el.get("geometry") or []
        if not geom:
            continue
        tags = el.get("tags") or {}
        ww = tags.get("waterway")
        name = tags.get("name")

        if ww:
            counts[ww] = counts.get(ww, 0) + 1
            length = polyline_km(geom)
            waterway_km += length
            if ww in ("river", "canal"):
                river_km += length
        elif tags.get("natural") == "water":
            water_area += ring_area_km2(geom)

        # nearest significant water feature: a named river/canal or any water body
        significant = ww in ("river", "canal") or tags.get("natural") == "water"
        if significant:
            for p in geom:
                d = haversine_km(lat, lon, p["lat"], p["lon"])
                if d < nearest:
                    nearest = d
                    nearest_name = name

    disc_area = math.pi * (OSM_RADIUS_M / 1000.0) ** 2
    return {
        "drainage_density_km_per_km2": round(waterway_km / disc_area, 3),
        "river_length_km": round(river_km, 2),
        "waterbody_area_km2": round(water_area, 3),
        "waterbody_fraction": round(min(water_area / disc_area, 1.0), 4),
        "dist_to_water_km": round(nearest, 3) if nearest != float("inf") else None,
        "nearest_water_name": nearest_name,
        "osm_waterway_counts": counts,
        "osm_radius_km": OSM_RADIUS_M / 1000.0,
    }


# ------------------------------------------------------------------------ main


STAGES = ("dem", "snap", "osm")


def load_locations() -> tuple[dict, list[dict]]:
    """Seed locations, overlaid with whatever a previous run already derived."""
    src = json.loads(SRC.read_text(encoding="utf-8"))
    locs = src["locations"]
    if OUT.exists():
        try:
            prev = {l["id"]: l for l in json.loads(OUT.read_text(encoding="utf-8"))["locations"]}
            for loc in locs:
                for key, val in prev.get(loc["id"], {}).items():
                    loc.setdefault(key, val)
            print(f"merged {len(prev)} previously enriched records from {OUT.name}")
        except Exception as exc:
            print(f"could not reuse {OUT.name}: {short_err(exc)}", file=sys.stderr)
    return src, locs


def stage_dem(client: httpx.Client, locs: list[dict]) -> None:
    print("[dem] DEM elevation + slope")
    stencils: list[tuple[float, float]] = []
    for loc in locs:
        stencils.extend(dem_stencil(loc["lat"], loc["lon"]))
    elevs = fetch_elevations(client, stencils)
    for idx, loc in enumerate(locs):
        elev, slope = slope_from_stencil(elevs[idx * 5 : idx * 5 + 5], loc["lat"])
        loc["elevation_m"] = elev
        loc["slope_deg"] = slope
        print(f"  {loc['name']:<20} elev={elev} m  slope={slope} deg")


def stage_snap(client: httpx.Client, locs: list[dict]) -> None:
    print("[snap] GloFAS channel snapping")
    snaps = snap_to_channel(client, locs)
    missing = []
    for loc in locs:
        s = snaps.get(loc["id"])
        if s:
            loc["glofas_lat"] = s["glofas_lat"]
            loc["glofas_lon"] = s["glofas_lon"]
            loc["glofas_snap_km"] = round(
                haversine_km(loc["lat"], loc["lon"], s["glofas_lat"], s["glofas_lon"]), 2
            )
            loc["glofas_baseline_mean"] = s["discharge_mean"]
        elif "glofas_lat" not in loc:
            # fall back to the town centroid so the pipeline still has a coordinate
            loc["glofas_lat"] = loc["lat"]
            loc["glofas_lon"] = loc["lon"]
            loc["glofas_snap_km"] = 0.0
            loc["glofas_baseline_mean"] = None
            missing.append(loc["name"])
        print(
            f"  {loc['name']:<20} -> {loc['glofas_lat']},{loc['glofas_lon']} "
            f"({loc.get('glofas_snap_km')} km, {loc.get('glofas_baseline_mean')} m3/s)"
        )
    if missing:
        print(f"  ! unsnapped, using centroid: {', '.join(missing)}", file=sys.stderr)


def stage_osm(client: httpx.Client, locs: list[dict], missing_only: bool = False) -> None:
    print("[osm] OSM hydrology via Overpass (throttled)")
    if missing_only:
        pending = [l for l in locs if l.get("drainage_density_km_per_km2") is None]
        print(f"  --missing-only: {len(pending)} of {len(locs)} still need hydrology")
        locs = pending
        if not locs:
            return
    for i, loc in enumerate(locs, start=1):
        try:
            hyd = fetch_hydrology(client, loc["lat"], loc["lon"])
            loc.update(hyd)
            print(
                f"  [{i}/{len(locs)}] {loc['name']:<20} "
                f"dd={hyd['drainage_density_km_per_km2']} km/km2  "
                f"nearest={hyd['dist_to_water_km']} km ({hyd['nearest_water_name']})"
            )
        except Exception as exc:
            print(f"  [{i}/{len(locs)}] {loc['name']:<20} OVERPASS FAILED: {short_err(exc)}", file=sys.stderr)
            loc.setdefault("drainage_density_km_per_km2", None)
            loc.setdefault("dist_to_water_km", None)
        time.sleep(2.0)  # be a good Overpass citizen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--only",
        action="append",
        choices=STAGES,
        help="run just this stage and merge it into the existing output (repeatable)",
    )
    ap.add_argument(
        "--missing-only",
        action="store_true",
        help="only process locations that are missing that stage's output",
    )
    args = ap.parse_args()
    stages = tuple(args.only) if args.only else STAGES

    src, locs = load_locations()
    print(f"enriching {len(locs)} locations; stages: {', '.join(stages)}")

    headers = {"User-Agent": "JalDrishti-prototype/1.0 (hackathon flood-risk prototype)"}
    with httpx.Client(headers=headers, follow_redirects=True) as client:
        if "dem" in stages:
            todo = [l for l in locs if l.get("elevation_m") is None] if args.missing_only else locs
            if todo:
                stage_dem(client, todo)
        if "snap" in stages:
            # the seed fallback copies lat/lon into glofas_*, so "unsnapped" means
            # there is no recorded baseline discharge yet
            todo = [l for l in locs if l.get("glofas_baseline_mean") is None] if args.missing_only else locs
            if todo:
                stage_snap(client, todo)
        if "osm" in stages:
            stage_osm(client, locs, missing_only=args.missing_only)

    meta = {}
    if OUT.exists():
        try:
            meta = json.loads(OUT.read_text(encoding="utf-8")).get("_meta", {})
        except Exception:
            meta = {}

    out = {
        "_meta": {
            **src.get("_meta", {}),
            **meta,
            "enriched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "stages_last_run": list(stages),
            "derived_fields": {
                "elevation_m": "Open-Meteo Elevation API (Copernicus DEM GLO-90)",
                "slope_deg": f"finite-difference slope over a +-{DEM_OFFSET} deg DEM stencil",
                "drainage_density_km_per_km2": f"OSM waterway length / area of a {OSM_RADIUS_M/1000} km disc",
                "dist_to_water_km": "great-circle distance to nearest OSM river/canal/water body",
                "glofas_lat/glofas_lon": (
                    f"GloFAS cell with the largest mean discharge in a "
                    f"{2*SNAP_RING+1}x{2*SNAP_RING+1} probe window on a {SNAP_STEP} deg pitch"
                ),
            },
        },
        "locations": locs,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT} ({OUT.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
