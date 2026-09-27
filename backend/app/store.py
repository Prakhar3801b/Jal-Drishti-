"""
SQLite persistence for the risk engine.

Deliberately small: five tables, JSON blobs for anything shaped like a document,
and no ORM. PostGIS was in the original plan, but every spatial question this
prototype actually asks ("which locations are in Maharashtra", "nearest monitored
location to this click") is answered from 40 rows held in memory, so a database
server would be ceremony. The schema is still normalised enough that swapping in
Postgres later is a connection-string change.

Two things are cached here for a long time because they never change between runs:
  * climatology - 30 years of GloFAS statistics per location per day-of-year
  * runs        - every scoring pass, so the UI can show history and prove the
                  system re-computes rather than replaying a fixed scenario
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import DB_PATH

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    trigger      TEXT NOT NULL,          -- 'startup' | 'schedule' | 'manual'
    status       TEXT NOT NULL,          -- 'running' | 'ok' | 'partial' | 'failed'
    locations    INTEGER DEFAULT 0,
    duration_ms  INTEGER,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS location_state (
    location_id  TEXT NOT NULL,
    run_id       INTEGER NOT NULL,
    computed_at  TEXT NOT NULL,
    score        REAL NOT NULL,
    tier         TEXT NOT NULL,
    confidence   REAL NOT NULL,
    payload      TEXT NOT NULL,          -- the full assessment document as JSON
    PRIMARY KEY (location_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_location_state_run ON location_state(run_id);

CREATE TABLE IF NOT EXISTS observations (
    location_id  TEXT NOT NULL,
    date         TEXT NOT NULL,
    kind         TEXT NOT NULL,          -- 'rain_mm' | 'discharge_cumecs' | ...
    value        REAL,
    horizon      TEXT NOT NULL,          -- 'observed' | 'forecast'
    run_id       INTEGER NOT NULL,
    PRIMARY KEY (location_id, date, kind, horizon)
);

-- The lat/lon columns are not decoration. Climatology is only comparable with
-- live discharge if both come from the same GloFAS cell, and the cell can move
-- when scripts/enrich_locations.py re-snaps a location to its river channel.
-- Storing the coordinates lets load_climatology() discard a stale baseline
-- instead of silently comparing a hillside's history against a main channel's
-- present -- which produced a "3943x the seasonal median" reading before this
-- check existed.
CREATE TABLE IF NOT EXISTS climatology (
    location_id  TEXT PRIMARY KEY,
    built_at     TEXT NOT NULL,
    start_year   INTEGER NOT NULL,
    end_year     INTEGER NOT NULL,
    lat          REAL,
    lon          REAL,
    stats        TEXT NOT NULL           -- {doy: {p50, p75, p90, p95, max, n}}
);

CREATE TABLE IF NOT EXISTS source_health (
    source       TEXT PRIMARY KEY,
    checked_at   TEXT NOT NULL,
    ok           INTEGER NOT NULL,
    latency_ms   INTEGER,
    detail       TEXT
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """Serialised connection. One writer is plenty for 40 locations."""
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


# Additive column migrations, applied idempotently on boot. Kept as a plain list
# because the schema is small; if it ever grows, this becomes Alembic.
MIGRATIONS = [
    ("climatology", "lat", "REAL"),
    ("climatology", "lon", "REAL"),
]


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        for table, column, coltype in MIGRATIONS:
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


# ----------------------------------------------------------------------- runs


def start_run(trigger: str) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, trigger, status) VALUES (?, ?, 'running')",
            (utcnow(), trigger),
        )
        return int(cur.lastrowid)


def finish_run(run_id: int, status: str, locations: int, duration_ms: int, notes: str = "") -> None:
    with db() as conn:
        conn.execute(
            "UPDATE runs SET finished_at=?, status=?, locations=?, duration_ms=?, notes=? WHERE id=?",
            (utcnow(), status, locations, duration_ms, notes, run_id),
        )


def latest_run(only_complete: bool = True) -> dict | None:
    clause = "WHERE status IN ('ok','partial')" if only_complete else ""
    with db() as conn:
        row = conn.execute(f"SELECT * FROM runs {clause} ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def recent_runs(limit: int = 12) -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


# ------------------------------------------------------------ location state


def save_assessments(run_id: int, assessments: list[dict]) -> None:
    now = utcnow()
    rows = [
        (
            a["location"]["id"],
            run_id,
            now,
            a["risk"]["score"],
            a["risk"]["tier"]["key"],
            a["confidence"]["value"],
            json.dumps(a, ensure_ascii=False),
        )
        for a in assessments
    ]
    with db() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO location_state "
            "(location_id, run_id, computed_at, score, tier, confidence, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def load_assessments(run_id: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT payload FROM location_state WHERE run_id=?", (run_id,)
        ).fetchall()
    return [json.loads(r["payload"]) for r in rows]


def score_history(location_id: str, limit: int = 48) -> list[dict]:
    """Past scores for one location, oldest first - the 'is it rising?' sparkline."""
    with db() as conn:
        rows = conn.execute(
            "SELECT ls.computed_at, ls.score, ls.tier, ls.confidence "
            "FROM location_state ls JOIN runs r ON r.id = ls.run_id "
            "WHERE ls.location_id=? AND r.status IN ('ok','partial') "
            "ORDER BY ls.run_id DESC LIMIT ?",
            (location_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def tier_before(location_id: str, run_id: int) -> dict | None:
    """
    The location's row from the last good run before `run_id`: the message a CAP
    Update references, or the warning an All Clear closes.
    """
    with db() as conn:
        row = conn.execute(
            "SELECT ls.run_id, ls.computed_at, ls.tier FROM location_state ls "
            "JOIN runs r ON r.id = ls.run_id "
            "WHERE ls.location_id=? AND ls.run_id<? AND r.status IN ('ok','partial') "
            "ORDER BY ls.run_id DESC LIMIT 1",
            (location_id, run_id),
        ).fetchone()
    return dict(row) if row else None


def tiers_as_of(when_iso: str | None, before_run: int) -> tuple[int | None, dict[str, dict]]:
    """
    Every location's tier and score in the last good run started at or before
    `when_iso` (or simply the run before `before_run` when no time is given) -
    the baseline for "what changed since you last looked".
    """
    with db() as conn:
        if when_iso:
            run = conn.execute(
                "SELECT id FROM runs WHERE status IN ('ok','partial') AND started_at<=? AND id<? ORDER BY id DESC LIMIT 1",
                (when_iso, before_run),
            ).fetchone()
        else:
            run = conn.execute(
                "SELECT id FROM runs WHERE status IN ('ok','partial') AND id<? ORDER BY id DESC LIMIT 1",
                (before_run,),
            ).fetchone()
        if not run:
            return None, {}
        rows = conn.execute(
            "SELECT location_id, tier, score FROM location_state WHERE run_id=?", (run["id"],)
        ).fetchall()
    return run["id"], {r["location_id"]: {"tier": r["tier"], "score": r["score"]} for r in rows}


def computed_at(location_id: str, run_id: int) -> str | None:
    """When a run stored this location. CAP `sent` must match across Alert and Update."""
    with db() as conn:
        row = conn.execute(
            "SELECT computed_at FROM location_state WHERE location_id=? AND run_id=?",
            (location_id, run_id),
        ).fetchone()
    return row["computed_at"] if row else None


# ------------------------------------------------------------- observations


def save_observations(run_id: int, rows: list[tuple[str, str, str, float | None, str]]) -> None:
    with db() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO observations "
            "(location_id, date, kind, value, horizon, run_id) VALUES (?, ?, ?, ?, ?, ?)",
            [(r[0], r[1], r[2], r[3], r[4], run_id) for r in rows],
        )


# -------------------------------------------------------------- climatology


def save_climatology(
    location_id: str,
    start_year: int,
    end_year: int,
    stats: dict[str, Any],
    lat: float | None = None,
    lon: float | None = None,
) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO climatology "
            "(location_id, built_at, start_year, end_year, lat, lon, stats) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (location_id, utcnow(), start_year, end_year, lat, lon, json.dumps(stats)),
        )


def seed_climatology(seed_path: Path) -> int:
    """
    Insert climatology rows from a bundled seed file for locations that have
    none yet. Existing rows (built locally, possibly newer) are never replaced.
    """
    if not seed_path.exists():
        return 0
    import gzip

    with gzip.open(seed_path, "rt", encoding="utf-8") as fh:
        rows = json.load(fh)
    with db() as conn:
        have = {r[0] for r in conn.execute("SELECT location_id FROM climatology").fetchall()}
        fresh = [r for r in rows if r["location_id"] not in have]
        conn.executemany(
            "INSERT INTO climatology (location_id, built_at, start_year, end_year, lat, lon, stats) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(r["location_id"], r["built_at"], r["start_year"], r["end_year"], r["lat"], r["lon"], json.dumps(r["stats"])) for r in fresh],
        )
    return len(fresh)


def load_climatology(expected_cells: dict[str, tuple[float, float]] | None = None) -> dict[str, dict]:
    """
    Load cached climatology, dropping any entry that was built at a different
    GloFAS cell than the one currently in use.

    `expected_cells` maps location_id -> (lat, lon). Rows that do not match are
    skipped so the engine rebuilds them rather than trusting an incomparable
    baseline. Pass None to load everything unchecked (used by diagnostics).
    """
    with db() as conn:
        rows = conn.execute(
            "SELECT location_id, stats, start_year, end_year, built_at, lat, lon FROM climatology"
        ).fetchall()

    out: dict[str, dict] = {}
    for r in rows:
        lid = r["location_id"]
        if expected_cells is not None:
            want = expected_cells.get(lid)
            have = (r["lat"], r["lon"])
            if want is None:
                continue
            if have[0] is None or have[1] is None:
                continue  # built before cells were tracked; treat as stale
            if abs(have[0] - want[0]) > 1e-4 or abs(have[1] - want[1]) > 1e-4:
                continue
        out[lid] = {
            "stats": json.loads(r["stats"]),
            "start_year": r["start_year"],
            "end_year": r["end_year"],
            "built_at": r["built_at"],
            "cell": [r["lat"], r["lon"]],
        }
    return out


def climatology_coverage() -> int:
    with db() as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM climatology").fetchone()["n"])


# ------------------------------------------------------------ source health


def record_source_health(source: str, ok: bool, latency_ms: int | None, detail: str = "") -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO source_health (source, checked_at, ok, latency_ms, detail) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, utcnow(), 1 if ok else 0, latency_ms, detail[:400]),
        )


def load_source_health() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM source_health ORDER BY source").fetchall()
    return [{**dict(r), "ok": bool(r["ok"])} for r in rows]
