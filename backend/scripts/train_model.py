"""
Fit the logistic classifier that calibrates the rule score.

Sampling design (the part that actually determines whether this is worth
anything)
--------------------------------------------------------------------------
The naive way to build this dataset is: positives = flood dates, negatives =
random dates. A model trained that way learns one thing, "it is the monsoon", and
scores 0.95 AUC while being useless — every Indian city is wet in July.

So instead, negatives are drawn from *the same calendar dates as the positives*.
For each date in the historical register we score all 41 monitored locations:
the location that actually flooded is the positive, and the other locations on
that same day — which experienced the same season, often the same monsoon
system — are negatives. Any location with a recorded event within +/-7 days of
that date is excluded rather than labelled negative, because the register is not
exhaustive and a near-miss is not a clean zero.

That forces the model to learn what distinguished Silchar on 2022-06-20 from
Lucknow on 2022-06-20, which is the question the dashboard is actually asking.
A handful of quiet off-season dates are added so the model also sees genuinely
calm conditions.

The features are produced by the same features.py + risk.normalise_features path
the live engine uses, so there is no train/serve skew.

Usage
-----
    python backend/scripts/train_model.py                 # full run
    python backend/scripts/train_model.py --max-dates 20  # quick smoke test

Writes backend/app/data/risk_model.json (coefficients as readable JSON, not a
pickle, so a reviewer can see exactly what the model weights).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold

from app import features, risk, sources, store
from app.config import (
    CLIMATOLOGY_END_YEAR,
    CLIMATOLOGY_START_YEAR,
    ML_MODEL_PATH,
)
from app.engine import EVENTS, LOCATIONS, engine
from app.risk import FEATURE_ORDER

EXCLUSION_DAYS = 7      # near an event, a location is neither a clean 1 nor a clean 0
LOOKBACK_DAYS = 10      # archive window needed to build 72h/7d accumulations
QUIET_DATES = 10        # extra off-season negatives
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "archive"
SAMPLES_PATH = ML_MODEL_PATH.parent / "training_samples.json"


def unique_event_dates() -> list[date]:
    seen = set()
    out = []
    for e in sorted(EVENTS, key=lambda e: e["date"]):
        try:
            d = date.fromisoformat(e["date"])
        except ValueError:
            continue
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def events_by_location() -> dict[str, list[date]]:
    out: dict[str, list[date]] = defaultdict(list)
    for e in EVENTS:
        try:
            out[e["location_id"]].append(date.fromisoformat(e["date"]))
        except ValueError:
            continue
    return out


def quiet_dates(rng: random.Random, n: int, event_dates: list[date]) -> list[date]:
    """Dry-season dates, far from any recorded event — the easy negatives."""
    busy = {d for ed in event_dates for d in (ed + timedelta(days=k) for k in range(-20, 21))}
    picks: list[date] = []
    guard = 0
    while len(picks) < n and guard < n * 60:
        guard += 1
        year = rng.randint(CLIMATOLOGY_START_YEAR + 6, CLIMATOLOGY_END_YEAR)
        month = rng.choice([1, 2, 3, 4, 11, 12])  # outside the SW monsoon
        day = rng.randint(1, 28)
        d = date(year, month, day)
        if d not in busy and d not in picks:
            picks.append(d)
    return picks


async def build_dataset(max_dates: int | None, seed: int) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    rng = random.Random(seed)
    loc_events = events_by_location()
    ev_dates = unique_event_dates()

    sample_dates = ev_dates + quiet_dates(rng, QUIET_DATES, ev_dates)
    if max_dates:
        sample_dates = sample_dates[:max_dates]

    print(f"{len(ev_dates)} event dates + {QUIET_DATES} quiet dates -> {len(sample_dates)} dates to fetch")
    print(f"each date scores up to {len(LOCATIONS)} locations\n")

    rows: list[dict] = []
    X: list[list[float]] = []
    y: list[int] = []

    async with sources.make_client() as client:
        for i, target in enumerate(sample_dates, start=1):
            start = target - timedelta(days=LOOKBACK_DAYS)
            end = target + timedelta(days=1)
            t0 = time.perf_counter()
            # Archive responses are cached per date so a run that hits Open-Meteo's
            # hourly quota can simply be re-run later and resume where it stopped.
            cache_file = CACHE_DIR / f"{target.isoformat()}.json"
            if cache_file.exists():
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                weather, flood = cached["weather"], cached["flood"]
            else:
                try:
                    weather, flood = await sources.fetch_archive(client, LOCATIONS, start, end)
                except Exception as exc:
                    print(f"[{i}/{len(sample_dates)}] {target} FETCH FAILED: {str(exc)[:110]}")
                    continue
                if len(weather) < len(LOCATIONS) // 2 or len(flood) < len(LOCATIONS) // 2:
                    print(f"[{i}/{len(sample_dates)}] {target} incomplete archive "
                          f"({len(weather)} weather / {len(flood)} flood) - likely quota; not cached")
                    continue
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps({"weather": weather, "flood": flood}), encoding="utf-8")

            reference = datetime.combine(target, datetime.min.time()).replace(hour=8)
            n_pos = n_neg = n_skip = 0

            for loc in LOCATIONS:
                w = weather.get(loc["id"])
                if not w:
                    continue

                nearest = min(
                    (abs((d - target).days) for d in loc_events.get(loc["id"], [])),
                    default=10_000,
                )
                if nearest == 0:
                    label = 1
                elif nearest <= EXCLUSION_DAYS:
                    n_skip += 1
                    continue  # ambiguous: too close to a recorded event to call negative
                else:
                    label = 0

                fv = features.build_feature_vector(
                    loc,
                    w,
                    flood.get(loc["id"], {}),
                    engine.climatology.get(loc["id"]),
                    EVENTS,
                    reference,
                )
                norm = risk.normalise_features(fv)
                X.append([norm.get(k, 0.0) / 100.0 for k in FEATURE_ORDER])
                y.append(label)
                event = next(
                    (e for e in EVENTS if e["location_id"] == loc["id"] and e["date"] == target.isoformat()),
                    None,
                ) if label else None
                rows.append(
                    {
                        "location_id": loc["id"],
                        "date": target.isoformat(),
                        "label": label,
                        "rule_score": risk.score_from_normalised(norm)["rule_score"],
                        # the normalised vector is what ml.py uses for analog search
                        # and anomaly detection, so it is kept, not just the label
                        "features": {k: round(norm.get(k, 0.0), 2) for k in FEATURE_ORDER},
                        "rain_24h_mm": fv["rain"].get("rain_24h_mm"),
                        "discharge_cumecs": fv["river"].get("current_cumecs"),
                        "percentile": fv["river"].get("percentile_for_season"),
                        "headline": event["headline"] if event else None,
                        "severity": event["severity"] if event else None,
                    }
                )
                n_pos += label
                n_neg += 1 - label

            print(
                f"[{i}/{len(sample_dates)}] {target}  +{n_pos} pos  {n_neg} neg  "
                f"{n_skip} skipped  ({time.perf_counter()-t0:.1f}s)"
            )

    return np.asarray(X, dtype=float), np.asarray(y, dtype=int), rows


def train(X: np.ndarray, y: np.ndarray) -> tuple[LogisticRegression, dict]:
    pos, neg = int(y.sum()), int(len(y) - y.sum())
    print(f"\ndataset: {len(y)} samples, {pos} positive, {neg} negative "
          f"({100*pos/max(len(y),1):.1f}% positive)")

    if pos < 8:
        raise SystemExit("too few positives to train anything meaningful")

    # Positives are rare by construction, so the classes are balanced by weight
    # rather than by resampling; L2 keeps the coefficients stable on a small,
    # correlated feature set.
    model = LogisticRegression(
        class_weight="balanced",
        C=0.6,
        max_iter=3000,
        solver="lbfgs",
    )

    metrics: dict = {}
    n_splits = min(5, pos, neg)
    if n_splits >= 3:
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=7)
        aucs, aps = [], []
        for train_idx, test_idx in cv.split(X, y):
            m = LogisticRegression(class_weight="balanced", C=0.6, max_iter=3000)
            m.fit(X[train_idx], y[train_idx])
            p = m.predict_proba(X[test_idx])[:, 1]
            if len(set(y[test_idx])) > 1:
                aucs.append(roc_auc_score(y[test_idx], p))
                aps.append(average_precision_score(y[test_idx], p))
        if aucs:
            metrics["cv_roc_auc"] = float(np.mean(aucs))
            metrics["cv_roc_auc_std"] = float(np.std(aucs))
            metrics["cv_average_precision"] = float(np.mean(aps))
            metrics["cv_folds"] = len(aucs)

    model.fit(X, y)
    train_p = model.predict_proba(X)[:, 1]
    if len(set(y)) > 1:
        metrics["train_roc_auc"] = float(roc_auc_score(y, train_p))
    metrics["positive_rate"] = float(pos / len(y))
    return model, metrics


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-dates", type=int, default=None, help="cap dates fetched (smoke test)")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--dump-dataset", type=Path, default=None, help="also write the raw samples as JSON")
    args = ap.parse_args()

    store.init_db()
    asyncio.run(engine.load_climatology())
    print(f"climatology available for {len(engine.climatology)}/{len(LOCATIONS)} locations")
    if len(engine.climatology) < len(LOCATIONS):
        print("  note: locations without a baseline will score 0 on the percentile feature")

    X, y, rows = asyncio.run(build_dataset(args.max_dates, args.seed))
    if not len(X):
        raise SystemExit("no samples collected — check network access to the Open-Meteo archive")

    model, metrics = train(X, y)

    coefficients = {name: round(float(c), 5) for name, c in zip(FEATURE_ORDER, model.coef_[0])}
    payload = {
        "kind": "logistic_regression",
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_samples": int(len(y)),
        "n_positive": int(y.sum()),
        "feature_order": FEATURE_ORDER,
        "coefficients": coefficients,
        "intercept": round(float(model.intercept_[0]), 5),
        "metrics": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in metrics.items()},
        "sampling": {
            "strategy": "date-matched negatives: all monitored locations scored on each event date",
            "exclusion_days": EXCLUSION_DAYS,
            "quiet_dates": QUIET_DATES,
            "climatology": f"{CLIMATOLOGY_START_YEAR}-{CLIMATOLOGY_END_YEAR}",
            "note": (
                "Negatives share calendar dates with positives so the model cannot win by "
                "learning seasonality alone."
            ),
        },
    }

    ML_MODEL_PATH.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    print("\n--- coefficients (positive = raises flood probability) ---")
    for name, c in sorted(coefficients.items(), key=lambda kv: -abs(kv[1])):
        bar = "#" * int(min(abs(c) * 6, 34))
        print(f"  {name:<26}{c:>9.4f}  {bar}")
    print(f"  {'(intercept)':<26}{payload['intercept']:>9.4f}")

    print("\n--- metrics ---")
    for k, v in payload["metrics"].items():
        print(f"  {k:<26}{v}")

    print(f"\nwrote {ML_MODEL_PATH}")

    SAMPLES_PATH.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(rows)} feature samples to {SAMPLES_PATH} (used for analogs + anomaly detection)")
    if args.dump_dataset:
        args.dump_dataset.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print(f"wrote dataset to {args.dump_dataset}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
