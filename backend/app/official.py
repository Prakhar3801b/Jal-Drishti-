"""
Official Government of India flood data: CWC river gauges and NDMA SACHET alerts.

Why this module exists
----------------------
The risk engine *estimates* flood risk from modelled rainfall and simulated river
discharge. The Central Water Commission *measures* it: ~1,700 gauge stations, over
a thousand of them with a published warning level, danger level and highest flood
level on record, reporting water levels hourly. And NDMA's SACHET platform carries
the Common Alerting Protocol warnings that IMD, CWC and State Disaster Management
Authorities actually issue.

When a CWC gauge beside a town is above its danger mark, that is not a model
input to be weighed against rainfall - it is the answer. So these sources are used
two ways:

  1. shown directly (gauge layer, official alert feed, per-station hydrographs), and
  2. fused into each location's assessment as a *floor*: the displayed score can
     never be lower than what the official observation implies.

Access notes, verified 2026-09
------------------------------
* CWC Flood Forecasting portal (ffs.india-water.gov.in) serves JSON to its own web
  app without authentication. Endpoints and the query "specification" format were
  taken from the portal's JavaScript bundle. It is not a documented public API and
  can change without notice; every call here degrades to "unavailable" rather than
  failing the refresh.
* NDMA SACHET (sachet.ndma.gov.in) publishes the national CAP alert list as JSON.
* IMD's district warning and nowcast APIs require IP whitelisting on request, so
  IMD warnings are consumed through SACHET, where IMD regional centres publish.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from urllib.parse import urlencode

import httpx

from . import store
from .config import CWC_RELAY, CWC_RELAY_TOKEN, DATA_DIR

log = logging.getLogger("jaldrishti.official")

CWC = "https://ffs.india-water.gov.in"
SACHET = "https://sachet.ndma.gov.in/cap_public_website/FetchAllAlertDetails"
HEADERS = {"User-Agent": "Mozilla/5.0 (JalDrishti flood-risk research prototype)", "Accept": "application/json"}

# The CWC portal does not answer requests from outside India (e.g. a Render
# server in Singapore). JALDRISHTI_CWC_RELAY points at the small relay in
# frontend/api/cwc.js, deployed on Vercel's Mumbai region, which forwards only
# CWC data paths and requires a shared token.
CWC_HOST = "ffs.india-water.gov.in"
RELAY_BATCH = 100

# CWC timestamps are Indian Standard Time without an offset.
IST = timezone(timedelta(hours=5, minutes=30))


def _cwc(path: str) -> str:
    return f"{CWC}{path}"


class _RelayTransport(httpx.AsyncBaseTransport):
    """
    Sends requests for the CWC host to the relay instead, with the original path
    and query in a header; every other host (SACHET, the relay itself) goes
    direct. Call sites keep using plain CWC URLs.
    """

    def __init__(self) -> None:
        self._inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == CWC_HOST:
            headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
            headers["x-cwc-target"] = request.url.raw_path.decode("ascii")
            headers["x-relay-token"] = CWC_RELAY_TOKEN
            request = httpx.Request("GET", CWC_RELAY, headers=headers, extensions=request.extensions)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _client(**kwargs) -> httpx.AsyncClient:
    """HTTP client for CWC/SACHET calls, routed through the relay when configured."""
    kwargs.setdefault("headers", HEADERS)
    if CWC_RELAY:
        kwargs["transport"] = _RelayTransport()
    return httpx.AsyncClient(**kwargs)


def _now_ist() -> datetime:
    return datetime.now(IST).replace(tzinfo=None)

CATALOG_PATH = DATA_DIR / "cwc_stations.json"
CATALOG_MAX_AGE_DAYS = 7
STATES_GEOJSON = DATA_DIR.parent.parent.parent / "frontend" / "public" / "geo" / "india-states.geojson"

GAUGE_RADIUS_KM = 35.0     # a gauge further than this is not "the river beside the town"
SERIES_TTL_S = 600

FLOOD_ALERT_WORDS = ("flood", "rain", "cyclone", "cloudburst", "landslide", "inundation", "surge")
CAP_CERTAINTY = ("observed", "likely", "possible", "unlikely", "unknown")


def _haversine(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _spec_eq(field: str, value: str) -> dict:
    return {"expression": {"valueIsRelationField": False, "fieldName": field, "operator": "eq", "value": value}}


def _spec_and(a: dict, b: dict) -> dict:
    # The portal's query builder nests the first condition under "where" and
    # attaches the second as "and".
    return {"where": a, "and": b}


class OfficialData:
    def __init__(self) -> None:
        self.catalog: dict[str, dict] = {}
        self.catalog_built_at: str | None = None
        self.above: dict[str, dict] = {}
        self.alerts: list[dict] = []
        self.fetched_at: str | None = None
        self.errors: dict[str, str] = {}
        self._series_cache: dict[str, tuple[float, list]] = {}
        # Latest hourly reading per gauge, read directly from the station's own
        # series. CWC's "above warning" summary endpoint periodically returns an
        # empty list, so status is derived from real readings wherever we have them.
        self.latest: dict[str, dict] = {}
        self.readings_at: str | None = None
        self.above_fetched_at: str | None = None
        self._load_catalog()

    # ---------------------------------------------------------------- catalog

    def _load_catalog(self) -> None:
        if not CATALOG_PATH.exists():
            return
        try:
            payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
            self.catalog = {s["code"]: s for s in payload["stations"]}
            self.catalog_built_at = payload.get("built_at")
        except Exception as exc:
            log.warning("could not read CWC catalog: %s", exc)

    def catalog_stale(self) -> bool:
        if not self.catalog or not self.catalog_built_at:
            return True
        try:
            built = datetime.fromisoformat(self.catalog_built_at)
            return (datetime.now(timezone.utc) - built).days >= CATALOG_MAX_AGE_DAYS
        except ValueError:
            return True

    async def build_catalog(self) -> int:
        """
        Station registry with danger marks and coordinates. Static data, rebuilt
        weekly: ~10 s for the level table, ~1 s per 100 coordinates.
        """
        async with _client(timeout=90) as c:
            r = await c.get(_cwc("/iam/api/flood-forecast-static/"), headers={"class-name": "FloodForecastStaticDto"})
            r.raise_for_status()
            static = [s for s in r.json() if s.get("dangerLevel") or s.get("warningLevel")]

            geo: dict[str, dict] = {}
            codes = [s["stationCode"] for s in static]
            for i in range(0, len(codes), 100):
                batch = ",".join(codes[i : i + 100])
                spec = {"expression": {"valueIsRelationField": False, "fieldName": "stationCode", "operator": "in", "value": batch}}
                try:
                    g = await c.get(
                        _cwc("/iam/api/layer-station-geo/specification/"),
                        params={"specification": json.dumps(spec)},
                        headers={"class-name": "LayerStationGeoDto"},
                    )
                    for row in g.json():
                        geo[row["stationCode"]] = row
                except Exception as exc:
                    log.warning("CWC geo batch %d failed: %s", i // 100, exc)
                await asyncio.sleep(0.3)

        state_of = _state_locator()
        stations = []
        for s in static:
            g = geo.get(s["stationCode"])
            if not g or g.get("lat") is None or g.get("lon") is None:
                continue
            lat, lon = float(g["lat"]), float(g["lon"])
            stations.append(
                {
                    "code": s["stationCode"],
                    "name": (g.get("name") or s.get("nearestTown") or s["stationCode"]).strip(),
                    "lat": round(lat, 5),
                    "lon": round(lon, 5),
                    "state": state_of(lat, lon) or s.get("meteorologicalSubDivision"),
                    "type": s.get("type"),
                    "warning_level": s.get("warningLevel"),
                    "danger_level": s.get("dangerLevel"),
                    "hfl": s.get("highestFlowLevel"),
                    "hfl_date": s.get("highestFlowLevelDate"),
                    "subdivision": s.get("meteorologicalSubDivision"),
                }
            )

        built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        CATALOG_PATH.write_text(
            json.dumps(
                {
                    "source": "Central Water Commission, Flood Forecasting portal (ffs.india-water.gov.in)",
                    "built_at": built_at,
                    "stations": stations,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.catalog = {s["code"]: s for s in stations}
        self.catalog_built_at = built_at
        store.record_source_health("cwc_catalog", ok=bool(stations), latency_ms=None, detail=f"{len(stations)} gauges with danger/warning levels")
        return len(stations)

    # ------------------------------------------------------------------- live

    async def refresh(self) -> None:
        """Live gauge exceedances and national alerts. Both calls are fast (<1 s)."""
        async def get_with_retry(c: httpx.AsyncClient, url: str):
            # One retry: a single dropped connection must not blank out a
            # danger-level gauge for a whole refresh cycle.
            for attempt in (1, 2):
                try:
                    r = await c.get(url)
                    if r.status_code == 200 or attempt == 2:
                        return r
                except Exception as exc:
                    if attempt == 2:
                        return exc
                await asyncio.sleep(2)

        async with _client(timeout=httpx.Timeout(45, connect=10)) as c:
            gauges, alerts = await asyncio.gather(
                get_with_retry(c, _cwc("/ffm/api/station-water-level-above-warning/")),
                get_with_retry(c, SACHET),
            )

        if isinstance(gauges, httpx.Response) and gauges.status_code == 200:
            rows = gauges.json()
            if rows or not self.above:
                self.above = {row["stationCode"]: row for row in rows}
                self.above_fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            # else: an empty list right after a non-empty one is the portal
            # resetting, not every river falling at once - keep the last list.
            self.errors.pop("cwc", None)
            store.record_source_health("cwc_live", ok=True, latency_ms=None, detail=f"{len(self.above)} gauges above warning")
        else:
            self.errors["cwc"] = repr(gauges)[:200] if not isinstance(gauges, httpx.Response) else f"HTTP {gauges.status_code}"
            store.record_source_health("cwc_live", ok=False, latency_ms=None, detail=self.errors["cwc"])

        if isinstance(alerts, httpx.Response) and alerts.status_code == 200:
            self.alerts = [a for a in (_normalise_alert(x) for x in alerts.json()) if a]
            self.errors.pop("sachet", None)
            store.record_source_health("ndma_sachet", ok=True, latency_ms=None, detail=f"{len(self.alerts)} active alerts")
        else:
            self.errors["sachet"] = repr(alerts)[:200] if not isinstance(alerts, httpx.Response) else f"HTTP {alerts.status_code}"
            store.record_source_health("ndma_sachet", ok=False, latency_ms=None, detail=self.errors["sachet"])

        self.fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def station_status(self, code: str) -> dict:
        st = self.catalog.get(code, {})
        danger, warning = st.get("danger_level"), st.get("warning_level")
        reading = self.latest.get(code)
        live = self.above.get(code)
        observed_at = None

        if reading:
            # Our own read of the station's latest hourly level wins: it is the
            # primary observation, not a derived summary.
            value, trend, observed_at = reading["level_m"], reading.get("trend"), reading["time"]
            if danger and value >= danger:
                status = "DANGER"
            elif warning and value >= warning:
                status = "WARNING"
            else:
                status = "NORMAL"
        elif live:
            value = live.get("value")
            status = (live.get("status") or "WARNING").upper()
            trend = (live.get("trend") or "").upper() or None
        else:
            # Neither a reading nor a listing: below warning as far as CWC reports.
            value, status, trend = None, "NORMAL", None

        return {
            **st,
            "status": status,
            "trend": trend,
            "level_m": value,
            "observed_at": observed_at,
            "above_danger_m": round(value - danger, 2) if (value is not None and danger) else None,
        }

    async def refresh_readings(self, codes: Sequence[str]) -> int:
        """
        Latest hourly level for specific gauges, eight at a time directly or a
        hundred per call through the relay. Readings older than 24 h are
        discarded as a stalled telemetry feed. If the portal cannot be reached
        at all, give up after one quick probe instead of timing out per gauge.
        """
        codes = [c for c in dict.fromkeys(codes) if c in self.catalog]
        if not codes:
            return 0
        now = _now_ist()
        fresh = 0
        failed = 0
        sort = json.dumps({"sortOrderDtos": [{"sortDirection": "DESC", "field": "id.dataTime"}]})

        def params_for(code: str) -> dict:
            spec = _spec_and(_spec_eq("id.stationCode", code), _spec_eq("id.datatypeCode", "HHS"))
            return {"sort-criteria": sort, "page-number": "0", "page-size": "4", "specification": json.dumps(spec)}

        def ingest(code: str, rows: list | None) -> None:
            nonlocal fresh, failed
            if rows is None:
                failed += 1
                return
            rows = [x for x in rows if x.get("dataValue") is not None]
            if not rows:
                return
            t = rows[0]["id"]["dataTime"]
            try:
                if (now - datetime.fromisoformat(t)).total_seconds() > 86400:
                    self.latest.pop(code, None)
                    return
            except ValueError:
                return
            trend = None
            if len(rows) >= 3:
                delta = rows[0]["dataValue"] - rows[2]["dataValue"]
                trend = "RISING" if delta > 0.02 else "FALLING" if delta < -0.02 else "STEADY"
            self.latest[code] = {"level_m": rows[0]["dataValue"], "time": t, "trend": trend}
            fresh += 1

        async with _client(timeout=httpx.Timeout(30, connect=10)) as c:
            if CWC_RELAY:
                async def batch(chunk: list[str]) -> None:
                    body = {"items": [{"path": "/iam/api/new-entry-data/specification/sorted-page", "params": params_for(code), "className": "NewEntryDataDto"} for code in chunk]}
                    results = None
                    for attempt in range(2):
                        try:
                            r = await c.post(CWC_RELAY, json=body, headers={"x-relay-token": CWC_RELAY_TOKEN}, timeout=httpx.Timeout(60, connect=10))
                            if r.status_code == 200:
                                results = r.json().get("results")
                                break
                            log.warning("CWC relay batch HTTP %s: %s", r.status_code, r.text[:120])
                        except Exception as exc:
                            log.warning("CWC relay batch failed: %r", exc)
                        await asyncio.sleep(3)
                    for i, code in enumerate(chunk):
                        item = results[i] if results and i < len(results) else None
                        ingest(code, item.get("data") if item and item.get("status") == 200 and isinstance(item.get("data"), list) else None)

                chunks = [codes[i : i + RELAY_BATCH] for i in range(0, len(codes), RELAY_BATCH)]
                sem = asyncio.Semaphore(3)

                async def guarded(chunk: list[str]) -> None:
                    async with sem:
                        await batch(chunk)

                await asyncio.gather(*(guarded(ch) for ch in chunks))
            else:
                try:
                    await c.get(_cwc("/ffm/api/station-water-level-above-warning/"), timeout=httpx.Timeout(12, connect=8))
                except httpx.TransportError as exc:
                    msg = f"CWC portal unreachable from this server ({type(exc).__name__}); set JALDRISHTI_CWC_RELAY"
                    log.warning(msg)
                    self.errors["cwc"] = msg
                    store.record_source_health("cwc_readings", ok=False, latency_ms=None, detail=msg)
                    return 0

                sem = asyncio.Semaphore(8)

                async def one(code: str) -> None:
                    rows = None
                    async with sem:
                        # The portal answers 500 for every station during its own
                        # brief outages, so retry with backoff before giving up. A
                        # gauge that still fails keeps its previous reading.
                        for attempt in range(3):
                            try:
                                r = await c.get(
                                    _cwc("/iam/api/new-entry-data/specification/sorted-page"),
                                    params=params_for(code),
                                    headers={"class-name": "NewEntryDataDto"},
                                )
                                if r.status_code == 200:
                                    rows = r.json()
                                    break
                            except Exception:
                                pass
                            await asyncio.sleep(1.5 * (attempt + 1))
                    ingest(code, rows)

                await asyncio.gather(*(one(code) for code in codes))

        detail = f"{fresh}/{len(codes)} gauges reporting in last 24 h" + (" via relay" if CWC_RELAY else "")
        if failed:
            detail += f"; portal failed for {failed}, last reading kept"
        store.record_source_health("cwc_readings", ok=fresh > 0, latency_ms=None, detail=detail)
        self.readings_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return fresh

    def nearest_codes(self, points: Sequence[tuple[float, float]]) -> list[str]:
        out = []
        for lat, lon in points:
            g = self.nearest_gauge(lat, lon)
            if g:
                out.append(g["code"])
        return out

    def stations_payload(self, only_alerting: bool = False) -> list[dict]:
        rows = [self.station_status(code) for code in self.catalog]
        if only_alerting:
            rows = [r for r in rows if r["status"] != "NORMAL"]
        order = {"DANGER": 0, "WARNING": 1, "NORMAL": 2}
        rows.sort(key=lambda r: (order.get(r["status"], 3), -(r.get("above_danger_m") or -99)))
        return rows

    # ---------------------------------------------------------------- series

    async def series(self, code: str, hours: int = 120) -> list[dict]:
        """Hourly observed water level (CWC datatype HHS), oldest first."""
        cached = self._series_cache.get(code)
        if cached and time.time() - cached[0] < SERIES_TTL_S:
            return cached[1]
        spec = _spec_and(_spec_eq("id.stationCode", code), _spec_eq("id.datatypeCode", "HHS"))
        sort = {"sortOrderDtos": [{"sortDirection": "DESC", "field": "id.dataTime"}]}
        async with _client(timeout=45) as c:
            r = await c.get(
                _cwc("/iam/api/new-entry-data/specification/sorted-page"),
                params={"sort-criteria": json.dumps(sort), "page-number": "0", "page-size": str(hours), "specification": json.dumps(spec)},
                headers={"class-name": "NewEntryDataDto"},
            )
        r.raise_for_status()
        rows = [
            {"time": x["id"]["dataTime"], "level_m": x["dataValue"]}
            for x in r.json()
            if x.get("dataValue") is not None
        ]
        rows.reverse()
        self._series_cache[code] = (time.time(), rows)
        return rows

    async def official_forecast(self, code: str) -> list[dict]:
        """CWC's own issued level forecast (datatype HHF), where one exists."""
        spec = _spec_and(_spec_eq("id.stationCode", code), _spec_eq("id.datatypeCode", "HHF"))
        sort = {"sortOrderDtos": [{"sortDirection": "DESC", "field": "id.issuedDate"}]}
        try:
            async with _client(timeout=30) as c:
                r = await c.get(
                    _cwc("/iam/api/new-forecasted-entry-data/specification/sorted-page"),
                    params={"sort-criteria": json.dumps(sort), "page-number": "0", "page-size": "12", "specification": json.dumps(spec)},
                    headers={"class-name": "NewForecastedEntryDataDto"},
                )
            if r.status_code != 200:
                return []
            out = []
            for x in r.json():
                ident = x.get("id") or {}
                if x.get("dataValue") is None:
                    continue
                out.append({"time": ident.get("forecastedDate"), "issued": ident.get("issuedDate"), "level_m": x["dataValue"]})
            out.sort(key=lambda row: row["time"] or "")
            return out
        except Exception:
            return []

    # ---------------------------------------------------------------- fusion

    def nearest_gauge(self, lat: float, lon: float) -> dict | None:
        best, best_d = None, GAUGE_RADIUS_KM
        for code, st in self.catalog.items():
            if not st.get("danger_level"):
                continue
            d = _haversine(lat, lon, st["lat"], st["lon"])
            if d < best_d:
                best, best_d = code, d
        if best is None:
            return None
        return {**self.station_status(best), "distance_km": round(best_d, 1)}

    def alerts_near(self, lat: float, lon: float) -> list[dict]:
        hits = []
        for a in self.alerts:
            if not a["flood_related"] or a["lat"] is None:
                continue
            d = _haversine(lat, lon, a["lat"], a["lon"])
            if d <= a["radius_km"] + 10:
                hits.append({**a, "distance_km": round(d, 1)})
        rank = {"red": 0, "orange": 1, "yellow": 2}
        hits.sort(key=lambda a: rank.get(a["colour"], 3))
        return hits

    def fuse(self, lat: float, lon: float) -> dict:
        """
        What the official record says about this place, and the minimum score it
        implies. A gauge above danger sets a Red floor, above warning an Orange
        floor; an official red/orange/yellow flood-related alert covering the
        location sets the matching floor.
        """
        gauge = self.nearest_gauge(lat, lon)
        alerts = self.alerts_near(lat, lon)
        floor, reasons_en, reasons_hi = 0.0, [], []

        if gauge and gauge["status"] == "DANGER":
            exceed = max(gauge.get("above_danger_m") or 0.0, 0.0)
            rising = 5.0 if gauge.get("trend") == "RISING" else 0.0
            floor = max(floor, min(95.0, 76.0 + 12.0 * exceed + rising))
            reasons_en.append(
                f"CWC gauge {gauge['name']} ({gauge['distance_km']} km) reads {gauge['level_m']} m, "
                f"{gauge['above_danger_m']} m above its danger level of {gauge['danger_level']} m"
                + (", and rising" if rising else "")
            )
            reasons_hi.append(
                f"केंद्रीय जल आयोग का गेज {gauge['name']} ({gauge['distance_km']} किमी) {gauge['level_m']} मी पर है, "
                f"खतरे के निशान {gauge['danger_level']} मी से {gauge['above_danger_m']} मी ऊपर"
                + (" और बढ़ रहा है" if rising else "")
            )
        elif gauge and gauge["status"] == "WARNING":
            span = (gauge["danger_level"] or 0) - (gauge.get("warning_level") or 0)
            frac = 0.0
            if gauge.get("level_m") is not None and gauge.get("warning_level") and span > 0:
                frac = max(0.0, min(1.0, (gauge["level_m"] - gauge["warning_level"]) / span))
            floor = max(floor, 52.0 + 20.0 * frac + (3.0 if gauge.get("trend") == "RISING" else 0.0))
            reasons_en.append(
                f"CWC gauge {gauge['name']} ({gauge['distance_km']} km) is above its warning level"
                + (f" at {gauge['level_m']} m (danger mark {gauge['danger_level']} m)" if gauge.get("level_m") is not None else "")
            )
            reasons_hi.append(f"केंद्रीय जल आयोग का गेज {gauge['name']} ({gauge['distance_km']} किमी) चेतावनी स्तर से ऊपर है")

        for a in alerts[:1]:
            implied = {"red": 78.0, "orange": 55.0, "yellow": 30.0}.get(a["colour"], 0.0)
            if implied > 0:
                floor = max(floor, implied)
                reasons_en.append(f"Official {a['colour']} alert from {a['source']}: {a['type']} ({a['area'][:80]})")
                reasons_hi.append(f"{a['source']} की आधिकारिक {a['colour']} चेतावनी: {a['type']}")

        return {
            "gauge": gauge,
            "alerts": alerts[:5],
            "floor": round(floor, 1),
            "reasons_en": reasons_en,
            "reasons_hi": reasons_hi,
            "fetched_at": self.fetched_at,
        }

    def summary(self) -> dict:
        from collections import Counter

        statuses = Counter(self.station_status(c)["status"] for c in self.catalog)
        read = len(self.latest)
        colours = Counter(a["colour"] for a in self.alerts)
        flood = [a for a in self.alerts if a["flood_related"]]
        return {
            "fetched_at": self.fetched_at,
            "catalog_built_at": self.catalog_built_at,
            "gauges": {
                "catalogued": len(self.catalog),
                "danger": statuses.get("DANGER", 0),
                "warning": statuses.get("WARNING", 0),
                "above_warning_nationally": len(self.above),
                "national_list_fetched_at": self.above_fetched_at,
                "stations_read_directly": read,
                "readings_at": self.readings_at,
            },
            "alerts": {
                "total": len(self.alerts),
                "flood_related": len(flood),
                "by_colour": dict(colours),
                "by_source": dict(Counter(a["source"] for a in self.alerts).most_common(10)),
            },
            "errors": self.errors,
            "sources": {
                "cwc": "Central Water Commission — ffs.india-water.gov.in",
                "sachet": "NDMA SACHET Common Alerting Protocol — sachet.ndma.gov.in",
            },
        }


