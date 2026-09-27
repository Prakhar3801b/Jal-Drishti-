"""
FastAPI application entry point.

The background scheduler is a plain asyncio task rather than APScheduler: one
periodic job does not justify a dependency, and this way the refresh loop shares
the event loop (and therefore the HTTP client pool) with the request handlers.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import store
from .api import router
from .gateway import gateway_router
from .config import (
    APP_NAME,
    APP_TAGLINE_EN,
    CORS_ORIGIN_REGEX,
    CORS_ORIGINS,
    REFRESH_MINUTES,
    REFRESH_ON_STARTUP,
    VERSION,
)
from .engine import engine

log = logging.getLogger("jaldrishti")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s")


async def _refresh_loop() -> None:
    """Re-score every REFRESH_MINUTES so the dashboard tracks changing conditions."""
    while True:
        # Until a first snapshot exists (e.g. the startup pull was rate limited),
        # retry every few minutes rather than leaving the dashboard empty.
        live = engine.snapshot is not None and engine.snapshot.trigger != "restored"
        await asyncio.sleep(REFRESH_MINUTES * 60 if live else FIRST_RUN_RETRY_S)
        if engine.refreshing:
            continue
        try:
            snap = await engine.refresh("schedule")
            log.info("scheduled refresh ok: run %s, %d locations", snap.run_id, len(snap.assessments))
        except Exception as exc:
            log.warning("scheduled refresh failed, keeping previous snapshot: %s", exc)


async def _notify_loop() -> None:
    """
    Push alerts out automatically: after every new scoring run, send each
    opted-in official the alerts for their area they have not had yet, and the
    daily brief once a day. Delivery goes through the automation webhook.
    """
    from . import notify, rivers

    notify.init()
    last_run = None
    while True:
        await asyncio.sleep(60)
        snap = engine.snapshot
        if snap is None or snap.trigger == "restored":
            continue
        try:
            waves = {r["id"]: r["threats"] for r in await asyncio.to_thread(rivers.towns_in_path)}
            if snap.run_id != last_run:
                counts = await notify.dispatch(snap, waves)
                last_run = snap.run_id
                # Re-optimise resource allocation against the new risk picture.
                from . import planning

                try:
                    await asyncio.to_thread(planning.current, snap, waves, "new risk data")
                except Exception as exc:
                    log.warning("re-planning failed: %s", exc)
                if any(counts.values()):
                    log.info("notifications for run %s: %s", snap.run_id, counts)
            sent = await notify.daily_brief_if_due(snap, waves)
            if sent:
                log.info("daily brief sent to %d recipients", sent)
        except Exception as exc:
            log.warning("notification dispatch failed: %s", exc)


KEEPALIVE_MINUTES = 10


async def _keepalive_loop() -> None:
    """
    Keep a free-tier host awake. Render's free plan spins an instance down after
    15 minutes without inbound traffic, which would also stop the gauge sweep,
    the refresh and the alert dispatch. A request to our own public URL goes in
    through Render's proxy and counts as traffic. Render sets RENDER_EXTERNAL_URL;
    JALDRISHTI_KEEPALIVE_URL overrides it (empty = off, e.g. when running locally).
    """
    import os

    import httpx

    base = os.getenv("JALDRISHTI_KEEPALIVE_URL", os.getenv("RENDER_EXTERNAL_URL", "")).strip().rstrip("/")
    if not base:
        return
    log.info("keep-alive: pinging %s/api/health every %d min", base, KEEPALIVE_MINUTES)
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "JalDrishti-keepalive"}) as client:
        while True:
            await asyncio.sleep(KEEPALIVE_MINUTES * 60)
            try:
                r = await client.get(f"{base}/api/health")
                if r.status_code >= 400:
                    log.warning("keep-alive ping answered HTTP %s", r.status_code)
            except Exception as exc:
                log.warning("keep-alive ping failed: %s", exc)


GAUGE_SWEEP_MINUTES = 15
FIRST_RUN_RETRY_S = 240


async def _gauge_loop() -> None:
    """
    Read every CWC gauge on its own, faster cadence than the weather refresh:
    river levels move hourly and the portal publishes hourly. When a gauge that
    sits beside a monitored town changes tier, re-score the towns so the
    official-data floor follows the river without waiting 90 minutes.
    """
    from .official import official
    from .engine import LOCATIONS

    await asyncio.sleep(20)  # let the bootstrap load the catalogue first
    while True:
        try:
            if official.catalog:
                near = set(official.nearest_codes([(l["lat"], l["lon"]) for l in LOCATIONS]))
                before = {c: official.station_status(c)["status"] for c in near}
                n = await official.refresh_readings(list(official.catalog.keys()))
                changed = [c for c in near if official.station_status(c)["status"] != before[c]]
                log.info("gauge sweep: %d gauges reporting, %d town gauges changed tier", n, len(changed))
                # Rebuild "towns in the path of a flood wave" from the new readings
                # now, so no page waits for it.
                from . import rivers

                rivers._path_cache["ts"] = 0.0
                await asyncio.to_thread(rivers.towns_in_path)
                if changed and engine.snapshot is not None and not engine.refreshing:
                    await engine.refresh("gauges")
        except Exception as exc:
            log.warning("gauge sweep failed: %s", exc)
        await asyncio.sleep(GAUGE_SWEEP_MINUTES * 60)


async def _build_travel() -> None:
    """Road drive times from every depot to every monitored place (OSRM, cached a week)."""
    from . import resources, travel
    from .engine import LOCATIONS

    places = [{"id": l["id"], "lat": l["lat"], "lon": l["lon"]} for l in LOCATIONS]
    ndrf = [{"id": d["id"], "lat": d["lat"], "lon": d["lon"]} for d in resources.depots() if d["kind"] == "ndrf"]
    await travel.build(ndrf + places, places)
    log.info("travel matrix: %s", travel.status())


async def _bootstrap() -> None:
    """
    Boot in the order that gets a usable screen soonest:
      1. score immediately against a short baseline
      2. build the 30-year climatology in the background
      3. re-score, now with real seasonal context
    """
    try:
        from .official import official

        if official.catalog_stale():
            n = await official.build_catalog()
            log.info("CWC gauge catalogue built: %d stations", n)
    except Exception as exc:
        log.warning("CWC catalogue unavailable, continuing model-only: %s", exc)

    try:
        from .config import DATA_DIR

        seeded = store.seed_climatology(DATA_DIR / "climatology_seed.json.gz")
        if seeded:
            log.info("climatology seeded from bundled file for %d locations", seeded)
    except Exception as exc:
        log.warning("climatology seed not loaded: %s", exc)

    try:
        await engine.load_climatology()
        if REFRESH_ON_STARTUP:
            snap = await engine.refresh("startup")
            log.info("startup refresh ok: run %s, %d locations", snap.run_id, len(snap.assessments))
    except Exception as exc:
        log.error("startup refresh failed: %s", exc)

    asyncio.create_task(_build_travel())

    try:
        built = await engine.ensure_climatology()
        if built:
            log.info("climatology built for %d locations; re-scoring", built)
            await engine.refresh("climatology")
    except Exception as exc:
        log.warning("climatology build failed, staying on the recent-window baseline: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    try:
        from . import apikeys
        apikeys.init_api_keys_db()
        log.info("API gateway tables ready")
    except Exception as exc:
        log.warning("API gateway table init failed (gateway unavailable): %s", exc)
    log.info("%s %s starting; refresh every %d min", APP_NAME, VERSION, REFRESH_MINUTES)
    try:
        from . import auth
        from .engine import LOCATIONS

        from . import notify

        notify.init()
        added = auth.init(LOCATIONS)
        from . import planning, resources

        resources.init()
        planning.init()
        seeded = notify.seed_from_env()
        if seeded:
            log.info("restored %d alert recipients from JALDRISHTI_NOTIFY_RECIPIENTS", seeded)
        if added:
            log.info("created %d sign-in accounts (central, states, districts)", added)
    except Exception as exc:
        log.warning("account setup failed: %s", exc)
    try:
        restored = engine.restore_last()
        if restored:
            log.info("serving stored run %s (%d locations) until the first live pass lands", restored.run_id, len(restored.assessments))
    except Exception as exc:
        log.warning("could not restore last run: %s", exc)
    boot = asyncio.create_task(_bootstrap())
    loop = asyncio.create_task(_refresh_loop())
    gauges = asyncio.create_task(_gauge_loop())
    notifier = asyncio.create_task(_notify_loop())
    keepalive = asyncio.create_task(_keepalive_loop())
    try:
        yield
    finally:
        for task in (boot, loop, gauges, notifier, keepalive):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title=f"{APP_NAME} API",
    description=(
        f"{APP_TAGLINE_EN}. A prototype hyperlocal flood risk engine for India built on "
        "Open-Meteo weather, GloFAS river discharge, Copernicus DEM and OpenStreetMap. "
        "Not an official Government of India service."
    ),
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(gateway_router)


@app.get("/", include_in_schema=False)
def root() -> JSONResponse:
    return JSONResponse(
        {
            "name": APP_NAME,
            "version": VERSION,
            "docs": "/docs",
            "api": "/api/system",
            "note": "Prototype. Not an official Government of India service.",
        }
    )
