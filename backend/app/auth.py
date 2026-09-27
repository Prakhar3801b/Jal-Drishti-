"""
Accounts, sign-in and area scope.

Three admin roles, matching how flood response is organised in India, and one
public role:

    central    NDMA / central control room - all of India          (admin)
    state      a State Disaster Management Authority - one state    (admin)
    district   a District Emergency Operations Centre - one district (admin)
    citizen    a resident - their home district, public-safety view only

Admins get the control-room tools (planning, notifications, time machine,
what-if, advisories). Citizens register themselves with a phone number or email
and a home district, and see that district's risk, safety steps and roads to
avoid; the server refuses admin endpoints for them (see `require_admin`).

Every monitored state and district gets an admin account on first boot (username
`central`, the state slug e.g. `bihar`, or `state.district` e.g. `bihar.patna`),
all with the seed password from JALDRISHTI_SEED_PASSWORD. Passwords are stored as
salted PBKDF2-SHA256 hashes. Sign-in returns a signed token (HMAC-SHA256) that
carries the user's role and area; the server checks it on every scoped request.

Demo sign-in (pick a role, no password) is on by default so judges can try every
view in one click; set JALDRISHTI_DEMO_LOGIN=0 to turn it off.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time

from fastapi import Header, HTTPException

from . import store
from .config import DEMO_LOGIN, SEED_PASSWORD, TOKEN_HOURS

PBKDF2_ITERATIONS = 200_000
ADMIN_ROLES = ("central", "state", "district")
ROLES = ADMIN_ROLES + ("citizen",)
MIN_PASSWORD = 8

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username    TEXT PRIMARY KEY,
    pw_hash     TEXT NOT NULL,
    role        TEXT NOT NULL,
    state       TEXT,
    district    TEXT,
    created_at  TEXT NOT NULL,
    name        TEXT
);
CREATE TABLE IF NOT EXISTS app_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _check(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(got.hex(), digest)
    except (ValueError, TypeError):
        return False


def _secret() -> bytes:
    """Signing key: from the environment, else generated once and kept in the database."""
    env = os.getenv("JALDRISHTI_SECRET", "").strip()
    if env:
        return env.encode()
    with store.db() as conn:
        row = conn.execute("SELECT value FROM app_meta WHERE key='token_secret'").fetchone()
        if row:
            return row["value"].encode()
        value = secrets.token_hex(32)
        conn.execute("INSERT INTO app_meta (key, value) VALUES ('token_secret', ?)", (value,))
        return value.encode()


def init(locations: list[dict]) -> int:
    """Create the tables and any missing seed accounts. Returns how many were added."""
    with store.db() as conn:
        conn.executescript(USERS_SCHEMA)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        if "name" not in cols:  # databases created before citizen accounts
            conn.execute("ALTER TABLE users ADD COLUMN name TEXT")
        existing = {r["username"] for r in conn.execute("SELECT username FROM users")}
    wanted = [("central", "central", None, None)]
    for state in sorted({l["state"] for l in locations}):
        wanted.append((slug(state), "state", state, None))
    for l in locations:
        if l.get("district"):
            wanted.append((f"{slug(l['state'])}.{slug(l['district'])}", "district", l["state"], l["district"]))
    added = 0
    now = store.utcnow()
    with store.db() as conn:
        for username, role, state, district in wanted:
            if username in existing:
                continue
            conn.execute(
                "INSERT INTO users (username, pw_hash, role, state, district, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (username, _hash(SEED_PASSWORD), role, state, district, now),
            )
            existing.add(username)
            added += 1
    return added


def _user_row(username: str) -> dict | None:
    with store.db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return dict(row) if row else None


def public(user: dict) -> dict:
    return {k: user.get(k) for k in ("username", "role", "state", "district", "name", "demo")}


def is_admin(user: dict) -> bool:
    return user.get("role") in ADMIN_ROLES


def contact_id(text: str) -> str | None:
    """A citizen's sign-in id: a lower-case email, or a phone number as +91XXXXXXXXXX."""
    text = (text or "").strip().lower()
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", text):
        return text
    digits = re.sub(r"\D", "", text)
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return "+" + digits
    return None


