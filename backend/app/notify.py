"""
Outbound notifications through an automation platform (e.g. viaSocket).

JalDrishti does not send email, WhatsApp, SMS or calls itself. It posts one JSON
event per message to a webhook (JALDRISHTI_NOTIFY_WEBHOOK); the automation flow
on the other side routes it by `channels` to Gmail, WhatsApp, SMS or a voice
call. That keeps provider accounts, templates and DLT registration out of this
codebase and lets the control room change who gets what without a deploy.

Events, each sent once per recipient:

    alert        JalDrishti issued an alert for the recipient's area: a place at
                 Orange/Red or just got worse, a river above danger, a flood
                 wave on the way, or an official IMD/CWC/SDMA alert. The system
                 decides what is alert-worthy; recipients do not pick a level.
                 Every alert carries public-safety steps: roads to avoid, safe
                 water, what to do.
    escalation   the same alert at Red: `voice_call` is true so the flow can ring
    all_clear    a place the recipient was alerted about is back to Green
    daily_brief  the area's brief, once a day at DAILY_BRIEF_HOUR IST
    test         from the "Send test" button

Every message says it comes from a research prototype. Recipients are the
signed-in officials who opted in; nothing is sent to the public.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape as xml_escape

import httpx

from . import email_template, safety, store
from .config import APP_NAME, DAILY_BRIEF_HOUR, NOTIFY_WEBHOOK_URL, PUBLIC_WEB_URL

log = logging.getLogger("jaldrishti.notify")

IST = timezone(timedelta(hours=5, minutes=30))
LEVEL_RANK = {"green": 0, "yellow": 1, "orange": 2, "red": 3}
CHANNELS = ("email", "whatsapp", "sms", "call")
DISCLAIMER = f"{APP_NAME} research prototype — not an official warning. Follow IMD, CWC and your SDMA."

SCHEMA = """
CREATE TABLE IF NOT EXISTS notify_prefs (
    username     TEXT PRIMARY KEY,
    role         TEXT NOT NULL,
    state        TEXT,
    district     TEXT,
    name         TEXT,
    email        TEXT,
    whatsapp     TEXT,
    phone        TEXT,
    channels     TEXT NOT NULL,
    min_level    TEXT NOT NULL DEFAULT 'orange',
    daily_brief  INTEGER NOT NULL DEFAULT 1,
    enabled      INTEGER NOT NULL DEFAULT 1,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notify_sent (
    username   TEXT NOT NULL,
    alert_id   TEXT NOT NULL,
    place_id   TEXT,
    level      TEXT,
    sent_at    TEXT NOT NULL,
    cleared    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (username, alert_id)
);
CREATE TABLE IF NOT EXISTS notify_log (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    username    TEXT NOT NULL,
    event       TEXT NOT NULL,
    title       TEXT,
    channels    TEXT,
    status      TEXT NOT NULL,
    detail      TEXT
);
CREATE TABLE IF NOT EXISTS notify_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""


def init() -> None:
    with store.db() as conn:
        conn.executescript(SCHEMA)


# ------------------------------------------------------------------ settings


def get_prefs(username: str) -> dict | None:
    with store.db() as conn:
        row = conn.execute("SELECT * FROM notify_prefs WHERE username=?", (username,)).fetchone()
    if not row:
        return None
    p = dict(row)
    p["channels"] = json.loads(p["channels"])
    p["daily_brief"] = bool(p["daily_brief"])
    p["enabled"] = bool(p["enabled"])
    return p


def _e164(number: str | None) -> str | None:
    """'+91 98765-43210' -> '+919876543210'; a bare 10-digit number is taken as Indian."""
    digits = "".join(ch for ch in (number or "") if ch.isdigit())
    if not digits:
        return None
    if len(digits) == 10 and not (number or "").strip().startswith("+"):
        digits = "91" + digits
    return "+" + digits[:15]


def save_prefs(user: dict, prefs: dict) -> dict:
    channels = [c for c in prefs.get("channels", []) if c in CHANNELS]
    min_level = prefs.get("min_level") if prefs.get("min_level") in ("yellow", "orange", "red") else "orange"
    with store.db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO notify_prefs (username, role, state, district, name, email, whatsapp, phone, "
            "channels, min_level, daily_brief, enabled, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user["username"],
                user["role"],
                user.get("state"),
                user.get("district"),
                (prefs.get("name") or "").strip()[:80] or None,
                (prefs.get("email") or "").strip()[:120] or None,
                _e164(prefs.get("whatsapp")),
                _e164(prefs.get("phone")),
                json.dumps(channels),
                min_level,
                1 if prefs.get("daily_brief", True) else 0,
                1 if prefs.get("enabled", True) else 0,
                store.utcnow(),
            ),
        )
    return get_prefs(user["username"])


