"""
Back-test the risk score against the historical flood register.

This is the script that answers "are your weights any good, or did you just pick
numbers that looked sensible?". It replays the engine over every dated event and
reports, per alert threshold:

    hit rate       - share of real events the model would have flagged
    false alarms   - share of same-day non-event locations it also flagged
    lead time      - whether the score was already elevated the day before

The same-day comparison is the important column. Reporting only a hit rate is easy
to game: a model that returns 100 for everything catches every flood. So each
event date is also scored at every *other* monitored location, and the false-alarm
rate on those is reported next to the hit rate. A useful model separates the two.

Usage
-----
    python backend/scripts/backtest.py                  # all events
    python backend/scripts/backtest.py --limit 10       # quick check
    python backend/scripts/backtest.py --csv out.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import features, risk, sources, store
from app.engine import EVENTS, LOCATIONS, LOCATIONS_BY_ID, engine

EXCLUSION_DAYS = 7
LOOKBACK_DAYS = 10
THRESHOLDS = [(25, "Yellow+"), (50, "Orange+"), (75, "Red")]


def events_by_location() -> dict[str, list[date]]:
    out: dict[str, list[date]] = defaultdict(list)
    for e in EVENTS:
        try:
            out[e["location_id"]].append(date.fromisoformat(e["date"]))
        except ValueError:
            continue
    return out


def score_one(loc: dict, weather: dict, flood: dict, when: date) -> dict:
    reference = datetime.combine(when, datetime.min.time()).replace(hour=8)
    fv = features.build_feature_vector(
        loc, weather, flood, engine.climatology.get(loc["id"]), EVENTS, reference
    )
    norm = risk.normalise_features(fv)
    scored = risk.score_from_normalised(norm)
    return {
        "score": scored["score"],
        "rule_score": scored["rule_score"],
        "top_factor": max(norm.items(), key=lambda kv: kv[1] * risk.WEIGHTS[kv[0]])[0],
        "rain_24h": fv["rain"].get("rain_24h_mm"),
        "percentile": fv["river"].get("percentile_for_season"),
    }


async def run(limit: int | None) -> list[dict]:
    loc_events = events_by_location()
    dated = []
    for e in EVENTS:
        try:
            dated.append((date.fromisoformat(e["date"]), e))
        except ValueError:
            continue
    dated.sort(key=lambda t: t[0])
    if limit:
        dated = dated[-limit:]

    print(f"back-testing {len(dated)} events across {len(LOCATIONS)} monitored locations\n")
    results: list[dict] = []

    async with sources.make_client() as client:
        for i, (target, event) in enumerate(dated, start=1):
            loc = LOCATIONS_BY_ID.get(event["location_id"])
            if loc is None:
                continue
            start = target - timedelta(days=LOOKBACK_DAYS)
            end = target + timedelta(days=1)
            t0 = time.perf_counter()
            try:
                weather, flood = await sources.fetch_archive(client, LOCATIONS, start, end)
            except Exception as exc:
                print(f"[{i}/{len(dated)}] {target} {loc['name']:<16} FETCH FAILED: {str(exc)[:90]}")
                continue

            w = weather.get(loc["id"])
            if not w:
                continue

            on_day = score_one(loc, w, flood.get(loc["id"], {}), target)
            day_before = score_one(loc, w, flood.get(loc["id"], {}), target - timedelta(days=1))

            # Same-day control group: every other location with no nearby event.
            controls = []
            for other in LOCATIONS:
                if other["id"] == loc["id"]:
                    continue
                nearest = min(
                    (abs((d - target).days) for d in loc_events.get(other["id"], [])),
                    default=10_000,
                )
                if nearest <= EXCLUSION_DAYS:
                    continue
                ow = weather.get(other["id"])
                if not ow:
                    continue
                controls.append(score_one(other, ow, flood.get(other["id"], {}), target)["score"])

            row = {
                "date": target.isoformat(),
                "location": loc["name"],
                "state": loc["state"],
                "severity": event["severity"],
                "driver": event["driver"],
                "score": on_day["score"],
                "score_day_before": day_before["score"],
                "top_factor": on_day["top_factor"],
                "rain_24h": on_day["rain_24h"],
                "percentile": on_day["percentile"],
                "control_n": len(controls),
                "control_mean": round(sum(controls) / len(controls), 1) if controls else None,
                "control_over_50": sum(1 for c in controls if c >= 50),
                "control_over_25": sum(1 for c in controls if c >= 25),
            }
            results.append(row)

            flag = "RED " if on_day["score"] >= 75 else "ORNG" if on_day["score"] >= 50 else "YELW" if on_day["score"] >= 25 else "  - "
            print(
                f"[{i}/{len(dated)}] {target} {loc['name']:<16} sev{event['severity']} "
                f"score={on_day['score']:>5.1f} {flag} (prev {day_before['score']:>5.1f}) "
                f"controls mean={row['control_mean']} n={row['control_n']} "
                f"({time.perf_counter()-t0:.1f}s)"
            )

    return results


def report(rows: list[dict]) -> None:
    if not rows:
        print("no results")
        return

    print("\n" + "=" * 74)
    print("BACK-TEST SUMMARY")
    print("=" * 74)
    print(f"events scored: {len(rows)}")

    scores = [r["score"] for r in rows]
    print(f"mean event score: {sum(scores)/len(scores):.1f}")
    controls = [r["control_mean"] for r in rows if r["control_mean"] is not None]
    if controls:
        print(f"mean same-day control score: {sum(controls)/len(controls):.1f}")
        print(f"separation: {sum(scores)/len(scores) - sum(controls)/len(controls):+.1f} points")

    print("\nby threshold:")
    print(f"  {'threshold':<12}{'hit rate':>12}{'false alarm':>14}{'lead (prev day)':>18}")
    for cut, name in THRESHOLDS:
        hits = sum(1 for r in rows if r["score"] >= cut)
        lead = sum(1 for r in rows if r["score_day_before"] >= cut)
        total_controls = sum(r["control_n"] for r in rows)
        key = "control_over_50" if cut >= 50 else "control_over_25"
        fa = sum(r[key] for r in rows) if cut != 75 else None
        fa_txt = f"{100*fa/total_controls:.1f}%" if fa is not None and total_controls else "—"
        print(
            f"  {name:<12}{100*hits/len(rows):>11.1f}%{fa_txt:>14}"
            f"{100*lead/len(rows):>17.1f}%"
        )

    print("\nby severity:")
    for sev in (3, 2, 1):
        sub = [r for r in rows if r["severity"] == sev]
        if not sub:
            continue
        mean = sum(r["score"] for r in sub) / len(sub)
        flagged = sum(1 for r in sub if r["score"] >= 50)
        print(f"  severity {sev}: n={len(sub):<4} mean={mean:>5.1f}  Orange+ {100*flagged/len(sub):>5.1f}%")

    print("\nby driver:")
    by_driver: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_driver[r["driver"]].append(r["score"])
    for driver, vals in sorted(by_driver.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        print(f"  {driver:<20} n={len(vals):<4} mean={sum(vals)/len(vals):>5.1f}")

    print("\nworst misses (real events the model scored lowest):")
    for r in sorted(rows, key=lambda r: r["score"])[:6]:
        print(
            f"  {r['date']} {r['location']:<16} score={r['score']:>5.1f} "
            f"sev{r['severity']} {r['driver']:<18} rain24={r['rain_24h']}"
        )

    print("\ntop factor on event days:")
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r["top_factor"]] += 1
    for factor, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {factor:<26}{n:>4}  ({100*n/len(rows):.0f}%)")
    print("=" * 74)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="only the N most recent events")
    ap.add_argument("--csv", type=Path, default=None, help="write per-event rows to CSV")
    args = ap.parse_args()

    store.init_db()
    asyncio.run(engine.load_climatology())
    print(f"climatology: {len(engine.climatology)}/{len(LOCATIONS)} locations")
    model = risk.load_ml_model()
    print(f"ml model: {'loaded' if model else 'not loaded (rules only)'}\n")

    rows = asyncio.run(run(args.limit))
    report(rows)

    if args.csv and rows:
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nwrote {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
