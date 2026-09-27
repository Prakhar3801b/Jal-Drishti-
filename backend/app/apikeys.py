"""
API key management for external platform access to JalDrishti.

Key lifecycle:
  1. Admin creates a key via POST /api/gateway/admin/keys with desired scopes and tier
  2. The full key (sk_live_... or sk_test_...) is returned ONCE — store it safely
  3. The system stores only the SHA-256 hash; the plaintext cannot be recovered
  4. External platforms include the key as:  Authorization: Bearer sk_live_...
  5. Each request is authenticated, scope-checked, and rate-limited
  6. Admin can revoke a key instantly via DELETE /api/gateway/admin/keys/{id}

Scopes:
  score_read      — GET risk scores, location assessments, country summaries
  forecast_read   — GET 72-hour trajectories, event replays, time machine
  maps_read       — GET inundation hotspot grids and river network layers
  simulate_write  — POST what-if scenarios, manual refresh, copilot, advisories
  alert_subscribe — GET official CWC gauge readings and NDMA alerts

Rate limits (per 1-hour window):
  standard   — 100 requests/hour
  enterprise — 1,000 requests/hour
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from . import store

# ---------------------------------------------------------------- constants

VALID_SCOPES = frozenset({
    "score_read",
    "forecast_read",
    "maps_read",
    "simulate_write",
    "alert_subscribe",
})

SCOPE_DESCRIPTIONS = {
    "score_read": "Read risk scores, location assessments, and country summaries",
    "forecast_read": "Read 72-hour forecasts, trajectories, and event replays",
    "maps_read": "Read inundation hotspot grids and river network layers",
    "simulate_write": "Run what-if scenarios, trigger refresh, use copilot and advisory generator",
    "alert_subscribe": "Read official CWC gauge readings and NDMA alerts",
}

TIER_RATE_LIMITS = {
    "standard": 100,
    "enterprise": 1000,
}

WINDOW_SECONDS = 3600  # 1-hour rate limit window

# ---------------------------------------------------------------- table schema
# Additive: CREATE TABLE IF NOT EXISTS guarantees no clash with the existing DB.

API_KEYS_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash     TEXT NOT NULL UNIQUE,
    key_prefix   TEXT NOT NULL,
    name         TEXT NOT NULL,
    environment  TEXT NOT NULL DEFAULT 'test',
    scopes       TEXT NOT NULL DEFAULT '["score_read"]',
    tier         TEXT NOT NULL DEFAULT 'standard',
    rate_limit   INTEGER NOT NULL DEFAULT 100,
    expires_at   TEXT,
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    revoked_at   TEXT,
    created_by   TEXT
);

CREATE TABLE IF NOT EXISTS api_key_usage (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id       INTEGER NOT NULL REFERENCES api_keys(id),
    timestamp    TEXT NOT NULL,
    endpoint     TEXT NOT NULL,
    method       TEXT NOT NULL,
    status_code  INTEGER NOT NULL DEFAULT 200,
    window_key   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_api_key_usage_key ON api_key_usage(key_id);
CREATE INDEX IF NOT EXISTS idx_api_key_usage_ts  ON api_key_usage(timestamp);
"""


def init_api_keys_db() -> None:
    """Create the api_keys and api_key_usage tables if they don't exist yet.

    Safe to call repeatedly; every statement is IF NOT EXISTS.
    """
    with store.db() as conn:
        conn.executescript(API_KEYS_SCHEMA)


# ---------------------------------------------------------------- helpers


def _hash_key(key: str) -> str:
    """SHA-256 hash of the API key.  The plaintext is never stored."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _display_prefix(key: str) -> str:
    """Show enough of the key for identification without exposing the secret."""
    return key[:12] + "..." + key[-4:]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _window_key(dt: datetime | None = None) -> str:
    """Hourly bucket key for rate limiting: ``YYYY-MM-DDTHH``."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H")