def register(name: str, contact: str, password: str, state: str, district: str, locations: list[dict]) -> dict:
    """Create a citizen account for a monitored home district."""
    username = contact_id(contact)
    if not username:
        raise HTTPException(status_code=400, detail="Enter a valid email or a 10-digit Indian mobile number.")
    if len(password or "") < MIN_PASSWORD:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD} characters.")
    name = (name or "").strip()[:80]
    if not name:
        raise HTTPException(status_code=400, detail="Enter your name.")
    if not any(l["state"] == state and l.get("district") == district for l in locations):
        raise HTTPException(status_code=400, detail="Choose your district from the list.")
    if _user_row(username):
        raise HTTPException(status_code=409, detail="An account with this email or phone already exists. Sign in instead.")
    with store.db() as conn:
        conn.execute(
            "INSERT INTO users (username, pw_hash, role, state, district, created_at, name) VALUES (?, ?, 'citizen', ?, ?, ?, ?)",
            (username, _hash(password), state, district, store.utcnow(), name),
        )
    return public(_user_row(username))


def issue_token(user: dict) -> str:
    payload = public(user) | {"exp": int(time.time() + TOKEN_HOURS * 3600)}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str) -> dict | None:
    try:
        body, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("exp", 0) < time.time() or payload.get("role") not in ROLES:
        return None
    return payload


def login(username: str, password: str) -> dict | None:
    # Citizens sign in with the email or phone they registered; admins with their username.
    user = _user_row(contact_id(username) or username.strip().lower())
    if not user or not _check(password, user["pw_hash"]):
        return None
    return public(user)


def demo_user(role: str, state: str | None, district: str | None, locations: list[dict]) -> dict:
    """A password-less account for trying a role. Validated against real areas."""
    if not DEMO_LOGIN:
        raise HTTPException(status_code=403, detail="Demo sign-in is turned off on this server.")
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="role must be central, state, district or citizen")
    states = {l["state"] for l in locations}
    if role in ("state", "district", "citizen") and state not in states:
        raise HTTPException(status_code=400, detail="Choose a monitored state.")
    if role in ("district", "citizen") and not any(l["state"] == state and l.get("district") == district for l in locations):
        raise HTTPException(status_code=400, detail="Choose a monitored district in that state.")
    username = "central" if role == "central" else slug(state) if role == "state" else f"{slug(state)}.{slug(district)}"
    if role == "citizen":
        username = f"citizen.{username}"
    return {
        "username": username,
        "role": role,
        "state": state if role != "central" else None,
        "district": district if role in ("district", "citizen") else None,
        "name": "Demo resident" if role == "citizen" else None,
        "demo": True,
    }


def current_user(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: the signed-in user, or 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in to see your area.")
    user = verify_token(authorization.split(" ", 1)[1].strip())
    if not user:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")
    return user


def require_admin(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: a signed-in central, state or district official, or 403."""
    user = current_user(authorization)
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="This is for officials only.")
    return user


def in_scope(loc: dict, user: dict) -> bool:
    if user["role"] == "central":
        return True
    if loc["state"] != user["state"]:
        return False
    return user["role"] == "state" or loc.get("district") == user["district"]


def scope_label(user: dict) -> dict:
    if user["role"] == "central":
        return {"en": "All India", "hi": "संपूर्ण भारत", "role_en": "Central control room", "role_hi": "केंद्रीय नियंत्रण कक्ष"}
    if user["role"] == "state":
        return {"en": user["state"], "hi": user["state"], "role_en": "State control room", "role_hi": "राज्य नियंत्रण कक्ष"}
    citizen = user["role"] == "citizen"
    return {
        "en": f"{user['district']}, {user['state']}",
        "hi": f"{user['district']}, {user['state']}",
        "role_en": "Resident" if citizen else "District control room",
        "role_hi": "निवासी" if citizen else "ज़िला नियंत्रण कक्ष",
    }
