"""
Flood response resource planning: who sends what, where, and why.

Given the live risk snapshot, the resource inventory and road travel times, the
planner allocates rescue teams, boats, dewatering pumps and barricade sets to
the places that need them, as a mixed-integer program (SciPy / HiGHS):

    maximise   sum  x[d,i,r,t] * v[d,i,r] * w[t]   expected people helped
    subject to sum_it x[d,i,r,t] <= available[d,r]  never more than a depot holds
               sum_d  x[d,i,r,t] <= need[i,r,t]      no more than a place can use
               x integer >= 0, only on feasible legs

Each place's need is split into three tranches worth w = 100%, 70% and 40% per
unit: the first units reach the worst-hit people, later ones widen coverage.
That diminishing return is what spreads scarce units across several places at
risk instead of emptying every depot into one.

For place i and resource type r:

    s_peak   worst score over the next 72 h: the forecast trajectory, and an
             upstream gauge above danger (flood wave) at its arrival time
    t_peak   hours until that peak (0 when it is happening now)
    p        chance of flooding at s_peak: the observed flood rate of each IMD
             band in the back-test (70 real flood days, 2,629 same-day non-flood
             days), interpolated between band centres
    exposed  population x (5% + 25% x s_peak / 100)   people in the flood area
    assets   hospitals and schools in the city's flood-prone 800 m cells (street
             grid, where one exists), counted as 1,000 and 300 people-equivalents;
             each such hospital also needs a pump, each underpass two barricade sets
    need     ceil(exposed x rel[r, mechanism] / cap[r]) minus units already there
    v        p x cap[r] x rel[r, mechanism] x timeliness

A unit counts in full only if it arrives (mobilisation + road time, slowed on
waterlogged roads) before the peak, or within 12 h for a flood already under way;
later arrivals count in proportion. SDRF and district stock stays in its state,
NDRF goes anywhere reachable by road. A unit whose expected benefit is under
MIN_VALUE people stays in reserve rather than being sent for nothing.

The same inputs also drive a severity-only baseline - rank places by current
score, fill each from its nearest depots - scored by the same yardstick, so the
plan can show what forecasting, exposure and travel time add. Each plan is
stored as a version with what changed and why; dispatched units become
deployments and the next plan builds around them.
"""

from __future__ import annotations

import json
import logging
import math
import uuid

import numpy as np

from . import resources, store, travel
from .resources import HOLDS, MOBILISE_H, RTYPES
from .engine import LOCATIONS_BY_ID

log = logging.getLogger("jaldrishti.planning")

