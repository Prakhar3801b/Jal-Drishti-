"""
REST surface.

Endpoint shapes follow the country -> state -> hyperlocal drill-down of the UI,
because that is also how CWC and NDMA structure flood response, so each screen
makes exactly one call.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from . import engine as eng
from . import cap, consensus, copilot, explain, llm, store
from .ml import ml
from .nowcast import status as nowcast_status

log = logging.getLogger("jaldrishti.api")
from .config import (
    ALERT_TIERS,
    APP_NAME,
    APP_TAGLINE_EN,
    APP_TAGLINE_HI,
    CLIMATOLOGY_END_YEAR,
    CLIMATOLOGY_START_YEAR,
    FACTOR_LABELS,
    IMD_RAIN_CLASSES,
    REFRESH_MINUTES,
    VERSION,
    WEIGHTS,
)
from .engine import EVENTS, LOCATIONS, LOCATIONS_BY_ID, engine
from .risk import load_ml_model

router = APIRouter(prefix="/api")


def _user(authorization: str | None = Header(default=None)) -> dict:
    from .auth import current_user

    return current_user(authorization)


def _admin(authorization: str | None = Header(default=None)) -> dict:
    """Officials only (central, state, district): citizens get 403."""
    from .auth import require_admin

    return require_admin(authorization)


# ------------------------------------------------------------------ area scope
#
# Every data endpoint answers for the signed-in user's area only: Central sees
# all of India, a State user one state, a District user (or a citizen, for their
# home district) one district. Places are
# filtered by the snapshot; gauges and official alerts by state name or by
# distance to the user's places, since neither carries a district.

GAUGE_NEAR_KM = 40.0


def _scoped(snap, user: dict):
    """The snapshot limited to the user's places (the same object for Central)."""
    if user["role"] == "central":
        return snap
    from .auth import in_scope

    sub = eng.Snapshot(
        snap.run_id,
        [a for a in snap.assessments if in_scope(a["location"], user)],
        snap.computed_at,
        snap.duration_ms,
        snap.trigger,
        snap.degraded,
    )
    sub.replay_date = getattr(snap, "replay_date", None)
    return sub


def _check_place(location_id: str, user: dict) -> dict:
    from .auth import in_scope

    loc = LOCATIONS_BY_ID.get(location_id)
    if loc is None:
        raise HTTPException(status_code=404, detail=f"Unknown location '{location_id}'")
    if not in_scope(loc, user):
        raise HTTPException(status_code=403, detail=f"{loc['name']} is outside your area.")
    return loc


def _scope_places(user: dict) -> list[dict]:
    from .auth import in_scope

    return [l for l in LOCATIONS if in_scope(l, user)]


def _gauge_in_scope(g: dict, user: dict, places: list[dict]) -> bool:
    if user["role"] == "central":
        return True
    from .official import _haversine

    near = g.get("lat") is not None and any(
        _haversine(g["lat"], g["lon"], p["lat"], p["lon"]) <= GAUGE_NEAR_KM for p in places
    )
    if user["role"] in ("district", "citizen"):
        return near
    return near or user["state"].lower() in (g.get("state") or "").lower()


def _alert_in_scope(a: dict, user: dict, places: list[dict]) -> bool:
    if user["role"] == "central":
        return True
    from .official import _haversine

    area = (a.get("area") or "").lower()
    name = (user["district"] if user["role"] in ("district", "citizen") else user["state"]).lower()
    if name in area:
        return True
    return a.get("lat") is not None and any(
        _haversine(a["lat"], a["lon"], p["lat"], p["lon"]) <= (a.get("radius_km") or 15.0) for p in places
    )


async def _snapshot(date_str: str | None, user: dict | None = None):
    """Live snapshot, or the Time Machine snapshot when ?date=YYYY-MM-DD is given."""
    if not date_str:
        return _require_snapshot()
    if user is not None and user["role"] == "citizen":
        raise HTTPException(status_code=403, detail="Historical replay is for officials only.")
    try:
        when = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    if when >= date.today() or when < date(1994, 1, 1):
        raise HTTPException(status_code=400, detail="Replay dates must be between 1994-01-01 and yesterday")
    try:
        return await engine.snapshot_for_date(when)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Historical replay unavailable: {exc}")


def _require_snapshot():
    if engine.snapshot is None:
        raise HTTPException(
            status_code=503,
            detail="No snapshot yet — the first ingestion run is still in flight. Retry in a few seconds.",
        )
    return engine.snapshot


def _weather_meta(snapshot) -> dict:
    """How fresh the weather behind this run is, and whether the source is paused."""
    from .sources import limit_status

    as_of = getattr(snapshot, "weather_as_of", snapshot.computed_at)
    paused = limit_status()
    return {
        "weather_mode": getattr(snapshot, "weather_mode", "live"),
        "weather_as_of": as_of.isoformat(timespec="seconds"),
        "weather_age_seconds": int((datetime.now(timezone.utc) - as_of).total_seconds()),
        "weather_paused_until": datetime.fromtimestamp(paused["until"], timezone.utc).isoformat(timespec="seconds") if paused["paused"] else None,
        "weather_pause_kind": paused["kind"],
    }


