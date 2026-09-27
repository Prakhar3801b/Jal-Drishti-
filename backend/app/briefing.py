"""
The signed-in user's area in one plain-language briefing.

This is the simple screen: everything an officer needs about *their* area,
computed automatically on every refresh so nobody has to go looking.

    status        how many places are at each colour, and the worst one
    alerts        places at Orange/Red, places that just got worse, river flood
                  waves heading into the area, gauges above danger and official
                  IMD/CWC/SDMA alerts - each with what to do and, for places, a
                  ready-to-review public advisory and SMS
    coming_next   places expected to get worse over the next 72 hours
    changes       what moved since the user last looked
    brief         a short daily brief in English and Hindi
    places        every place in the area, worst first
"""

from __future__ import annotations

from . import auth, copilot, safety, store

TIER_RANK = {"green": 0, "yellow": 1, "orange": 2, "red": 3}
TIER_WORD = {
    "en": {"green": "Green (normal)", "yellow": "Yellow (be aware)", "orange": "Orange (be prepared)", "red": "Red (take action)"},
    "hi": {"green": "हरा (सामान्य)", "yellow": "पीला (सतर्क रहें)", "orange": "नारंगी (तैयार रहें)", "red": "लाल (कार्रवाई करें)"},
}
SHORT = {
    "en": {"green": "Green", "yellow": "Yellow", "orange": "Orange", "red": "Red"},
    "hi": {"green": "हरा", "yellow": "पीला", "orange": "नारंगी", "red": "लाल"},
}
MAX_ALERTS = 30


def _name(a: dict, lang: str) -> str:
    loc = a["location"]
    return (loc.get("name_hi") or loc["name"]) if lang == "hi" else loc["name"]


def _place_row(a: dict) -> dict:
    loc = a["location"]
    return {
        "id": loc["id"],
        "name": loc["name"],
        "name_hi": loc.get("name_hi"),
        "district": loc.get("district"),
        "state": loc["state"],
        "tier": a["risk"]["tier"]["key"],
        "score": round(a["risk"]["score"]),
        "direction": a["risk"]["direction"]["key"],
        "reason_en": a["factors"][0]["label_en"] if a["factors"] else None,
        "reason_hi": a["factors"][0]["label_hi"] if a["factors"] else None,
        "weather": a.get("current_weather"),
    }


def _worst_future(a: dict) -> dict | None:
    """The worst tier the 72 h trajectory reaches after now, if worse than now."""
    now = TIER_RANK[a["risk"]["tier"]["key"]]
    worst = None
    for step in a.get("trajectory", [])[1:]:
        if TIER_RANK.get(step["tier"], 0) > max(now, TIER_RANK.get(worst["tier"], -1) if worst else -1):
            worst = step
    return worst


