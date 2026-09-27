"""
HTML email for a notification event.

Email clients ignore stylesheets and most modern CSS, so this is the classic
email-safe shape: nested tables, inline styles, web-safe fonts, 600 px wide,
no images or scripts. Every value is HTML-escaped.
"""

from __future__ import annotations

from html import escape

from .config import APP_NAME

NAVY = "#0B2A5B"
SAFFRON = "#F26A1B"
INK = "#1F2937"
MUTED = "#6B7280"
LINE = "#E5E7EB"
LEVEL = {
    "red": ("#C1121F", "RED — TAKE ACTION NOW", "लाल — अभी कार्रवाई करें"),
    "orange": ("#E4701E", "ORANGE — BE PREPARED", "नारंगी — तैयार रहें"),
    "yellow": ("#B08600", "YELLOW — BE AWARE", "पीला — सतर्क रहें"),
    "green": ("#0B8A3D", "GREEN — ALL CLEAR", "हरा — सब सामान्य"),
}
EVENT_LABEL = {
    "alert": "Flood alert",
    "escalation": "Urgent flood alert",
    "alert_summary": "Flood alerts",
    "all_clear": "All clear",
    "daily_brief": "Daily flood brief",
    "test": "Test message",
    "deployment": "Deployment order",
}
FONT = "font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;"


def _p(text: str, style: str = "") -> str:
    return f'<p style="margin:0 0 10px;{FONT}font-size:15px;line-height:1.55;color:{INK};{style}">{escape(text)}</p>'


def _box(title: str, inner: str, accent: str, bg: str) -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 16px;">'
        f'<tr><td style="border-left:4px solid {accent};background:{bg};border-radius:6px;padding:12px 16px;">'
        f'<div style="{FONT}font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{accent};margin:0 0 6px;">{escape(title)}</div>'
        f"{inner}</td></tr></table>"
    )


