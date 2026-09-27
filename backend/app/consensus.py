"""
Multi-model rainfall consensus.

Open-Meteo blends several numerical weather models, but it is still one pipeline.
With a free OpenWeatherMap key the engine fetches an independent 5-day / 3-hour
forecast and compares the next-24-hour rainfall from both. Agreement raises
confidence; a large disagreement lowers it and is written out as a reason, which
is exactly the situation a duty officer should know about before acting.

Budget: 41 calls per refresh, every 90 minutes ~ 656 calls/day, inside the free
tier's 1,000/day and 60/minute limits (concurrency is capped at 5).
"""

from __future__ import annotations

import asyncio
import time
from typing import Sequence

import httpx

from . import store
from .config import OPENWEATHER_API_KEY

URL = "https://api.openweathermap.org/data/2.5/forecast"


def enabled() -> bool:
    return bool(OPENWEATHER_API_KEY)


async def _one(client: httpx.AsyncClient, sem: asyncio.Semaphore, loc: dict) -> tuple[str, float | None]:
    async with sem:
        try:
            r = await client.get(
                URL,
                params={"lat": loc["lat"], "lon": loc["lon"], "appid": OPENWEATHER_API_KEY, "units": "metric"},
            )
            if r.status_code != 200:
                return loc["id"], None
            items = r.json().get("list") or []
            # First eight 3-hour slots = the next 24 hours.
            total = sum(float((it.get("rain") or {}).get("3h", 0.0)) for it in items[:8])
            return loc["id"], round(total, 1)
        except Exception:
            return loc["id"], None


async def fetch_owm_next24(locations: Sequence[dict]) -> dict[str, float]:
    if not enabled():
        return {}
    started = time.perf_counter()
    sem = asyncio.Semaphore(5)
    async with httpx.AsyncClient(timeout=20.0) as client:
        pairs = await asyncio.gather(*(_one(client, sem, l) for l in locations))
    out = {k: v for k, v in pairs if v is not None}
    store.record_source_health(
        "openweathermap",
        ok=len(out) >= len(locations) * 0.8,
        latency_ms=int((time.perf_counter() - started) * 1000),
        detail=f"{len(out)}/{len(locations)} locations",
    )
    return out


def compare(open_meteo_mm: float | None, owm_mm: float | None) -> dict:
    """Agreement between two independent next-24h rainfall forecasts."""
    if owm_mm is None or open_meteo_mm is None:
        return {"available": False}
    hi, lo = max(open_meteo_mm, owm_mm), min(open_meteo_mm, owm_mm)
    # Both near-dry is agreement, not a 0/0 disagreement.
    if hi < 2.5:
        agreement = 1.0
    else:
        agreement = lo / hi
    level = "strong" if agreement >= 0.6 else "partial" if agreement >= 0.3 else "conflict"
    return {
        "available": True,
        "open_meteo_mm": round(open_meteo_mm, 1),
        "openweathermap_mm": round(owm_mm, 1),
        "agreement": round(agreement, 2),
        "level": level,
    }