PLAN_MIN_SCORE = 25.0  # Yellow and above
MIN_VALUE = 5.0  # expected people helped per unit below which a unit stays in reserve
ONGOING_WINDOW_H = 12.0  # a flood already under way: rescue arriving within 12 h still counts in full
FLOOD_ROAD_FACTOR = {"red": 1.5, "orange": 1.25}  # slower approach roads (assumption)
WAVE_SCORE = {"DANGER": 60.0, "WARNING": 45.0}  # upstream gauge -> downstream score at arrival (assumption)
MAX_NEED = 60  # units of one type a single place can absorb
TRANCHE_W = (1.0, 0.7, 0.4)  # worth of the first, second and last third of a place's need
PRONE_SUSCEPTIBILITY = 60.0  # a street cell this susceptible counts as flood-prone
HOSPITAL_EQ, SCHOOL_EQ = 1000, 300  # people-equivalents of a flood-prone hospital / school (assumption)
KEEP_PLANS = 60
# OSRM routes to the island UTs over ferry lines with unreliable times; mainland
# units reach them by sea or air lift, which this planner does not schedule.
ISLAND_STATES = {"Andaman and Nicobar Islands", "Lakshadweep"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_runs (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    trigger     TEXT NOT NULL,
    run_id      INTEGER,
    body        TEXT NOT NULL
);
"""

_calibration: dict | None = None
_current: dict | None = None
_current_key: tuple | None = None


def init() -> None:
    with store.db() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------- calibration


def calibration() -> dict:
    """
    Score -> chance of flooding, from the stored back-test samples: the share of
    place-days in each IMD band (Green/Yellow/Orange/Red) that actually flooded.
    Band rates rather than a fine-grained fit, because the top band holds only
    ~76 samples and a per-score curve would overfit them.
    """
    global _calibration
    if _calibration is not None:
        return _calibration
    from . import risk
    from .config import DATA_DIR

    samples = json.loads((DATA_DIR / "training_samples.json").read_text(encoding="utf-8"))
    scores = np.array([risk.score_from_normalised(s["features"])["score"] for s in samples])
    labels = np.array([s["label"] for s in samples])
    bands = []
    for lo, hi in ((0, 25), (25, 50), (50, 75), (75, 101)):
        m = (scores >= lo) & (scores < hi)
        bands.append({"from": lo, "to": min(hi, 100), "centre": (lo + min(hi, 100)) / 2, "days": int(m.sum()),
                      "floods": int(labels[m].sum()), "rate": round(float(labels[m].mean()), 4) if m.any() else 0.0})
    _calibration = {"bands": bands, "samples": int(len(labels)), "floods": int(labels.sum()),
                    "method": "observed flood rate per IMD band, interpolated between band centres"}
    return _calibration


def p_flood(score: float) -> float:
    bands = calibration()["bands"]
    return float(np.interp(score, [b["centre"] for b in bands], [b["rate"] for b in bands]))


# ------------------------------------------------------------------- places


def _assets(place_id: str) -> dict | None:
    """Critical facilities in the city's flood-prone street cells (None without a street grid)."""
    from . import safety

    grid = safety._static(place_id)
    if not grid:
        return None
    n = lambda v: len(v) if isinstance(v, list) else int(v or 0)  # noqa: E731
    prone = [c for c in grid.get("cells", []) if not c.get("sea") and (c.get("susceptibility") or 0) >= PRONE_SUSCEPTIBILITY]
    tunnels = sum(1 for c in prone for t in (c.get("tunnels") or []) if t)
    return {
        "cells_prone": len(prone),
        "hospitals": sum(n(c.get("hospitals")) for c in prone),
        "schools": sum(n(c.get("schools")) for c in prone),
        "fire_stations": sum(n(c.get("fire")) for c in prone),
        "underpasses": tunnels,
        "note": "named facilities in OpenStreetMap, up to 4 per 800 m cell - a lower bound",
    }


def _situation(a: dict, threats: list[dict]) -> dict:
    loc, risk = a["location"], a["risk"]
    s_now = float(risk["score"])
    s_peak, t_peak, driver = s_now, 0.0, "now"
    for pt in a.get("trajectory") or []:
        if pt["hours"] > 0 and pt["score"] > s_peak + 2:
            s_peak, t_peak, driver = float(pt["score"]), float(pt["hours"]), "forecast"
    for t in threats or []:
        cand = WAVE_SCORE.get(t.get("status"))
        if cand and cand > s_peak:
            s_peak, t_peak, driver = cand, float(t["eta_h"]["p50"]), f"wave:{t.get('river')}"
    mech = (risk.get("dominant") or {}).get("mechanism", "riverine")
    pop = int(loc.get("population") or 0)
    p = p_flood(s_peak)
    exposed = pop * (0.05 + 0.25 * s_peak / 100.0)
    assets = _assets(loc["id"])
    asset_eq = (HOSPITAL_EQ * assets["hospitals"] + SCHOOL_EQ * assets["schools"]) if assets else 0
    return {
        "id": loc["id"], "name": loc["name"], "name_hi": loc.get("name_hi"), "state": loc["state"],
        "district": loc.get("district"), "lat": loc["lat"], "lon": loc["lon"], "population": pop,
        "tier": risk["tier"]["key"], "s_now": round(s_now, 1), "s_peak": round(s_peak, 1), "t_peak": t_peak,
        "driver": driver, "mechanism": mech, "p": round(p, 4), "exposed": int(exposed), "assets": assets, "asset_eq": asset_eq,
        "window_h": max(t_peak, ONGOING_WINDOW_H),
    }


def _need(pl: dict, rtype: str, score: float | None = None) -> int:
    spec = RTYPES[rtype]
    s = pl["s_peak"] if score is None else score
    exposed = pl["population"] * (0.05 + 0.25 * s / 100.0) + pl.get("asset_eq", 0)
    n = math.ceil(exposed * spec["rel"][pl["mechanism"]] / spec["cap"])
    assets = pl.get("assets")
    if assets and s >= PLAN_MIN_SCORE:
        # Street-level needs the population share misses: a pump for every flood-prone
        # hospital, two barricade sets to close every flood-prone underpass.
        n += {"pump": assets["hospitals"], "barricade": 2 * assets["underpasses"]}.get(rtype, 0)
    return min(MAX_NEED, n)


def _point(depot: dict) -> dict:
    # SDRF and district depots sit at a monitored place: share its travel row.
    return {"id": depot["place_id"] or depot["id"], "lat": depot["lat"], "lon": depot["lon"]}


def _leg(depot: dict, pl: dict, rtype: str) -> dict | None:
    """Arrival time for one unit from depot to place, or None when not feasible."""
    if depot["kind"] != "ndrf" and depot["state"] != pl["state"]:
        return None
    if pl["state"] in ISLAND_STATES and depot["state"] != pl["state"]:
        return None
    lg = travel.leg(_point(depot), {"id": pl["id"], "lat": pl["lat"], "lon": pl["lon"]})
    if lg["h"] is None:
        return None
    drive = lg["h"] * FLOOD_ROAD_FACTOR.get(pl["tier"], 1.0)
    if drive > RTYPES[rtype]["max_h"]:
        return None
    arrive = MOBILISE_H[depot["kind"]] + drive
    timely = 1.0 if arrive <= pl["window_h"] else pl["window_h"] / arrive
    return {"drive_h": round(drive, 1), "km": lg["km"], "basis": lg["basis"], "arrive_h": round(arrive, 1), "timely": round(timely, 3)}


def _value(pl: dict, rtype: str, timely: float) -> float:
    spec = RTYPES[rtype]
    return pl["p"] * spec["cap"] * spec["rel"][pl["mechanism"]] * timely


def _tranches(n: int) -> list[int]:
    """Split a need of n units into three tranches (first ones largest)."""
    a = math.ceil(n / 3)
    b = math.ceil((n - a) / 2)
    return [a, b, n - a - b]


def _evaluate(allocs: list[dict], by_place: dict, need_left: dict) -> dict:
    """
    Expected people helped by a set of allocations, by the planner's own yardstick:
    per place and type, the most timely units fill the first tranche, then the
    second and third; units beyond the need add nothing. Used for the plan and the
    baseline alike, so the two are compared on equal terms.
    """
    by_type: dict = {r: 0.0 for r in RTYPES}
    by_place_value: dict = {}
    groups: dict = {}
    for o in allocs:
        groups.setdefault((o["place_id"], o["rtype"]), []).extend([o["timely"]] * o["count"])
    for (pid, rtype), units in groups.items():
        pl = by_place[pid]
        caps = _tranches(max(0, need_left.get((pid, rtype), 0)))
        slots = [w for w, c in zip(TRANCHE_W, caps) for _ in range(c)]
        value = sum(_value(pl, rtype, t) * w for t, w in zip(sorted(units, reverse=True), slots))
        by_type[rtype] += value
        by_place_value[pid] = by_place_value.get(pid, 0.0) + value
    return {"by_type": by_type, "by_place": by_place_value, "total": sum(by_type.values())}


# ------------------------------------------------------------------- solving


def _solve(cands: list[dict], supply: dict, need: dict) -> tuple[np.ndarray, dict]:
    """MILP over candidate legs; returns units per candidate and depot shadow values."""
    from scipy.optimize import Bounds, LinearConstraint, linprog, milp
    from scipy.sparse import lil_matrix

    n = len(cands)
    if n == 0:
        return np.zeros(0), {}
    s_keys = sorted({(c["depot_id"], c["rtype"]) for c in cands})
    n_keys = sorted({c["nkey"] for c in cands})
    s_idx = {k: i for i, k in enumerate(s_keys)}
    n_idx = {k: len(s_keys) + i for i, k in enumerate(n_keys)}
    A = lil_matrix((len(s_keys) + len(n_keys), n))
    for j, c in enumerate(cands):
        A[s_idx[(c["depot_id"], c["rtype"])], j] = 1
        A[n_idx[c["nkey"]], j] = 1
    ub = np.array([supply[k] for k in s_keys] + [need[k] for k in n_keys], dtype=float)
    # Ties go to the nearer depot: a hair less value per hour of arrival.
    c_obj = -np.array([c["value"] * (1 - 0.001 * c["arrive_h"]) for c in cands])
    upper = np.array([min(supply[(c["depot_id"], c["rtype"])], need[c["nkey"]]) for c in cands], dtype=float)
    A = A.tocsr()
    res = milp(c_obj, constraints=LinearConstraint(A, -np.inf, ub), integrality=np.ones(n), bounds=Bounds(0, upper))
    x = np.round(res.x).astype(int) if res.x is not None else np.zeros(n, dtype=int)
    # Shadow values from the LP relaxation: what one more unit at a depot is worth.
    shadow: dict = {}
    try:
        lp = linprog(c_obj, A_ub=A, b_ub=ub, bounds=list(zip(np.zeros(n), upper)), method="highs")
        if lp.status == 0:
            for k, i in s_idx.items():
                shadow[k] = round(float(-lp.ineqlin.marginals[i]), 1)
    except Exception as exc:  # shadow values are a nicety; the plan stands without them
        log.debug("LP relaxation for shadow values failed: %s", exc)
    return x, shadow


def _baseline(places: list[dict], depots: list[dict], supply: dict, deployed: dict) -> list[dict]:
    """Severity-only: rank by current score, fill each place from its nearest depots."""
    left = dict(supply)
    out = []
    for pl in sorted([p for p in places if p["s_now"] >= PLAN_MIN_SCORE], key=lambda p: -p["s_now"]):
        for rtype in RTYPES:
            need = _need(pl, rtype, pl["s_now"]) - deployed.get((pl["id"], rtype), 0)
            if need <= 0:
                continue
            legs = []
            for d in depots:
                if rtype in HOLDS[d["kind"]] and left.get((d["id"], rtype), 0) > 0:
                    lg = _leg(d, pl, rtype)
                    if lg:
                        legs.append((lg["arrive_h"], d, lg))
            for _, d, lg in sorted(legs, key=lambda t: t[0]):
                if need <= 0:
                    break
                k = min(need, left[(d["id"], rtype)])
                left[(d["id"], rtype)] -= k
                need -= k
                out.append({"depot_id": d["id"], "place_id": pl["id"], "rtype": rtype, "count": k, **lg,
                            "value": _value(pl, rtype, lg["timely"])})
    return out


# ------------------------------------------------------------------- building


def _texts(pl: dict, rtype: str, depot: dict, o: dict) -> dict:
    spec = RTYPES[rtype]
    unit_en = spec["unit_en"] + ("s" if o["count"] != 1 else "")
    when_en = f"peak in ~{pl['t_peak']:.0f} h" if pl["t_peak"] else "flooding risk is now"
    when_hi = f"~{pl['t_peak']:.0f} घंटे में शिखर" if pl["t_peak"] else "जोखिम अभी है"
    on_time = o["arrive_h"] <= pl["window_h"]
    road = {"road": "by road", "estimated": "estimated road time", "same_place": "already on site"}[o["basis"]]
    return {
        "en": f"{o['count']} {unit_en} from {depot['name']}: {o['drive_h']} h {road}"
        + (f" ({o['km']:.0f} km)" if o.get("km") else "")
        + f" + {MOBILISE_H[depot['kind']]:.1f} h to mobilise, arriving in ~{o['arrive_h']} h — "
        + ("before the expected peak." if on_time else f"after the expected peak ({when_en}), so it counts {o['timely']:.0%}."),
        "hi": f"{depot['name']} से {o['count']} {spec['unit_hi']}: सड़क से {o['drive_h']} घंटे + {MOBILISE_H[depot['kind']]:.1f} घंटे तैयारी, "
        + f"~{o['arrive_h']} घंटे में पहुँच — " + ("अपेक्षित शिखर से पहले।" if on_time else f"शिखर के बाद ({when_hi})।"),
    }


def _place_texts(pl: dict) -> dict:
    mech_en = "river flooding" if pl["mechanism"] == "riverine" else "rain waterlogging"
    mech_hi = "नदी की बाढ़" if pl["mechanism"] == "riverine" else "वर्षा जलभराव"
    if pl["driver"].startswith("wave:"):
        why_en = f"a flood wave on the {pl['driver'][5:]} arrives in ~{pl['t_peak']:.0f} h"
        why_hi = f"{pl['driver'][5:]} नदी की बाढ़ लहर ~{pl['t_peak']:.0f} घंटे में"
    elif pl["driver"] == "forecast":
        why_en = f"forecast to reach {pl['s_peak']:.0f} in ~{pl['t_peak']:.0f} h"
        why_hi = f"~{pl['t_peak']:.0f} घंटे में {pl['s_peak']:.0f} तक पहुँचने का पूर्वानुमान"
    else:
        why_en, why_hi = "risk is at its peak now", "जोखिम अभी शिखर पर"
    a = pl.get("assets")
    assets_en = assets_hi = ""
    if a and (a["hospitals"] or a["schools"] or a["underpasses"]):
        assets_en = f" Flood-prone streets hold {a['hospitals']} hospitals, {a['schools']} schools and {a['underpasses']} underpasses."
        assets_hi = f" बाढ़-प्रवण गलियों में {a['hospitals']} अस्पताल, {a['schools']} स्कूल और {a['underpasses']} अंडरपास।"
    return {
        "en": f"Score {pl['s_now']:.0f} now, {why_en}; {mech_en}; {pl['population']:,} people, about {pl['exposed']:,} in the flood area; "
        f"{pl['p']:.0%} chance of flooding at this level (calibrated on past floods).{assets_en}",
        "hi": f"अभी स्कोर {pl['s_now']:.0f}, {why_hi}; {mech_hi}; {pl['population']:,} लोग, लगभग {pl['exposed']:,} बाढ़ क्षेत्र में; "
        f"इस स्तर पर बाढ़ की संभावना {pl['p']:.0%}।{assets_hi}",
    }


def build(snap, waves_by_place: dict, trigger: str) -> dict:
    """Solve a fresh national plan from the snapshot, inventory and travel times."""
    depots = resources.depots()
    active = resources.deployments()
    deployed: dict = {}
    for dep in active:
        deployed[(dep["place_id"], dep["rtype"])] = deployed.get((dep["place_id"], dep["rtype"]), 0) + dep["count"]

    places = [_situation(a, waves_by_place.get(a["location"]["id"], [])) for a in snap.assessments]
    by_place = {p["id"]: p for p in places}
    planned = [p for p in places if p["s_peak"] >= PLAN_MIN_SCORE]
    supply = {(d["id"], r): s["available"] for d in depots for r, s in d["stock"].items()}
    depot_by_id = {d["id"]: d for d in depots}

    need_left, need, cands, unreachable = {}, {}, [], set()
    for pl in planned:
        for rtype in RTYPES:
            n = _need(pl, rtype) - deployed.get((pl["id"], rtype), 0)
            if n <= 0:
                continue
            need_left[(pl["id"], rtype)] = n
            sizes = _tranches(n)
            for t, size in enumerate(sizes):
                if size:
                    need[(pl["id"], rtype, t)] = size
            reach = False
            for d in depots:
                if rtype not in HOLDS[d["kind"]] or supply.get((d["id"], rtype), 0) <= 0:
                    continue
                lg = _leg(d, pl, rtype)
                if not lg:
                    continue
                reach = True
                v = _value(pl, rtype, lg["timely"])
                for t, size in enumerate(sizes):
                    if size and v * TRANCHE_W[t] >= MIN_VALUE:
                        cands.append({"depot_id": d["id"], "place_id": pl["id"], "rtype": rtype, "nkey": (pl["id"], rtype, t),
                                      "value": v * TRANCHE_W[t], **lg})
            if not reach:
                unreachable.add((pl["id"], rtype))

    x, shadow = _solve(cands, supply, need)
    merged: dict = {}
    for c, k in zip(cands, x):
        if k > 0:
            key = (c["depot_id"], c["place_id"], c["rtype"])
            o = merged.setdefault(key, {k2: v2 for k2, v2 in c.items() if k2 not in ("nkey", "value")} | {"count": 0, "value": 0.0})
            o["count"] += int(k)
            o["value"] += c["value"] * int(k)
    orders = [o | {"value": round(o["value"], 1)} for o in merged.values()]
    base = _baseline(places, depots, supply, deployed)
    for o in base:  # the baseline's worth, by the same tranche yardstick
        o["value"] = 0.0
    base_eval = _evaluate(base, by_place, need_left)

    # ------------------------------------------------ per place: ours vs baseline
    got: dict = {}
    for o in orders:
        got[(o["place_id"], o["rtype"])] = got.get((o["place_id"], o["rtype"]), 0) + o["count"]
    base_got: dict = {}
    for o in base:
        base_got[(o["place_id"], o["rtype"])] = base_got.get((o["place_id"], o["rtype"]), 0) + o["count"]

    ours_eval = _evaluate(orders, by_place, need_left)
    ours_value, base_value = ours_eval["by_place"], base_eval["by_place"]
    base_rank = {p["id"]: i + 1 for i, p in enumerate(sorted([p for p in places if p["s_now"] >= PLAN_MIN_SCORE], key=lambda p: -p["s_now"]))}

    # Priority = expected people affected (chance of flooding x people in the flood
    # area): independent of any resource assumption.
    place_rows = []
    for pl in sorted(planned, key=lambda p: -(p["p"] * (p["exposed"] + p["asset_eq"]))):
        types = {}
        for rtype in RTYPES:
            n_total = _need(pl, rtype)
            if n_total <= 0:
                continue
            short = max(0, need_left.get((pl["id"], rtype), 0) - got.get((pl["id"], rtype), 0))
            worth = _value(pl, rtype, 1.0) >= MIN_VALUE
            types[rtype] = {
                "need": n_total,
                "already": deployed.get((pl["id"], rtype), 0),
                "planned": got.get((pl["id"], rtype), 0),
                "baseline": base_got.get((pl["id"], rtype), 0),
                "short": short if worth else 0,
                "short_reason": (
                    None if not short or not worth
                    else "island_needs_lift" if pl["state"] in ISLAND_STATES and (pl["id"], rtype) in unreachable
                    else "no_depot_in_reach" if (pl["id"], rtype) in unreachable
                    else "stock_committed"
                ),
            }
        place_rows.append({**pl, "types": types, "expected_affected": round(pl["p"] * (pl["exposed"] + pl["asset_eq"])),
                           "value": round(ours_value.get(pl["id"], 0), 1),
                           "baseline_value": round(base_value.get(pl["id"], 0), 1),
                           "baseline_rank": base_rank.get(pl["id"]), "why": _place_texts(pl)})
    for i, row in enumerate(place_rows):
        row["rank"] = i + 1

    for o in orders:
        pl, d = by_place[o["place_id"]], depot_by_id[o["depot_id"]]
        o["id"] = f"{o['depot_id']}|{o['place_id']}|{o['rtype']}"
        o["depot_name"], o["depot_kind"] = d["name"], d["kind"]
        o["depot_lat"], o["depot_lon"], o["depot_state"] = d["lat"], d["lon"], d["state"]
        o["place_name"], o["place_state"], o["place_district"] = pl["name"], pl["state"], pl["district"]
        o["why"] = _texts(pl, o["rtype"], d, o)
    rank = {r["id"]: r["rank"] for r in place_rows}
    orders.sort(key=lambda o: (rank.get(o["place_id"], 999), list(RTYPES).index(o["rtype"]), -o["count"]))

    # ------------------------------------------------ releases for places now safe
    releases = []
    for dep in active:
        pl = by_place.get(dep["place_id"])
        if pl and pl["s_peak"] < PLAN_MIN_SCORE:
            releases.append({**dep, "place_name": pl["name"], "place_state": pl["state"],
                             "depot_name": depot_by_id.get(dep["depot_id"], {}).get("name"),
                             "why_en": f"{pl['name']} is now at {pl['s_peak']:.0f} with no worsening forecast — these units can return to reserve.",
                             "why_hi": f"{pl['name']} अब {pl['s_peak']:.0f} पर, बिगड़ने का पूर्वानुमान नहीं — इकाइयाँ रिज़र्व में लौट सकती हैं।"})

    marginal = sorted(
        ({"depot_id": k[0], "rtype": k[1], "depot_name": depot_by_id[k[0]]["name"], "per_unit": v} for k, v in shadow.items() if v > 0),
        key=lambda m: -m["per_unit"],
    )[:8]

    plan = {
        "id": str(uuid.uuid4()),
        "created_at": store.utcnow(),
        "trigger": trigger,
        "run_id": snap.run_id,
        "computed_at": snap.computed_at.isoformat(timespec="seconds"),
        "inventory_version": resources.version(),
        "travel": travel.status(),
        "orders": orders,
        "baseline": [
            {"depot_id": o["depot_id"], "place_id": o["place_id"], "rtype": o["rtype"], "count": o["count"],
             "arrive_h": o["arrive_h"], "timely": o["timely"]}
            for o in base
        ],
        "need_left": [{"place_id": k[0], "rtype": k[1], "n": v} for k, v in need_left.items()],
        "places": place_rows,
        "releases": releases,
        "marginal": marginal,
        "deployments": active,
        "assumptions": {
            "rtypes": {k: {kk: v[kk] for kk in ("en", "hi", "cap", "rel", "max_h")} for k, v in RTYPES.items()},
            "mobilise_h": MOBILISE_H,
            "flood_road_factor": FLOOD_ROAD_FACTOR,
            "wave_score": WAVE_SCORE,
            "min_value": MIN_VALUE,
            "tranche_weights": TRANCHE_W,
            "ongoing_window_h": ONGOING_WINDOW_H,
            "exposed_share": "5% + 25% x score/100 of population",
            "assets": {"prone_susceptibility": PRONE_SUSCEPTIBILITY, "hospital_eq": HOSPITAL_EQ, "school_eq": SCHOOL_EQ,
                       "pump_per_hospital": 1, "barricades_per_underpass": 2},
            "calibration": calibration(),
        },
    }
    return plan


# ------------------------------------------------------------------ versions


def _summary(plan: dict, keep) -> dict:
    """Headline numbers for the places `keep` selects: ours vs severity-only."""
    ids = {p["id"] for p in plan["places"] if keep(p)}
    by_place = {p["id"]: p for p in plan["places"]}
    need_left = {(n["place_id"], n["rtype"]): n["n"] for n in plan.get("need_left", [])}
    total_need = {r: sum(n for (pid, rt), n in need_left.items() if rt == r and pid in ids) for r in RTYPES}

    def side(allocs: list[dict]) -> dict:
        mine = [o for o in allocs if o["place_id"] in ids]
        ev = _evaluate(mine, by_place, need_left)
        units = sum(o["count"] for o in mine)
        on_time = sum(o["count"] for o in mine if o["timely"] >= 0.999)
        ahead = {o["place_id"] for o in mine if by_place[o["place_id"]]["t_peak"] > 0 and o["timely"] >= 0.999}
        by_type = {}
        for r in RTYPES:
            sent = sum(min(o["count"], 10**6) for o in mine if o["rtype"] == r)
            by_type[r] = {"helped": round(ev["by_type"][r]), "units": sent,
                          "on_time": sum(o["count"] for o in mine if o["rtype"] == r and o["timely"] >= 0.999)}
        rescue = by_type["rescue_team"]["helped"] + by_type["boat"]["helped"]
        return {"helped": rescue, "units": units, "on_time_units": on_time, "late_units": units - on_time,
                "places_served": len({o["place_id"] for o in mine}), "prepositioned": len(ahead), "by_type": by_type}

    ours, base = side(plan["orders"]), side(plan["baseline"])
    worsening = sum(1 for i in ids if by_place[i]["t_peak"] > 0)
    gain = ours["helped"] - base["helped"]
    return {
        "ours": ours,
        "baseline": base,
        "need": total_need,
        "headline": "expected people reached by rescue teams and boats",
        "gain": gain,
        "gain_pct": round(100 * gain / base["helped"], 1) if base["helped"] else None,
        "places_at_risk": len(ids),
        "places_worsening": worsening,
        "short_places": sum(1 for i in ids if any(t["short"] for t in by_place[i]["types"].values())),
    }


def _diff(prev: dict | None, plan: dict) -> list[dict]:
    """What moved since the previous plan, with the reason from the data."""
    if not prev:
        return []
    old = {}
    for o in prev.get("orders", []):
        old[(o["place_id"], o["rtype"])] = old.get((o["place_id"], o["rtype"]), 0) + o["count"]
    new = {}
    for o in plan["orders"]:
        new[(o["place_id"], o["rtype"])] = new.get((o["place_id"], o["rtype"]), 0) + o["count"]
    prev_places = {p["id"]: p for p in prev.get("places", [])}
    places = {p["id"]: p for p in plan["places"]}

    def deployed(pl: dict) -> dict:
        out: dict = {}
        for d in pl.get("deployments", []):
            out[(d["place_id"], d["rtype"])] = out.get((d["place_id"], d["rtype"]), 0) + d["count"]
        return out

    dep_was, dep_now = deployed(prev), deployed(plan)
    out = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key, 0), new.get(key, 0)
        if a == b:
            continue
        pid, rtype = key
        now, was = places.get(pid), prev_places.get(pid)
        name = (now or was or {}).get("name", pid)
        moved = dep_now.get(key, 0) - dep_was.get(key, 0)
        if moved > 0 and b < a:
            reason_en, reason_hi = f"{moved} dispatched — now on their way", f"{moved} रवाना — रास्ते में"
        elif moved < 0 and b > a:
            reason_en, reason_hi = f"{-moved} released back to reserve", f"{-moved} रिज़र्व में वापस"
        elif now and was and abs(now["s_peak"] - was["s_peak"]) >= 2:
            reason_en = f"expected peak moved {was['s_peak']:.0f} → {now['s_peak']:.0f}"
            reason_hi = f"अपेक्षित शिखर {was['s_peak']:.0f} → {now['s_peak']:.0f}"
        elif not now:
            reason_en, reason_hi = "risk fell below Yellow", "जोखिम पीले से नीचे"
        elif prev.get("inventory_version") != plan["inventory_version"]:
            reason_en, reason_hi = "stock or deployments changed", "भंडार या तैनाती बदली"
        else:
            reason_en, reason_hi = "rebalanced against other places", "अन्य स्थानों के साथ पुनर्संतुलन"
        out.append({"place_id": pid, "place_name": name, "state": (now or was or {}).get("state"), "rtype": rtype,
                    "was": a, "now": b, "reason_en": reason_en, "reason_hi": reason_hi})
    return sorted(out, key=lambda c: -abs(c["now"] - c["was"]))


