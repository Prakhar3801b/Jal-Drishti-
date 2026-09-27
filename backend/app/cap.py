"""
OASIS Common Alerting Protocol (CAP) 1.2 output.

CAP is the XML format India's alerting chain already speaks: IMD, CWC and the
State Disaster Management Authorities publish CAP to NDMA SACHET, which
disseminates by SMS, cell broadcast and feeds. Publishing JalDrishti's warnings
as CAP lets any of those systems read them without a custom integration.

Mapping, chosen to match what SACHET's own CAP messages use:

    tier    severity   responseType          (IMD four-colour scale)
    red     Extreme    Evacuate, Prepare
    orange  Severe     Prepare
    yellow  Moderate   Monitor
    green   -          no message, unless it lifts a warning (All Clear)

    urgency    Immediate if the peak is now and the tier is Orange or Red,
               Expected if the peak is now, otherwise Future
    certainty  Observed when an official gauge or alert set the score,
               Likely at high model confidence, otherwise Possible

Message threading follows the spec: the first warning for a place is an Alert;
each later run that still warns is an Update that references the previous
message; the run where the place drops to Green sends an Update with
responseType AllClear. Status is always Exercise or Test (see config), never
Actual - this is a research prototype, not an official warning service.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence
from xml.etree import ElementTree as ET

from . import store
from .config import (
    APP_NAME,
    CAP_AREA_RADIUS_KM,
    CAP_SENDER,
    CAP_STATUS,
    PUBLIC_WEB_URL,
    REFRESH_MINUTES,
    VERSION,
)

CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"
ATOM_NS = "http://www.w3.org/2005/Atom"
IST = timezone(timedelta(hours=5, minutes=30))

WARNING_TIERS = ("yellow", "orange", "red")
SEVERITY = {"red": "Extreme", "orange": "Severe", "yellow": "Moderate"}
RESPONSE = {"red": ["Evacuate", "Prepare"], "orange": ["Prepare"], "yellow": ["Monitor"]}
SEVERITY_ORDER = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}

SENDER_NAME = {
    "en-IN": f"{APP_NAME} research prototype (not an official Government of India service)",
    "hi-IN": f"{APP_NAME} शोध प्रोटोटाइप (भारत सरकार की आधिकारिक सेवा नहीं)",
}
NOTE = (
    f"{APP_NAME} {VERSION} research prototype. Status {CAP_STATUS}: not an official "
    "warning. For operational warnings follow IMD, CWC and your State Disaster "
    "Management Authority."
)



def _c(path: str) -> str:
    """Namespace a CAP element path for find()/findtext()."""
    return "/".join(f"{{{CAP_NS}}}{part}" for part in path.split("/"))


def _cap_time(iso: str | datetime) -> str:
    """CAP forbids 'Z' and fractional seconds: 2026-09-27T11:00:00+05:30."""
    dt = datetime.fromisoformat(iso) if isinstance(iso, str) else iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).replace(microsecond=0).isoformat()


def identifier(location_id: str, run_id: int) -> str:
    # No spaces, commas, '<' or '&' (CAP 1.2 section 3.2.1).
    return f"IN-{APP_NAME.upper()}-{location_id}-{run_id}"


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, _c(tag))
    if text is not None:
        el.text = str(text)
    return el


def _pair(parent: ET.Element, tag: str, name: str, value) -> None:
    el = _sub(parent, tag)
    _sub(el, "valueName", name)
    _sub(el, "value", value)


def _urgency(tier: str, peak_hours: int) -> str:
    if peak_hours <= 0:
        return "Immediate" if tier in ("orange", "red") else "Expected"
    return "Future"


def _certainty(a: dict) -> str:
    if a["risk"].get("official_floor_applied"):
        return "Observed"
    return "Likely" if a["confidence"]["level"] == "high" else "Possible"


def _parameters(info: ET.Element, a: dict) -> None:
    risk, obs, river = a["risk"], a["observations"], a["river"]
    _pair(info, "parameter", "RiskScore", f"{risk['score']:.0f}")
    _pair(info, "parameter", "ModelScore", f"{risk['model_score']:.0f}")
    _pair(info, "parameter", "Confidence", f"{a['confidence']['value']:.2f}")
    _pair(info, "parameter", "Mechanism", risk["dominant"].get("mechanism", ""))
    _pair(info, "parameter", "Trend", risk["direction"]["key"])
    if obs.get("rain_24h_mm") is not None:
        _pair(info, "parameter", "Rain24hMM", f"{obs['rain_24h_mm']:.1f}")
    if obs.get("rain_next_24h_mm") is not None:
        _pair(info, "parameter", "RainNext24hMM", f"{obs['rain_next_24h_mm']:.1f}")
    if river.get("percentile_for_season") is not None:
        _pair(info, "parameter", "RiverSeasonalPercentile", f"{river['percentile_for_season']:.0f}")
    gauge = (a.get("official") or {}).get("gauge")
    if gauge:
        _pair(info, "parameter", "CWCGauge", f"{gauge['code']} {gauge['name']} {gauge['status']}")
        if gauge.get("above_danger_m") is not None:
            _pair(info, "parameter", "CWCAboveDangerM", f"{gauge['above_danger_m']:+.2f}")
    for alert in (a.get("official") or {}).get("alerts") or []:
        _pair(info, "parameter", "OfficialAlert", f"{alert['source']}: {alert['type']} ({alert['colour']})")


def _info(alert: ET.Element, a: dict, lang: str, sent: datetime, clear: bool) -> None:
    loc, risk, expl, acts = a["location"], a["risk"], a["explanation"], a["actions"]
    tier = risk["tier"]["key"]
    hi = lang == "hi-IN"
    name = (loc.get("name_hi") or loc["name"]) if hi else loc["name"]

    info = _sub(alert, "info")
    _sub(info, "language", lang)
    _sub(info, "category", "Met")
    _sub(info, "event", "बाढ़" if hi else "Flood")
    if clear:
        _sub(info, "responseType", "AllClear")
        _sub(info, "urgency", "Past")
        _sub(info, "severity", "Minor")
        _sub(info, "certainty", "Likely")
    else:
        for rt in RESPONSE[tier]:
            _sub(info, "responseType", rt)
        _sub(info, "urgency", _urgency(tier, risk["peak"]["hours"]))
        _sub(info, "severity", SEVERITY[tier])
        _sub(info, "certainty", _certainty(a))
    _pair(info, "eventCode", "IMDColourCode", tier.title())

    _sub(info, "effective", _cap_time(sent))
    if not clear:
        _sub(info, "onset", _cap_time(sent + timedelta(hours=risk["peak"]["hours"])))
    # Superseded at the next refresh; the margin covers one missed refresh.
    _sub(info, "expires", _cap_time(sent + timedelta(minutes=2 * REFRESH_MINUTES)))
    _sub(info, "senderName", SENDER_NAME[lang])

    if clear:
        headline = (
            f"{name} के लिए बाढ़ चेतावनी हटाई गई — अब हरा स्तर"
            if hi
            else f"Flood warning for {name} lifted — now Green"
        )
    else:
        headline = expl["headline_hi" if hi else "headline_en"]
    _sub(info, "headline", headline)
    _sub(info, "description", expl["narrative_hi" if hi else "narrative_en"])
    instruction = " ".join(
        x for x in (acts.get("imd_meaning_hi" if hi else "imd_meaning_en"), acts.get("ndma_action_hi" if hi else "ndma_action_en")) if x
    )
    if instruction:
        _sub(info, "instruction", instruction)
    if PUBLIC_WEB_URL:
        _sub(info, "web", f"{PUBLIC_WEB_URL}/#/location/{loc['id']}")
    _parameters(info, a)

    area = _sub(info, "area")
    district = loc.get("district")
    if hi:
        _sub(area, "areaDesc", ", ".join(x for x in (name, district, loc["state"]) if x))
    else:
        _sub(area, "areaDesc", ", ".join(x for x in (name, f"{district} district" if district else None, loc["state"]) if x))
    _sub(area, "circle", f"{loc['lat']:.4f},{loc['lon']:.4f} {CAP_AREA_RADIUS_KM:g}")
    _pair(area, "geocode", "JalDrishtiLocationID", loc["id"])


def build_alert(a: dict, run_id: int) -> ET.Element | None:
    """
    The CAP message this run issues for one location, or None when there is
    nothing to say (Green now and no warning to lift).
    """
    loc_id = a["location"]["id"]
    tier = a["risk"]["tier"]["key"]
    prev = store.tier_before(loc_id, run_id)
    prev_warned = bool(prev and prev["tier"] in WARNING_TIERS)
    warning = tier in WARNING_TIERS
    if not warning and not prev_warned:
        return None

    sent = datetime.fromisoformat(store.computed_at(loc_id, run_id) or datetime.now(timezone.utc).isoformat())
    alert = ET.Element(_c("alert"))
    _sub(alert, "identifier", identifier(loc_id, run_id))
    _sub(alert, "sender", CAP_SENDER)
    _sub(alert, "sent", _cap_time(sent))
    _sub(alert, "status", CAP_STATUS)
    _sub(alert, "msgType", "Update" if prev_warned else "Alert")
    _sub(alert, "source", f"{APP_NAME} {VERSION}")
    _sub(alert, "scope", "Public")
    _sub(alert, "note", NOTE)
    if prev_warned:
        _sub(alert, "references", f"{CAP_SENDER},{identifier(loc_id, prev['run_id'])},{_cap_time(prev['computed_at'])}")
    for lang in ("en-IN", "hi-IN"):
        _info(alert, a, lang, sent, clear=not warning)
    return alert


def to_xml(el: ET.Element) -> bytes:
    ET.indent(el)
    return ET.tostring(el, encoding="utf-8", xml_declaration=True, default_namespace=CAP_NS)


def build_feed(assessments: Sequence[dict], run_id: int, base_url: str) -> bytes:
    """
    Atom index of every message this run issued, most severe first - the usual
    way CAP alerts are listed for aggregators to poll.
    """
    base = base_url.rstrip("/")
    items = []
    for a in assessments:
        msg = build_alert(a, run_id)
        if msg is not None:
            items.append((a, msg))

    def sev(msg: ET.Element) -> int:
        return SEVERITY_ORDER.get(msg.findtext(_c("info/severity")), 9)

    items.sort(key=lambda it: (sev(it[1]), -it[0]["risk"]["score"]))

    # Plain tags plus a literal xmlns: ElementTree's default_namespace option
    # rejects the unqualified attributes (rel, href) Atom links need.
    A = lambda tag: tag  # noqa: E731
    feed = ET.Element("feed", xmlns=ATOM_NS)
    ET.SubElement(feed, A("id")).text = f"urn:{APP_NAME.lower()}:cap:feed"
    ET.SubElement(feed, A("title")).text = f"{APP_NAME} flood warnings (CAP 1.2, {CAP_STATUS})"
    ET.SubElement(feed, A("subtitle")).text = NOTE
    updated = max((it[1].findtext(_c("sent")) for it in items), default=_cap_time(datetime.now(timezone.utc)))
    ET.SubElement(feed, A("updated")).text = updated
    ET.SubElement(ET.SubElement(feed, A("author")), A("name")).text = SENDER_NAME["en-IN"]
    ET.SubElement(feed, A("link"), rel="self", href=f"{base}/api/cap/feed.atom")

    for a, msg in items:
        info = msg.find(_c("info"))
        entry = ET.SubElement(feed, A("entry"))
        ET.SubElement(entry, A("id")).text = f"urn:{APP_NAME.lower()}:cap:{msg.findtext(_c('identifier'))}"
        ET.SubElement(entry, A("title")).text = info.findtext(_c("headline"))
        ET.SubElement(entry, A("updated")).text = msg.findtext(_c("sent"))
        ET.SubElement(entry, A("summary")).text = " · ".join(
            [info.findtext(_c(t)) for t in ("severity", "urgency", "certainty")] + [msg.findtext(_c("msgType"))]
        )
        ET.SubElement(
            entry, A("link"), rel="alternate", type="application/cap+xml",
            href=f"{base}/api/cap/alerts/{a['location']['id']}.xml",
        )
    ET.indent(feed)
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True)
