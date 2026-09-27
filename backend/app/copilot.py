"""
JalDrishti Copilot: questions in plain English or Hindi, answered from the live
risk snapshot, plus generated public advisories.

Grounding is the whole design. The model receives a compact table of every
monitored location's current score, tier, confidence, top drivers and the raw
numbers behind them, and is told to answer only from that table. It is a
phrasing layer over the engine, not a second forecaster.

With no LLM key, a deterministic answerer handles the questions an operations
room actually asks - "where is it worst", "what about Assam", "why is Patna
orange", "who is on the Brahmaputra" - directly from the same data, so the feature
works offline and at zero cost.
"""

from __future__ import annotations

import re
from typing import Sequence

from . import llm

# Real Indian emergency numbers, used in generated advisories.
HELPLINES = {
    "en": "National emergency 112 · NDMA disaster helpline 1078 · State/District EOC 1070/1077",
    "hi": "राष्ट्रीय आपातकाल 112 · एनडीएमए आपदा हेल्पलाइन 1078 · राज्य/जिला ईओसी 1070/1077",
}

# Hindi names for rivers and states, so a question typed in Devanagari reaches
# the same lookups as its English equivalent.
HINDI_ALIASES = {
    "गंगा": "ganga", "ब्रह्मपुत्र": "brahmaputra", "यमुना": "yamuna", "गोदावरी": "godavari",
    "कृष्णा": "krishna", "महानदी": "mahanadi", "बराक": "barak", "तापी": "tapi",
    "कावेरी": "cauvery", "झेलम": "jhelum", "तीस्ता": "teesta", "बागमती": "bagmati",
    "गोमती": "gomti", "राप्ती": "rapti", "हुगली": "hooghly", "साबरमती": "sabarmati",
    "असम": "assam", "बिहार": "bihar", "महाराष्ट्र": "maharashtra", "केरल": "kerala",
    "उत्तर प्रदेश": "uttar pradesh", "पश्चिम बंगाल": "west bengal", "गुजरात": "gujarat",
    "ओडिशा": "odisha", "तमिल नाडु": "tamil nadu", "आंध्र प्रदेश": "andhra pradesh",
    "तेलंगाना": "telangana", "कर्नाटक": "karnataka", "दिल्ली": "delhi", "मणिपुर": "manipur",
    "त्रिपुरा": "tripura", "उत्तराखंड": "uttarakhand", "जम्मू": "jammu and kashmir",
}

TIER_WORD = {
    "en": {"red": "Red", "orange": "Orange", "yellow": "Yellow", "green": "Green"},
    "hi": {"red": "लाल", "orange": "नारंगी", "yellow": "पीला", "green": "हरा"},
}

SYSTEM_INSTRUCTIONS = """You are JalDrishti Copilot, an assistant inside a flood-risk dashboard for India used by disaster-management officers.

How to answer:
- Answer ONLY from the LIVE DATA table provided. Never invent a location, a number, a date or a forecast that is not in it. If the data does not contain the answer, say so plainly.
- Quote the actual numbers (score out of 100, alert tier, mm of rain, discharge percentile) so the officer can check them against the dashboard.
- Alert tiers follow IMD's colour scale: Green (<25) no warning, Yellow (25-50) be aware, Orange (50-75) be prepared, Red (>=75) take action.
- When recommending action, stay consistent with the NDMA tier actions in the data. Do not recommend evacuations for Green or Yellow locations.
- Be concise: a short direct answer first, then at most a few bullet points.
- Reply in the language the user writes in. If they write in Hindi (Devanagari), reply in Hindi.
- This is a prototype, not an official warning service; if asked about official warnings, direct people to IMD, CWC and their State Disaster Management Authority."""


