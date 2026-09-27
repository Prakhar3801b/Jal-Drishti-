"""
Offline back-test over the archive cache written by train_model.py.

No network: it re-scores every cached flood date for every monitored location and
reports how well the score separates real flood days from same-day non-flood days.
Fast enough to run after every change to the scoring rules.

    python backend/scripts/evaluate_cached.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from sklearn.metrics import roc_auc_score

from app import features, risk, store
from app.engine import EVENTS, LOCATIONS, engine

CACHE = Path(__file__).resolve().parent.parent / ".cache" / "archive"
EXCLUSION_DAYS = 7


def collect() -> tuple[list[float], list[float], list[int], list[str]]:
    loc_events: dict[str, list[date]] = defaultdict(list)
    for e in EVENTS:
        loc_events[e["location_id"]].append(date.fromisoformat(e["date"]))

    rule, final, labels, names = [], [], [], []
    for f in sorted(CACHE.glob("*.json")):
        target = date.fromisoformat(f.stem)
        cached = json.loads(f.read_text(encoding="utf-8"))
        ref = datetime.combine(target, datetime.min.time()).replace(hour=8)
        for loc in LOCATIONS:
            w = cached["weather"].get(loc["id"])
            if not w:
                continue
            nearest = min((abs((d - target).days) for d in loc_events.get(loc["id"], [])), default=9999)
            if 0 < nearest <= EXCLUSION_DAYS:
                continue
            fv = features.build_feature_vector(
                loc, w, cached["flood"].get(loc["id"], {}), engine.climatology.get(loc["id"]), EVENTS, ref
            )
            scored = risk.score_from_normalised(risk.normalise_features(fv))
            rule.append(scored["rule_score"])
            final.append(scored["score"])
            labels.append(1 if nearest == 0 else 0)
            names.append(f"{target} {loc['name']}")
    return rule, final, labels, names


def report(title: str, scores: list[float], labels: list[int]) -> None:
    s, y = np.array(scores), np.array(labels)
    pos, neg = s[y == 1], s[y == 0]
    print(f"\n{title}")
    print(f"  samples {len(y)} ({int(y.sum())} flood days)   ROC AUC {roc_auc_score(y, s):.3f}")
    print(f"  mean score: flood days {pos.mean():.1f}  |  non-flood days {neg.mean():.1f}")
    print(f"  {'threshold':<14}{'flood days caught':>20}{'false alarms':>16}")
    for cut, name in ((25, 'Yellow+'), (50, 'Orange+'), (75, 'Red')):
        print(f"  {name:<14}{100 * (pos >= cut).mean():>19.1f}%{100 * (neg >= cut).mean():>15.1f}%")


def main() -> int:
    store.init_db()
    asyncio.run(engine.load_climatology())
    rule, final, labels, names = collect()
    report("Rule score", rule, labels)
    report("Final score (rules + ML blend)", final, labels)
    missed = sorted((f, n) for f, n, l in zip(final, names, labels) if l == 1)[:8]
    print("\n  lowest-scored real floods:")
    for f, n in missed:
        print(f"    {f:5.1f}  {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