def build(user: dict, snapshot, since: str | None, waves_by_place: dict[str, list[dict]]) -> dict:
    items = [a for a in snapshot.assessments if auth.in_scope(a["location"], user)]
    items.sort(key=lambda a: a["risk"]["score"], reverse=True)
    counts = {t: sum(1 for a in items if a["risk"]["tier"]["key"] == t) for t in ("red", "orange", "yellow", "green")}
    worst = items[0] if items else None
    label = auth.scope_label(user)

    # --------------------------------------------------------------- changes
    base_run, before = store.tiers_as_of(since, snapshot.run_id)
    changes = []
    for a in items:
        prev = before.get(a["location"]["id"])
        if not prev:
            continue
        now_t, was_t = a["risk"]["tier"]["key"], prev["tier"]
        if now_t != was_t:
            changes.append(
                {
                    **_place_row(a),
                    "from": was_t,
                    "to": now_t,
                    "worse": TIER_RANK[now_t] > TIER_RANK[was_t],
                    "delta": round(a["risk"]["score"] - prev["score"]),
                }
            )
    changes.sort(key=lambda c: (not c["worse"], -abs(c["delta"])))
    worse_ids = {c["id"] for c in changes if c["worse"]}

    # ---------------------------------------------------------------- alerts
    alerts = []
    for a in items:
        loc, tier = a["location"], a["risk"]["tier"]["key"]
        if tier in ("red", "orange") or loc["id"] in worse_ids and tier != "green":
            got_worse = loc["id"] in worse_ids
            adv = copilot.offline_advisory(a)
            alerts.append(
                {
                    "id": f"place:{loc['id']}:{tier}",
                    "level": tier,
                    "kind": "place",
                    "place_id": loc["id"],
                    "title_en": f"{loc['name']} is at {SHORT['en'][tier]}" + (" — just got worse" if got_worse else ""),
                    "title_hi": f"{_name(a, 'hi')} {SHORT['hi'][tier]} स्तर पर" + (" — अभी बिगड़ा" if got_worse else ""),
                    "detail_en": a["explanation"]["headline_en"] + (" " + a["explanation"]["bullets_en"][0] if a["explanation"]["bullets_en"] else ""),
                    "detail_hi": a["explanation"]["headline_hi"] + (" " + a["explanation"]["bullets_hi"][0] if a["explanation"]["bullets_hi"] else ""),
                    "do_en": a["actions"]["ndma_action_en"],
                    "do_hi": a["actions"]["ndma_action_hi"],
                    "advisory": adv,
                }
            )
        gauge = (a.get("official") or {}).get("gauge")
        if gauge and gauge.get("status") == "DANGER":
            alerts.append(
                {
                    "id": f"gauge:{gauge['code']}",
                    "level": "red",
                    "kind": "gauge",
                    "place_id": loc["id"],
                    "title_en": f"River above danger at {gauge['name']}",
                    "title_hi": f"{gauge['name']} पर नदी खतरे के निशान से ऊपर",
                    "detail_en": f"CWC gauge near {loc['name']} reads {gauge['level_m']} m, {gauge['above_danger_m']} m above its danger mark"
                    + (f" and {gauge['trend'].lower()}" if gauge.get("trend") else "") + ".",
                    "detail_hi": f"{_name(a, 'hi')} के पास CWC गेज {gauge['level_m']} मी पर, खतरे के निशान से {gauge['above_danger_m']} मी ऊपर।",
                    "do_en": "Alert riverside wards and embankment patrols; keep evacuation routes open.",
                    "do_hi": "नदी किनारे के वार्डों व तटबंध गश्त को सचेत करें; निकासी मार्ग खुले रखें।",
                }
            )
        for off in (a.get("official") or {}).get("alerts") or []:
            alerts.append(
                {
                    "id": f"official:{off['id']}",
                    "level": off.get("colour") or "yellow",
                    "kind": "official",
                    "place_id": loc["id"],
                    "title_en": f"Official {off.get('colour', '')} alert: {off['type']}".replace("  ", " "),
                    "title_hi": f"आधिकारिक चेतावनी: {off['type']}",
                    "detail_en": f"{off['source']} — {off['area']}",
                    "detail_hi": f"{off['source']} — {off['area']}",
                    "do_en": "Follow the issuing authority's instructions.",
                    "do_hi": "जारी करने वाले प्राधिकरण के निर्देशों का पालन करें।",
                }
            )

    # River flood waves heading into the area.
    # One wave per place: the most serious, soonest gauge upstream, with a note
    # when more gauges upstream are also high - one alert, not one per gauge.
    waves = []
    for a in items:
        threats = [t for t in waves_by_place.get(a["location"]["id"], []) if t["evidence"] != "weak"]
        if threats:
            threats.sort(key=lambda t: (t["status"] != "DANGER", t["eta_h"]["p50"]))
            waves.append((a, threats[0], len(threats) - 1))
    for a, t, more in waves:
        e = t["eta_h"]
        alerts.append(
            {
                "id": f"wave:{a['location']['id']}:{t['code']}",
                "level": "orange" if t["status"] == "DANGER" else "yellow",
                "kind": "wave",
                "place_id": a["location"]["id"],
                "title_en": f"Flood wave heading to {a['location']['name']}",
                "title_hi": f"{_name(a, 'hi')} की ओर बाढ़ लहर",
                "detail_en": f"The {t['river']} at {t['name']}, {t['distance_km']} km upstream, is "
                + ("above its danger mark" if t["status"] == "DANGER" else "above its warning level" if t["status"] == "WARNING" else "rising towards danger")
                + (f" and {t['trend'].lower()}" if t.get("trend") else "")
                + f". Water could arrive in about {e['p50']} h ({e['p10']}–{e['p90']} h)."
                + (f" {more} more gauge{'s' if more > 1 else ''} upstream {'are' if more > 1 else 'is'} also high." if more else ""),
                "detail_hi": f"{t['river']} नदी {t['name']} पर, {t['distance_km']} किमी ऊपर, "
                + ("खतरे के निशान से ऊपर" if t["status"] == "DANGER" else "चेतावनी स्तर से ऊपर" if t["status"] == "WARNING" else "खतरे की ओर बढ़ रही")
                + f"। पानी लगभग {e['p50']} घंटे ({e['p10']}–{e['p90']} घं) में पहुँच सकता है।"
                + (f" ऊपर के {more} और गेज भी ऊँचे हैं।" if more else ""),
                "do_en": "Warn low-lying riverside areas now; pre-position boats and relief material before the wave arrives.",
                "do_hi": "नदी किनारे के निचले इलाकों को अभी सचेत करें; लहर पहुँचने से पहले नावें व राहत सामग्री तैनात करें।",
            }
        )

    # One alert per id; most serious first.
    seen, uniq = set(), []
    for al in sorted(alerts, key=lambda x: (-TIER_RANK.get(x["level"], 0), x["kind"] != "place")):
        if al["id"] not in seen:
            seen.add(al["id"])
            uniq.append(al)
    alerts = uniq[:MAX_ALERTS]
    # Every alert carries public-safety steps: roads to avoid, safe water, what to do.
    for al in alerts:
        al["safety"] = safety.advice(al.get("place_id"), al["level"], al["kind"])

    # ----------------------------------------------------------- coming next
    coming = []
    for a in items:
        fut = _worst_future(a)
        if fut:
            coming.append(
                {
                    **_place_row(a),
                    "to": fut["tier"],
                    "in_hours": fut["hours"],
                    "to_score": round(fut["score"]),
                }
            )
    coming.sort(key=lambda c: (c["in_hours"], -TIER_RANK[c["to"]]))
    wave_next = [
        {
            "id": a["location"]["id"],
            "name": a["location"]["name"],
            "name_hi": a["location"].get("name_hi"),
            "river": t["river"],
            "gauge": t["name"],
            "eta_h": t["eta_h"],
            "evidence": t["evidence"],
        }
        for a, t, _ in sorted(waves, key=lambda w: w[1]["eta_h"]["p50"])
    ]

    # ----------------------------------------------------------------- brief
    n = len(items)
    brief = {}
    for lang in ("en", "hi"):
        w = SHORT[lang]
        lines = []
        if lang == "en":
            if counts["red"] + counts["orange"] + counts["yellow"] == 0:
                lines.append(f"All {n} monitored place{'s are' if n != 1 else ' is'} normal (Green).")
            else:
                parts = [f"{counts[t]} at {w[t]}" for t in ("red", "orange", "yellow") if counts[t]]
                if counts["green"]:
                    parts.append(f"{counts['green']} normal")
                lines.append(f"{label['en']}: {', '.join(parts)} — out of {n} monitored place{'s' if n != 1 else ''}.")
            if worst and worst["risk"]["tier"]["key"] != "green":
                reason = worst["factors"][0]["label_en"].lower() if worst["factors"] else ""
                lines.append(f"Highest risk: {worst['location']['name']} ({worst['risk']['score']:.0f}/100, {w[worst['risk']['tier']['key']]}){' — ' + reason if reason else ''}.")
            lines.append(
                f"{len(coming)} place{'s are' if len(coming) != 1 else ' is'} expected to get worse in the next 3 days."
                if coming
                else "No place is expected to get worse in the next 3 days."
            )
            if wave_next:
                wv = wave_next[0]
                lines.append(f"A flood wave on the {wv['river']} could reach {wv['name']} in about {wv['eta_h']['p50']} hours.")
            official_n = sum(1 for al in alerts if al["kind"] == "official")
            if official_n:
                lines.append(f"{official_n} official IMD/CWC/SDMA alert{'s cover' if official_n != 1 else ' covers'} your area.")
            if base_run:
                worse = sum(1 for c in changes if c["worse"])
                better = len(changes) - worse
                lines.append(
                    f"Since {'you last looked' if since else 'the last update'}: {worse} got worse, {better} improved."
                    if changes
                    else f"Nothing has changed since {'you last looked' if since else 'the last update'}."
                )
        else:
            if counts["red"] + counts["orange"] + counts["yellow"] == 0:
                lines.append(f"सभी {n} निगरानी स्थान सामान्य (हरा) हैं।")
            else:
                parts = [f"{counts[t]} {w[t]}" for t in ("red", "orange", "yellow") if counts[t]]
                if counts["green"]:
                    parts.append(f"{counts['green']} सामान्य")
                lines.append(f"{label['hi']}: {n} में से {', '.join(parts)}।")
            if worst and worst["risk"]["tier"]["key"] != "green":
                lines.append(f"सर्वाधिक जोखिम: {_name(worst, 'hi')} ({worst['risk']['score']:.0f}/100, {w[worst['risk']['tier']['key']]})।")
            lines.append(
                f"अगले 3 दिनों में {len(coming)} स्थानों पर स्थिति बिगड़ने की आशंका।" if coming else "अगले 3 दिनों में किसी स्थान पर स्थिति बिगड़ने की आशंका नहीं।"
            )
            if wave_next:
                wv = wave_next[0]
                lines.append(f"{wv['river']} नदी की बाढ़ लहर लगभग {wv['eta_h']['p50']} घंटे में {wv['name_hi'] or wv['name']} पहुँच सकती है।")
            official_n = sum(1 for al in alerts if al["kind"] == "official")
            if official_n:
                lines.append(f"आपके क्षेत्र में {official_n} आधिकारिक IMD/CWC/SDMA चेतावनियाँ।")
            if base_run:
                worse = sum(1 for c in changes if c["worse"])
                ref = "पिछली बार से" if since else "पिछले अद्यतन से"
                lines.append(f"{ref}: {worse} बिगड़े, {len(changes) - worse} सुधरे।" if changes else f"{ref} कोई बदलाव नहीं।")
        brief[lang] = lines

    top = worst["risk"]["tier"]["key"] if worst else "green"
    return {
        "scope": auth.public(user) | {"label": label},
        "run_id": snapshot.run_id,
        "computed_at": snapshot.computed_at.isoformat(timespec="seconds"),
        "status": {
            "tier": top,
            "tier_en": TIER_WORD["en"][top],
            "tier_hi": TIER_WORD["hi"][top],
            "counts": counts,
            "places": n,
            "people_at_risk": sum(a["location"]["population"] or 0 for a in items if a["risk"]["tier"]["key"] in ("orange", "red")),
            "worst": _place_row(worst) if worst else None,
        },
        "alerts": alerts,
        "coming_next": {"places": coming[:12], "waves": wave_next[:8]},
        "changes": {"since": since, "compared_run": base_run, "items": changes[:20]},
        "brief": brief,
        "places": [_place_row(a) for a in items[:200]],
    }