def _save(plan: dict) -> None:
    with store.db() as conn:
        conn.execute(
            "INSERT INTO plan_runs (id, created_at, trigger, run_id, body) VALUES (?,?,?,?,?)",
            (plan["id"], plan["created_at"], plan["trigger"], plan["run_id"], json.dumps(plan, default=str)),
        )
        conn.execute(
            "DELETE FROM plan_runs WHERE id NOT IN (SELECT id FROM plan_runs ORDER BY created_at DESC LIMIT ?)",
            (KEEP_PLANS,),
        )


def _last_saved() -> dict | None:
    with store.db() as conn:
        row = conn.execute("SELECT body FROM plan_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    return json.loads(row["body"]) if row else None


def current(snap, waves_by_place: dict, trigger: str = "requested", force: bool = False) -> dict:
    """The plan for this snapshot + inventory + travel matrix, re-solved when any changes."""
    global _current, _current_key
    key = (snap.run_id, resources.version(), travel.status().get("built_at"))
    if _current is not None and _current_key == key and not force:
        return _current
    if _current is not None and not force:
        if _current_key[0] != key[0]:
            trigger = "new risk data"
        elif _current_key[1] != key[1]:
            trigger = "stock or deployments changed"
        elif _current_key[2] != key[2]:
            trigger = "road travel times updated"
    prev = _current or _last_saved()
    plan = build(snap, waves_by_place, trigger)
    plan["changes"] = _diff(prev, plan)
    plan["previous_id"] = prev["id"] if prev else None
    _save(plan)
    _current, _current_key = plan, key
    log.info("plan %s (%s): %d orders", plan["id"][:8], trigger, len(plan["orders"]))
    return plan


def history(limit: int = 20) -> list[dict]:
    with store.db() as conn:
        rows = conn.execute("SELECT body FROM plan_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        p = json.loads(r["body"])
        s = _summary(p, lambda _p: True)
        out.append({"id": p["id"], "created_at": p["created_at"], "trigger": p["trigger"], "run_id": p["run_id"],
                    "orders": len(p["orders"]), "units": s["ours"]["units"], "helped": s["ours"]["helped"],
                    "baseline_helped": s["baseline"]["helped"], "changes": len(p.get("changes", []))})
    return out


# ------------------------------------------------------------------ scoping


def for_user(plan: dict, user: dict) -> dict:
    """The part of the national plan a user acts on, with its own headline numbers."""
    role = user["role"]

    def place_ok(p: dict) -> bool:
        if role == "central":
            return True
        if p["state"] != user["state"]:
            return False
        return role == "state" or p.get("district") == user["district"]

    places = {p["id"]: p for p in plan["places"]}

    def order_ok(o: dict) -> bool:
        if role == "central":
            return True
        pl = places.get(o["place_id"], {"state": o.get("place_state"), "district": o.get("place_district")})
        if place_ok(pl):
            return True
        # A state also sees what its own SDRF / district stores are sending.
        return role == "state" and o.get("depot_kind") != "ndrf" and o.get("depot_state") == user["state"]

    return {
        **{k: plan[k] for k in ("id", "created_at", "trigger", "run_id", "computed_at", "travel", "assumptions", "previous_id")},
        "summary": _summary(plan, place_ok),
        "orders": [o for o in plan["orders"] if order_ok(o)],
        "baseline": [o for o in plan["baseline"] if place_ok(places.get(o["place_id"], {"state": None}))],
        "places": [p for p in plan["places"] if place_ok(p)],
        "releases": [r for r in plan["releases"] if role == "central" or r.get("place_state") == user["state"]],
        "marginal": plan["marginal"] if role == "central" else [m for m in plan["marginal"] if not m["depot_id"].startswith("ndrf-")],
        "changes": [c for c in plan.get("changes", []) if role == "central" or c.get("state") == user["state"]],
        "deployments": [d for d in plan["deployments"] if role == "central" or place_ok(LOCATIONS_BY_ID.get(d["place_id"], {"state": None}))],
    }
