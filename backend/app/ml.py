"""
Machine-learning features layered on the rule engine.

1. Analog forecasting (k-nearest neighbours)
   "Today in Patna looks most like Silchar on 2022-06-20." Every sample in
   training_samples.json is a real, dated location-day scored by the same
   feature pipeline, so the nearest *flood* days are genuine historical analogs,
   and the flood share among the k nearest days is an independent, non-parametric
   probability that needs no fitted weights at all.

2. Anomaly detection (Isolation Forest)
   Fitted on the non-flood days only, i.e. on what "normal" looks like across
   India. A high anomaly score means today's combination of rain, river and soil
   is rare *even if no single feature is extreme* - the case a threshold rule
   misses by construction.

3. Model attribution
   For the logistic classifier, coefficient x feature value is an exact additive
   decomposition of the log-odds, so the UI can show why the *model* agrees or
   disagrees with the rules, not just that it does.

All of it degrades cleanly: with no training samples, analogs are empty and
anomaly detection falls back to a z-score against the live snapshot.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Sequence

import numpy as np

from .config import DATA_DIR, FACTOR_LABELS, WEIGHTS
from .risk import FEATURE_ORDER, load_ml_model

log = logging.getLogger("jaldrishti.ml")

SAMPLES_PATH = DATA_DIR / "training_samples.json"
K_NEIGHBOURS = 15

# Weighted distance: a mismatch in heavily weighted features (today's rain, the
# river's percentile) matters more to "is this the same kind of day" than a
# mismatch in historical frequency.
_W = np.array([math.sqrt(WEIGHTS[k]) for k in FEATURE_ORDER])


class MLService:
    def __init__(self) -> None:
        self.samples: list[dict] = []
        self.X: np.ndarray | None = None
        self.y: np.ndarray | None = None
        self.forest = None
        self.active: np.ndarray | None = None
        self.normal_p95: np.ndarray | None = None
        self.score_ref: tuple[float, float] | None = None
        self.load()

    # ------------------------------------------------------------------ setup

    def load(self) -> None:
        if not SAMPLES_PATH.exists():
            log.info("no training samples yet; analogs disabled, anomaly uses snapshot z-scores")
            return
        try:
            rows = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("could not read training samples: %s", exc)
            return
        rows = [r for r in rows if r.get("features")]
        if len(rows) < 30:
            return
        self.samples = rows
        self.X = np.array([[r["features"].get(k, 0.0) / 100.0 for k in FEATURE_ORDER] for r in rows])
        self.y = np.array([int(r["label"]) for r in rows])

        # A feature that never varied in training (soil moisture: the historical
        # archive does not serve those layers) carries no information, and worse,
        # any live non-zero value would look "anomalous". Such columns are dropped
        # from the forest, the percentile check and the analog distance.
        self.active = self.X.std(axis=0) > 1e-6
        dropped = [k for k, a in zip(FEATURE_ORDER, self.active) if not a]
        if dropped:
            log.info("ML ignoring features constant in training: %s", ", ".join(dropped))

        normal = self.X[self.y == 0][:, self.active]
        if len(normal) >= 30:
            from sklearn.ensemble import IsolationForest

            self.forest = IsolationForest(n_estimators=300, contamination="auto", random_state=7)
            self.forest.fit(normal)
            # decision_function: higher = more normal. Calibrate to 0-100 using the
            # spread of scores on normal days and on recorded flood days.
            normal_scores = self.forest.decision_function(normal)
            self.score_ref = (float(np.percentile(normal_scores, 50)), float(np.percentile(normal_scores, 1)))
            self.normal_p95 = np.percentile(normal, 95, axis=0)
        log.info("ML service: %d samples (%d floods)", len(rows), int(self.y.sum()))

    @property
    def ready(self) -> bool:
        return self.X is not None

    # --------------------------------------------------------------- analogs

    def analogs(self, norm: dict[str, float], exclude_location: str | None = None, top: int = 3) -> dict:
        if not self.ready:
            return {"available": False, "reason": "no training samples - run scripts/bootstrap_ml.py"}

        x = np.array([norm.get(k, 0.0) / 100.0 for k in FEATURE_ORDER])
        w = _W * self.active
        dist = np.sqrt((((self.X - x) * w) ** 2).sum(axis=1))
        order = np.argsort(dist)

        k_idx = order[:K_NEIGHBOURS]
        # Distance-weighted vote among the k nearest days, flood or not.
        vote = 1.0 / (dist[k_idx] + 0.02)
        knn_prob = float((vote * self.y[k_idx]).sum() / vote.sum())

        max_d = float(np.sqrt((w**2).sum()))  # distance between all-zeros and all-ones
        matches = []
        for i in order:
            if self.y[i] != 1:
                continue
            row = self.samples[i]
            similarity = max(0.0, 1.0 - float(dist[i]) / (max_d * 0.6))
            matches.append(
                {
                    "location_id": row["location_id"],
                    "date": row["date"],
                    "headline": row.get("headline"),
                    "severity": row.get("severity"),
                    "similarity": round(similarity, 3),
                    "rain_24h_mm": row.get("rain_24h_mm"),
                    "percentile": row.get("percentile"),
                    "same_location": row["location_id"] == exclude_location,
                }
            )
            if len(matches) >= top:
                break

        return {
            "available": True,
            "knn_flood_probability": round(knn_prob, 3),
            "k": K_NEIGHBOURS,
            "neighbours_that_flooded": int(self.y[k_idx].sum()),
            "matches": matches,
            "training_days": len(self.samples),
        }

    # --------------------------------------------------------------- anomaly

    def anomaly(self, norm: dict[str, float], population: Sequence[dict[str, float]] = ()) -> dict:
        x = np.array([norm.get(k, 0.0) / 100.0 for k in FEATURE_ORDER])

        if self.forest is not None and self.score_ref is not None:
            xa = x[self.active]
            raw = float(self.forest.decision_function(xa.reshape(1, -1))[0])
            median, p1 = self.score_ref
            # median of normal days -> 0, 1st percentile of normal days -> 80.
            span = max(median - p1, 1e-6)
            score = max(0.0, min(100.0, 80.0 * (median - raw) / span))
            active_keys = [k for k, a in zip(FEATURE_ORDER, self.active) if a]
            unusual = [
                k for k, v, p in zip(active_keys, xa, self.normal_p95) if v > p and v >= 0.25
            ]
            method = "isolation_forest"
        else:
            # Fallback: how far outside today's national spread each feature sits.
            if len(population) < 5:
                return {"available": False}
            P = np.array([[p.get(k, 0.0) / 100.0 for k in FEATURE_ORDER] for p in population])
            mu, sd = P.mean(axis=0), P.std(axis=0) + 1e-6
            z = (x - mu) / sd
            score = float(max(0.0, min(100.0, 22.0 * max(z.max(), 0.0))))
            unusual = [k for k, zz in zip(FEATURE_ORDER, z) if zz > 1.5]
            method = "snapshot_zscore"

        level = "extreme" if score >= 75 else "high" if score >= 50 else "elevated" if score >= 25 else "normal"
        return {
            "available": True,
            "score": round(score, 1),
            "level": level,
            "method": method,
            "unusual_features": [
                {"key": k, "label_en": FACTOR_LABELS[k][0], "label_hi": FACTOR_LABELS[k][1]} for k in unusual
            ],
        }

    # ----------------------------------------------------------- attribution

    @staticmethod
    def attribution(norm: dict[str, float]) -> list[dict] | None:
        model = load_ml_model()
        if model is None:
            return None
        rows = []
        for k in model.feature_order:
            contrib = model.coefficients.get(k, 0.0) * (norm.get(k, 0.0) / 100.0)
            rows.append(
                {
                    "key": k,
                    "label_en": FACTOR_LABELS[k][0],
                    "label_hi": FACTOR_LABELS[k][1],
                    "log_odds": round(contrib, 3),
                }
            )
        rows.sort(key=lambda r: abs(r["log_odds"]), reverse=True)
        return rows


ml = MLService()