def _row(a: dict) -> str:
    loc, risk, obs, river, conf = a["location"], a["risk"], a["observations"], a["river"], a["confidence"]
    top = ", ".join(f"{f['label_en']} {f['value']:.0f}" for f in a["factors"][:3])
    pct = river.get("percentile_for_season")
    anomaly = (a.get("ai") or {}).get("anomaly") or {}
    analog = (a.get("ai") or {}).get("analogs") or {}
    parts = [
        f"{loc['name']} ({loc.get('name_hi') or ''}), {loc['state']}",
        f"river {loc.get('river') or '-'}",
        f"score {risk['score']:.0f} {risk['tier']['key']}",
        f"trend {risk['direction']['key']} ({risk['direction']['delta']:+.0f} over 72h)",
        f"confidence {conf['level']}",
        f"rain24h {obs.get('rain_24h_mm')}mm",
        f"rain next24h {obs.get('rain_next_24h_mm')}mm",
        f"discharge pct {pct if pct is not None else '-'}",
        f"top drivers: {top}",
        f"pop {loc.get('population')}",
    ]
    if anomaly.get("available"):
        parts.append(f"anomaly {anomaly['score']:.0f} ({anomaly['level']})")
    if analog.get("available"):
        parts.append(f"analog flood prob {analog['knn_flood_probability']:.2f}")
    return " | ".join(parts)


def snapshot_context(snapshot) -> str:
    rows = sorted(snapshot.assessments, key=lambda a: a["risk"]["score"], reverse=True)
    counts = snapshot.tier_counts
    header = (
        f"LIVE DATA (computed {snapshot.computed_at.isoformat(timespec='minutes')} UTC, "
        f"{len(rows)} monitored locations; red {counts['red']}, orange {counts['orange']}, "
        f"yellow {counts['yellow']}, green {counts['green']}). Sorted by risk score, highest first:"
    )
    return header + "\n" + "\n".join(f"- {_row(a)}" for a in rows)


def _is_hindi(text: str) -> bool:
    return bool(re.search(r"[ऀ-ॿ]", text))


# ------------------------------------------------------------ offline answerer


def _fmt(a: dict, lang: str) -> str:
    loc, risk = a["location"], a["risk"]
    name = loc.get("name_hi") if lang == "hi" and loc.get("name_hi") else loc["name"]
    tier = TIER_WORD[lang][risk["tier"]["key"]]
    rain = a["observations"].get("rain_24h_mm")
    return f"{name} — {risk['score']:.0f}/100 {tier}" + (f", {rain:.0f} mm/24h" if rain is not None else "")