def render(body: dict) -> str:
    event = body.get("event", "alert")
    level = body.get("level") or "yellow"
    colour, label_en, label_hi = LEVEL.get(level, LEVEL["yellow"])
    recipient = body.get("recipient") or {}
    area = recipient.get("district") or recipient.get("state") or "All India"
    if recipient.get("district") and recipient.get("state"):
        area = f"{recipient['district']}, {recipient['state']}"

    parts: list[str] = []

    if event in ("daily_brief", "test"):
        items = "".join(
            f'<tr><td valign="top" style="{FONT}font-size:14px;color:{SAFFRON};padding:0 8px 8px 0;">&#9679;</td>'
            f'<td style="{FONT}font-size:15px;line-height:1.5;color:{INK};padding:0 0 8px;">{escape(x)}</td></tr>'
            for x in body.get("brief") or []
        )
        if event == "test":
            parts.append(_p("This is a test. If you are reading it, JalDrishti alerts for your area will reach you here.", "font-weight:600;"))
        parts.append(_box("Today in your area", f'<table role="presentation" cellpadding="0" cellspacing="0">{items}</table>', NAVY, "#F3F6FB"))
        if body.get("alert_count"):
            parts.append(_p(f"{body['alert_count']} active alert(s) in your area — open JalDrishti for details."))
    elif event == "alert_summary":
        cards = ""
        for it in body.get("items") or []:
            c, lab, _ = LEVEL.get(it.get("level"), LEVEL["yellow"])
            avoid = ", ".join(it.get("routes_to_avoid") or [])
            cards += (
                f'<tr><td style="padding:0 0 10px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
                f'<tr><td style="border:1px solid {LINE};border-left:4px solid {c};border-radius:6px;padding:10px 14px;">'
                f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;background:{c};{FONT}font-size:10.5px;font-weight:800;color:#FFFFFF;">{escape(lab.split(" — ")[0])}</span>'
                f'<div style="{FONT}font-size:15px;font-weight:700;color:{NAVY};margin:6px 0 4px;">{escape(it.get("title") or "")}</div>'
                f'<div style="{FONT}font-size:13.5px;line-height:1.5;color:{INK};"><b>Do:</b> {escape(it.get("what_to_do") or "")}</div>'
                + (f'<div style="{FONT}font-size:13px;color:#A50F1A;margin-top:4px;">&#9940; Avoid: {escape(avoid)}</div>' if avoid else "")
                + "</td></tr></table></td></tr>"
            )
        parts.append(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 6px;">{cards}</table>')
        steps = "".join(
            f'<tr><td valign="top" style="{FONT}font-size:14px;color:{NAVY};padding:0 8px 6px 0;">&#8226;</td>'
            f'<td style="{FONT}font-size:14px;line-height:1.5;color:{INK};padding:0 0 6px;">{escape(s)}</td></tr>'
            for s in body.get("safety") or []
        )
        if steps:
            parts.append(_box("Stay safe — tell residents", f'<table role="presentation" cellpadding="0" cellspacing="0">{steps}</table>', NAVY, "#F3F6FB"))
    elif event == "all_clear":
        parts.append(_p(body.get("message") or body.get("title") or ""))
    else:
        if body.get("detail"):
            parts.append(_p(body["detail"]))
        if body.get("what_to_do"):
            parts.append(_box("What authorities should do", _p(body["what_to_do"], "margin:0;font-weight:600;"), colour, "#FFF7F2"))
        routes = body.get("routes_to_avoid") or []
        safety = [s for s in (body.get("safety") or []) if not s.startswith("Avoid these roads")]
        if routes or safety:
            chips = "".join(
                f'<span style="display:inline-block;margin:0 6px 6px 0;padding:4px 10px;border:1px solid #F3B4B8;border-radius:6px;'
                f'background:#FFFFFF;{FONT}font-size:13px;font-weight:600;color:#A50F1A;">&#9940; {escape(r)}</span>'
                for r in routes
            )
            steps = "".join(
                f'<tr><td valign="top" style="{FONT}font-size:14px;color:{NAVY};padding:0 8px 6px 0;">&#8226;</td>'
                f'<td style="{FONT}font-size:14px;line-height:1.5;color:{INK};padding:0 0 6px;">{escape(s)}</td></tr>'
                for s in safety
            )
            inner = ""
            if routes:
                inner += f'<div style="{FONT}font-size:13px;font-weight:700;color:{INK};margin:0 0 6px;">Avoid these roads:</div><div style="margin:0 0 8px;">{chips}</div>'
            inner += f'<table role="presentation" cellpadding="0" cellspacing="0">{steps}</table>'
            parts.append(_box("Stay safe — tell residents", inner, NAVY, "#F3F6FB"))
        if body.get("message_hi"):
            hi = escape(body["message_hi"]).replace("\n", "<br>")
            parts.append(
                f'<div style="{FONT}font-size:11px;font-weight:700;letter-spacing:.08em;color:{MUTED};margin:6px 0 6px;">हिंदी में</div>'
                f'<div style="font-family:Nirmala UI,Mangal,Arial,sans-serif;font-size:14px;line-height:1.6;color:{INK};margin:0 0 16px;">{hi}</div>'
            )

    if body.get("link"):
        parts.append(
            f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:4px 0 8px;"><tr>'
            f'<td style="background:{NAVY};border-radius:8px;"><a href="{escape(body["link"])}" '
            f'style="display:inline-block;padding:11px 20px;{FONT}font-size:14px;font-weight:700;color:#FFFFFF;text-decoration:none;">'
            f"Open in {APP_NAME} &rarr;</a></td></tr></table>"
        )

    counts = body.get("counts")
    if counts:
        badge = "".join(
            f'<span style="display:inline-block;margin:0 6px 6px 0;padding:5px 12px;border-radius:6px;background:{LEVEL[t][0]};'
            f'{FONT}font-size:12px;font-weight:800;letter-spacing:.04em;color:#FFFFFF;">{counts.get(t, 0)} {LEVEL[t][1].split(" — ")[0]}</span>'
            for t in ("red", "orange", "yellow", "green")
            if counts.get(t)
        )
    else:
        badge = (
            f'<span style="display:inline-block;padding:5px 12px;border-radius:6px;background:{colour};{FONT}font-size:12px;font-weight:800;letter-spacing:.06em;color:#FFFFFF;">{escape(label_en)}</span>'
            f'<span style="font-family:Nirmala UI,Mangal,Arial,sans-serif;font-size:12px;color:{MUTED};">&nbsp; {escape(label_hi)}</span>'
        )

    title = escape(body.get("title") or EVENT_LABEL.get(event, "Flood alert"))
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#EEF1F5;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#EEF1F5;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#FFFFFF;border-radius:12px;overflow:hidden;border:1px solid {LINE};">
  <tr><td style="background:{NAVY};padding:18px 24px;">
    <span style="font-family:Nirmala UI,Mangal,Arial,sans-serif;font-size:20px;font-weight:700;color:{SAFFRON};">जलदृष्टि</span>
    <span style="{FONT}font-size:20px;font-weight:800;color:#FFFFFF;">&nbsp;{APP_NAME}</span>
    <div style="{FONT}font-size:12px;color:#C7D2E3;margin-top:2px;">{escape(EVENT_LABEL.get(event, "Flood alert"))} · {escape(area)}</div>
  </td></tr>
  <tr><td style="height:4px;line-height:4px;font-size:0;background:linear-gradient(90deg,#FF9933 0 33%,#FFFFFF 33% 66%,#138808 66% 100%);background-color:{SAFFRON};">&nbsp;</td></tr>
  <tr><td style="padding:22px 24px 8px;">
    {badge}
    <h1 style="margin:14px 0 12px;{FONT}font-size:22px;line-height:1.3;color:{NAVY};">{title}</h1>
    {"".join(parts)}
  </td></tr>
  <tr><td style="padding:16px 24px 20px;border-top:1px solid {LINE};background:#FAFBFC;">
    <div style="{FONT}font-size:13px;color:{INK};margin:0 0 6px;"><b>Emergency:</b> 112 &nbsp;·&nbsp; <b>NDMA helpline:</b> 1078 &nbsp;·&nbsp; <b>State/District EOC:</b> 1070 / 1077</div>
    <div style="{FONT}font-size:11.5px;line-height:1.5;color:{MUTED};">{escape(body.get("disclaimer") or "")}</div>
  </td></tr>
</table>
<div style="{FONT}font-size:11px;color:{MUTED};margin-top:10px;">Sent automatically by {APP_NAME} to {escape(recipient.get("name") or recipient.get("email") or "you")} because you turned on alerts for {escape(area)}.</div>
</td></tr></table>
</body></html>"""
