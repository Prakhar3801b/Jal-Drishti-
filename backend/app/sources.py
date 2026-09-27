"""
Clients for the live data sources.

Design notes worth knowing before editing:

* Open-Meteo accepts many coordinates in one request (`latitude=a,b,c`) and returns
  a JSON *array* in the same order. Forty locations therefore cost two requests per
  refresh instead of eighty, which is both faster and far politer.
* The free tier counts every coordinate as one call against a per-minute budget,
  so batches are capped and the client paces itself between them.
* Nothing here raises on a single source failing. A partial refresh that reports
  which source degraded is more useful in a live demo than an exception, and the
  dashboard surfaces source health directly.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Sequence

import httpx

from . import store
from .config import (
    BATCH_COORDS,
    CLIMATOLOGY_END_YEAR,
    CLIMATOLOGY_START_YEAR,
    COORDS_PER_MIN,
    CWC_RELAY,
    CWC_RELAY_TOKEN,
    HTTP_TIMEOUT,
    OPEN_METEO_ARCHIVE,
    OPEN_METEO_FLOOD,
    OPEN_METEO_FORECAST,
    TIMEZONE,
)

log = logging.getLogger("jaldrishti.sources")

USER_AGENT = "JalDrishti-prototype/1.0 (hackathon flood-risk prototype)"

HOURLY_VARS = "precipitation,soil_moisture_0_to_1cm,soil_moisture_3_to_9cm,soil_moisture_9_to_27cm"
DAILY_WEATHER_VARS = "precipitation_sum,precipitation_hours,precipitation_probability_max"
# Conditions right now, for display only; the risk engine scores the hourly series.
CURRENT_WEATHER_VARS = (
    "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,"
    "weather_code,cloud_cover,wind_speed_10m,wind_direction_10m,is_day"
)
DAILY_FLOOD_VARS = (
    "river_discharge,river_discharge_mean,river_discharge_median,"
    "river_discharge_max,river_discharge_min,river_discharge_p25,river_discharge_p75"
)

PAST_DAYS = 7
FORECAST_DAYS = 7


class SourceError(RuntimeError):
    """Raised inside a single fetch; callers downgrade it to degraded health."""


# Open-Meteo's free tier has minute, hour and day quotas per IP. A 429 names which
# one was hit; until it resets, every Open-Meteo call fails fast here instead of
# retrying every few minutes and keeping the quota exhausted.
_limit: dict = {"until": 0.0, "kind": None, "reason": None}


def _note_limit(reason: str) -> None:
    now = time.time()
    text = (reason or "").lower()
    if "daily" in text:
        # Daily quotas reset at 00:00 UTC; probe again a few minutes after.
        until, kind = (math.floor(now / 86400) + 1) * 86400 + 300, "daily"
    elif "hourly" in text:
        until, kind = (math.floor(now / 3600) + 1) * 3600 + 60, "hourly"
    else:
        until, kind = now + 65, "minutely"
    _limit.update({"until": until, "kind": kind, "reason": (reason or "rate limited")[:160]})
    log.warning("Open-Meteo %s limit reached; pausing Open-Meteo calls until %s UTC", kind,
                time.strftime("%Y-%m-%d %H:%M", time.gmtime(until)))


def limit_status() -> dict:
    """Whether Open-Meteo calls are paused by a quota, and until when (epoch seconds)."""
    active = time.time() < _limit["until"]
    return {"paused": active, "until": _limit["until"] if active else None, "kind": _limit["kind"] if active else None,
            "reason": _limit["reason"] if active else None}


def _chunks(seq: Sequence[Any], n: int) -> Iterable[Sequence[Any]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _coord_params(points: Sequence[tuple[float, float]]) -> dict[str, str]:
    return {
        "latitude": ",".join(f"{la:.4f}" for la, _ in points),
        "longitude": ",".join(f"{lo:.4f}" for _, lo in points),
    }


def _as_list(payload: Any, expected: int) -> list[dict]:
    """Open-Meteo returns a bare object for one coordinate and an array for many."""
    if isinstance(payload, dict):
        if payload.get("error"):
            raise SourceError(str(payload.get("reason", "unknown API error"))[:200])
        payload = [payload]
    if len(payload) != expected:
        raise SourceError(f"expected {expected} coordinate results, got {len(payload)}")
    return payload


async def _get_json(
    client: httpx.AsyncClient,
    url: str,
    params: dict,
    *,
    tries: int = 3,
    timeout: float = HTTP_TIMEOUT,
    retry_delay: float = 20.0,
) -> Any:
    delay = retry_delay
    last: Exception | None = None
    via_relay = False
    if "open-meteo.com" in url and time.time() < _limit["until"] and not CWC_RELAY:
        raise SourceError(f"rate limited (429): Open-Meteo {_limit['kind']} limit, paused until "
                          f"{time.strftime('%H:%M', time.gmtime(_limit['until']))} UTC")
    for attempt in range(1, tries + 1):
        try:
            if via_relay:
                target = str(httpx.URL(url, params=params))
                resp = await client.get(
                    CWC_RELAY,
                    headers={"x-relay-token": CWC_RELAY_TOKEN, "x-cwc-target": target},
                    timeout=max(timeout, 75.0),
                )
            else:
                resp = await client.get(url, params=params, timeout=timeout)
            if resp.status_code == 429:
                if CWC_RELAY and not via_relay:
                    # This server's shared IP is over Open-Meteo's quota; the
                    # Mumbai relay has its own, so retry through it at once.
                    log.info("Open-Meteo rate limited this server; retrying via relay")
                    via_relay = True
                    last = SourceError("rate limited (429)")
                    continue
                try:
                    reason = resp.json().get("reason", "")
                except ValueError:
                    reason = ""
                if "open-meteo.com" in url and not via_relay:
                    _note_limit(reason)
                raise SourceError("rate limited (429)" + (" via relay" if via_relay else "") + (f": {reason}" if reason else ""))
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last = exc
            if "rate limited" in str(exc):
                raise  # a quota does not clear in 20 s; waiting only holds the refresh open
            if attempt < tries:
                await asyncio.sleep(delay)
                delay *= 1.6
                continue
    raise SourceError(str(last)[:200])


async def _pace(n_coords: int) -> None:
    await asyncio.sleep(60.0 * n_coords / COORDS_PER_MIN)


# --------------------------------------------------------------------- weather


async def fetch_weather(client: httpx.AsyncClient, locations: Sequence[dict]) -> dict[str, dict]:
    """
    Hourly rainfall and soil moisture, 7 days back and 7 days forward.

    Hourly rather than daily because "rainfall in the last 24 hours" is a rolling
    window ending now, not a calendar day - and IMD's own thresholds are defined
    on a 24-hour accumulation.
    """
    out: dict[str, dict] = {}
    started = time.perf_counter()
    errors: list[str] = []

    for batch in _chunks(list(locations), BATCH_COORDS):
        params = {
            **_coord_params([(l["lat"], l["lon"]) for l in batch]),
            "hourly": HOURLY_VARS,
            "daily": DAILY_WEATHER_VARS,
            "current": CURRENT_WEATHER_VARS,
            "past_days": PAST_DAYS,
            "forecast_days": FORECAST_DAYS,
            "timezone": TIMEZONE,
        }
        try:
            payload = _as_list(await _get_json(client, OPEN_METEO_FORECAST, params), len(batch))
        except Exception as exc:
            errors.append(str(exc)[:120])
            continue
        for loc, item in zip(batch, payload):
            out[loc["id"]] = {
                "hourly": item.get("hourly") or {},
                "daily": item.get("daily") or {},
                "current": item.get("current") or {},
                "elevation": item.get("elevation"),
                "utc_offset_seconds": item.get("utc_offset_seconds", 0),
            }
        await _pace(len(batch))

    latency = int((time.perf_counter() - started) * 1000)
    store.record_source_health(
        "open_meteo_weather",
        ok=bool(out) and not errors,
        latency_ms=latency,
        detail=f"{len(out)}/{len(locations)} locations" + (f"; errors: {'; '.join(errors)}" if errors else ""),
    )
    if not out:
        raise SourceError("weather API returned nothing: " + "; ".join(errors))
    return out


# ----------------------------------------------------------------------- flood


async def fetch_flood(client: httpx.AsyncClient, locations: Sequence[dict]) -> dict[str, dict]:
    """
    GloFAS daily river discharge with its ensemble statistics.

    Queried at the location's snapped channel coordinate (see
    scripts/enrich_locations.py), not the town centroid - that is the difference
    between reading the Brahmaputra and reading a hillside rivulet next to it.
    """
    out: dict[str, dict] = {}
    started = time.perf_counter()
    errors: list[str] = []

    for batch in _chunks(list(locations), BATCH_COORDS):
        points = [(l.get("glofas_lat", l["lat"]), l.get("glofas_lon", l["lon"])) for l in batch]
        params = {
            **_coord_params(points),
            "daily": DAILY_FLOOD_VARS,
            "past_days": PAST_DAYS,
            "forecast_days": 30,  # GloFAS publishes far further out than the weather model
        }
        try:
            payload = _as_list(await _get_json(client, OPEN_METEO_FLOOD, params, timeout=120), len(batch))
        except Exception as exc:
            errors.append(str(exc)[:120])
            continue
        for loc, item in zip(batch, payload):
            out[loc["id"]] = {"daily": item.get("daily") or {}}
        await _pace(len(batch))

    latency = int((time.perf_counter() - started) * 1000)
    store.record_source_health(
        "open_meteo_flood",
        ok=bool(out) and not errors,
        latency_ms=latency,
        detail=f"{len(out)}/{len(locations)} locations" + (f"; errors: {'; '.join(errors)}" if errors else ""),
    )
    if not out:
        raise SourceError("flood API returned nothing: " + "; ".join(errors))
    return out


# ----------------------------------------------------------------- climatology


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def _build_doy_stats(dates: list[str], values: list[float | None], window: int) -> dict[str, dict]:
    """
    Group 30 years of daily discharge by day-of-year with a +/- window, then take
    percentiles. This is what lets the engine say "the 97th percentile for
    mid-September" instead of a bare cumecs number nobody can interpret.
    """
    by_doy: dict[int, list[float]] = {}
    for iso, val in zip(dates, values):
        if val is None:
            continue
        try:
            doy = datetime.strptime(iso, "%Y-%m-%d").timetuple().tm_yday
        except ValueError:
            continue
        by_doy.setdefault(min(doy, 365), []).append(float(val))

    stats: dict[str, dict] = {}
    for doy in range(1, 366):
        pool: list[float] = []
        for offset in range(-window, window + 1):
            d = ((doy - 1 + offset) % 365) + 1
            pool.extend(by_doy.get(d, ()))
        if not pool:
            continue
        pool.sort()
        stats[str(doy)] = {
            "p50": round(_percentile(pool, 50), 3),
            "p75": round(_percentile(pool, 75), 3),
            "p90": round(_percentile(pool, 90), 3),
            "p95": round(_percentile(pool, 95), 3),
            "p99": round(_percentile(pool, 99), 3),
            "max": round(pool[-1], 3),
            "n": len(pool),
        }
    return stats


async def build_climatology(
    client: httpx.AsyncClient,
    locations: Sequence[dict],
    *,
    chunk: int = 8,
    window: int | None = None,
) -> int:
    """
    Fetch the full GloFAS reanalysis for each location once and cache per-day-of-year
    percentiles. Runs in the background on first boot; until it finishes the engine
    falls back to a short-window baseline and says so in the confidence reasons.
    """
    from .config import CLIMATOLOGY_WINDOW_DAYS

    window = CLIMATOLOGY_WINDOW_DAYS if window is None else window
    start = f"{CLIMATOLOGY_START_YEAR}-01-01"
    end = f"{CLIMATOLOGY_END_YEAR}-12-31"
    built = 0

    for batch in _chunks(list(locations), chunk):
        points = [(l.get("glofas_lat", l["lat"]), l.get("glofas_lon", l["lon"])) for l in batch]
        params = {
            **_coord_params(points),
            "daily": "river_discharge",
            "start_date": start,
            "end_date": end,
        }
        try:
            payload = _as_list(await _get_json(client, OPEN_METEO_FLOOD, params, timeout=240), len(batch))
        except Exception as exc:
            store.record_source_health(
                "glofas_climatology", ok=False, latency_ms=None, detail=str(exc)[:200]
            )
            continue

        for (loc, (cell_lat, cell_lon)), item in zip(zip(batch, points), payload):
            daily = item.get("daily") or {}
            stats = _build_doy_stats(
                daily.get("time") or [], daily.get("river_discharge") or [], window
            )
            if stats:
                # Record which cell this baseline describes, so it can be
                # invalidated if the location is later re-snapped.
                store.save_climatology(
                    loc["id"],
                    CLIMATOLOGY_START_YEAR,
                    CLIMATOLOGY_END_YEAR,
                    stats,
                    lat=cell_lat,
                    lon=cell_lon,
                )
                built += 1
        await _pace(len(batch))

    store.record_source_health(
        "glofas_climatology",
        ok=built == len(locations),
        latency_ms=None,
        detail=f"{built}/{len(locations)} locations, {CLIMATOLOGY_START_YEAR}-{CLIMATOLOGY_END_YEAR}",
    )
    return built


# --------------------------------------------------------- archive (replay mode)


async def fetch_archive(
    client: httpx.AsyncClient,
    locations: Sequence[dict],
    start: date,
    end: date,
) -> tuple[dict[str, dict], dict[str, dict]]:
    """
    Historical rainfall and discharge for a past window - the engine behind Event
    Replay ("what would this system have said the day before the 2018 Kerala
    floods?") and behind scripts/train_model.py.
    """
    weather: dict[str, dict] = {}
    flood: dict[str, dict] = {}
    s, e = start.isoformat(), end.isoformat()

    for batch in _chunks(list(locations), BATCH_COORDS):
        wparams = {
            **_coord_params([(l["lat"], l["lon"]) for l in batch]),
            "daily": "precipitation_sum",
            "hourly": HOURLY_VARS,
            "start_date": s,
            "end_date": e,
            "timezone": TIMEZONE,
        }
        try:
            payload = _as_list(await _get_json(client, OPEN_METEO_ARCHIVE, wparams, timeout=120), len(batch))
            for loc, item in zip(batch, payload):
                weather[loc["id"]] = {"hourly": item.get("hourly") or {}, "daily": item.get("daily") or {}}
        except Exception as exc:
            store.record_source_health("open_meteo_archive", ok=False, latency_ms=None, detail=str(exc)[:200])
        await _pace(len(batch))

        fparams = {
            **_coord_params([(l.get("glofas_lat", l["lat"]), l.get("glofas_lon", l["lon"])) for l in batch]),
            "daily": "river_discharge",
            "start_date": s,
            "end_date": e,
        }
        try:
            payload = _as_list(await _get_json(client, OPEN_METEO_FLOOD, fparams, timeout=120), len(batch))
            for loc, item in zip(batch, payload):
                flood[loc["id"]] = {"daily": item.get("daily") or {}}
        except Exception as exc:
            store.record_source_health("glofas_archive", ok=False, latency_ms=None, detail=str(exc)[:200])
        await _pace(len(batch))

    return weather, flood


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=HTTP_TIMEOUT,
        limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
    )


def window_for_replay(target: date, lookback: int = 12, lookahead: int = 4) -> tuple[date, date]:
    """Replay needs history before the event (to build features) and a little after."""
    return target - timedelta(days=lookback), target + timedelta(days=lookahead)