def _meta(snapshot) -> dict:
    """The 'is this live?' block every screen shows."""
    age = (datetime.now(timezone.utc) - snapshot.computed_at).total_seconds()
    if getattr(snapshot, "replay_date", None):
        return {
            "mode": "replay",
            "replay_date": snapshot.replay_date,
            "run_id": 0,
            "computed_at": snapshot.computed_at.isoformat(timespec="seconds"),
            "age_seconds": 0,
            "duration_ms": snapshot.duration_ms,
            "trigger": "replay",
            "refresh_minutes": REFRESH_MINUTES,
            "next_refresh_in_seconds": 0,
            "locations": len(snapshot.assessments),
            "degraded": snapshot.degraded,
            "refreshing": False,
            "climatology_locations": len(engine.climatology),
            "climatology_years": f"{CLIMATOLOGY_START_YEAR}-{CLIMATOLOGY_END_YEAR}",
        }
    return {
        "mode": "live",
        "run_id": snapshot.run_id,
        "computed_at": snapshot.computed_at.isoformat(timespec="seconds"),
        "age_seconds": int(age),
        "duration_ms": snapshot.duration_ms,
        "trigger": snapshot.trigger,
        "refresh_minutes": REFRESH_MINUTES,
        "next_refresh_in_seconds": max(0, int(REFRESH_MINUTES * 60 - age)),
        "locations": len(snapshot.assessments),
        "degraded": snapshot.degraded,
        "refreshing": engine.refreshing,
        **_weather_meta(snapshot),
        "climatology_locations": len(engine.climatology),
        "climatology_years": f"{CLIMATOLOGY_START_YEAR}-{CLIMATOLOGY_END_YEAR}",
    }


# ------------------------------------------------------------------ meta/system


@router.get("/system", summary="App identity, model card and data-source health")
def system() -> dict:
    model = load_ml_model()
    return {
        "app": {
            "name": APP_NAME,
            "version": VERSION,
            "tagline_en": APP_TAGLINE_EN,
            "tagline_hi": APP_TAGLINE_HI,
            "disclaimer_en": (
                "Prototype for research and demonstration. Not an official Government of India "
                "service and not a public flood warning. For operational warnings follow IMD, "
                "CWC and your State Disaster Management Authority."
            ),
            "disclaimer_hi": (
                "यह शोध एवं प्रदर्शन हेतु प्रोटोटाइप है। यह भारत सरकार की आधिकारिक सेवा नहीं है "
                "और न ही सार्वजनिक बाढ़ चेतावनी। आधिकारिक चेतावनी के लिए IMD, CWC एवं राज्य "
                "आपदा प्रबंधन प्राधिकरण का पालन करें।"
            ),
        },
        "model": {
            "kind": "hybrid weighted-rule score blended with a logistic classifier",
            "features": [
                {"key": k, "weight": w, "label_en": FACTOR_LABELS[k][0], "label_hi": FACTOR_LABELS[k][1]}
                for k, w in WEIGHTS.items()
            ],
            "alert_tiers": ALERT_TIERS,
            "imd_rain_classes": IMD_RAIN_CLASSES,
            "trained_model": model.as_dict() if model else None,
        },
        "sources": eng.source_manifest(),
        "coverage": {
            "locations": len(LOCATIONS),
            "states": len({l["state"] for l in LOCATIONS}),
            "historical_events": len(EVENTS),
            "enriched": eng.ENRICHED,
        },
        "runs": store.recent_runs(10),
        "status": {
            "has_snapshot": engine.snapshot is not None,
            "refreshing": engine.refreshing,
            "last_error": engine.last_error,
            "climatology_locations": len(engine.climatology),
        },
    }


@router.get("/health", summary="Liveness probe")
def health() -> dict:
    return {
        "ok": engine.snapshot is not None,
        "refreshing": engine.refreshing,
        "locations": len(engine.snapshot.assessments) if engine.snapshot else 0,
        "last_error": engine.last_error,
    }


# --------------------------------------------------------------- country view


@router.get("/country/summary", summary="National roll-up for the India choropleth")
async def country_summary(date: str | None = None, user: dict = Depends(_user)) -> dict:
    snap = _scoped(await _snapshot(date, user), user)
    states = eng.state_rollup(snap)
    counts = snap.tier_counts
    worst = snap.worst(6)

    return {
        "meta": _meta(snap),
        "counts": counts,
        "total_locations": len(snap.assessments),
        "states": states,
        "summary": explain.national_summary_text(counts, len(snap.assessments), worst),
        "population_at_risk": sum(s["population_at_risk"] for s in states),
        "worst": [
            {
                "id": a["location"]["id"],
                "name": a["location"]["name"],
                "name_hi": a["location"].get("name_hi"),
                "state": a["location"]["state"],
                "river": a["location"].get("river"),
                "lat": a["location"]["lat"],
                "lon": a["location"]["lon"],
                "score": a["risk"]["score"],
                "tier": a["risk"]["tier"]["key"],
                "direction": a["risk"]["direction"],
                "confidence": a["confidence"]["level"],
                "headline_en": a["explanation"]["headline_en"],
                "headline_hi": a["explanation"]["headline_hi"],
            }
            for a in worst
        ],
        "basins": _basin_rollup(snap),
    }


def _basin_rollup(snap) -> list[dict]:
    """Risk by CWC river basin — the axis a water-resources engineer thinks in."""
    from collections import Counter, defaultdict

    grouped: dict[str, list[dict]] = defaultdict(list)
    for a in snap.assessments:
        grouped[a["location"].get("cwc_basin") or "Other"].append(a)
    rows = []
    for basin, items in grouped.items():
        scores = [a["risk"]["score"] for a in items]
        counts = Counter(a["risk"]["tier"]["key"] for a in items)
        rows.append(
            {
                "basin": basin,
                "score": round(max(scores), 1),
                "mean_score": round(sum(scores) / len(scores), 1),
                "locations": len(items),
                "counts": {k: counts.get(k, 0) for k in ("red", "orange", "yellow", "green")},
            }
        )
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