def recent_log(username: str, limit: int = 20) -> list[dict]:
    with store.db() as conn:
        rows = conn.execute(
            "SELECT * FROM notify_log WHERE username=? ORDER BY created_at DESC LIMIT ?", (username, limit)
        ).fetchall()
    return [dict(r) | {"channels": json.loads(r["channels"] or "[]")} for r in rows]


def _all_prefs() -> list[dict]:
    with store.db() as conn:
        rows = conn.execute("SELECT username FROM notify_prefs WHERE enabled=1").fetchall()
    return [p for p in (get_prefs(r["username"]) for r in rows) if p]


def _meta(key: str) -> str | None:
    with store.db() as conn:
        row = conn.execute("SELECT value FROM notify_meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def _set_meta(key: str, value: str) -> None:
    with store.db() as conn:
        conn.execute("INSERT OR REPLACE INTO notify_meta (key, value) VALUES (?, ?)", (key, value))


# ------------------------------------------------------------------- sending


def _recipient(p: dict) -> dict:
    return {
        "username": p["username"],
        "name": p.get("name"),
        "role": p["role"],
        "state": p.get("state"),
        "district": p.get("district"),
        "email": p.get("email"),
        "whatsapp": p.get("whatsapp"),
        "phone": p.get("phone"),
    }


def _link(place_id: str | None) -> str | None:
    if not PUBLIC_WEB_URL:
        return None
    return f"{PUBLIC_WEB_URL}/#/location/{place_id}" if place_id else PUBLIC_WEB_URL


async def _post(client: httpx.AsyncClient, p: dict, event: str, payload: dict) -> str:
    """Send one event; log the outcome. Returns 'sent', 'failed' or 'no_webhook'."""
    channels = [c for c in p["channels"] if c != "call" or payload.get("voice_call")]
    body = {
        "event": event,
        "event_id": str(uuid.uuid4()),
        "sent_at": datetime.now(IST).isoformat(timespec="seconds"),
        "source": APP_NAME,
        "disclaimer": DISCLAIMER,
        "recipient": _recipient(p),
        "channels": channels,
        **payload,
    }
    # A designed HTML version for email steps (map the email body to `email_html`).
    body["email_html"] = email_template.render(body)
    if "call" in channels:
        body["call_twiml"] = _call_twiml(body)
    status, detail = "no_webhook", "JALDRISHTI_NOTIFY_WEBHOOK is not set"
    if NOTIFY_WEBHOOK_URL:
        try:
            r = await client.post(NOTIFY_WEBHOOK_URL, json=body, timeout=15)
            status = "sent" if r.status_code < 300 else "failed"
            detail = f"HTTP {r.status_code}"
        except Exception as exc:
            status, detail = "failed", str(exc)[:200]
    with store.db() as conn:
        conn.execute(
            "INSERT INTO notify_log (id, created_at, username, event, title, channels, status, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (body["event_id"], store.utcnow(), p["username"], event, payload.get("title"), json.dumps(channels), status, detail),
        )
    return status


def _spoken(text: str | None) -> str:
    """Flatten a message for text-to-speech: no bullets or line breaks, XML-safe."""
    t = " ".join((text or "").replace("•", "").split())
    return xml_escape(t[:1200])


def _call_twiml(body: dict) -> str:
    """Ready-to-use TwiML for the voice-call step: English, then Hindi, then the disclaimer, said twice."""
    en = _spoken(body.get("message") or body.get("title"))
    hi = _spoken(body.get("message_hi"))
    note = _spoken(body.get("disclaimer"))
    say = f'<Say voice="Polly.Raveena" language="en-IN">{en}</Say>'
    if hi:
        say += f'<Pause length="1"/><Say voice="Polly.Aditi" language="hi-IN">{hi}</Say>'
    say += f'<Pause length="1"/><Say voice="Polly.Raveena" language="en-IN">{note}</Say>'
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{say}<Pause length="2"/>{say}</Response>'


def _message(al: dict, lang: str = "en") -> str:
    """Text for WhatsApp / email / the voice call script: what, why, and how to stay safe."""
    k = "hi" if lang == "hi" else "en"
    steps = (al.get("safety") or {}).get(k) or []
    if k == "hi":
        head = f"{al['title_hi']}। {al['detail_hi']}\nप्रशासन: {al['do_hi']}"
        tail = "\nसुरक्षित रहें:\n" + "\n".join(f"• {x}" for x in steps) if steps else ""
    else:
        head = f"{al['title_en']}. {al['detail_en']}\nAuthorities: {al['do_en']}"
        tail = "\nStay safe:\n" + "\n".join(f"• {x}" for x in steps) if steps else ""
    return head + tail


def _sms(al: dict) -> str:
    """One SMS (160 chars): the warning, the first road to avoid, safe water."""
    routes = (al.get("safety") or {}).get("routes") or []
    avoid = f" Avoid {routes[0]}." if routes else " Avoid flooded roads."
    return f"{APP_NAME}: {al['title_en']}.{avoid} Drink boiled water. Help 112/1078"[:160]


SUMMARY_OVER = 3  # more new alerts than this in one update -> one summary message


def _mark_sent(username: str, alerts: list[dict]) -> None:
    with store.db() as conn:
        for al in alerts:
            conn.execute(
                "INSERT OR REPLACE INTO notify_sent (username, alert_id, place_id, level, sent_at, cleared) VALUES (?, ?, ?, ?, ?, 0)",
                (username, al["id"], al.get("place_id"), al["level"], store.utcnow()),
            )


def _alert_payload(al: dict) -> dict:
    adv = (al.get("advisory") or {}).get("en") or {}
    return {
        "level": al["level"],
        "kind": al["kind"],
        "place_id": al.get("place_id"),
        "title": al["title_en"],
        "title_hi": al["title_hi"],
        "detail": al["detail_en"],
        "what_to_do": al["do_en"],
        "message": _message(al, "en"),
        "message_hi": _message(al, "hi"),
        "sms": adv.get("sms") or _sms(al),
        "safety": (al.get("safety") or {}).get("en", []),
        "safety_hi": (al.get("safety") or {}).get("hi", []),
        "routes_to_avoid": (al.get("safety") or {}).get("routes", []),
        "advisory_title": adv.get("title"),
        "advisory_body": adv.get("body"),
        "voice_call": al["level"] == "red",
        "link": _link(al.get("place_id")),
    }


def _summary_payload(alerts: list[dict], brief: dict) -> dict:
    """Several new alerts as one message, most serious first."""
    alerts = sorted(alerts, key=lambda a: -LEVEL_RANK.get(a["level"], 0))
    top = alerts[0]["level"]
    reds = sum(1 for a in alerts if a["level"] == "red")
    area = brief["scope"]["label"]
    n = len(alerts)
    lines = [f"• [{a['level'].upper()}] {a['title_en']} — {a['do_en']}" for a in alerts]
    lines_hi = [f"• {a['title_hi']} — {a['do_hi']}" for a in alerts]
    general = safety.advice(None, top, "place")["en"]
    title = f"{n} new flood alerts in {area['en']}" + (f" — {reds} at Red" if reds else "")
    return {
        "level": top,
        "kind": "summary",
        "title": title,
        "title_hi": f"{area['hi']} में {n} नई बाढ़ चेतावनियाँ",
        "items": [
            {
                "level": a["level"],
                "title": a["title_en"],
                "detail": a["detail_en"],
                "what_to_do": a["do_en"],
                "routes_to_avoid": (a.get("safety") or {}).get("routes", []),
                "place_id": a.get("place_id"),
            }
            for a in alerts
        ],
        "message": f"{title}.\n" + "\n".join(lines) + "\nStay safe:\n" + "\n".join(f"• {x}" for x in general),
        "message_hi": f"{area['hi']} में {n} नई बाढ़ चेतावनियाँ।\n" + "\n".join(lines_hi),
        "sms": f"{APP_NAME}: {n} new flood alerts in {area['en']}" + (f", {reds} RED" if reds else "") + ". Open dashboard. Help 112/1078",
        "safety": general,
        "voice_call": reds > 0,
        "link": _link(None),
    }


async def dispatch(snapshot, waves_by_place: dict) -> dict:
    """
    Send new alerts, escalations and all-clears to every opted-in user.
    Called once per scoring run; each alert goes to each person once.
    """
    from . import briefing

    counts = {"sent": 0, "failed": 0, "no_webhook": 0}
    prefs = _all_prefs()
    if not prefs or not NOTIFY_WEBHOOK_URL:
        # Without a webhook nothing is delivered, so nothing is marked as sent:
        # current alerts go out as soon as the automation is connected.
        return counts
    async with httpx.AsyncClient(headers={"User-Agent": f"{APP_NAME}-notify"}) as client:
        for p in prefs:
            user = {"username": p["username"], "role": p["role"], "state": p.get("state"), "district": p.get("district")}
            brief = briefing.build(user, snapshot, None, waves_by_place)
            with store.db() as conn:
                sent = {r["alert_id"]: dict(r) for r in conn.execute("SELECT * FROM notify_sent WHERE username=?", (p["username"],))}
            new = [al for al in brief["alerts"] if al["id"] not in sent]
            if len(new) > SUMMARY_OVER:
                # Many at once (e.g. Central at the start of a storm): one summary
                # message listing them all, not a burst of separate messages.
                status = await _post(client, p, "alert_summary", _summary_payload(new, brief))
                counts[status] += 1
                if status == "sent":
                    _mark_sent(p["username"], new)
            else:
                for al in new:
                    status = await _post(client, p, "escalation" if al["level"] == "red" else "alert", _alert_payload(al))
                    counts[status] += 1
                    if status == "sent":
                        _mark_sent(p["username"], [al])

            # All clear: places we warned about that are now Green.
            green = {pl["id"] for pl in brief["places"] if pl["tier"] == "green"}
            names = {pl["id"]: pl["name"] for pl in brief["places"]}
            done = set()
            for s in sent.values():
                pid = s.get("place_id")
                if s["cleared"] or pid not in green or pid in done:
                    continue
                done.add(pid)
                status = await _post(
                    client,
                    p,
                    "all_clear",
                    {
                        "level": "green",
                        "place_id": pid,
                        "title": f"All clear: {names.get(pid, pid)} is back to Green",
                        "message": f"All clear: {names.get(pid, pid)} is back to Green (normal). No flood warning in force.",
                        "voice_call": False,
                        "link": _link(pid),
                    },
                )
                counts[status] += 1
                if status == "sent":
                    with store.db() as conn:
                        conn.execute("UPDATE notify_sent SET cleared=1 WHERE username=? AND place_id=?", (p["username"], pid))
    return counts


async def daily_brief_if_due(snapshot, waves_by_place: dict) -> int:
    """Send the daily brief once a day at DAILY_BRIEF_HOUR IST."""
    from . import briefing

    now = datetime.now(IST)
    today = now.date().isoformat()
    if now.hour < DAILY_BRIEF_HOUR or _meta("daily_brief_date") == today:
        return 0
    _set_meta("daily_brief_date", today)
    n = 0
    async with httpx.AsyncClient(headers={"User-Agent": f"{APP_NAME}-notify"}) as client:
        for p in _all_prefs():
            if not p["daily_brief"]:
                continue
            user = {"username": p["username"], "role": p["role"], "state": p.get("state"), "district": p.get("district")}
            b = briefing.build(user, snapshot, None, waves_by_place)
            await _post(client, p, "daily_brief", _brief_payload(b))
            n += 1
    return n


def _brief_payload(b: dict) -> dict:
    label = b["scope"]["label"]
    # A state or all of India has no single level (one Red district does not make
    # the country Red), so those briefs carry counts per level instead.
    aggregate = b["scope"]["role"] != "district"
    return {
        "level": None if aggregate else b["status"]["tier"],
        "counts": b["status"]["counts"] if aggregate else None,
        "title": f"Daily flood brief — {label['en']}",
        "brief": b["brief"]["en"],
        "brief_hi": b["brief"]["hi"],
        "message": f"Daily flood brief — {label['en']}: " + " ".join(b["brief"]["en"]),
        "message_hi": f"दैनिक बाढ़ सारांश — {label['hi']}: " + " ".join(b["brief"]["hi"]),
        "alert_count": len(b["alerts"]),
        "voice_call": False,
        "link": _link(None),
    }


async def send_test(p: dict, snapshot, waves_by_place: dict) -> str:
    """A sample message through the whole chain, marked as a test."""
    from . import briefing

    user = {"username": p["username"], "role": p["role"], "state": p.get("state"), "district": p.get("district")}
    b = briefing.build(user, snapshot, None, waves_by_place)
    payload = _brief_payload(b) | {
        "title": f"TEST — {APP_NAME} notifications are working",
        "message": f"TEST from {APP_NAME}. If you received this, alerts for {b['scope']['label']['en']} will reach you here. "
        + (b["brief"]["en"][0] if b["brief"]["en"] else ""),
        "voice_call": "call" in p["channels"],
    }
    async with httpx.AsyncClient(headers={"User-Agent": f"{APP_NAME}-notify"}) as client:
        return await _post(client, p, "test", payload)


def user_by_phone(number: str) -> dict | None:
    """Match an inbound WhatsApp/SMS sender to an opted-in user (last 10 digits)."""
    digits = "".join(ch for ch in number if ch.isdigit())[-10:]
    if len(digits) < 10:
        return None
    for p in _all_prefs():
        for field in ("whatsapp", "phone"):
            if "".join(ch for ch in (p.get(field) or "") if ch.isdigit())[-10:] == digits:
                return p
    return None


async def send_deployment(orders: list[dict], by: dict) -> int:
    """
    Tell the officials at each destination that units are on the way: one
    `deployment` event per recipient per destination, through the same webhook.
    Only opted-in officials whose area covers the destination receive it.
    """
    from .auth import in_scope
    from .engine import LOCATIONS_BY_ID
    from .resources import RTYPES

    by_place: dict[str, list[dict]] = {}
    for o in orders:
        by_place.setdefault(o["place_id"], []).append(o)
    sent = 0
    async with httpx.AsyncClient(headers={"User-Agent": f"{APP_NAME}-notify"}) as client:
        for place_id, items in by_place.items():
            loc = LOCATIONS_BY_ID.get(place_id)
            if not loc:
                continue
            lines = [
                f"{o['count']} {RTYPES[o['rtype']]['en'].lower()} from {o['depot_name']}, arriving in ~{o['arrive_h']} h"
                for o in items
            ]
            lines_hi = [
                f"{o['depot_name']} से {o['count']} {RTYPES[o['rtype']]['hi']}, ~{o['arrive_h']} घंटे में"
                for o in items
            ]
            units = sum(o["count"] for o in items)
            payload = {
                "level": "orange",
                "kind": "deployment",
                "place_id": place_id,
                "title": f"Deployment: {units} units on the way to {loc['name']}",
                "title_hi": f"तैनाती: {units} इकाइयाँ {loc.get('name_hi') or loc['name']} की ओर",
                "detail": "Dispatched by " + by["username"] + " from the JalDrishti response plan. " + "; ".join(lines) + ".",
                "what_to_do": "Prepare staging areas and local guides; confirm arrival on the response plan.",
                "message": f"Deployment to {loc['name']}: " + "; ".join(lines) + ". Reply ACK to confirm.",
                "message_hi": f"{loc.get('name_hi') or loc['name']} हेतु तैनाती: " + "; ".join(lines_hi) + "।",
                "sms": f"{APP_NAME}: {units} units en route to {loc['name']}. " + lines[0][:90],
                "orders": [{k: o[k] for k in ("rtype", "count", "depot_name", "arrive_h")} for o in items],
                "voice_call": False,
                "link": _link(place_id),
            }
            for p in _all_prefs():
                if in_scope(loc, {"role": p["role"], "state": p.get("state"), "district": p.get("district")}):
                    status = await _post(client, p, "deployment", payload)
                    sent += status == "sent"
    return sent


def seed_from_env() -> int:
    """
    Recreate opted-in recipients from JALDRISHTI_NOTIFY_RECIPIENTS at boot.

    A host without a persistent disk (Render Free) starts every deploy with an empty
    database, which would silently drop everyone who opted in on the Notifications
    page. This env var - a JSON list set in the host's dashboard, never committed -
    brings them back. Each entry names an existing account plus its contact details:

        [{"username": "central", "name": "Control room", "email": "ops@example.org",
          "whatsapp": "+9198xxxxxxxx", "channels": ["email", "whatsapp"]}]

    Recipients already in the database are left as they are (the UI wins).
    """
    import os

    from .auth import _user_row

    raw = os.getenv("JALDRISHTI_NOTIFY_RECIPIENTS", "").strip()
    if not raw:
        return 0
    try:
        entries = json.loads(raw)
    except ValueError:
        log.warning("JALDRISHTI_NOTIFY_RECIPIENTS is not valid JSON; ignored")
        return 0
    n = 0
    for e in entries if isinstance(entries, list) else []:
        user = _user_row(str(e.get("username", "")).strip().lower())
        if not user:
            log.warning("JALDRISHTI_NOTIFY_RECIPIENTS: no account %r; skipped", e.get("username"))
            continue
        if get_prefs(user["username"]):
            continue
        save_prefs(user, {"channels": ["email"], "daily_brief": True, "enabled": True} | e)
        n += 1
    return n