def _window_reset(window: str) -> int:
    """Unix timestamp when the current rate-limit window resets."""
    dt = datetime.strptime(window, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
    return int((dt + timedelta(hours=1)).timestamp())


def _row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "key_prefix": row["key_prefix"],
        "name": row["name"],
        "environment": row["environment"],
        "scopes": json.loads(row["scopes"]),
        "tier": row["tier"],
        "rate_limit": row["rate_limit"],
        "expires_at": row["expires_at"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "revoked_at": row["revoked_at"],
        "created_by": row["created_by"],
    }


# ---------------------------------------------------------------- key generation


def generate_key(environment: str = "test") -> str:
    """
    Generate a new API key.

    Format:  ``sk_live_<64 hex chars>``  or  ``sk_test_<64 hex chars>``
    Returns the full plaintext key (shown once at creation, never stored).
    """
    if environment not in ("live", "test"):
        raise ValueError("environment must be 'live' or 'test'")
    prefix = "sk_live_" if environment == "live" else "sk_test_"
    return prefix + secrets.token_hex(32)


# ---------------------------------------------------------------- CRUD


def create_key(
    name: str,
    environment: str = "test",
    scopes: list[str] | None = None,
    tier: str = "standard",
    expires_at: str | None = None,
    created_by: str | None = None,
) -> dict:
    """
    Create and persist a new API key.

    Returns a dict that includes the full plaintext ``key`` — this is the only
    time the plaintext is available; store it securely.
    """
    if scopes is None:
        scopes = ["score_read"]
    invalid = set(scopes) - VALID_SCOPES
    if invalid:
        raise ValueError(f"Invalid scopes: {sorted(invalid)}. Valid: {sorted(VALID_SCOPES)}")
    if tier not in TIER_RATE_LIMITS:
        raise ValueError(f"Invalid tier: {tier}. Valid: {sorted(TIER_RATE_LIMITS)}")

    plaintext = generate_key(environment)
    key_hash = _hash_key(plaintext)
    prefix = _display_prefix(plaintext)
    rate_limit = TIER_RATE_LIMITS[tier]
    now = _utcnow()

    with store.db() as conn:
        conn.execute(
            """INSERT INTO api_keys
               (key_hash, key_prefix, name, environment, scopes, tier,
                rate_limit, expires_at, is_active, created_at, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (key_hash, prefix, name, environment, json.dumps(sorted(scopes)),
             tier, rate_limit, expires_at, now, created_by),
        )
        key_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    return {
        "id": key_id,
        "key": plaintext,
        "key_prefix": prefix,
        "name": name,
        "environment": environment,
        "scopes": sorted(scopes),
        "tier": tier,
        "rate_limit": rate_limit,
        "expires_at": expires_at,
        "is_active": True,
        "created_at": now,
    }


def validate_key(plaintext: str) -> dict | None:
    """
    Validate an API key and return its metadata if it is active and not expired.
    Returns ``None`` for any invalid, revoked, or expired key.
    """
    key_hash = _hash_key(plaintext)
    with store.db() as conn:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)
        ).fetchone()

    if row is None or not row["is_active"]:
        return None

    # Expiration check
    if row["expires_at"]:
        try:
            exp = datetime.fromisoformat(row["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                return None
        except ValueError:
            pass

    return {
        "id": row["id"],
        "key_prefix": row["key_prefix"],
        "name": row["name"],
        "environment": row["environment"],
        "scopes": json.loads(row["scopes"]),
        "tier": row["tier"],
        "rate_limit": row["rate_limit"],
        "expires_at": row["expires_at"],
        "is_active": True,
        "created_at": row["created_at"],
    }


def revoke_key(key_id: int) -> bool:
    """Revoke a key immediately.  Returns True if the key was active and is now revoked."""
    now = _utcnow()
    with store.db() as conn:
        cur = conn.execute(
            "UPDATE api_keys SET is_active = 0, revoked_at = ? WHERE id = ? AND is_active = 1",
            (now, key_id),
        )
        return cur.rowcount > 0


def get_key(key_id: int) -> dict | None:
    """Get key metadata by ID (never returns the hash or plaintext)."""
    with store.db() as conn:
        row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def list_keys(include_revoked: bool = False) -> list[dict]:
    """List all API keys (never includes the hash or plaintext)."""
    with store.db() as conn:
        sql = "SELECT * FROM api_keys"
        if not include_revoked:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY created_at DESC"
        rows = conn.execute(sql).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_key(key_id: int, **fields) -> dict | None:
    """Update mutable fields of a key (scopes, tier, rate_limit, expires_at, name)."""
    allowed = {"scopes", "tier", "rate_limit", "expires_at", "name"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get_key(key_id)

    if "scopes" in updates:
        invalid = set(updates["scopes"]) - VALID_SCOPES
        if invalid:
            raise ValueError(f"Invalid scopes: {sorted(invalid)}")
        updates["scopes"] = json.dumps(sorted(updates["scopes"]))
    if "tier" in updates:
        if updates["tier"] not in TIER_RATE_LIMITS:
            raise ValueError(f"Invalid tier: {updates['tier']}")
        updates["rate_limit"] = TIER_RATE_LIMITS[updates["tier"]]

    sets = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [key_id]
    with store.db() as conn:
        conn.execute(f"UPDATE api_keys SET {sets} WHERE id = ?", vals)
    return get_key(key_id)


# ---------------------------------------------------------------- rate limiting

# In-memory counters for fast rate-limit checks.  Backed by SQLite for
# persistence and analytics but the hot path reads memory only.
# Old windows are cleaned up lazily on each check.
_rate_counters: dict[int, dict[str, int]] = {}


def check_rate_limit(key_id: int, rate_limit: int) -> tuple[bool, int, int, int]:
    """
    Check whether the key has exceeded its rate limit for the current window.

    Returns ``(allowed, limit, remaining, reset_unix_timestamp)``.
    Does **not** increment the counter — call :func:`record_usage` for that.
    """
    window = _window_key()
    reset = _window_reset(window)

    if key_id not in _rate_counters:
        _rate_counters[key_id] = {}
    counters = _rate_counters[key_id]

    # Purge stale windows
    for old in [k for k in counters if k != window]:
        del counters[old]

    current = counters.get(window, 0)
    remaining = max(0, rate_limit - current)
    return current < rate_limit, rate_limit, remaining, reset


def record_usage(key_id: int, endpoint: str, method: str, status_code: int = 200) -> None:
    """Increment the rate counter and persist the request to SQLite."""
    window = _window_key()
    now = _utcnow()

    # In-memory increment
    if key_id not in _rate_counters:
        _rate_counters[key_id] = {}
    _rate_counters[key_id][window] = _rate_counters[key_id].get(window, 0) + 1

    # SQLite persistence (fire-and-forget; a missed row only affects analytics)
    try:
        with store.db() as conn:
            conn.execute(
                """INSERT INTO api_key_usage
                   (key_id, timestamp, endpoint, method, status_code, window_key)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (key_id, now, endpoint, method, status_code, window),
            )
    except Exception:
        pass  # rate tracking is best-effort; never fail a request over analytics


# ---------------------------------------------------------------- usage analytics


def usage_stats(key_id: int, hours: int = 24) -> dict:
    """Aggregate usage statistics for a key over the last *hours* hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    with store.db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM api_key_usage WHERE key_id = ? AND timestamp >= ?",
            (key_id, cutoff),
        ).fetchone()[0]

        by_endpoint = conn.execute(
            """SELECT endpoint, method, COUNT(*) as count
               FROM api_key_usage WHERE key_id = ? AND timestamp >= ?
               GROUP BY endpoint, method ORDER BY count DESC""",
            (key_id, cutoff),
        ).fetchall()

        by_hour = conn.execute(
            """SELECT window_key, COUNT(*) as count
               FROM api_key_usage WHERE key_id = ? AND timestamp >= ?
               GROUP BY window_key ORDER BY window_key DESC LIMIT ?""",
            (key_id, cutoff, hours),
        ).fetchall()

        by_status = conn.execute(
            """SELECT status_code, COUNT(*) as count
               FROM api_key_usage WHERE key_id = ? AND timestamp >= ?
               GROUP BY status_code ORDER BY count DESC""",
            (key_id, cutoff),
        ).fetchall()

    window = _window_key()
    current_count = _rate_counters.get(key_id, {}).get(window, 0)

    return {
        "key_id": key_id,
        "period_hours": hours,
        "total_requests": total,
        "current_window": window,
        "current_window_count": current_count,
        "by_endpoint": [
            {"endpoint": r["endpoint"], "method": r["method"], "count": r["count"]}
            for r in by_endpoint
        ],
        "by_hour": [
            {"window": r["window_key"], "count": r["count"]}
            for r in by_hour
        ],
        "by_status": [
            {"status_code": r["status_code"], "count": r["count"]}
            for r in by_status
        ],
    }


def overview_stats() -> dict:
    """High-level overview for the admin dashboard."""
    with store.db() as conn:
        total_keys = conn.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]
        active_keys = conn.execute(
            "SELECT COUNT(*) FROM api_keys WHERE is_active = 1"
        ).fetchone()[0]

        today_cutoff = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0
        ).isoformat(timespec="seconds")
        requests_today = conn.execute(
            "SELECT COUNT(*) FROM api_key_usage WHERE timestamp >= ?",
            (today_cutoff,),
        ).fetchone()[0]

        hour_cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat(timespec="seconds")
        requests_last_hour = conn.execute(
            "SELECT COUNT(*) FROM api_key_usage WHERE timestamp >= ?",
            (hour_cutoff,),
        ).fetchone()[0]

        by_env = conn.execute(
            """SELECT environment, COUNT(*) as count
               FROM api_keys WHERE is_active = 1
               GROUP BY environment"""
        ).fetchall()

        by_tier = conn.execute(
            """SELECT tier, COUNT(*) as count
               FROM api_keys WHERE is_active = 1
               GROUP BY tier"""
        ).fetchall()

        top_consumers = conn.execute(
            """SELECT k.id, k.name, k.key_prefix, COUNT(u.id) as count
               FROM api_key_usage u JOIN api_keys k ON u.key_id = k.id
               WHERE u.timestamp >= ?
               GROUP BY k.id ORDER BY count DESC LIMIT 5""",
            (today_cutoff,),
        ).fetchall()

    return {
        "keys": {
            "total": total_keys,
            "active": active_keys,
            "revoked": total_keys - active_keys,
            "by_environment": {r["environment"]: r["count"] for r in by_env},
            "by_tier": {r["tier"]: r["count"] for r in by_tier},
        },
        "requests": {
            "today": requests_today,
            "last_hour": requests_last_hour,
        },
        "top_consumers_today": [
            {"id": r["id"], "name": r["name"], "key_prefix": r["key_prefix"], "requests": r["count"]}
            for r in top_consumers
        ],
    }