@router.get("/locations", summary="Every monitored location with its current score")
async def all_locations(date: str | None = None, user: dict = Depends(_user)) -> dict:
    snap = _scoped(await _snapshot(date, user), user)
    return {
        "meta": _meta(snap),
        "locations": [
            {
                "id": a["location"]["id"],
                "name": a["location"]["name"],
                "name_hi": a["location"].get("name_hi"),
                "state": a["location"]["state"],
                "district": a["location"].get("district"),
                "lat": a["location"]["lat"],
                "lon": a["location"]["lon"],
                "river": a["location"].get("river"),
                "basin": a["location"].get("basin"),
                "coastal": a["location"]["coastal"],
                "population": a["location"]["population"],
                "population_label": a["exposure"]["population_label"],
                "score": a["risk"]["score"],
                "tier": a["risk"]["tier"]["key"],
                "colour": a["risk"]["tier"]["colour"],
                "direction": a["risk"]["direction"],
                "confidence": a["confidence"]["level"],
                "confidence_value": a["confidence"]["value"],
                "impact_index": a["exposure"]["impact_index"],
                "rain_24h_mm": a["observations"]["rain_24h_mm"],
                "weather": a.get("current_weather"),
                "discharge_cumecs": a["river"].get("current_cumecs"),
                "percentile_for_season": a["river"].get("percentile_for_season"),
                "top_factor": a["factors"][0]["label_en"] if a["factors"] else None,
                "top_factor_hi": a["factors"][0]["label_hi"] if a["factors"] else None,
            }
            for a in sorted(snap.assessments, key=lambda a: a["risk"]["score"], reverse=True)
        ],
    }


# ------------------------------------------------------------------ state view


@router.get("/state/{state_name}/locations", summary="Drill-down for one state or UT")
async def state_locations(state_name: str, date: str | None = None, user: dict = Depends(_user)) -> dict:
    if user["role"] != "central" and state_name.strip().lower() != user["state"].lower():
        raise HTTPException(status_code=403, detail=f"{state_name} is outside your area.")
    snap = _scoped(await _snapshot(date, user), user)
    target = state_name.strip().lower()
    items = [a for a in snap.assessments if a["location"]["state"].lower() == target]
    if not items:
        known = sorted({a["location"]["state"] for a in snap.assessments})
        raise HTTPException(status_code=404, detail=f"No monitored locations in '{state_name}'. Monitored: {known}")

    items.sort(key=lambda a: a["risk"]["score"], reverse=True)
    scores = [a["risk"]["score"] for a in items]
    from collections import Counter

    counts = Counter(a["risk"]["tier"]["key"] for a in items)
    return {
        "meta": _meta(snap),
        "state": items[0]["location"]["state"],
        "score": round(max(scores), 1),
        "mean_score": round(sum(scores) / len(scores), 1),
        "counts": {k: counts.get(k, 0) for k in ("red", "orange", "yellow", "green")},
        "population_at_risk": sum(
            a["location"]["population"] or 0 for a in items if a["risk"]["tier"]["key"] in ("orange", "red")
        ),
        "districts": sorted({a["location"].get("district") for a in items if a["location"].get("district")}),
        "locations": items,
    }


# -------------------------------------------------------------- location views


@router.get("/location/{location_id}/detail", summary="Full hyperlocal assessment")
async def location_detail(location_id: str, date: str | None = None, user: dict = Depends(_user)) -> dict:
    _check_place(location_id, user)
    snap = await _snapshot(date, user)
    a = snap.by_id.get(location_id)
    if a is None:
        raise HTTPException(status_code=404, detail=f"Unknown location '{location_id}'")
    return {
        "meta": _meta(snap),
        "assessment": a,
        "score_history": [] if date else store.score_history(location_id),
        # Flood waves on this town's river, from gauges upstream (live only: no
        # archive of past gauge readings exists for replays).
        "upstream": [] if date else _upstream(a["location"]),
        "peers": [
            {
                "id": p["location"]["id"],
                "name": p["location"]["name"],
                "score": p["risk"]["score"],
                "tier": p["risk"]["tier"]["key"],
            }
            for p in sorted(
                (x for x in _scoped(snap, user).assessments if x["location"]["state"] == a["location"]["state"]),
                key=lambda x: x["risk"]["score"],
                reverse=True,
            )
            if p["location"]["id"] != location_id
        ][:6],
    }


@router.get("/location/{location_id}/timeline", summary="72-hour risk trajectory with uncertainty band")
async def location_timeline(location_id: str, date: str | None = None, user: dict = Depends(_user)) -> dict:
    _check_place(location_id, user)
    snap = await _snapshot(date, user)
    a = snap.by_id.get(location_id)
    if a is None:
        raise HTTPException(status_code=404, detail=f"Unknown location '{location_id}'")
    return {
        "meta": _meta(snap),
        "location": a["location"],
        "trajectory": a["trajectory"],
        "direction": a["risk"]["direction"],
        "peak": a["risk"]["peak"],
        "river": {
            "observed": a["river"].get("observed"),
            "forecast": a["river"].get("forecast"),
            "seasonal_bands": a["river"].get("seasonal_bands"),
            "units": "m³/s",
        },
        "score_history": [] if date else store.score_history(location_id),
    }


@router.get("/location/{location_id}/replay", summary="Event replay — score a past date")
async def location_replay(
    location_id: str,
    target: str = Query(..., description="Date to replay, YYYY-MM-DD"),
    user: dict = Depends(_admin),
) -> dict:
    _check_place(location_id, user)
    try:
        when = date.fromisoformat(target)
    except ValueError:
        raise HTTPException(status_code=400, detail="target must be YYYY-MM-DD")
    if when >= date.today():
        raise HTTPException(status_code=400, detail="Replay only works on past dates")
    try:
        return await engine.replay(location_id, when)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Archive fetch failed: {exc}")