def offline_answer(question: str, snapshot, lang: str) -> str:
    q = question.lower()
    for hindi, english in HINDI_ALIASES.items():
        if hindi in q:
            q += " " + english
    rows = sorted(snapshot.assessments, key=lambda a: a["risk"]["score"], reverse=True)

    # 1. A specific location named?
    for a in rows:
        loc = a["location"]
        names = [loc["name"].lower(), (loc.get("name_hi") or "").lower(), loc["id"]]
        if any(n and n in q for n in names):
            f = a["factors"][:3]
            drivers = ", ".join((x["label_hi"] if lang == "hi" else x["label_en"]) for x in f)
            narrative = a["explanation"]["narrative_hi" if lang == "hi" else "narrative_en"]
            action = a["actions"]["ndma_action_hi" if lang == "hi" else "ndma_action_en"]
            lead = "मुख्य कारक" if lang == "hi" else "Main drivers"
            act = "अनुशंसित कार्रवाई" if lang == "hi" else "Recommended action"
            return f"{narrative}\n\n• {lead}: {drivers}\n• {act}: {action}"

    # 2. A state named?
    states = {a["location"]["state"] for a in rows}
    for st in states:
        if st.lower() in q:
            items = [a for a in rows if a["location"]["state"] == st]
            head = f"{items[0]['location']['state']}: {len(items)} निगरानी स्थान" if lang == "hi" else f"{st}: {len(items)} monitored locations"
            return head + "\n" + "\n".join(f"• {_fmt(a, lang)}" for a in items)

    # 3. A river named?
    rivers = {(a["location"].get("river") or "").lower() for a in rows} - {""}
    for rv in rivers:
        if rv in q:
            items = [a for a in rows if (a["location"].get("river") or "").lower() == rv]
            head = f"{rv.title()} नदी पर स्थान:" if lang == "hi" else f"Locations on the {rv.title()}:"
            return head + "\n" + "\n".join(f"• {_fmt(a, lang)}" for a in items)

    # 4. Unusual / anomaly?
    if any(w in q for w in ("unusual", "anomal", "strange", "असामान्य")):
        items = sorted(
            (a for a in rows if (a.get("ai") or {}).get("anomaly", {}).get("available")),
            key=lambda a: a["ai"]["anomaly"]["score"],
            reverse=True,
        )[:5]
        if items:
            head = "सबसे असामान्य स्थितियाँ:" if lang == "hi" else "Most unusual conditions right now:"
            return head + "\n" + "\n".join(
                f"• {_fmt(a, lang)} · anomaly {a['ai']['anomaly']['score']:.0f}" for a in items
            )

    # 5. Default: national picture.
    counts = snapshot.tier_counts
    if lang == "hi":
        head = (f"{len(rows)} स्थानों में: लाल {counts['red']}, नारंगी {counts['orange']}, "
                f"पीला {counts['yellow']}, हरा {counts['green']}। सर्वाधिक जोखिम:")
        tail = "\n\nकिसी शहर, राज्य या नदी का नाम लिखकर विस्तार से पूछें।"
    else:
        head = (f"Across {len(rows)} locations: {counts['red']} Red, {counts['orange']} Orange, "
                f"{counts['yellow']} Yellow, {counts['green']} Green. Highest risk now:")
        tail = "\n\nAsk about a city, state or river by name for detail."
    return head + "\n" + "\n".join(f"• {_fmt(a, lang)}" for a in rows[:5]) + tail


