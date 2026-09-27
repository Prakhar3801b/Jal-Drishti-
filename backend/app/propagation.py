"""
Flood propagation between connected cells of a city grid.

The hotspot grid is treated as a directed graph: each 800 m cell is a node, and
water flows along edges to its lower neighbours (multiple-flow-direction routing,
split by slope). Every hour each cell

    gains   local runoff (rain x runoff coefficient) + inflow spilled by upslope cells
    loses   drainage capacity and a slow infiltration/evaporation decay
    holds   up to a storage depth that grows with how deep a pocket it sits in
    spills  a share of anything above that depth to its downslope neighbours,
            which receive it the following hour

so flooding travels: a low pocket fills, overflows, and the next cell down the
slope floods an hour or more later. That is what lets the system name places
that are dry now but will be hit next, and say where their water comes from.

Uncertainty is carried by an ensemble. Each member perturbs what we know least
well: rainfall amount (city-wide and per cell) and timing (+/- 1 h), drain
capacity, and terrain - a few metres of DEM error, which on flat ground changes
which way water flows. From the members come each cell's probability of
flooding, the spread of its arrival time, and an evidence rating that says so
when members disagree rather than presenting a guess as a forecast.
"""

from __future__ import annotations

import zlib

import numpy as np

FLOOD_MM = 10.0  # ponding depth at which a cell counts as affected (risk ~40, "elevated")
DECAY = 0.85  # per-hour storage retention after infiltration and evaporation
SPILL = 0.6  # share of storage above holding depth that moves downslope each hour
MEMBERS = 20
DEM_NOISE_M = 1.5  # vertical error of a 90 m DEM over flat urban ground
FLAT_DROP_M = 1.0  # steepest drop below this: flow direction is within DEM error
MFD_EXP = 1.1  # slope exponent for splitting flow between lower neighbours