@router.get("/events", summary="The historical flood register")
def events(location_id: str | None = None, user: dict = Depends(_user)) -> dict:
    from .auth import in_scope

    rows = [
        e
        for e in EVENTS
        if (location_id is None or e["location_id"] == location_id)
        and e["location_id"] in LOCATIONS_BY_ID
        and in_scope(LOCATIONS_BY_ID[e["location_id"]], user)
    ]
    rows.sort(key=lambda e: e["date"], reverse=True)
    for e in rows:
        loc = LOCATIONS_BY_ID.get(e["location_id"], {})
        e = e.setdefault("location_name", loc.get("name", e["location_id"]))
    return {
        "count": len(rows),
        "events": [
            {
                **e,
                "location_name": LOCATIONS_BY_ID.get(e["location_id"], {}).get("name", e["location_id"]),
                "state": LOCATIONS_BY_ID.get(e["location_id"], {}).get("state"),
            }
            for e in rows
        ],
    }


# ---------------------------------------------------------------------- refresh


@router.post("/refresh", summary="Trigger a re-ingestion and re-score now")
async def refresh(user: dict = Depends(_admin)) -> dict:
    if engine.refreshing:
        return {"started": False, "reason": "A refresh is already running", "meta": _meta(engine.snapshot) if engine.snapshot else None}
    try:
        snap = await engine.refresh("manual")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Refresh failed: {exc}")
    return {
        "started": True,
        "meta": _meta(snap),
        "counts": _scoped(snap, user).tier_counts,
        "changed": _diff_against_previous(_scoped(snap, user)),
    }


def _diff_against_previous(snap) -> list[dict]:
    """
    What moved since the previous run. This is the proof that the system adapts
    rather than serving a fixed scenario — press refresh on stage and watch rows
    appear here.
    """
    history_runs = [r for r in store.recent_runs(6) if r["status"] in ("ok", "partial") and r["id"] != snap.run_id]
    if not history_runs:
        return []
    prev = store.load_assessments(history_runs[0]["id"])
    prev_by_id = {a["location"]["id"]: a for a in prev}
    changes = []
    for a in snap.assessments:
        before = prev_by_id.get(a["location"]["id"])
        if not before:
            continue
        delta = round(a["risk"]["score"] - before["risk"]["score"], 1)
        if abs(delta) >= 0.5 or a["risk"]["tier"]["key"] != before["risk"]["tier"]["key"]:
            changes.append(
                {
                    "id": a["location"]["id"],
                    "name": a["location"]["name"],
                    "from_score": before["risk"]["score"],
                    "to_score": a["risk"]["score"],
                    "delta": delta,
                    "from_tier": before["risk"]["tier"]["key"],
                    "to_tier": a["risk"]["tier"]["key"],
                    "tier_changed": a["risk"]["tier"]["key"] != before["risk"]["tier"]["key"],
                }
            )
    changes.sort(key=lambda c: abs(c["delta"]), reverse=True)
    return changes[:20]


# ------------------------------------------------------------------- AI / ML


@router.get("/ai/status", summary="Which AI providers, keys and ML models are active")
def ai_status() -> dict:
    model = load_ml_model()
    return {
        "llm": llm.status(),
        "openweathermap": {"enabled": consensus.enabled()},
        "classifier": model.as_dict() if model else None,
        "analogs": {"enabled": ml.ready, "training_days": len(ml.samples)},
        "anomaly": {"method": "isolation_forest" if ml.forest is not None else "snapshot_zscore"},
        "nowcast": nowcast_status(),
    }


class ChatTurn(BaseModel):
    role: str
    content: str


class CopilotRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list)
    lang: str | None = None


@router.post("/copilot", summary="Ask a question about current flood risk")
async def copilot_ask(req: CopilotRequest, user: dict = Depends(_user)) -> dict:
    snap = _scoped(_require_snapshot(), user)
    return await copilot.answer(
        req.question, [t.model_dump() for t in req.history], snap, req.lang
    )


@router.post("/location/{location_id}/advisory", summary="Generate a bilingual public advisory")
async def location_advisory(location_id: str, user: dict = Depends(_admin)) -> dict:
    _check_place(location_id, user)
    snap = _require_snapshot()
    a = snap.by_id.get(location_id)
    if a is None:
        raise HTTPException(status_code=404, detail=f"Unknown location '{location_id}'")
    return await copilot.advisory(a)


class SimulateRequest(BaseModel):
    extra_rain_past_24h: float = Field(0.0, ge=0, le=600)
    extra_rain_next_24h: float = Field(0.0, ge=0, le=600)
    discharge_multiplier: float = Field(1.0, ge=0.2, le=6.0)
    soil_moisture: float | None = Field(None, ge=0.05, le=0.6)


@router.post("/location/{location_id}/simulate", summary="What-if scenario on live inputs")
def location_simulate(location_id: str, req: SimulateRequest, user: dict = Depends(_admin)) -> dict:
    _check_place(location_id, user)
    _require_snapshot()
    try:
        result = engine.simulate(location_id, **req.model_dump())
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No live inputs for '{location_id}' yet")
    s = result["scenario"]
    # The full assessment is large; the simulator needs the headline, drivers,
    # trajectory and the ML read, not the history list and river series.
    return {
        "inputs": result["inputs"],
        "baseline": result["baseline"],
        "delta": result["delta"],
        "scenario": {
            "risk": {k: v for k, v in s["risk"].items() if k != "normalised"},
            "confidence": s["confidence"],
            "factors": s["factors"],
            "trajectory": s["trajectory"],
            "actions": s["actions"],
            "explanation": s["explanation"],
            "observations": s["observations"],
            "ai": {"analogs": s["ai"]["analogs"], "anomaly": s["ai"]["anomaly"]},
        },
    }


