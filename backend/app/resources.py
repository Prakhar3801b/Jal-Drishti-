"""
Response resources: where they are, how many, and where they have been sent.

Three kinds of depot, matching who holds what in India:

    ndrf      the 16 NDRF battalions (central government). Base cities and the
              18 search-and-rescue teams per battalion are public (NDRF / MHA);
              boat counts are not, so those are demo values.
    sdrf      one State Disaster Response Force depot per state, placed at the
              state's most populous monitored city. Demo values.
    district  a district store at every monitored place: dewatering pumps and
              barricade sets. Demo values.

No public source publishes live resource counts: India's inventory (IDRN, run by
NIDM) is open to government officers only. Every demo number is flagged `demo`
and shown as such, and officials can overwrite any count on the Resources page,
which is how real IDRN figures would come in.

Units sent out are recorded as deployments; a depot's available stock is its
total minus its active deployments. Every change bumps an inventory version so
the planner knows to re-optimise.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException

from . import store
from .engine import LOCATIONS

NDRF_SOURCE = "NDRF battalion bases and 18 teams per battalion: ndrf.gov.in / MHA; locations city-level"

# Base city of each NDRF battalion (city-level coordinates).
NDRF_BATTALIONS = [
    ("01", "Guwahati", "Assam", 26.1445, 91.7362),
    ("02", "Nadia (Haringhata)", "West Bengal", 22.9580, 88.5670),
    ("03", "Cuttack (Mundali)", "Odisha", 20.4625, 85.8830),
    ("04", "Arakkonam", "Tamil Nadu", 13.0840, 79.6700),
    ("05", "Pune", "Maharashtra", 18.5204, 73.8567),
    ("06", "Vadodara", "Gujarat", 22.3072, 73.1812),
    ("07", "Bathinda", "Punjab", 30.2110, 74.9455),
    ("08", "Ghaziabad", "Uttar Pradesh", 28.6692, 77.4538),
    ("09", "Patna (Bihta)", "Bihar", 25.5620, 84.8700),
    ("10", "Vijayawada", "Andhra Pradesh", 16.5062, 80.6480),
    ("11", "Varanasi", "Uttar Pradesh", 25.3176, 82.9739),
    ("12", "Itanagar", "Arunachal Pradesh", 27.0844, 93.6053),
    ("13", "Samba", "Jammu and Kashmir", 32.5625, 75.1199),
    ("14", "Mandi", "Himachal Pradesh", 31.7087, 76.9320),
    ("15", "Haldwani", "Uttarakhand", 29.2183, 79.5130),
    ("16", "Najafgarh (Delhi)", "Delhi", 28.6092, 76.9798),
]
NDRF_TEAMS_PER_BN = 18
NDRF_TEAM_SIZE = 45  # personnel per team (NDRF; some sources give 47)

# Resource types and the planning assumptions behind them. `cap` = people one unit
# can serve in a flooded area in the first day; `rel` = how much the type matters
# for each flood mechanism; `max_h` = the longest drive worth planning for.
# These are stated assumptions, not measured rates, and are shown in the UI.
RTYPES = {
    "rescue_team": {
        "en": "Rescue teams", "hi": "बचाव दल", "unit_en": "team", "unit_hi": "दल",
        "cap": 2000, "rel": {"riverine": 1.0, "pluvial": 0.6}, "max_h": 24.0,
    },
    "boat": {
        "en": "Boats", "hi": "नावें", "unit_en": "boat", "unit_hi": "नाव",
        "cap": 400, "rel": {"riverine": 1.0, "pluvial": 0.2}, "max_h": 24.0,
    },
    "pump": {
        "en": "Dewatering pumps", "hi": "जल-निकासी पंप", "unit_en": "pump", "unit_hi": "पंप",
        "cap": 40000, "rel": {"riverine": 0.3, "pluvial": 1.0}, "max_h": 8.0,
    },
    "barricade": {
        "en": "Barricade sets", "hi": "बैरिकेड सेट", "unit_en": "set", "unit_hi": "सेट",
        "cap": 25000, "rel": {"riverine": 0.5, "pluvial": 1.0}, "max_h": 6.0,
    },
}
HOLDS = {"ndrf": ("rescue_team", "boat"), "sdrf": ("rescue_team", "boat"), "district": ("pump", "barricade")}
MOBILISE_H = {"ndrf": 2.0, "sdrf": 1.5, "district": 0.5}  # time to load and leave (assumption)
KIND_LABEL = {
    "ndrf": ("NDRF", "एनडीआरएफ"),
    "sdrf": ("SDRF", "एसडीआरएफ"),
    "district": ("District store", "ज़िला भंडार"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS res_depots (
    id        TEXT PRIMARY KEY,
    kind      TEXT NOT NULL,
    name      TEXT NOT NULL,
    state     TEXT NOT NULL,
    district  TEXT,
    place_id  TEXT,
    lat       REAL NOT NULL,
    lon       REAL NOT NULL,
    source    TEXT
);
CREATE TABLE IF NOT EXISTS res_stock (
    depot_id    TEXT NOT NULL,
    rtype       TEXT NOT NULL,
    total       INTEGER NOT NULL,
    demo        INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT,
    PRIMARY KEY (depot_id, rtype)
);
CREATE TABLE IF NOT EXISTS res_deployments (
    id           TEXT PRIMARY KEY,
    depot_id     TEXT NOT NULL,
    rtype        TEXT NOT NULL,
    place_id     TEXT NOT NULL,
    count        INTEGER NOT NULL,
    status       TEXT NOT NULL,
    plan_id      TEXT,
    created_at   TEXT NOT NULL,
    created_by   TEXT,
    released_at  TEXT
);
"""


