"""
River-level nowcasting with Amazon Chronos-Bolt (Hugging Face).

Chronos-Bolt is a pretrained time-series foundation model: given the last week of
a CWC gauge's hourly water levels it forecasts the next 48 hours zero-shot, with
quantiles, in about a quarter of a second on CPU. No per-station training, so it
works for any of the ~1,000 gauges on the day a flood starts.

What it adds over the gauge reading alone is *lead time*: "above danger now" becomes
"expected to cross the danger mark in ~14 h (p90 in ~9 h)" or "expected to fall
back below danger in ~20 h".

Honest limits, shown in the UI: it extrapolates the hydrograph's own shape and knows
nothing about upstream rain or dam releases, so it is strongest at 6-24 h and should
be read next to CWC's official forecast, never instead of it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta

from .official import official

log = logging.getLogger("jaldrishti.nowcast")

MODEL_ID = os.getenv("JALDRISHTI_CHRONOS_MODEL", "amazon/chronos-bolt-small")
CONTEXT_HOURS = 168
HORIZON_HOURS = 48
CACHE_TTL_S = 900

_pipeline = None
_load_error: str | None = None
_lock = asyncio.Lock()
_cache: dict[str, tuple[float, dict]] = {}


def _load_sync():
    import torch
    from chronos import BaseChronosPipeline

    return BaseChronosPipeline.from_pretrained(MODEL_ID, device_map="cpu", torch_dtype=torch.float32)


async def pipeline():
    global _pipeline, _load_error
    if _pipeline is not None or _load_error:
        return _pipeline
    async with _lock:
        if _pipeline is None and not _load_error:
            try:
                _pipeline = await asyncio.to_thread(_load_sync)
                log.info("Chronos model %s loaded", MODEL_ID)
            except Exception as exc:
                _load_error = str(exc)[:300]
                log.warning("Chronos unavailable: %s", _load_error)
    return _pipeline


def status() -> dict:
    return {"model": MODEL_ID, "loaded": _pipeline is not None, "error": _load_error}


def _first_crossing(times: list[str], values: list[float], threshold: float, above: bool) -> float | None:
    for i, v in enumerate(values):
        if (v >= threshold) if above else (v < threshold):
            return float(i + 1)
    return None


async def forecast_station(code: str) -> dict:
    cached = _cache.get(code)
    if cached and time.time() - cached[0] < CACHE_TTL_S:
        return cached[1]

    station = official.station_status(code)
    series = await official.series(code, CONTEXT_HOURS)
    cwc_forecast = await official.official_forecast(code)
    result: dict = {
        "station": station,
        "observed": series,
        "cwc_forecast": cwc_forecast,
        "ai_forecast": None,
        "model": MODEL_ID,
    }

    pipe = await pipeline()
    if pipe is None or len(series) < 24:
        result["ai_note"] = _load_error or "not enough recent readings to forecast"
        _cache[code] = (time.time(), result)
        return result

    import torch

    values = torch.tensor([r["level_m"] for r in series], dtype=torch.float32)
    q, _ = await asyncio.to_thread(
        pipe.predict_quantiles, values, prediction_length=HORIZON_HOURS, quantile_levels=[0.1, 0.5, 0.9]
    )
    last = datetime.fromisoformat(series[-1]["time"])
    times = [(last + timedelta(hours=h + 1)).isoformat(timespec="minutes") for h in range(HORIZON_HOURS)]
    p10 = [round(float(x), 3) for x in q[0, :, 0]]
    p50 = [round(float(x), 3) for x in q[0, :, 1]]
    p90 = [round(float(x), 3) for x in q[0, :, 2]]

    danger, warning = station.get("danger_level"), station.get("warning_level")
    now_level = series[-1]["level_m"]
    outlook: dict = {}
    if danger:
        if now_level >= danger:
            outlook["hours_to_below_danger"] = _first_crossing(times, p50, danger, above=False)
        else:
            outlook["hours_to_danger_p50"] = _first_crossing(times, p50, danger, above=True)
            outlook["hours_to_danger_p90"] = _first_crossing(times, p90, danger, above=True)
    if warning and now_level < warning:
        outlook["hours_to_warning_p50"] = _first_crossing(times, p50, warning, above=True)
    outlook["peak_p50_m"] = max(p50)
    outlook["peak_p90_m"] = max(p90)
    outlook["change_24h_p50_m"] = round(p50[23] - now_level, 3)

    result["ai_forecast"] = {"times": times, "p10": p10, "p50": p50, "p90": p90, "outlook": outlook}
    _cache[code] = (time.time(), result)
    return result