@router.get("/insights", summary="ML insights across all locations")
async def insights(date: str | None = None, user: dict = Depends(_admin)) -> dict:
    snap = _scoped(await _snapshot(date, user), user)
    rows = []
    for a in snap.assessments:
        ai = a.get("ai") or {}
        an, ag = ai.get("anomaly") or {}, ai.get("analogs") or {}
        rows.append(
            {
                "id": a["location"]["id"],
                "name": a["location"]["name"],
                "name_hi": a["location"].get("name_hi"),
                "state": a["location"]["state"],
                "score": a["risk"]["score"],
                "tier": a["risk"]["tier"]["key"],
                "ml_probability": a["risk"].get("ml_probability"),
                "anomaly_score": an.get("score") if an.get("available") else None,
                "anomaly_level": an.get("level"),
                "unusual_features": an.get("unusual_features", []),
                "knn_flood_probability": ag.get("knn_flood_probability") if ag.get("available") else None,
                "top_analog": (ag.get("matches") or [None])[0] if ag.get("available") else None,
                "consensus": ai.get("forecast_consensus"),
            }
        )
    by_anomaly = sorted((r for r in rows if r["anomaly_score"] is not None), key=lambda r: -r["anomaly_score"])
    by_knn = sorted((r for r in rows if r["knn_flood_probability"] is not None), key=lambda r: -r["knn_flood_probability"])
    # Where the independent ML reads disagree with the rule score by a wide
    # margin is where a human should look twice.
    disagreements = sorted(
        (
            r | {"gap": round((r["knn_flood_probability"] * 100) - r["score"], 1)}
            for r in rows
            if r["knn_flood_probability"] is not None
        ),
        key=lambda r: -abs(r["gap"]),
    )[:5]
    return {
        "meta": _meta(snap),
        "status": ai_status(),
        "anomalies": by_anomaly[:8],
        "analog_ranking": by_knn[:8],
        "model_disagreements": disagreements,
    }


@router.get("/timemachine/presets", summary="Well-documented flood days for the national Time Machine")
def timemachine_presets(user: dict = Depends(_admin)) -> dict:
    """Severity-3, exact-day events in the user's area: the days worth replaying."""
    from .auth import in_scope

    rows = [
        e
        for e in EVENTS
        if e.get("severity") == 3
        and e.get("date_precision") == "day"
        and e["location_id"] in LOCATIONS_BY_ID
        and in_scope(LOCATIONS_BY_ID[e["location_id"]], user)
    ]
    rows.sort(key=lambda e: e["date"], reverse=True)
    seen, out = set(), []
    for e in rows:
        if e["date"] in seen:
            continue
        seen.add(e["date"])
        loc = LOCATIONS_BY_ID.get(e["location_id"], {})
        out.append({**e, "location_name": loc.get("name"), "location_name_hi": loc.get("name_hi"), "state": loc.get("state")})
    return {"presets": out}


# -------------------------------------------------------- official government data


@router.get("/official/summary", summary="CWC gauge and NDMA SACHET alert counts")
def official_summary(user: dict = Depends(_user)) -> dict:
    from collections import Counter

    from .official import official

    out = official.summary()
    if user["role"] == "central":
        return out
    places = _scope_places(user)
    gauges = [official.station_status(c) for c in official.catalog]
    gauges = [g for g in gauges if _gauge_in_scope(g, user, places)]
    alerts = [a for a in official.alerts if _alert_in_scope(a, user, places)]
    status = Counter(g["status"] for g in gauges)
    out["gauges"] = out["gauges"] | {"catalogued": len(gauges), "danger": status.get("DANGER", 0), "warning": status.get("WARNING", 0)}
    out["alerts"] = {
        "total": len(alerts),
        "flood_related": sum(1 for a in alerts if a["flood_related"]),
        "by_colour": dict(Counter(a["colour"] for a in alerts)),
        "by_source": dict(Counter(a["source"] for a in alerts).most_common(10)),
    }
    return out


@router.get("/official/stations", summary="CWC gauges with danger marks and live status")
def official_stations(only_alerting: bool = False, user: dict = Depends(_user)) -> dict:
    from .official import official

    places = _scope_places(user)
    rows = [g for g in official.stations_payload(only_alerting) if _gauge_in_scope(g, user, places)]
    return {"count": len(rows), "fetched_at": official.fetched_at, "stations": rows}


@router.get("/official/alerts", summary="Active NDMA SACHET CAP alerts")
def official_alerts(flood_only: bool = False, user: dict = Depends(_user)) -> dict:
    from .official import official

    places = _scope_places(user)
    rows = [a for a in official.alerts if (a["flood_related"] or not flood_only) and _alert_in_scope(a, user, places)]
    rank = {"red": 0, "orange": 1, "yellow": 2}
    rows.sort(key=lambda a: rank.get(a["colour"], 3))
    return {"count": len(rows), "fetched_at": official.fetched_at, "alerts": rows}


@router.get("/official/station/{code}", summary="Gauge hydrograph + CWC forecast + Chronos AI forecast")
async def official_station(code: str, user: dict = Depends(_user)) -> dict:
    # Any gauge may be opened: river profiles deliberately include gauges upstream
    # of the user's area, because that water is what arrives next.
    from .nowcast import forecast_station
    from .official import official

    if code not in official.catalog:
        raise HTTPException(status_code=404, detail=f"Unknown CWC station '{code}'")
    try:
        return await forecast_station(code)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"CWC data unavailable: {exc}")