def flow_matrix(elev: np.ndarray, sea: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Row-normalised weights W[a, b]: the share of a's spill that goes to b.
    Also returns each cell's main downstream neighbour (-1 for pits and sea)
    and its steepest drop in metres.
    """
    size = n * n
    W = np.zeros((size, size))
    main = np.full(size, -1)
    drop_max = np.zeros(size)
    for k in range(size):
        if sea[k]:
            continue  # the sea absorbs; it never spills back
        i, j = divmod(k, n)
        weights = {}
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == dj == 0:
                    continue
                ii, jj = i + di, j + dj
                if not (0 <= ii < n and 0 <= jj < n):
                    continue
                kk = ii * n + jj
                drop = elev[k] - elev[kk]
                if drop > 0:
                    weights[kk] = (drop / (1.414 if di and dj else 1.0)) ** MFD_EXP
                    drop_max[k] = max(drop_max[k], drop)
        total = sum(weights.values())
        if total > 0:
            for kk, w in weights.items():
                W[k, kk] = w / total
            main[k] = max(weights, key=weights.get)
    return W, main, drop_max


def mobility(drop_max: np.ndarray, W: np.ndarray) -> np.ndarray:
    """
    Share of a cell's surface water that runs off downslope each hour: most of it
    on a slope, little on flat ground, none from a pit with no lower neighbour.
    """
    has_out = W.sum(axis=1) > 0
    return np.where(has_out, np.clip(0.1 + 0.6 * (1.0 - np.exp(-drop_max / 2.0)), 0.0, 0.7), 0.0)


def route(
    rain: np.ndarray,
    runoff: np.ndarray,
    capacity: np.ndarray,
    hold: np.ndarray,
    amp: np.ndarray,
    W: np.ndarray,
    mob: np.ndarray,
    isolate: bool = False,
) -> dict:
    """
    Run the graph model over `rain` (hours x cells, mm/h). Returns per-hour
    ponding, outflow (spill), inflow and local runoff, all hours x cells in mm.

    `isolate` discards all inflow - the counterfactual "what if no water arrived
    from upslope?" that separates cells flooded by propagation from cells flooded
    by their own rain.
    """
    hours, cells = rain.shape
    has_out = W.sum(axis=1) > 0
    storage = np.zeros(cells)
    spill = np.zeros(cells)
    pond = np.zeros((hours, cells))
    out = np.zeros((hours, cells))
    inflow_h = np.zeros((hours, cells))
    local_h = np.zeros((hours, cells))
    for t in range(hours):
        inflow = np.zeros(cells) if isolate else spill @ W
        local = rain[t] * runoff
        storage = np.maximum(0.0, DECAY * storage + local + inflow - capacity)
        # Overland flow downslope, plus overflow of anything the cell cannot hold.
        excess = np.maximum(0.0, storage - hold)
        spill = np.where(has_out, mob * np.minimum(storage, hold) + SPILL * excess, 0.0)
        storage = storage - spill
        pond[t] = storage * amp
        out[t] = spill
        inflow_h[t] = inflow
        local_h[t] = local
    return {"pond": pond, "out": out, "inflow": inflow_h, "local": local_h}


def _first_at_or_above(series: np.ndarray, start: int, threshold: float) -> np.ndarray:
    """Hours after `start` until each column first reaches `threshold`; -1 if never."""
    future = series[start:] >= threshold
    hit = future.any(axis=0)
    first = future.argmax(axis=0)
    return np.where(hit, first, -1)


def simulate(
    cells: list[dict],
    rain: np.ndarray,
    now_pos: int,
    capacity_scale: float,
    *,
    seed_key: str,
    design_storm: bool,
) -> dict:
    """
    Central run plus ensemble. `rain` is hours x cells in mm/h for the hours the
    page shows; `now_pos` is the index of the current hour in it.
    """
    n = int(round(len(cells) ** 0.5))
    elev = np.array([c["elev"] for c in cells], dtype=float)
    sea = np.array([c["sea"] for c in cells])
    runoff = np.array([c["runoff_coeff"] for c in cells], dtype=float)
    cap = np.array([c["capacity_mm_h"] for c in cells], dtype=float)
    sink = np.array([c["sink_m"] for c in cells], dtype=float)
    # Deeper pockets hold more water before they overflow into the next cell.
    hold = np.where(sea, 1e6, 15.0 + 50.0 * np.minimum(sink, 4.0))
    amp = 1.0 + np.minimum(sink / 3.0, 1.0)

    W, main, drop_max = flow_matrix(elev, sea, n)
    mob = mobility(drop_max, W)
    mid = route(rain, runoff, cap * capacity_scale, hold, amp, W, mob)
    alone = route(rain, runoff, cap * capacity_scale, hold, amp, W, mob, isolate=True)

    # ------------------------------------------------------------ ensemble
    rng = np.random.default_rng(zlib.crc32(seed_key.encode()))
    hours = rain.shape[0]
    ens_pond = np.zeros((MEMBERS, hours, len(cells)))
    for m in range(MEMBERS):
        if design_storm:
            # The storm is an input, not a forecast: only its local spread varies.
            r = rain * rng.lognormal(0.0, 0.10) * rng.lognormal(0.0, 0.10, size=len(cells))
        else:
            r = rain * rng.lognormal(0.0, 0.35) * rng.lognormal(0.0, 0.15, size=len(cells))
            shift = int(rng.integers(-1, 2))
            if shift:
                r = np.roll(r, shift, axis=0)
                if shift > 0:
                    r[:shift] = 0.0
                else:
                    r[shift:] = 0.0
        cap_m = cap * capacity_scale * rng.uniform(0.75, 1.25)
        W_m, _, drop_m = flow_matrix(elev + rng.normal(0.0, DEM_NOISE_M, size=len(cells)), sea, n)
        ens_pond[m] = route(r, runoff, cap_m, hold, amp, W_m, mobility(drop_m, W_m))["pond"]

    # ------------------------------------------------------- per-cell stats
    future = ens_pond[:, now_pos:, :]
    flooded = (future >= FLOOD_MM).any(axis=1)  # members x cells
    prob = flooded.mean(axis=0)
    arrival = np.stack([_first_at_or_above(ens_pond[m], now_pos, FLOOD_MM) for m in range(MEMBERS)])
    peaks = future.max(axis=1)
    peak_p10, peak_p90 = np.percentile(peaks, 10, axis=0), np.percentile(peaks, 90, axis=0)

    mid_arrival = _first_at_or_above(mid["pond"], now_pos, FLOOD_MM)
    alone_arrival = _first_at_or_above(alone["pond"], now_pos, FLOOD_MM)
    flooded_now = mid["pond"][now_pos] >= FLOOD_MM

    stats = []
    for k, c in enumerate(cells):
        hits = arrival[:, k][arrival[:, k] >= 0]
        eta = None
        if len(hits):
            p10, p50, p90 = np.percentile(hits, [10, 50, 90])
            eta = {"p10": int(round(p10)), "p50": int(round(p50)), "p90": int(round(p90))}

        # Where does its water come from? Compare with the run where nothing
        # arrives from upslope: the difference in peak is the propagated share.
        mid_peak = float(mid["pond"][now_pos:, k].max())
        alone_peak = float(alone["pond"][now_pos:, k].max())
        share = max(0.0, 1.0 - alone_peak / mid_peak) if mid_peak > 0 else 0.0
        if mid_arrival[k] >= 0 and alone_arrival[k] < 0:
            driver = "upstream"  # floods only because water arrives from upslope
        elif mid_arrival[k] >= 0 and (share >= 0.33 or mid_arrival[k] < alone_arrival[k]):
            driver = "mixed"  # would flood anyway, but sooner or deeper with inflow
        else:
            driver = "rain"
        upto = now_pos + (mid_arrival[k] if mid_arrival[k] >= 0 else int(mid["pond"][now_pos:, k].argmax()))
        source = None
        if driver != "rain" and upto > 0:
            donors = mid["out"][: upto + 1].sum(axis=0) * W[:, k]
            if donors.max() > 0:
                source = int(donors.argmax())

        reasons = []
        if not c["sea"]:
            if 0.2 < prob[k] < 0.8:
                reasons.append(f"ensemble split: {prob[k] * 100:.0f}% of {MEMBERS} runs flood it")
            if eta and eta["p90"] - eta["p10"] > 6:
                reasons.append(f"arrival time uncertain by {eta['p90'] - eta['p10']} h")
            if drop_max[k] < FLAT_DROP_M and share >= 0.35:
                reasons.append("flat ground: which way water flows is within terrain error")
        evidence = "weak" if len(reasons) >= 2 or (0.35 <= prob[k] <= 0.65) else "moderate" if reasons else "strong"

        stats.append(
            {
                "prob_flood": round(float(prob[k]), 2),
                "eta_h": eta,
                "inflow_share": round(share, 2),
                "driver": driver,
                "source_k": source,
                "downstream_k": int(main[k]),
                "flooded_now": bool(flooded_now[k]),
                "evidence": evidence,
                "evidence_reasons": reasons,
                "peak_p10_mm": round(float(peak_p10[k]), 1),
                "peak_p90_mm": round(float(peak_p90[k]), 1),
            }
        )

    counts = (ens_pond >= FLOOD_MM).sum(axis=2)  # members x hours
    band = np.percentile(counts, [10, 50, 90], axis=0)
    return {
        "mid": mid,
        "cells": stats,
        "flooded_count_band": [[int(round(v)) for v in band[:, t]] for t in range(hours)],
        "members": MEMBERS,
    }


def chain(stats: list[dict], k: int, depth: int = 4) -> list[int]:
    """Follow the main water source upstream: k <- source <- its source ..."""
    path, seen = [], {k}
    cur = stats[k]["source_k"]
    while cur is not None and cur not in seen and len(path) < depth:
        path.append(cur)
        seen.add(cur)
        cur = stats[cur]["source_k"]
    return path