async def answer(question: str, history: Sequence[dict], snapshot, lang: str | None = None) -> dict:
    lang = lang or ("hi" if _is_hindi(question) else "en")
    messages = [
        {"role": m["role"], "content": str(m["content"])[:2000]}
        for m in history[-8:]
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    messages.append({"role": "user", "content": question[:2000]})
    # Providers require the conversation to open with a user turn.
    while messages and messages[0]["role"] != "user":
        messages.pop(0)

    try:
        result = await llm.generate(
            [SYSTEM_INSTRUCTIONS, snapshot_context(snapshot)], messages, max_tokens=1500
        )
        return {"answer": result.text, "provider": result.provider, "model": result.model, "grounded": True}
    except llm.LLMUnavailable as exc:
        return {
            "answer": offline_answer(question, snapshot, lang),
            "provider": "offline",
            "model": "rule-based",
            "grounded": True,
            "note": str(exc),
        }


# ------------------------------------------------------------------ advisory


def offline_advisory(a: dict) -> dict:
    loc, risk, obs = a["location"], a["risk"], a["observations"]
    tier = risk["tier"]["key"]
    from .safety import advice

    steps = advice(loc["id"], tier, "place")
    routes = steps["routes"]
    out = {}
    for lang in ("en", "hi"):
        name = loc.get("name_hi") if lang == "hi" and loc.get("name_hi") else loc["name"]
        residents = "\n".join(f"• {x}" for x in steps[lang])
        drivers = "; ".join(
            b for b in a["explanation"]["bullets_hi" if lang == "hi" else "bullets_en"]
        )
        action = a["actions"]["ndma_action_hi" if lang == "hi" else "ndma_action_en"]
        meaning = a["actions"]["imd_meaning_hi" if lang == "hi" else "imd_meaning_en"]
        if lang == "hi":
            title = f"बाढ़ जोखिम सलाह — {name} ({TIER_WORD['hi'][tier]} स्तर)"
            body = (
                f"{name} में वर्तमान बाढ़ जोखिम {risk['score']:.0f}/100 ({TIER_WORD['hi'][tier]}) है। {meaning}\n"
                f"कारण: {drivers}।\n"
                f"प्रशासन हेतु: {action}\n"
                f"नागरिकों के लिए:\n{residents}\n"
                f"हेल्पलाइन: {HELPLINES['hi']}"
            )
            avoid = f" {routes[0]} से बचें।" if routes else " जलभराव वाली सड़कों से बचें।"
            sms = f"जलदृष्टि: {name} बाढ़ जोखिम {TIER_WORD['hi'][tier]}।{avoid} उबला पानी पिएँ। आपात 112/1078"
        else:
            title = f"Flood risk advisory — {name} ({TIER_WORD['en'][tier]})"
            body = (
                f"Current flood risk in {name} is {risk['score']:.0f}/100 ({TIER_WORD['en'][tier]}). {meaning}\n"
                f"Why: {drivers}.\n"
                f"For authorities: {action}\n"
                f"For residents:\n{residents}\n"
                f"Helplines: {HELPLINES['en']}"
            )
            avoid = f" Avoid {routes[0]}." if routes else " Avoid flooded roads."
            sms = f"JalDrishti: {name} flood risk {TIER_WORD['en'][tier]}.{avoid} Drink boiled water. Emergency 112/1078"
        out[lang] = {"title": title, "body": body, "sms": sms[:160]}
    return out


ADVISORY_PROMPT = """Write a public flood advisory for the location below, based ONLY on the data given.

Return exactly this format, with no other text:
[EN_TITLE] one line
[EN_BODY] 4-6 short lines: current situation with the score and tier; why (quote the numbers); what authorities should do (consistent with the NDMA action given); what residents should do; the helplines line exactly as given
[EN_SMS] one SMS under 160 characters
[HI_TITLE] the same title in natural Hindi
[HI_BODY] the same body in natural, official-register Hindi (not a word-for-word translation)
[HI_SMS] one Hindi SMS under 160 characters

Do not add any number that is not in the data. Do not escalate beyond the alert tier."""


def _parse_advisory(text: str) -> dict | None:
    tags = ["EN_TITLE", "EN_BODY", "EN_SMS", "HI_TITLE", "HI_BODY", "HI_SMS"]
    found = {}
    for i, tag in enumerate(tags):
        nxt = tags[i + 1] if i + 1 < len(tags) else None
        pattern = rf"\[{tag}\]\s*(.*?)" + (rf"(?=\[{nxt}\])" if nxt else r"$")
        m = re.search(pattern, text, re.S)
        if not m:
            return None
        found[tag] = m.group(1).strip()
    return {
        "en": {"title": found["EN_TITLE"], "body": found["EN_BODY"], "sms": found["EN_SMS"][:160]},
        "hi": {"title": found["HI_TITLE"], "body": found["HI_BODY"], "sms": found["HI_SMS"][:160]},
    }


async def advisory(a: dict) -> dict:
    data = (
        _row(a)
        + f"\nNarrative: {a['explanation']['narrative_en']}"
        + f"\nIMD meaning: {a['actions']['imd_meaning_en']}"
        + f"\nNDMA action: {a['actions']['ndma_action_en']}"
        + f"\nHelplines (EN): {HELPLINES['en']}\nHelplines (HI): {HELPLINES['hi']}"
    )
    try:
        result = await llm.generate(
            [SYSTEM_INSTRUCTIONS, ADVISORY_PROMPT], [{"role": "user", "content": data}], max_tokens=2000
        )
        parsed = _parse_advisory(result.text)
        if parsed:
            return {**parsed, "provider": result.provider, "model": result.model}
    except llm.LLMUnavailable:
        pass
    return {**offline_advisory(a), "provider": "offline", "model": "template"}
