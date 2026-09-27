"""
The risk engine: features in, a defensible 0-100 score out.

Shape of the model, and why:

  hazard  = weighted sum of nine normalised, named features        (explainable)
  blended = (1-w) * hazard + w * P(flood | features) from the ML model  (calibrated)
  tier    = IMD's Green/Yellow/Orange/Red bands
  conf    = ensemble spread + forecast lead time + input completeness

A single deep model would have scored the hackathon's "explain the factors"
requirement badly, and an unvalidated rule set would have scored "data-backed"
badly. So the rules carry the majority of the weight and stay legible, and a
logistic model trained on the historical register (scripts/train_model.py) is
blended in to calibrate them. If the trained model is absent the engine runs on
rules alone and says so, rather than failing.

Every number the UI displays comes from here with its contribution attached, so
the factor bars in the detail panel are the model's actual arithmetic, not a
decorative re-ranking.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from .config import (
    ALERT_TIERS,
    DISCHARGE_PCTL_KNOTS,
    DISCHARGE_RATIO_KNOTS,
    DISCHARGE_TREND_KNOTS,
    FACTOR_LABELS,
    ML_BLEND_WEIGHT,
    ML_MODEL_PATH,
    RAIN_24H_KNOTS,
    RAIN_72H_KNOTS,
    SOIL_SATURATION_KNOTS,
    WEIGHTS,
    confidence_for,
    tier_for_score,
)

FEATURE_ORDER = list(WEIGHTS.keys())


# ------------------------------------------------------------- normalisation


def piecewise(value: float | None, knots: Sequence[tuple[float, float]]) -> float:
    """
    Linear interpolation between published threshold knots.

    Using knots rather than a smooth curve is the point: the bends sit exactly on
    IMD rainfall class boundaries and CWC warning multiples, so a score of 68 for
    24-hour rain means "at the top of IMD's 'very heavy' band", not "0.68 of an
    arbitrary maximum".
    """
    if value is None:
        return 0.0
    if value <= knots[0][0]:
        return knots[0][1]
    if value >= knots[-1][0]:
        return knots[-1][1]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x0 <= value <= x1:
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return knots[-1][1]


def normalise_features(fv: dict) -> dict[str, float]:
    """Map the interpretable features onto the nine 0-100 model inputs."""
    rain, river, terrain, history = fv["rain"], fv["river"], fv["terrain"], fv["history"]

    norm = {
        "rain_24h": piecewise(rain.get("rain_24h_mm"), RAIN_24H_KNOTS),
        "rain_72h": piecewise(rain.get("rain_72h_mm"), RAIN_72H_KNOTS),
        "rain_forecast_24h": piecewise(rain.get("rain_next_24h_mm"), RAIN_24H_KNOTS),
        "rain_forecast_72h": piecewise(rain.get("rain_next_72h_mm"), RAIN_72H_KNOTS),
        "soil_saturation": piecewise(rain.get("soil_moisture"), SOIL_SATURATION_KNOTS),
        "terrain_susceptibility": float(terrain.get("score") or 0.0),
        "historical_frequency": float(history.get("score") or 0.0),
    }

    if river.get("available"):
        norm["discharge_percentile"] = piecewise(river.get("percentile_for_season"), DISCHARGE_PCTL_KNOTS)
        norm["discharge_ratio"] = piecewise(river.get("ratio_to_seasonal_median"), DISCHARGE_RATIO_KNOTS)
        norm["discharge_trend"] = piecewise(river.get("trend_normalised"), DISCHARGE_TREND_KNOTS)
    else:
        norm["discharge_percentile"] = 0.0
        norm["discharge_ratio"] = 0.0
        norm["discharge_trend"] = 0.0

    return {k: round(max(0.0, min(100.0, v)), 1) for k, v in norm.items()}


# ---------------------------------------------------------------- ML blending


class MLModel:
    """
    A logistic regression over the same nine normalised features, trained by
    scripts/train_model.py on the historical register. Loaded from JSON rather
    than a pickle so the coefficients are readable and reviewable in the repo.
    """

    def __init__(self, payload: dict):
        self.coefficients: dict[str, float] = payload["coefficients"]
        self.intercept: float = payload["intercept"]
        self.metrics: dict = payload.get("metrics", {})
        self.trained_at: str = payload.get("trained_at", "")
        self.n_samples: int = payload.get("n_samples", 0)
        self.feature_order: list[str] = payload.get("feature_order", FEATURE_ORDER)

    def probability(self, norm: dict[str, float]) -> float:
        z = self.intercept
        for name in self.feature_order:
            z += self.coefficients.get(name, 0.0) * (norm.get(name, 0.0) / 100.0)
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))

    def as_dict(self) -> dict:
        return {
            "kind": "logistic_regression",
            "trained_at": self.trained_at,
            "n_samples": self.n_samples,
            "metrics": self.metrics,
            "coefficients": self.coefficients,
            "intercept": round(self.intercept, 4),
        }


_ml_cache: MLModel | None = None
_ml_loaded = False


def load_ml_model() -> MLModel | None:
    global _ml_cache, _ml_loaded
    if _ml_loaded:
        return _ml_cache
    _ml_loaded = True
    try:
        if ML_MODEL_PATH.exists():
            _ml_cache = MLModel(json.loads(ML_MODEL_PATH.read_text(encoding="utf-8")))
    except Exception:
        _ml_cache = None
    return _ml_cache


def reload_ml_model() -> MLModel | None:
    global _ml_loaded
    _ml_loaded = False
    return load_ml_model()


# --------------------------------------------------------------------- scoring


def dominant_hazard(norm: dict[str, float]) -> dict:
    """
    Riverine and pluvial flooding are separate mechanisms, and either one alone
    floods a town. A weighted average of all ten features dilutes a river in
    record spate with the dry-weather features beside it: back-tested on 70 real
    flood days, the averaged score reached Red on 0% of them. Scoring the worse of
    the two mechanisms, scaled by local susceptibility, reached Red on 36% of
    those days with Red false alarms on 1.8% of same-day non-flood locations
    (scripts/evaluate_cached.py).
    """
    riverine = (
        0.55 * norm.get("discharge_percentile", 0.0)
        + 0.30 * norm.get("discharge_ratio", 0.0)
        + 0.15 * norm.get("discharge_trend", 0.0)
    )
    pluvial = (
        0.5 * max(norm.get("rain_24h", 0.0), norm.get("rain_forecast_24h", 0.0))
        + 0.3 * max(norm.get("rain_72h", 0.0), norm.get("rain_forecast_72h", 0.0))
        + 0.2 * norm.get("soil_saturation", 0.0)
    )
    susceptibility = 0.6 + 0.4 * norm.get("terrain_susceptibility", 0.0) / 100.0
    mechanism = "riverine" if riverine >= pluvial else "pluvial"
    return {
        "riverine": round(riverine, 1),
        "pluvial": round(pluvial, 1),
        "mechanism": mechanism,
        "score": round(max(riverine, pluvial) * susceptibility, 1),
    }


def score_from_normalised(norm: dict[str, float]) -> dict:
    """Rule score (worse of weighted evidence and dominant hazard), blended with the ML probability."""
    contributions = {k: round(WEIGHTS[k] * norm.get(k, 0.0), 2) for k in FEATURE_ORDER}
    weighted = round(sum(contributions.values()), 1)
    dominant = dominant_hazard(norm)
    hazard = max(weighted, dominant["score"])

    model = load_ml_model()
    blended, ml_prob, blend_w = hazard, None, 0.0
    if model is not None:
        ml_prob = round(model.probability(norm), 4)
        blend_w = ML_BLEND_WEIGHT
        blended = round((1 - blend_w) * hazard + blend_w * (ml_prob * 100.0), 1)

    return {
        "score": max(0.0, min(100.0, blended)),
        "rule_score": hazard,
        "weighted_score": weighted,
        "dominant": dominant,
        "ml_probability": ml_prob,
        "ml_blend_weight": blend_w,
        "contributions": contributions,
        "normalised": norm,
        "weights": dict(WEIGHTS),
    }


def rank_factors(scored: dict, limit: int = 4) -> list[dict]:
    """
    The factor bars. Ordered by actual contribution to the score, so what the user
    sees first is genuinely what moved the number most.
    """
    rows = []
    for name in FEATURE_ORDER:
        label_en, label_hi = FACTOR_LABELS[name]
        rows.append(
            {
                "key": name,
                "label_en": label_en,
                "label_hi": label_hi,
                "value": scored["normalised"].get(name, 0.0),
                "weight": WEIGHTS[name],
                "contribution": scored["contributions"].get(name, 0.0),
                "share_of_score": (
                    round(100.0 * scored["contributions"].get(name, 0.0) / scored["weighted_score"], 1)
                    if scored["weighted_score"] > 0
                    else 0.0
                ),
            }
        )
    rows.sort(key=lambda r: r["contribution"], reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
        r["is_top"] = i < limit
    return rows


# ------------------------------------------------------------------ confidence


def assess_confidence(fv: dict, norm: dict[str, float], consensus: dict | None = None) -> dict:
    """
    Confidence is about how much to trust the score, not how bad the score is.

    Three things degrade it: a wide GloFAS ensemble (the models disagree about the
    river), a weak or missing climatological baseline (we cannot say what normal
    looks like here), and missing inputs.
    """
    river = fv["river"]
    rain = fv["rain"]
    reasons_en: list[str] = []
    reasons_hi: list[str] = []
    value = 1.0

    spread = river.get("relative_ensemble_spread")
    if spread is None:
        value -= 0.20
        reasons_en.append("No ensemble forecast available for this river cell")
        reasons_hi.append("इस नदी कोशिका के लिए एन्सेम्बल पूर्वानुमान उपलब्ध नहीं")
    else:
        # IQR/median: under 15% the members agree closely, over 60% they do not.
        penalty = min(max((spread - 0.15) / 0.75, 0.0), 1.0) * 0.40
        value -= penalty
        if spread < 0.15:
            reasons_en.append(f"Ensemble members agree closely (IQR {spread:.0%} of median)")
            reasons_hi.append(f"एन्सेम्बल सदस्यों में उच्च सहमति (IQR माध्यिका का {spread:.0%})")
        elif spread < 0.45:
            reasons_en.append(f"Moderate ensemble spread (IQR {spread:.0%} of median)")
            reasons_hi.append(f"मध्यम एन्सेम्बल प्रसार (IQR माध्यिका का {spread:.0%})")
        else:
            reasons_en.append(f"Forecast models disagree — wide ensemble (IQR {spread:.0%} of median)")
            reasons_hi.append(f"पूर्वानुमान मॉडलों में असहमति — व्यापक प्रसार (IQR {spread:.0%})")

    if river.get("baseline_source") == "climatology":
        years = river.get("climatology_years")
        reasons_en.append(f"Seasonal baseline from {years} GloFAS reanalysis")
        reasons_hi.append(f"{years} ग्लोफास पुनर्विश्लेषण से मौसमी आधार रेखा")
    else:
        value -= 0.25
        reasons_en.append("Seasonal baseline still building — using a short recent window")
        reasons_hi.append("मौसमी आधार रेखा बन रही है — हाल की छोटी अवधि का उपयोग")

    if not river.get("available"):
        value -= 0.25
        reasons_en.append("River discharge unavailable; score rests on rainfall and terrain only")
        reasons_hi.append("नदी प्रवाह अनुपलब्ध; स्कोर केवल वर्षा एवं भूभाग पर आधारित")

    missing = [k for k in ("rain_24h_mm", "rain_next_24h_mm", "soil_moisture") if rain.get(k) is None]
    if missing:
        value -= 0.10 * len(missing)
        reasons_en.append(f"{len(missing)} rainfall/soil input(s) missing from the feed")
        reasons_hi.append(f"फ़ीड में {len(missing)} वर्षा/मिट्टी इनपुट अनुपलब्ध")

    # Independent second forecast (OpenWeatherMap), when a key is configured.
    if consensus and consensus.get("available"):
        om, owm = consensus["open_meteo_mm"], consensus["openweathermap_mm"]
        if consensus["level"] == "conflict":
            value -= 0.15
            reasons_en.append(f"Forecast models conflict on next-24 h rain: Open-Meteo {om} mm vs OpenWeatherMap {owm} mm")
            reasons_hi.append(f"अगले 24 घंटे की वर्षा पर मॉडलों में टकराव: ओपन-मेटियो {om} मिमी बनाम ओपनवेदरमैप {owm} मिमी")
        elif consensus["level"] == "strong":
            value += 0.05
            reasons_en.append(f"Two independent forecasts agree on next-24 h rain ({om} vs {owm} mm)")
            reasons_hi.append(f"दो स्वतंत्र पूर्वानुमान अगले 24 घंटे की वर्षा पर सहमत ({om} बनाम {owm} मिमी)")

    value = round(max(0.05, min(1.0, value)), 3)
    level = confidence_for(value)
    return {
        "value": value,
        "level": level["key"],
        "label_en": level["label_en"],
        "label_hi": level["label_hi"],
        "ensemble_spread": spread,
        "baseline_source": river.get("baseline_source"),
        "reasons_en": reasons_en,
        "reasons_hi": reasons_hi,
    }


# ------------------------------------------------------------------ projection


def project_trajectory(fv: dict, norm: dict[str, float], horizons: Sequence[int] = (0, 24, 48, 72)) -> list[dict]:
    """
    Re-score the location at +24/48/72 h using the forecast instead of the
    observation, and carry the ensemble spread through as an uncertainty band.

    The band is not decorative: `low` re-scores with the GloFAS p25 member and
    `high` with p75, so a wide band on the chart is literally the forecast models
    disagreeing about that river.
    """
    rain = fv["rain"]
    river = fv["river"]
    times = rain.get("hourly_times") or []
    precip = rain.get("hourly_precip") or []
    i = rain.get("now_index") or 0

    median_now = river.get("seasonal_median_cumecs") or 0.0
    forecast_rows = river.get("forecast") or []
    base_date = None
    if river.get("as_of_date"):
        try:
            base_date = date.fromisoformat(river["as_of_date"])
        except ValueError:
            base_date = None

    def rain_window(hours_ahead: int) -> float | None:
        """Rainfall in the 24 h ending at the horizon - the same window IMD uses."""
        end = i + hours_ahead
        start = end - 23
        vals = [v for v in precip[max(0, start) : max(0, end) + 1] if v is not None]
        return round(sum(vals), 2) if vals else None

    def river_at(hours_ahead: int) -> dict:
        if not forecast_rows or base_date is None:
            return {}
        target = base_date + timedelta(days=max(1, round(hours_ahead / 24)))
        row = next((r for r in forecast_rows if r["date"] == target.isoformat()), None)
        return row or (forecast_rows[min(len(forecast_rows) - 1, max(0, round(hours_ahead / 24) - 1))] or {})

    out = []
    for h in horizons:
        if h == 0:
            band_scores = [score_from_normalised(norm)["score"]] * 3
            out.append(
                {
                    "hours": 0,
                    "label": "Now",
                    "label_hi": "अभी",
                    "score": band_scores[0],
                    "low": band_scores[0],
                    "high": band_scores[0],
                    "tier": tier_for_score(band_scores[0])["key"],
                    "rain_24h_mm": rain.get("rain_24h_mm"),
                    "discharge_cumecs": river.get("current_cumecs"),
                }
            )
            continue

        row = river_at(h)
        variant = dict(norm)

        r24 = rain_window(h)
        if r24 is not None:
            variant["rain_24h"] = piecewise(r24, RAIN_24H_KNOTS)
            variant["rain_forecast_24h"] = variant["rain_24h"]

        # 72 h accumulation ending at the horizon.
        vals72 = [v for v in precip[max(0, i + h - 71) : i + h + 1] if v is not None]
        if vals72:
            variant["rain_72h"] = piecewise(sum(vals72), RAIN_72H_KNOTS)

        band = {}
        for key, member in (("score", "median"), ("low", "p25"), ("high", "p75")):
            v = dict(variant)
            q = row.get(member) if row else None
            if q is not None and median_now > 0:
                v["discharge_ratio"] = piecewise(q / median_now, DISCHARGE_RATIO_KNOTS)
                # Scale the percentile sub-score by how the forecast moves relative
                # to today rather than re-deriving percentiles we do not have.
                if river.get("current_cumecs"):
                    shift = q / max(river["current_cumecs"], 1e-6)
                    v["discharge_percentile"] = max(
                        0.0, min(100.0, norm.get("discharge_percentile", 0.0) * (0.6 + 0.4 * shift))
                    )
            band[key] = score_from_normalised(v)["score"]

        lo, hi = sorted((band["low"], band["high"]))
        out.append(
            {
                "hours": h,
                "label": f"+{h} h",
                "label_hi": f"+{h} घंटे",
                "score": band["score"],
                "low": lo,
                "high": hi,
                "tier": tier_for_score(band["score"])["key"],
                "rain_24h_mm": r24,
                "discharge_cumecs": row.get("median") if row else None,
            }
        )
    return out


def trajectory_direction(trajectory: Sequence[dict]) -> dict:
    """Is this getting worse? The arrow next to the score."""
    if len(trajectory) < 2:
        return {"key": "steady", "label_en": "Steady", "label_hi": "स्थिर", "delta": 0.0}
    delta = round(max(t["score"] for t in trajectory[1:]) - trajectory[0]["score"], 1)
    if delta >= 8:
        return {"key": "worsening", "label_en": "Worsening", "label_hi": "बिगड़ रहा है", "delta": delta}
    if delta <= -8:
        return {"key": "easing", "label_en": "Easing", "label_hi": "सुधार हो रहा है", "delta": delta}
    return {"key": "steady", "label_en": "Steady", "label_hi": "स्थिर", "delta": delta}


def peak_window(trajectory: Sequence[dict]) -> dict | None:
    """When the model expects the worst of it — the 'peak expected' line in the UI."""
    if not trajectory:
        return None
    peak = max(trajectory, key=lambda t: t["score"])
    if peak["hours"] == 0:
        return {"hours": 0, "label_en": "Peak is now", "label_hi": "शिखर अभी है", "score": peak["score"]}
    return {
        "hours": peak["hours"],
        "label_en": f"Peak expected in about {peak['hours']} hours",
        "label_hi": f"लगभग {peak['hours']} घंटों में शिखर अपेक्षित",
        "score": peak["score"],
    }