def _clamp(v: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(v))))


def _seed_rows() -> tuple[list[dict], list[tuple[str, str, int, int]]]:
    depots, stock = [], []
    for num, city, state, lat, lon in NDRF_BATTALIONS:
        did = f"ndrf-{num}"
        depots.append({"id": did, "kind": "ndrf", "name": f"{num} Bn NDRF, {city}", "state": state, "district": None,
                       "place_id": None, "lat": lat, "lon": lon, "source": NDRF_SOURCE})
        stock.append((did, "rescue_team", NDRF_TEAMS_PER_BN, 0))  # public figure
        stock.append((did, "boat", 30, 1))  # demo: boat counts are not published
    by_state: dict[str, list[dict]] = {}
    for l in LOCATIONS:
        by_state.setdefault(l["state"], []).append(l)
    for state, places in sorted(by_state.items()):
        hub = max(places, key=lambda l: l.get("population") or 0)
        people = sum(l.get("population") or 0 for l in places)
        did = f"sdrf-{hub['id']}"
        depots.append({"id": did, "kind": "sdrf", "name": f"SDRF {state} ({hub['name']})", "state": state,
                       "district": hub.get("district"), "place_id": hub["id"], "lat": hub["lat"], "lon": hub["lon"],
                       "source": "demo inventory"})
        teams = _clamp(4 + people / 5_000_000, 4, 12)
        stock.append((did, "rescue_team", teams, 1))
        stock.append((did, "boat", teams * 2, 1))
    for l in LOCATIONS:
        pop = l.get("population") or 0
        did = f"dist-{l['id']}"
        depots.append({"id": did, "kind": "district", "name": f"{l['name']} district store", "state": l["state"],
                       "district": l.get("district"), "place_id": l["id"], "lat": l["lat"], "lon": l["lon"],
                       "source": "demo inventory"})
        stock.append((did, "pump", _clamp(pop / 150_000, 2, 25), 1))
        stock.append((did, "barricade", _clamp(pop / 60_000, 5, 60), 1))
    return depots, stock


def init() -> None:
    """Create the tables and seed any depot or stock row not there yet."""
    depots, stock = _seed_rows()
    now = store.utcnow()
    with store.db() as conn:
        conn.executescript(SCHEMA)
        have = {r["id"] for r in conn.execute("SELECT id FROM res_depots")}
        for d in depots:
            if d["id"] not in have:
                conn.execute(
                    "INSERT INTO res_depots (id, kind, name, state, district, place_id, lat, lon, source) VALUES (?,?,?,?,?,?,?,?,?)",
                    (d["id"], d["kind"], d["name"], d["state"], d["district"], d["place_id"], d["lat"], d["lon"], d["source"]),
                )
        have_s = {(r["depot_id"], r["rtype"]) for r in conn.execute("SELECT depot_id, rtype FROM res_stock")}
        for did, rtype, total, demo in stock:
            if (did, rtype) not in have_s:
                conn.execute(
                    "INSERT INTO res_stock (depot_id, rtype, total, demo, updated_at, updated_by) VALUES (?,?,?,?,?,?)",
                    (did, rtype, total, demo, now, "seed"),
                )


def version() -> str:
    """Changes whenever stock or deployments change, so plans know to re-optimise."""
    with store.db() as conn:
        a = conn.execute("SELECT MAX(updated_at) m, SUM(total) t FROM res_stock").fetchone()
        b = conn.execute("SELECT COUNT(*) n, MAX(COALESCE(released_at, created_at)) m FROM res_deployments").fetchone()
    return f"{a['m']}:{a['t']}:{b['n']}:{b['m']}"