# ------------------------------------------------------------- rivers & hotspots


# ------------------------------------------------------------ sign-in and scope


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=1, max_length=200)


class DemoRequest(BaseModel):
    role: str
    state: str | None = None
    district: str | None = None


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    contact: str = Field(..., min_length=5, max_length=120, description="Email or 10-digit mobile number")
    password: str = Field(..., min_length=1, max_length=200)
    state: str = Field(..., max_length=80)
    district: str = Field(..., max_length=80)


@router.get("/auth/options", summary="Areas a user can sign in for, and whether demo sign-in is on")
def auth_options() -> dict:
    from .config import DEMO_LOGIN

    states: dict[str, list[str]] = {}
    for l in LOCATIONS:
        states.setdefault(l["state"], [])
        if l.get("district") and l["district"] not in states[l["state"]]:
            states[l["state"]].append(l["district"])
    return {
        "demo": DEMO_LOGIN,
        "places": len(LOCATIONS),
        "states": [{"name": s, "districts": sorted(d)} for s, d in sorted(states.items())],
        "username_hint": "central · <state> e.g. bihar · <state>.<district> e.g. bihar.patna",
        "citizen_signup": True,
    }


@router.post("/auth/login", summary="Sign in with username and password")
def auth_login(req: LoginRequest) -> dict:
    from . import auth

    user = auth.login(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    return {"token": auth.issue_token(user), "user": user}


@router.post("/auth/register", summary="Create a citizen account for a home district")
def auth_register(req: RegisterRequest) -> dict:
    from . import auth

    user = auth.register(req.name, req.contact, req.password, req.state, req.district, LOCATIONS)
    return {"token": auth.issue_token(user), "user": user}


@router.post("/auth/demo", summary="One-click demo sign-in for a role and area")
def auth_demo(req: DemoRequest) -> dict:
    from . import auth

    user = auth.demo_user(req.role, req.state, req.district, LOCATIONS)
    return {"token": auth.issue_token(user), "user": user}


@router.get("/auth/me", summary="The signed-in user")
def auth_me(user: dict = Depends(_user)) -> dict:
    from . import auth

    return user | {"label": auth.scope_label(user)}


@router.get("/me/brief", summary="Everything about the signed-in user's area, in plain language")
def my_brief(since: str | None = None, user: dict = Depends(_user)) -> dict:
    from . import briefing
    from .rivers import towns_in_path

    snap = _require_snapshot()
    try:
        waves = {r["id"]: r["threats"] for r in towns_in_path()}
    except Exception as exc:
        log.warning("river waves unavailable for brief: %s", exc)
        waves = {}
    brief = briefing.build(user, snap, since, waves) | {"meta": _meta(snap)}
    if user["role"] == "citizen":
        from . import safety

        # Ready-to-send advisories and SMS drafts are control-room tools.
        for al in brief["alerts"]:
            al.pop("advisory", None)
        home = brief["places"][0] if brief["places"] else None
        brief["resident"] = safety.advice(home["id"] if home else None, home["tier"] if home else "green", "place")
    return brief


# ------------------------------------------------------------- notifications


class NotifyPrefs(BaseModel):
    name: str | None = Field(None, max_length=80)
    email: str | None = Field(None, max_length=120)
    whatsapp: str | None = Field(None, max_length=20)
    phone: str | None = Field(None, max_length=20)
    channels: list[str] = Field(default_factory=lambda: ["email", "whatsapp"])
    min_level: str = "orange"
    daily_brief: bool = True
    enabled: bool = True


def _waves() -> dict:
    from .rivers import towns_in_path

    try:
        return {r["id"]: r["threats"] for r in towns_in_path()}
    except Exception:
        return {}


@router.get("/me/notify", summary="The signed-in user's notification settings and recent deliveries")
def my_notify(user: dict = Depends(_admin)) -> dict:
    from . import notify
    from .config import NOTIFY_WEBHOOK_URL

    return {
        "prefs": notify.get_prefs(user["username"]),
        "webhook_configured": bool(NOTIFY_WEBHOOK_URL),
        "log": notify.recent_log(user["username"]),
    }


@router.put("/me/notify", summary="Save notification settings")
def save_my_notify(req: NotifyPrefs, user: dict = Depends(_admin)) -> dict:
    from . import notify

    if req.enabled and not (req.email or req.whatsapp or req.phone):
        raise HTTPException(status_code=400, detail="Add at least an email, a WhatsApp number or a phone number.")
    return {"prefs": notify.save_prefs(user, req.model_dump())}


@router.post("/me/notify/test", summary="Send a test message through the automation webhook")
async def test_my_notify(user: dict = Depends(_admin)) -> dict:
    from . import notify

    p = notify.get_prefs(user["username"])
    if not p:
        raise HTTPException(status_code=400, detail="Save your notification settings first.")
    status = await notify.send_test(p, _require_snapshot(), _waves())
    return {"status": status, "log": notify.recent_log(user["username"])}


class InboundMessage(BaseModel):
    from_: str = Field(..., alias="from", max_length=40)
    text: str = Field("", max_length=500)


@router.post("/hooks/inbound", summary="Inbound WhatsApp/SMS from the automation platform; returns the reply text")
async def inbound_message(msg: InboundMessage, x_jaldrishti_secret: str | None = Header(default=None)) -> dict:
    """
    For a WhatsApp bot: the automation flow forwards an incoming message here and
    sends back `reply`. Only numbers registered in notification settings get an
    answer, and only about their own area.
    """
    import hmac

    from . import briefing, notify
    from .auth import in_scope
    from .config import NOTIFY_INBOUND_SECRET

    if not NOTIFY_INBOUND_SECRET or not hmac.compare_digest(x_jaldrishti_secret or "", NOTIFY_INBOUND_SECRET):
        raise HTTPException(status_code=401, detail="Bad or missing X-JalDrishti-Secret.")
    p = notify.user_by_phone(msg.from_)
    if not p:
        return {"reply": "This number is not registered for JalDrishti alerts. Add it under Notifications in the dashboard."}
    user = {"username": p["username"], "role": p["role"], "state": p.get("state"), "district": p.get("district")}
    text = msg.text.strip()
    low = text.lower()
    snap = _require_snapshot()
    if low in ("ack", "ok", "received", "acknowledged"):
        with store.db() as conn:
            conn.execute(
                "INSERT INTO notify_log (id, created_at, username, event, title, channels, status, detail) VALUES (?, ?, ?, 'ack', ?, '[]', 'received', ?)",
                (f"ack-{store.utcnow()}-{p['username']}", store.utcnow(), p["username"], "Acknowledged", msg.from_),
            )
        return {"reply": "Acknowledged — thank you. JalDrishti logged your acknowledgement.", "ack": True}
    if low in ("", "status", "brief", "hi", "hello", "help"):
        b = briefing.build(user, snap, None, _waves())
        lines = "\n".join(f"• {x}" for x in b["brief"]["en"])
        return {"reply": f"JalDrishti — {b['scope']['label']['en']}\n{lines}\n\nReply 'status <place>' for one place, ACK to acknowledge, or ask a question."}
    if low.startswith("status "):
        name = low[7:].strip()
        a = next((x for x in snap.assessments if in_scope(x["location"], user) and name in x["location"]["name"].lower()), None)
        if not a:
            return {"reply": f"No monitored place matching '{name}' in your area."}
        return {"reply": f"{a['explanation']['headline_en']}\nWhat to do: {a['actions']['ndma_action_en']}"}
    ans = await copilot.answer(text, [], _scoped(snap, user), "hi" if any("ऀ" <= ch <= "ॿ" for ch in text) else "en")
    return {"reply": ans.get("answer") or ans.get("text") or "Sorry, I could not answer that."}


# ---------------------------------------------------------------------- CAP 1.2

# application/xml rather than application/cap+xml so a browser shows the message
# instead of downloading it; CAP consumers key on the namespace, not the type.
XML = "application/xml; charset=utf-8"


@router.get("/cap/feed.atom", summary="Atom index of current CAP 1.2 warnings", response_class=Response)
def cap_feed(request: Request) -> Response:
    snap = _require_snapshot()
    return Response(cap.build_feed(snap.assessments, snap.run_id, str(request.base_url)), media_type=XML)


@router.get("/cap/alerts/{location_id}.xml", summary="CAP 1.2 message for one location", response_class=Response)
def cap_alert(location_id: str) -> Response:
    snap = _require_snapshot()
    a = next((x for x in snap.assessments if x["location"]["id"] == location_id), None)
    if a is None:
        raise HTTPException(status_code=404, detail=f"Unknown location '{location_id}'")
    msg = cap.build_alert(a, snap.run_id)
    if msg is None:
        raise HTTPException(status_code=404, detail=f"No active warning for {a['location']['name']} (Green).")
    return Response(cap.to_xml(msg), media_type=XML)


@router.get("/rivers", summary="India river network coloured by CWC gauge status")
def rivers_status(user: dict = Depends(_user)) -> dict:
    from .auth import in_scope
    from .official import official
    from .rivers import network_status, towns_in_path

    net = network_status()
    towns = [r for r in towns_in_path() if in_scope(LOCATIONS_BY_ID[r["id"]], user)]
    if user["role"] == "central":
        return net | {"towns_in_path": towns, "scope": "central"}
    # A river is in the area if one of its gauges is, or one of the user's places
    # sits on it. Its whole profile is kept: upstream water is what arrives next.
    places = _scope_places(user)
    codes = {c for c in official.catalog if _gauge_in_scope(official.station_status(c), user, places)}
    place_rivers = {(p.get("river") or "").lower() for p in places}
    keep = {
        r["name"]
        for r in net["rivers"]
        if any(g["code"] in codes for g in r["profile"]) or r["name"].lower() in place_rivers
    }
    rivers = [r for r in net["rivers"] if r["name"] in keep]
    features = [f for f in net["reaches"]["features"] if f["properties"]["river"] in keep]
    return net | {
        "rivers": rivers,
        "gauges_on_rivers": sum(r["gauges"] for r in rivers),
        "reaches": {"type": "FeatureCollection", "features": features},
        "towns_in_path": towns,
        "scope": user["role"],
    }


def _upstream(loc: dict) -> list[dict]:
    from .rivers import upstream_threats

    try:
        return upstream_threats(loc["lat"], loc["lon"])
    except Exception as exc:
        log.warning("upstream threats for %s failed: %s", loc["id"], exc)
        return []


@router.get("/hotspots/{location_id}", summary="Hyperlocal water-accumulation grid for one city")
async def city_hotspots(
    location_id: str,
    capacity: float = Query(1.0, ge=0.3, le=3.0, description="Drainage capacity multiplier"),
    scenario_mm_h: float | None = Query(None, ge=1, le=200, description="Design storm intensity"),
    scenario_hours: int = Query(3, ge=1, le=12),
    user: dict = Depends(_user),
) -> dict:
    from .hotspots import hotspots

    _check_place(location_id, user)
    try:
        return await hotspots(location_id, capacity, scenario_mm_h, scenario_hours)
    except Exception as exc:
        log.warning("hotspots %s failed: %s", location_id, str(exc)[:300])
        busy = "429" in str(exc) or "rate limit" in str(exc).lower()
        raise HTTPException(
            status_code=503 if busy else 502,
            detail=(
                "The weather service is busy right now, so street-level data for this city could not be loaded. Please try again in a minute."
                if busy
                else "Street-level data for this city is temporarily unavailable. Please try again shortly."
            ),
        )


# ------------------------------------------------------ response planning (officials)
#
# One national plan per scoring run + inventory + travel matrix, re-solved when any
# of them changes; each official sees the part their area acts on.


class StockUpdate(BaseModel):
    depot_id: str = Field(..., max_length=80)
    rtype: str = Field(..., max_length=40)
    total: int = Field(..., ge=0, le=10_000)


class DispatchRequest(BaseModel):
    plan_id: str = Field(..., max_length=64)
    order_ids: list[str] = Field(..., min_length=1, max_length=500)


def _plan(trigger: str = "requested", force: bool = False) -> dict:
    from . import planning

    return planning.current(_require_snapshot(), _waves(), trigger, force)


@router.get("/plan", summary="Resource allocation plan for the signed-in official's area")
def plan_get(user: dict = Depends(_admin)) -> dict:
    from . import planning

    return planning.for_user(_plan(), user)


@router.post("/plan/replan", summary="Re-optimise the plan now")
def plan_replan(user: dict = Depends(_admin)) -> dict:
    from . import planning

    return planning.for_user(_plan("manual re-plan", force=True), user)


@router.get("/plan/history", summary="Recent plan versions with what triggered each")
def plan_history(user: dict = Depends(_admin)) -> dict:
    from . import planning

    return {"plans": planning.history()}


@router.post("/plan/dispatch", summary="Dispatch plan orders: the units become deployments")
async def plan_dispatch(req: DispatchRequest, user: dict = Depends(_admin)) -> dict:
    from . import notify, planning, resources

    plan = _plan()
    if plan["id"] != req.plan_id:
        raise HTTPException(status_code=409, detail="The plan changed since you opened it. Review the new plan and dispatch again.")
    by_id = {o["id"]: o for o in plan["orders"]}
    orders = [by_id[i] for i in req.order_ids if i in by_id]
    if not orders:
        raise HTTPException(status_code=400, detail="None of those orders are in the current plan.")
    n = resources.dispatch(user, orders, plan["id"])
    # Deployment orders go out to the destination's officials through the webhook.
    try:
        notified = await notify.send_deployment(orders, user)
    except Exception as exc:
        log.warning("deployment notification failed: %s", exc)
        notified = 0
    return {"dispatched_units": n, "notified": notified, "plan": planning.for_user(_plan("dispatched units"), user)}


@router.post("/deployments/{deployment_id}/release", summary="Return deployed units to their depot")
def deployment_release(deployment_id: str, user: dict = Depends(_admin)) -> dict:
    from . import resources

    resources.release(user, deployment_id)
    return {"ok": True}


@router.get("/resources", summary="Depots, stock and deployments visible to the signed-in official")
def resources_get(user: dict = Depends(_admin)) -> dict:
    from . import resources, travel

    rows = []
    for d in resources.depots():
        mine = resources.can_manage(user, d)
        visible = user["role"] == "central" or d["kind"] == "ndrf" or d["state"] == user["state"]
        if visible:
            rows.append(d | {"can_edit": mine})
    return {
        "depots": rows,
        "types": {k: {kk: v[kk] for kk in ("en", "hi", "unit_en", "unit_hi", "cap", "rel", "max_h")} for k, v in resources.RTYPES.items()},
        "holds": resources.HOLDS,
        "mobilise_h": resources.MOBILISE_H,
        "ndrf": {"battalions": len(resources.NDRF_BATTALIONS), "teams_per_battalion": resources.NDRF_TEAMS_PER_BN,
                 "team_size": resources.NDRF_TEAM_SIZE, "source": resources.NDRF_SOURCE},
        "travel": travel.status(),
    }


@router.post("/resources/stock", summary="Set a depot's total stock of one resource type")
def resources_set(req: StockUpdate, user: dict = Depends(_admin)) -> dict:
    from . import resources

    resources.set_stock(user, req.depot_id, req.rtype, req.total)
    return {"ok": True}


@router.get("/plan/city/{location_id}", summary="Street-level deployment of a city's pumps and barricades")
async def plan_city(location_id: str, user: dict = Depends(_admin)) -> dict:
    from . import city_plan, resources, safety
    from .hotspots import hotspots

    loc = _check_place(location_id, user)
    plan = _plan()
    row = next((p for p in plan["places"] if p["id"] == location_id), None)
    if row:
        pool = {r: row["types"].get(r, {}).get("planned", 0) + row["types"].get(r, {}).get("already", 0) for r in ("pump", "barricade")}
        basis = "national plan"
    else:
        store_row = next((d for d in resources.depots() if d["id"] == f"dist-{location_id}"), None)
        pool = {r: (store_row or {}).get("stock", {}).get(r, {}).get("available", 0) for r in ("pump", "barricade")}
        basis = "district store (pre-positioning; the place is not at risk)"
    try:
        hot = await hotspots(location_id, 1.0, None, 3)
    except Exception as exc:
        log.warning("city plan %s: street grid unavailable: %s", location_id, str(exc)[:200])
        raise HTTPException(status_code=503, detail="Street-level data for this city is unavailable right now. Please try again shortly.")
    live = (hot.get("rain_source") or "none") != "none"
    out = city_plan.build(loc, hot, safety._static(location_id), pool, live)
    return out | {"pool_basis": basis, "place_name": loc["name"], "plan_id": plan["id"],
                  "confidence": hot.get("confidence"), "rain_source": hot.get("rain_source")}
