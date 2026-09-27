"""
Feature engineering: raw API series in, interpretable numbers out.

Each feature here is something a district officer could be told out loud — "92 mm
in the last 24 hours", "the river is at the 97th percentile for mid-September",
"the soil is already at 0.41 m3/m3". Nothing is a latent dimension. That is a
deliberate constraint: the scoring layer has to be able to explain itself, and it
can only explain features that mean something.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from .config import CLIMATOLOGY_WINDOW_DAYS, IMD_RAIN_CLASSES


def imd_rain_class(mm_24h: float) -> dict:
    """Bucket a 24-hour accumulation into IMD's published rainfall categories."""
    for cls in IMD_RAIN_CLASSES:
        if cls["min"] <= mm_24h < cls["max"]:
            return cls
    return IMD_RAIN_CLASSES[-1]


def _parse_hour(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def _now_index(times: Sequence[str], reference: datetime | None) -> int:
    """
    Index of the last hour at or before `reference`.

    Open-Meteo returns local-time strings when a timezone is requested, so the
    reference clock must be local too. Bisecting on the parsed values rather than
    trusting a fixed offset keeps this correct across the past/forecast boundary.
    """
    if not times:
        return 0
    if reference is None:
        reference = datetime.now()
    lo, hi = 0, len(times) - 1
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        t = _parse_hour(times[mid])
        if t is None:
            lo = mid + 1
            continue
        if t <= reference:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _window_sum(values: Sequence[float | None], start: int, end: int) -> float | None:
    """Sum of a half-open slice, tolerating gaps but not inventing them as zeros."""
    start, end = max(0, start), min(len(values), end)
    if start >= end:
        return None
    seen = [v for v in values[start:end] if v is not None]
    if not seen:
        return None
    return round(float(sum(seen)), 2)


def _mean(values: Sequence[float | None]) -> float | None:
    seen = [v for v in values if v is not None]
    return round(sum(seen) / len(seen), 4) if seen else None


def rainfall_features(weather: dict, reference: datetime | None = None) -> dict:
    """Rolling rainfall accumulations and antecedent soil moisture around 'now'."""
    hourly = weather.get("hourly") or {}
    times = hourly.get("time") or []
    precip = hourly.get("precipitation") or []
    i = _now_index(times, reference)

    soil_layers = [
        hourly.get("soil_moisture_0_to_1cm") or [],
        hourly.get("soil_moisture_3_to_9cm") or [],
        hourly.get("soil_moisture_9_to_27cm") or [],
    ]
    # Depth-weighted mean of the top ~27 cm: the layers Open-Meteo exposes are
    # 1 cm, 6 cm and 18 cm thick respectively.
    weights = [1.0, 6.0, 18.0]
    soil_now: float | None = None
    parts, wsum = 0.0, 0.0
    for layer, w in zip(soil_layers, weights):
        if i < len(layer) and layer[i] is not None:
            parts += float(layer[i]) * w
            wsum += w
    if wsum:
        soil_now = round(parts / wsum, 4)

    return {
        "as_of_hour": times[i] if i < len(times) else None,
        "rain_24h_mm": _window_sum(precip, i - 23, i + 1),
        "rain_72h_mm": _window_sum(precip, i - 71, i + 1),
        "rain_7d_mm": _window_sum(precip, i - 167, i + 1),
        "rain_next_24h_mm": _window_sum(precip, i + 1, i + 25),
        "rain_next_48h_mm": _window_sum(precip, i + 1, i + 49),
        "rain_next_72h_mm": _window_sum(precip, i + 1, i + 73),
        "rain_peak_hour_mm": max((v for v in precip[max(0, i - 23) : i + 1] if v is not None), default=None),
        "soil_moisture": soil_now,
        "soil_moisture_7d_mean": _mean(
            [v for layer in soil_layers[1:] for v in layer[max(0, i - 167) : i + 1]]
        ),
        "hourly_times": times,
        "hourly_precip": precip,
        "now_index": i,
    }


def _series_pairs(daily: dict, key: str) -> list[tuple[str, float]]:
    times = daily.get("time") or []
    vals = daily.get(key) or []
    return [(t, float(v)) for t, v in zip(times, vals) if v is not None]


def discharge_features(
    flood: dict,
    climatology: dict | None,
    reference: date | None = None,
) -> dict:
    """
    Current river state relative to what is normal here at this time of year, plus
    the ensemble spread that becomes the confidence badge.
    """
    daily = flood.get("daily") or {}
    today = reference or date.today()
    today_iso = today.isoformat()

    series = _series_pairs(daily, "river_discharge")
    if not series:
        return {"available": False}

    # The row for today, or the most recent row before it.
    idx = max((k for k, (t, _) in enumerate(series) if t <= today_iso), default=0)
    current = series[idx][1]

    past = [v for _, v in series[max(0, idx - 6) : idx + 1]]
    trend_per_day = None
    if len(past) >= 3:
        # Least-squares slope over the recent limb, in cumecs/day.
        n = len(past)
        xs = list(range(n))
        mx, my = sum(xs) / n, sum(past) / n
        denom = sum((x - mx) ** 2 for x in xs)
        if denom:
            trend_per_day = sum((x - mx) * (y - my) for x, y in zip(xs, past)) / denom

    # Climatological reference for this day-of-year.
    doy = str(min(today.timetuple().tm_yday, 365))
    climo = (climatology or {}).get("stats", {}).get(doy) if climatology else None
    if climo is None and climatology:
        # Nearest available day-of-year, in case a gap left this one empty.
        stats = climatology.get("stats", {})
        if stats:
            target = int(doy)
            nearest = min(stats.keys(), key=lambda k: min(abs(int(k) - target), 365 - abs(int(k) - target)))
            climo = stats[nearest]

    baseline_source = "climatology"
    if climo:
        p50 = climo.get("p50") or 0.0
    else:
        # Fallback until the 30-year climatology finishes building: the mean of the
        # available window. Honest but weaker, and the confidence layer is told.
        window = [v for _, v in series]
        p50 = (sum(window) / len(window)) if window else 0.0
        climo = None
        baseline_source = "recent_window"

    ratio = (current / p50) if p50 > 0 else None
    percentile = None
    if climo:
        # Where does `current` sit among this day-of-year's historical percentiles?
        ladder = [(50.0, climo["p50"]), (75.0, climo["p75"]), (90.0, climo["p90"]),
                  (95.0, climo["p95"]), (99.0, climo["p99"]), (100.0, climo["max"])]
        if current <= ladder[0][1]:
            percentile = 50.0 * (current / ladder[0][1]) if ladder[0][1] > 0 else 0.0
        else:
            percentile = 100.0
            for (plo, vlo), (phi, vhi) in zip(ladder, ladder[1:]):
                if vlo <= current <= vhi:
                    frac = (current - vlo) / (vhi - vlo) if vhi > vlo else 0.0
                    percentile = plo + frac * (phi - plo)
                    break
        percentile = round(min(percentile, 100.0), 1)

    # Ensemble spread on the forecast horizon -> uncertainty.
    med = _series_pairs(daily, "river_discharge_median")
    p25 = _series_pairs(daily, "river_discharge_p25")
    p75 = _series_pairs(daily, "river_discharge_p75")
    dmin = _series_pairs(daily, "river_discharge_min")
    dmax = _series_pairs(daily, "river_discharge_max")

    def at(pairs: list[tuple[str, float]], iso: str) -> float | None:
        return next((v for t, v in pairs if t == iso), None)

    forecast_iso = [t for t, _ in series if t > today_iso][:7]
    spreads: list[float] = []
    for iso in forecast_iso[:3]:
        lo, hi, mid = at(p25, iso), at(p75, iso), at(med, iso)
        if lo is not None and hi is not None and mid and mid > 0:
            spreads.append((hi - lo) / mid)
    rel_spread = round(sum(spreads) / len(spreads), 4) if spreads else None

    forecast = [
        {
            "date": iso,
            "discharge": at(series, iso),
            "median": at(med, iso),
            "p25": at(p25, iso),
            "p75": at(p75, iso),
            "min": at(dmin, iso),
            "max": at(dmax, iso),
        }
        for iso in forecast_iso
    ]

    return {
        "available": True,
        "as_of_date": series[idx][0],
        "current_cumecs": round(current, 2),
        "seasonal_median_cumecs": round(p50, 2) if p50 else None,
        "baseline_source": baseline_source,
        "ratio_to_seasonal_median": round(ratio, 3) if ratio is not None else None,
        "percentile_for_season": percentile,
        "trend_cumecs_per_day": round(trend_per_day, 3) if trend_per_day is not None else None,
        "trend_normalised": (
            round(trend_per_day / p50, 4) if (trend_per_day is not None and p50 > 0) else None
        ),
        "relative_ensemble_spread": rel_spread,
        "climatology_years": (
            f"{climatology.get('start_year')}-{climatology.get('end_year')}" if climatology else None
        ),
        "climatology_window_days": CLIMATOLOGY_WINDOW_DAYS if climatology else None,
        "observed": [{"date": t, "discharge": round(v, 2)} for t, v in series[max(0, idx - 9) : idx + 1]],
        "forecast": forecast,
        "seasonal_bands": (
            {k: climo[k] for k in ("p50", "p75", "p90", "p95", "max") if k in climo} if climo else None
        ),
    }


def terrain_features(loc: dict) -> dict:
    """
    Static susceptibility from DEM and OpenStreetMap, combined into one 0-100
    number. All four inputs were derived from real data at build time; see
    scripts/enrich_locations.py.
    """
    elev = loc.get("elevation_m")
    slope = loc.get("slope_deg")
    dd = loc.get("drainage_density_km_per_km2")
    dist = loc.get("dist_to_water_km")
    water_frac = loc.get("waterbody_fraction")

    parts: dict[str, float] = {}

    # Low-lying ground ponds. Below ~10 m (coastal/deltaic) is the worst case.
    if elev is not None:
        parts["low_elevation"] = _clamp(100.0 * math.exp(-max(elev, 0.0) / 120.0))

    # Flat ground drains slowly. Steep ground sheds water fast but concentrates it
    # downstream, so only the flat end of the scale raises local risk.
    if slope is not None:
        parts["flat_terrain"] = _clamp(100.0 * math.exp(-max(slope, 0.0) / 0.35))

    # A dense drain/stream network in a city is mostly a sign of a floodplain that
    # has been built over; it correlates with flooding rather than preventing it.
    if dd is not None:
        parts["drainage_density"] = _clamp(100.0 * min(dd / 2.5, 1.0))

    # Proximity to a channel that can overtop.
    if dist is not None:
        parts["river_proximity"] = _clamp(100.0 * math.exp(-max(dist, 0.0) / 1.5))

    if water_frac is not None:
        parts["standing_water"] = _clamp(100.0 * min(water_frac / 0.12, 1.0))

    if loc.get("coastal"):
        parts["coastal_backwater"] = 60.0

    score = round(sum(parts.values()) / len(parts), 1) if parts else 40.0
    return {"score": score, "components": {k: round(v, 1) for k, v in parts.items()},
            "inputs": {"elevation_m": elev, "slope_deg": slope,
                       "drainage_density_km_per_km2": dd, "dist_to_water_km": dist,
                       "nearest_water_name": loc.get("nearest_water_name"),
                       "coastal": bool(loc.get("coastal"))}}


def historical_features(loc_id: str, events: Sequence[dict], reference: date | None = None) -> dict:
    """
    How often, how badly, and how recently this place has flooded before.

    Weighted so a severity-3 disaster counts more than waterlogging, and a 2024
    event counts more than a 2005 one, because drainage and land use change.
    """
    today = reference or date.today()
    # Only events strictly before the reference date. Counting the event on the
    # reference day itself leaks the label during training and replay: a flood
    # would raise its own "historical frequency" and the back-test would look
    # better than the model really is.
    mine = [e for e in events if e["location_id"] == loc_id and e["date"] < today.isoformat()]
    if not mine:
        return {"score": 0.0, "count": 0, "events": [], "most_recent": None}

    total = 0.0
    listed = []
    for e in mine:
        try:
            when = datetime.strptime(e["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        years_ago = max((today - when).days / 365.25, 0.0)
        recency = math.exp(-years_ago / 12.0)      # 12-year e-folding
        severity = {1: 0.5, 2: 1.0, 3: 1.8}.get(e.get("severity", 2), 1.0)
        total += severity * recency
        listed.append({**e, "years_ago": round(years_ago, 1)})

    listed.sort(key=lambda e: e["date"], reverse=True)
    # 4.0 of weighted evidence is treated as "floods here are a recurring fact".
    score = _clamp(100.0 * min(total / 4.0, 1.0))
    return {
        "score": round(score, 1),
        "count": len(mine),
        "weighted_evidence": round(total, 2),
        "most_recent": listed[0] if listed else None,
        "events": listed,
    }


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def build_feature_vector(
    loc: dict,
    weather: dict,
    flood: dict,
    climatology: dict | None,
    events: Sequence[dict],
    reference: datetime | None = None,
) -> dict:
    """Assemble everything the scorer needs for one location."""
    ref_dt = reference
    ref_date = (reference or datetime.now()).date()
    rain = rainfall_features(weather, ref_dt)
    river = discharge_features(flood, climatology, ref_date)
    terrain = terrain_features(loc)
    history = historical_features(loc["id"], events, ref_date)

    rain_24 = rain.get("rain_24h_mm") or 0.0
    return {
        "rain": rain,
        "river": river,
        "terrain": terrain,
        "history": history,
        "imd_class": imd_rain_class(rain_24),
        "reference": (ref_dt or datetime.now()).isoformat(timespec="seconds"),
    }
