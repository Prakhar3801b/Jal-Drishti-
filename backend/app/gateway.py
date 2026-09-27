"""
External API Gateway for JalDrishti.

This module exposes a **separate** set of endpoints under ``/api/gateway/``
for third-party platforms to consume JalDrishti data using API keys.
It is fully isolated from the internal dashboard routes in ``api.py`` and
the user auth system in ``auth.py``.

Two groups of endpoints:

  /api/gateway/admin/*   — key management (requires internal admin login)
  /api/gateway/v1/*      — external data endpoints (requires a valid API key)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from . import apikeys
from .engine import LOCATIONS, LOCATIONS_BY_ID, engine

log = logging.getLogger("jaldrishti.gateway")

gateway_router = APIRouter(prefix="/api/gateway", tags=["API Gateway"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ dependencies ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _admin_user(authorization: str | None = Header(default=None)) -> dict:
    """Re-uses the internal admin auth — only central/state/district officials
    can manage API keys.  This dependency is ONLY used on /api/gateway/admin/*.
    """
    from .auth import require_admin

    return require_admin(authorization)


def _api_key(request: Request, authorization: str | None = Header(default=None)) -> dict:
    """Validate Bearer API key for external platform requests.

    Checks:
      1. key exists and is active
      2. key is not expired
      3. rate limit not exceeded

    Returns the key metadata dict on success.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing API key.  Include 'Authorization: Bearer sk_live_...' header.",
        )
    token = authorization.split(" ", 1)[1].strip()

    # Reject internal JWT tokens that accidentally hit the gateway
    if not token.startswith(("sk_live_", "sk_test_")):
        raise HTTPException(
            status_code=401,
            detail="Invalid API key format.  Keys start with 'sk_live_' or 'sk_test_'.",
        )

    key_meta = apikeys.validate_key(token)
    if key_meta is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key.")

    # Rate-limit check
    allowed, limit, remaining, reset = apikeys.check_rate_limit(
        key_meta["id"], key_meta["rate_limit"]
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded.",
            headers={
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset),
                "Retry-After": str(max(1, reset - int(__import__("time").time()))),
            },
        )

    # Stash rate-limit info for the after-response hook
    request.state.gateway_key = key_meta
    request.state.rate_limit = limit
    request.state.rate_remaining = remaining
    request.state.rate_reset = reset
    return key_meta


def _require_scope(scope: str):
    """Factory: returns a dependency that asserts the API key carries *scope*."""

    def checker(key: dict = Depends(_api_key)) -> dict:
        if scope not in key.get("scopes", []):
            raise HTTPException(
                status_code=403,
                detail=f"This endpoint requires the '{scope}' scope.",
            )
        return key

    return checker


def _rate_headers(response: Response, request: Request) -> None:
    """Add standard rate-limit headers to every gateway response."""
    meta = getattr(request.state, "gateway_key", None)
    if meta:
        response.headers["X-RateLimit-Limit"] = str(request.state.rate_limit)
        response.headers["X-RateLimit-Remaining"] = str(request.state.rate_remaining)
        response.headers["X-RateLimit-Reset"] = str(request.state.rate_reset)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━ admin key management ━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    environment: str = Field(default="test", pattern="^(live|test)$")
    scopes: list[str] = Field(default=["score_read"])
    tier: str = Field(default="standard", pattern="^(standard|enterprise)$")
    expires_at: str | None = None


class UpdateKeyRequest(BaseModel):
    name: str | None = None
    scopes: list[str] | None = None
    tier: str | None = None
    expires_at: str | None = None


@gateway_router.get("/admin/keys", summary="List all API keys (admin)")
def admin_list_keys(
    include_revoked: bool = False,
    user: dict = Depends(_admin_user),
) -> dict:
    return {
        "keys": apikeys.list_keys(include_revoked=include_revoked),
        "scopes": apikeys.SCOPE_DESCRIPTIONS,
        "tiers": apikeys.TIER_RATE_LIMITS,
    }


@gateway_router.post("/admin/keys", summary="Create a new API key (admin)", status_code=201)
def admin_create_key(req: CreateKeyRequest, user: dict = Depends(_admin_user)) -> dict:
    try:
        result = apikeys.create_key(
            name=req.name,
            environment=req.environment,
            scopes=req.scopes,
            tier=req.tier,
            expires_at=req.expires_at,
            created_by=user.get("username"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@gateway_router.get("/admin/keys/{key_id}", summary="Get key metadata (admin)")
def admin_get_key(key_id: int, user: dict = Depends(_admin_user)) -> dict:
    key = apikeys.get_key(key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found.")
    return key


@gateway_router.patch("/admin/keys/{key_id}", summary="Update key settings (admin)")
def admin_update_key(
    key_id: int, req: UpdateKeyRequest, user: dict = Depends(_admin_user)
) -> dict:
    try:
        result = apikeys.update_key(
            key_id,
            name=req.name,
            scopes=req.scopes,
            tier=req.tier,
            expires_at=req.expires_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="Key not found.")
    return result


@gateway_router.delete("/admin/keys/{key_id}", summary="Revoke an API key (admin)")
def admin_revoke_key(key_id: int, user: dict = Depends(_admin_user)) -> dict:
    if not apikeys.revoke_key(key_id):
        raise HTTPException(status_code=404, detail="Key not found or already revoked.")
    return {"ok": True, "detail": "Key revoked."}


@gateway_router.get("/admin/keys/{key_id}/usage", summary="Usage analytics for a key (admin)")
def admin_key_usage(
    key_id: int, hours: int = 24, user: dict = Depends(_admin_user)
) -> dict:
    key = apikeys.get_key(key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="Key not found.")
    return apikeys.usage_stats(key_id, hours=hours)


@gateway_router.get("/admin/overview", summary="High-level API key stats (admin)")
def admin_overview(user: dict = Depends(_admin_user)) -> dict:
    return apikeys.overview_stats()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━ external data endpoints ━━━━━━━━━━━━━━━━━━━━━━━━
#
# These mirror the most useful internal endpoints but are:
#   - authenticated via API key (not user login)
#   - scope-gated
#   - rate-limited
#   - un-scoped (no area filter; external consumers see all data)
#   - read-only (simulate_write is the exception)


def _require_snapshot():
    snap = engine.snapshot
    if snap is None:
        raise HTTPException(status_code=503, detail="No risk data yet. The engine is still initialising.")
    return snap


@gateway_router.get("/v1/scores/summary", summary="Country-wide risk summary")
def ext_country_summary(
    request: Request,
    response: Response,
    key: dict = Depends(_require_scope("score_read")),
) -> dict:
    snap = _require_snapshot()
    from .config import ALERT_TIERS

    tiers = {t["key"]: 0 for t in ALERT_TIERS}
    for a in snap.assessments:
        tiers[a["risk"]["tier"]["key"]] = tiers.get(a["risk"]["tier"]["key"], 0) + 1

    apikeys.record_usage(key["id"], "/v1/scores/summary", "GET")
    _rate_headers(response, request)
    return {
        "run_id": snap.run_id,
        "computed_at": snap.computed_at,
        "locations": len(snap.assessments),
        "tiers": tiers,
    }


@gateway_router.get("/v1/scores/locations", summary="All location risk scores")
def ext_all_locations(
    request: Request,
    response: Response,
    key: dict = Depends(_require_scope("score_read")),
) -> dict:
    snap = _require_snapshot()
    items = []
    for a in snap.assessments:
        items.append({
            "id": a["location"]["id"],
            "name": a["location"]["name"],
            "state": a["location"]["state"],
            "district": a["location"].get("district"),
            "lat": a["location"]["lat"],
            "lon": a["location"]["lon"],
            "score": a["risk"]["score"],
            "tier": a["risk"]["tier"]["key"],
            "confidence": a["confidence"]["value"],
        })

    apikeys.record_usage(key["id"], "/v1/scores/locations", "GET")
    _rate_headers(response, request)
    return {
        "run_id": snap.run_id,
        "computed_at": snap.computed_at,
        "locations": items,
    }


@gateway_router.get("/v1/scores/locations/{location_id}", summary="Single location detail")
def ext_location_detail(
    location_id: str,
    request: Request,
    response: Response,
    key: dict = Depends(_require_scope("score_read")),
) -> dict:
    snap = _require_snapshot()
    assessment = next((a for a in snap.assessments if a["location"]["id"] == location_id), None)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Location not found.")

    apikeys.record_usage(key["id"], f"/v1/scores/locations/{location_id}", "GET")
    _rate_headers(response, request)
    return {
        "run_id": snap.run_id,
        "computed_at": snap.computed_at,
        "assessment": assessment,
    }


@gateway_router.get("/v1/forecasts/{location_id}", summary="72-hour forecast trajectory")
def ext_forecast(
    location_id: str,
    request: Request,
    response: Response,
    key: dict = Depends(_require_scope("forecast_read")),
) -> dict:
    snap = _require_snapshot()
    assessment = next((a for a in snap.assessments if a["location"]["id"] == location_id), None)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Location not found.")

    apikeys.record_usage(key["id"], f"/v1/forecasts/{location_id}", "GET")
    _rate_headers(response, request)
    return {
        "run_id": snap.run_id,
        "location_id": location_id,
        "trajectory": assessment.get("trajectory"),
        "weather": assessment.get("weather"),
    }


@gateway_router.get("/v1/alerts", summary="Official CWC gauge readings and NDMA alerts")
def ext_alerts(
    request: Request,
    response: Response,
    flood_only: bool = False,
    key: dict = Depends(_require_scope("alert_subscribe")),
) -> dict:
    from .official import official

    raw_alerts = getattr(official, "alerts", []) or []
    if flood_only:
        alerts = [a for a in raw_alerts if a.get("flood_related")]
    else:
        alerts = list(raw_alerts)

    apikeys.record_usage(key["id"], "/v1/alerts", "GET")
    _rate_headers(response, request)
    return {"count": len(alerts), "alerts": alerts}


@gateway_router.get("/v1/alerts/gauges", summary="CWC gauge station readings")
def ext_gauges(
    request: Request,
    response: Response,
    key: dict = Depends(_require_scope("alert_subscribe")),
) -> dict:
    from .official import official

    stations = []
    for code, station in (official.catalog or {}).items():
        status = official.station_status(code)
        stations.append({
            "code": code,
            "name": station.get("name"),
            "river": station.get("river"),
            "state": station.get("state"),
            **status,
        })

    apikeys.record_usage(key["id"], "/v1/alerts/gauges", "GET")
    _rate_headers(response, request)
    return {"stations": stations}


@gateway_router.get("/v1/rivers", summary="River flood-wave propagation and towns at risk")
def ext_rivers(
    request: Request,
    response: Response,
    key: dict = Depends(_require_scope("maps_read")),
) -> dict:
    from . import rivers

    try:
        paths = rivers.towns_in_path()
    except Exception:
        paths = []

    apikeys.record_usage(key["id"], "/v1/rivers", "GET")
    _rate_headers(response, request)
    return {"flood_paths": paths}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ gateway health ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@gateway_router.get("/health", summary="Gateway health check (no auth required)")
def gateway_health() -> dict:
    return {
        "status": "ok",
        "service": "JalDrishti API Gateway",
        "scopes": list(apikeys.VALID_SCOPES),
        "tiers": apikeys.TIER_RATE_LIMITS,
    }
