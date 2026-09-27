# Notifications: email, WhatsApp, SMS and calls via viaSocket

JalDrishti does not send messages itself. It posts one JSON **event** per message
to a webhook; a [viaSocket](https://viasocket.com) flow receives it and sends the
email, WhatsApp, SMS or voice call. Provider accounts, templates and DLT
registration stay in viaSocket, and the control room can change routing without
a deploy.

Every message states that it comes from a research prototype, not an official
warning. Send only to officials who opted in on the Notifications page — never
to the public.

## 1. Connect JalDrishti to viaSocket

1. In viaSocket, create a flow and choose **Webhook** as the trigger. Copy its URL.
2. In `backend/.env` set:

   ```
   JALDRISHTI_NOTIFY_WEBHOOK=<the webhook URL>
   JALDRISHTI_NOTIFY_SECRET=<any long random string>   # only for the WhatsApp bot
   JALDRISHTI_PUBLIC_WEB_URL=<dashboard URL>           # optional, for links
   ```

3. Restart the backend. Sign in, open **Notifications**, add your email /
   WhatsApp / phone, pick channels and a level, **Save**, then **Send a test
   message**. The test event appears in viaSocket's run history; use it as the
   sample payload while building the steps below.

## 2. What JalDrishti sends

`POST <webhook>` with `Content-Type: application/json`:

```json
{
  "event": "alert",                 // alert | escalation | all_clear | daily_brief | test
  "event_id": "…uuid…",
  "sent_at": "2026-09-27T14:40:00+05:30",
  "level": "orange",                // green | yellow | orange | red
  "kind": "place",                  // place | gauge | wave | official (alerts only)
  "place_id": "patna",
  "title": "Patna is at Orange",
  "title_hi": "पटना नारंगी स्तर पर",
  "detail": "Patna is at 64/100 — orange on the IMD four-colour scale. …",
  "what_to_do": "Pre-position SDRF teams and boats; ready relief shelters; issue public advisory.",
  "message": "Short text for WhatsApp / SMS / the call script",
  "message_hi": "वही संदेश हिंदी में",
  "sms": "JalDrishti: Patna flood risk Orange. Avoid East Boring Canal Road Underpass. Drink boiled water. Emergency 112/1078",
  "routes_to_avoid": ["East Boring Canal Road Underpass", "Ashok Rajpath", "Nehru Nagar"],
  "safety": ["Avoid these roads: …", "Do not walk or drive through flood water — …",
             "Drink only boiled or chlorinated water; …", "…", "Emergency: 112 · NDMA 1078."],
  "safety_hi": ["इन सड़कों से बचें: …", "…"],
  "advisory_title": "Flood risk advisory — Patna (Orange)",
  "advisory_body": "Full public advisory text …",
  "voice_call": false,              // true for Red (escalation) and for a test with calls on
  "channels": ["email", "whatsapp"],// what this recipient chose; "call" only when voice_call
  "link": "https://…/#/location/patna",
  "recipient": { "name": "…", "email": "…", "whatsapp": "+91…", "phone": "+91…",
                 "role": "state", "state": "Bihar", "district": null },
  "disclaimer": "JalDrishti research prototype — not an official warning. …",
  "source": "JalDrishti"
}
```

Events that include a call also carry `call_twiml` (escaped TwiML for Twilio's *Make call*).
Every event also carries `email_html`: the same content as a designed, email-safe
HTML page — use it as the email body. `daily_brief` and `test` also carry `brief` and `brief_hi` (lists of sentences)
and `alert_count`.

When they are sent: after every scoring run (every 90 minutes, sooner when a
river gauge changes level), each new alert JalDrishti issues for the recipient's
area goes to them **once** — the system decides what is alert-worthy; recipients
only choose channels. `message` already includes the safety steps ("Stay safe:"
list with roads to avoid, safe water, what to do); `safety` and
`routes_to_avoid` are there if a flow wants to format them itself. Roads come
from the city's street-level grid (most flood-prone named roads and underpasses). `escalation` = a Red alert. `all_clear`
= a place they were warned about is back to Green. `daily_brief` = once a day at
`JALDRISHTI_DAILY_BRIEF_HOUR` (IST, default 8).

## 3. Build the flow in viaSocket

After the Webhook trigger, add one branch per channel, each with a condition on
`channels`:

| Branch | Condition | Action (viaSocket app) | Fields |
|---|---|---|---|
| Email | `channels` contains `email` and `recipient.email` is set | Gmail / Outlook / SMTP — *Send email* | To: `recipient.email` · Subject: `title` · Body: `email_html` (a designed HTML email with the alert, what to do, roads to avoid, safety steps, Hindi text and helplines) |
| WhatsApp | `channels` contains `whatsapp` | Twilio (WhatsApp) or MSG91 WhatsApp — *Send message* | To: `recipient.whatsapp` · Text: `message` (or `message_hi`) + `disclaimer` |
| SMS | `channels` contains `sms` | MSG91 or Twilio — *Send SMS* | To: `recipient.phone` · Text: `sms` |
| Voice call | `voice_call` is true and `channels` contains `call` | Twilio or Exotel — *Make call* | To: `recipient.phone` · TwiML: `call_twiml` (ready-made: English, then Hindi, then the disclaimer, said twice) |
| Log | always | Google Sheets — *Add row* | `sent_at`, `event`, `level`, `title`, `recipient.name`, `channels` |
| Control-room chat | `event` is `escalation` | Slack / Teams / Telegram — *Send message* | `title` + `message` + `link` |

For the demo, the fastest channels are Gmail and Twilio's WhatsApp sandbox (no
template approval) and Twilio voice.

**India notes.** Commercial SMS needs sender-ID and template registration on the
TRAI DLT portal (MSG91 handles this; it takes days). WhatsApp messages the
system starts need pre-approved templates on the production API — the sandbox
does not. Keep every message marked as a prototype.

## 4. WhatsApp question bot (optional)

A second flow lets officials reply on WhatsApp:

1. Trigger: *incoming WhatsApp message* (Twilio / MSG91).
2. Action: **HTTP request** `POST <backend>/api/hooks/inbound`
   with header `X-JalDrishti-Secret: <JALDRISHTI_NOTIFY_SECRET>` and body
   `{"from": "<sender number>", "text": "<message text>"}`.
3. Action: send `reply` from the response back to the sender.

Replies, for numbers registered on the Notifications page only and about their
own area only:

| They send | JalDrishti replies |
|---|---|
| `status` (or `hi`, `help`) | the area's brief |
| `status patna` | that place's level and what to do (if it is in their area) |
| `ACK` | acknowledgement, logged in their delivery history |
| any question | an answer from the AI Copilot, limited to their area |

Unregistered numbers get a short "not registered" reply; a missing or wrong
secret is refused.
