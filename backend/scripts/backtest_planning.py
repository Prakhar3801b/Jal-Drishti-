"""
Back-test the response planner against severity-only prioritisation on real floods.

For each of the 67 dates in the stored back-test samples (70 real flood days, the
other monitored places on the same dates as controls), both planners allocate the
same national stock of rescue teams and boats:

    severity-only  rank places by their *current* score (observed rain and river
                   only - forecast rain removed) and fill each from its nearest depots
    JalDrishti     the MILP planner: forecast-inclusive score, calibrated chance of
                   flooding, people exposed, road travel time, diminishing returns

Then the outcome is read from what actually happened (the flood register):

    flooded places reached    places that really flooded that got at least one
                              rescue team or boat arriving in time
    units to flooded places   share of dispatched units that went where a flood
                              really happened
    people reached (realised) the planner's own reach measure, counted only in
                              places that really flooded

Limits, stated: timing is approximate (forecast-driven places peak at 24 h, the
rest now), the register lists which places flooded but not how many people were
rescued, and it is not exhaustive (a unit sent to an unlisted flood counts as
wasted). Travel times come from the cached OSRM matrix when present.

    python backend/scripts/backtest_planning.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import planning, risk  # noqa: E402
from app.config import DATA_DIR  # noqa: E402
from app.engine import LOCATIONS_BY_ID  # noqa: E402
from app.resources import HOLDS, _seed_rows  # noqa: E402

RESCUE = ("rescue_team", "boat")


def situation(loc: dict, features: dict) -> dict:
    full = risk.score_from_normalised(features)["score"]
    observed = risk.score_from_normalised(features | {"rain_forecast_24h": 0.0, "rain_forecast_72h": 0.0})["score"]
    forecast_driven = full > observed + 2
    s_peak = max(full, observed)
    t_peak = 24.0 if forecast_driven else 0.0
    mech = risk.dominant_hazard(features)["mechanism"]
    pop = int(loc.get("population") or 0)
    tier = "red" if observed >= 75 else "orange" if observed >= 50 else "yellow" if observed >= 25 else "green"
    return {
        "id": loc["id"], "name": loc["name"], "state": loc["state"], "district": loc.get("district"),
        "lat": loc["lat"], "lon": loc["lon"], "population": pop, "tier": tier,
        "s_now": round(observed, 1), "s_peak": round(s_peak, 1), "t_peak": t_peak, "driver": "forecast" if forecast_driven else "now",
        "mechanism": mech, "p": planning.p_flood(s_peak), "exposed": int(pop * (0.05 + 0.25 * s_peak / 100.0)),
        "window_h": max(t_peak, planning.ONGOING_WINDOW_H),
    }


def ours(places: list[dict], depots: list[dict], supply: dict) -> list[dict]:
    need, cands = {}, []
    for pl in places:
        if pl["s_peak"] < planning.PLAN_MIN_SCORE:
            continue
        for rtype in RESCUE:
            sizes = planning._tranches(planning._need(pl, rtype))
            for t, size in enumerate(sizes):
                if size:
                    need[(pl["id"], rtype, t)] = size
            for d in depots:
                if rtype not in HOLDS[d["kind"]] or supply.get((d["id"], rtype), 0) <= 0:
                    continue
                lg = planning._leg(d, pl, rtype)
                if not lg:
                    continue
                v = planning._value(pl, rtype, lg["timely"])
                for t, size in enumerate(sizes):
                    if size and v * planning.TRANCHE_W[t] >= planning.MIN_VALUE:
                        cands.append({"depot_id": d["id"], "place_id": pl["id"], "rtype": rtype,
                                      "nkey": (pl["id"], rtype, t), "value": v * planning.TRANCHE_W[t], **lg})
    x, _ = planning._solve(cands, supply, need)
    return [{**c, "count": int(k)} for c, k in zip(cands, x) if k > 0]


def main() -> int:
    samples = json.loads((DATA_DIR / "training_samples.json").read_text(encoding="utf-8"))
    by_date: dict[str, list[dict]] = defaultdict(list)
    for s in samples:
        if s["location_id"] in LOCATIONS_BY_ID:
            by_date[s["date"]].append(s)

    depot_rows, stock = _seed_rows()
    depots = [d | {"stock": {}} for d in depot_rows]
    supply0 = {(did, r): total for did, r, total, _ in stock if r in RESCUE}

    tot = {k: defaultdict(float) for k in ("ours", "base")}
    n_flood = 0
    for date, rows in sorted(by_date.items()):
        places = [situation(LOCATIONS_BY_ID[r["location_id"]], r["features"]) for r in rows]
        flooded = {r["location_id"] for r in rows if r["label"] == 1}
        n_flood += len(flooded)
        by_place = {p["id"]: p for p in places}
        need_left = {(p["id"], r): planning._need(p, r) for p in places for r in RESCUE}
        # Realised outcome: the flood happened (p = 1) where the register says so, and not elsewhere.
        truth = {pid: p | {"p": 1.0 if pid in flooded else 0.0} for pid, p in by_place.items()}

        plans = {
            "ours": ours(places, depots, dict(supply0)),
            "base": [o for o in planning._baseline(places, depots, dict(supply0), {}) if o["rtype"] in RESCUE],
        }
        for name, allocs in plans.items():
            t = tot[name]
            units = sum(o["count"] for o in allocs)
            to_flooded = sum(o["count"] for o in allocs if o["place_id"] in flooded)
            reached = {o["place_id"] for o in allocs if o["place_id"] in flooded and o["timely"] >= 0.999}
            t["units"] += units
            t["units_to_flooded"] += to_flooded
            t["flooded_reached_in_time"] += len(reached)
            t["flooded_reached_any"] += len({o["place_id"] for o in allocs if o["place_id"] in flooded})
            t["people_reached"] += planning._evaluate(allocs, truth, need_left)["total"]

    print(f"\n{len(by_date)} flood dates, {n_flood} real flood place-days, same national stock of rescue teams and boats each day\n")
    print(f"{'':42s}{'severity-only':>16s}{'JalDrishti':>14s}")
    rows = [
        ("Flooded places reached in time", "flooded_reached_in_time", lambda v: f"{int(v)} / {n_flood}"),
        ("Flooded places reached at all", "flooded_reached_any", lambda v: f"{int(v)} / {n_flood}"),
        ("Units sent to places that flooded", "units_to_flooded", None),
        ("People reached in places that flooded", "people_reached", lambda v: f"{v:,.0f}"),
    ]
    for label, key, fmt in rows:
        b, o = tot["base"][key], tot["ours"][key]
        if fmt is None:
            fb = f"{100 * b / tot['base']['units']:.1f}%" if tot["base"]["units"] else "—"
            fo = f"{100 * o / tot['ours']['units']:.1f}%" if tot["ours"]["units"] else "—"
        else:
            fb, fo = fmt(b), fmt(o)
        print(f"{label:42s}{fb:>16s}{fo:>14s}")
    gain = tot["ours"]["people_reached"] - tot["base"]["people_reached"]
    if tot["base"]["people_reached"]:
        print(f"\nRealised reach: {gain:+,.0f} people ({100 * gain / tot['base']['people_reached']:+.1f}%) vs severity-only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