def _normalise_alert(a: dict) -> dict | None:
    try:
        lon, lat = (float(x) for x in str(a.get("centroid", "")).split(","))
    except ValueError:
        lat = lon = None
    try:
        area = float(a.get("area_covered") or 0.0)
    except ValueError:
        area = 0.0
    kind = str(a.get("disaster_type") or "")
    colour = str(a.get("severity_color") or "").lower()
    # SACHET's severity_level carries the CAP certainty for IMD alerts ("Likely")
    # but the river trend for CWC flood alerts ("rising"); keep them apart.
    level = str(a.get("severity_level") or "").strip()
    certainty = level.title() if level.lower() in CAP_CERTAINTY else None
    trend = level.lower() if level.lower() in ("rising", "falling", "steady") else None
    return {
        "id": str(a.get("identifier")),
        "source": a.get("alert_source") or "NDMA SACHET",
        "type": kind,
        "severity": a.get("severity"),
        "certainty": certainty,
        "trend": trend,
        "colour": colour,
        "area": a.get("area_description") or "",
        "message": a.get("warning_message") or "",
        "start": a.get("effective_start_time"),
        "end": a.get("effective_end_time"),
        "lat": lat,
        "lon": lon,
        "area_km2": round(area, 1),
        # The feed gives a centroid and an area, not a polygon: treat the alert as
        # a disc of equal area. Generous for long thin districts, which is the
        # safe direction for a warning.
        "radius_km": round(math.sqrt(area / math.pi), 1) if area > 0 else 15.0,
        "flood_related": any(w in kind.lower() for w in FLOOD_ALERT_WORDS),
    }


def _state_locator():
    """Point-in-polygon against the state boundaries the map already uses."""
    try:
        from shapely.geometry import Point, shape
        from shapely.prepared import prep

        gj = json.loads(STATES_GEOJSON.read_text(encoding="utf-8"))
        polys = [(f["properties"]["st_nm"], prep(shape(f["geometry"]))) for f in gj["features"]]

        def locate(lat: float, lon: float) -> str | None:
            pt = Point(lon, lat)
            for name, poly in polys:
                if poly.contains(pt):
                    return name
            return None

        return locate
    except Exception as exc:  # shapely missing or file moved: fall back to CWC sub-division
        log.warning("state lookup unavailable: %s", exc)
        return lambda lat, lon: None


official = OfficialData()