def depots() -> list[dict]:
    """Every depot with its stock: total, deployed and available per type."""
    with store.db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM res_depots ORDER BY kind, state, name")]
        stock = [dict(r) for r in conn.execute("SELECT * FROM res_stock")]
        out = conn.execute(
            "SELECT depot_id, rtype, SUM(count) n FROM res_deployments WHERE released_at IS NULL GROUP BY depot_id, rtype"
        ).fetchall()
    deployed = {(r["depot_id"], r["rtype"]): r["n"] for r in out}
    by_depot: dict[str, dict] = {}
    for s in stock:
        used = deployed.get((s["depot_id"], s["rtype"]), 0)
        by_depot.setdefault(s["depot_id"], {})[s["rtype"]] = {
            "total": s["total"],
            "deployed": used,
            "available": max(0, s["total"] - used),
            "demo": bool(s["demo"]),
            "updated_at": s["updated_at"],
            "updated_by": s["updated_by"],
        }
    for r in rows:
        r["stock"] = by_depot.get(r["id"], {})
        r["kind_en"], r["kind_hi"] = KIND_LABEL[r["kind"]]
    return rows


def deployments(active_only: bool = True) -> list[dict]:
    q = "SELECT * FROM res_deployments" + (" WHERE released_at IS NULL" if active_only else "") + " ORDER BY created_at DESC"
    with store.db() as conn:
        return [dict(r) for r in conn.execute(q)]


# ------------------------------------------------------------ permissions


def can_manage(user: dict, depot: dict) -> bool:
    """Central manages everything; a state its SDRF and district stores; a district its own store."""
    if user["role"] == "central":
        return True
    if depot["kind"] == "ndrf" or depot["state"] != user["state"]:
        return False
    if user["role"] == "state":
        return True
    return user["role"] == "district" and depot["kind"] == "district" and depot.get("district") == user["district"]


def _depot(depot_id: str) -> dict:
    with store.db() as conn:
        row = conn.execute("SELECT * FROM res_depots WHERE id=?", (depot_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Unknown depot.")
    return dict(row)


def set_stock(user: dict, depot_id: str, rtype: str, total: int) -> None:
    depot = _depot(depot_id)
    if not can_manage(user, depot):
        raise HTTPException(status_code=403, detail="You cannot change this depot's stock.")
    if rtype not in HOLDS[depot["kind"]]:
        raise HTTPException(status_code=400, detail="This depot does not hold that resource.")
    if not 0 <= total <= 10_000:
        raise HTTPException(status_code=400, detail="Enter a count between 0 and 10,000.")
    with store.db() as conn:
        conn.execute(
            "UPDATE res_stock SET total=?, demo=0, updated_at=?, updated_by=? WHERE depot_id=? AND rtype=?",
            (total, store.utcnow(), user["username"], depot_id, rtype),
        )


def dispatch(user: dict, orders: list[dict], plan_id: str | None) -> int:
    """Record plan orders as deployments. Each order: depot_id, rtype, place_id, count."""
    stock = {d["id"]: d for d in depots()}
    now, n = store.utcnow(), 0
    with store.db() as conn:
        for o in orders:
            depot = stock.get(o["depot_id"])
            if not depot or not can_manage(user, depot):
                raise HTTPException(status_code=403, detail="You cannot dispatch from one of these depots.")
            avail = depot["stock"].get(o["rtype"], {}).get("available", 0)
            count = int(o["count"])
            if count < 1 or count > avail:
                raise HTTPException(status_code=409, detail=f"{depot['name']} has only {avail} available — re-plan and try again.")
            depot["stock"][o["rtype"]]["available"] = avail - count
            conn.execute(
                "INSERT INTO res_deployments (id, depot_id, rtype, place_id, count, status, plan_id, created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), o["depot_id"], o["rtype"], o["place_id"], count, "en_route", plan_id, now, user["username"]),
            )
            n += count
    return n


def release(user: dict, deployment_id: str) -> None:
    with store.db() as conn:
        row = conn.execute("SELECT * FROM res_deployments WHERE id=? AND released_at IS NULL", (deployment_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No active deployment with that id.")
    if not can_manage(user, _depot(row["depot_id"])):
        raise HTTPException(status_code=403, detail="You cannot release units from this depot.")
    with store.db() as conn:
        conn.execute("UPDATE res_deployments SET released_at=?, status='returned' WHERE id=?", (store.utcnow(), deployment_id))
