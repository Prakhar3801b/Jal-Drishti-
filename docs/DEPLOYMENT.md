# Deploying JalDrishti

The **backend** (FastAPI) runs on **Render**. The **frontend** (React + Vite) runs on **Vercel**.

```
Browser ──► Vercel (static React app)
               │  VITE_API_BASE = https://<your-api>.onrender.com
               ▼
            Render, Singapore (FastAPI) ──► Open-Meteo, GloFAS, NDMA SACHET, OSM
               │  JALDRISHTI_CWC_RELAY = https://<your-app>.vercel.app/api/cwc
               ▼
            Vercel Function, Mumbai (frontend/api/cwc.js) ──► CWC flood portal
```

**Why the relay?** The CWC flood portal (ffs.india-water.gov.in) does not answer
requests from outside India. Render has no Indian region, so the API cannot read
river gauges directly. A small function in the frontend project runs on Vercel's
Mumbai region and forwards CWC reads:
- It only accepts calls that carry a shared secret token.
- It only reaches CWC data paths.
- It reads gauges in batches of 100, so a full sweep costs about 11 function calls.

Without the relay, the app still works, but river gauges stay empty and the backend logs `CWC portal unreachable`.

Deploy the backend first, because the frontend needs its URL.

---

## 0. Before you start

- The code must be on GitHub. This guide uses `Harshalacro/jaldhristi`.
- You need accounts on [render.com](https://render.com) and [vercel.com](https://vercel.com). Sign in to both with GitHub.
- Optional free API keys, listed in [`backend/.env.example`](../backend/.env.example):
  - `GEMINI_API_KEY` or `GROQ_API_KEY`: gives the AI Copilot and advisories a large language model. Without one they use built-in fallbacks.
  - `OPENWEATHER_API_KEY`: adds a second rainfall forecast for the consensus check.

  Never commit keys. You enter them in the Render dashboard.

---

## 1. Backend on Render

### Option A: Blueprint (recommended)

The repository includes [`render.yaml`](../render.yaml), so Render can read the settings from it.

1. Open the Render dashboard, then **New → Blueprint**.
2. Connect GitHub and pick the repository (the hackathon repo, `HackIndore-4-0/Python-X`), branch `main`.
3. Render shows one service, **jaldrishti-api**. It generates `JALDRISHTI_SECRET` and `JALDRISHTI_NOTIFY_SECRET` itself, and asks for the values marked `sync: false`:

   | Key | What to enter |
   |---|---|
   | `JALDRISHTI_SEED_PASSWORD` | A new password for the central/state/district admin accounts. Leave it empty and they keep the public default from the README |
   | `JALDRISHTI_NOTIFY_WEBHOOK` | The viaSocket flow's webhook URL (docs/NOTIFICATIONS.md) |
   | `JALDRISHTI_NOTIFY_RECIPIENTS` | Who gets alerts, as JSON. It is restored at every boot, since the free plan's database resets on each deploy: `[{"username":"central","email":"you@example.org","whatsapp":"+9198xxxxxxxx","channels":["email","whatsapp"]}]` |
   | `JALDRISHTI_CWC_RELAY`, `JALDRISHTI_CWC_RELAY_TOKEN` | Fill in after step 2b |
   | `GEMINI_API_KEY`, `GROQ_API_KEY`, `ANTHROPIC_API_KEY`, `OPENWEATHER_API_KEY` | The keys you have; leave the others empty. A free Gemini key turns on the full AI Copilot |
4. Click **Apply**. The first build takes about 3–5 minutes.
5. When the service shows **Live**, copy its URL, for example `https://jaldrishti-api-7t3r.onrender.com` (Render adds a suffix when the name is taken).

### Option B: Manual web service

1. **New → Web Service**, then connect the repository.
2. Fill in these settings:

   | Field | Value |
   |---|---|
   | Root Directory | `backend` |
   | Runtime | Python 3 |
   | Region | Singapore (closest to India) |
   | Build Command | `pip install --upgrade pip && pip install -r requirements.txt` |
   | Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"` |
   | Health Check Path | `/api/health` |
   | Instance Type | Free (or Starter) |

3. Under **Environment**, add:

   | Key | Value |
   |---|---|
   | `PYTHON_VERSION` | `3.12.8` |
   | `PYTHONUNBUFFERED` | `1` |
   | `JALDRISHTI_CORS` | `https://jaldrishti.vercel.app` (you will fix this in step 3) |
   | `JALDRISHTI_CORS_REGEX` | `https://jaldrishti(-[a-z0-9-]+)?\.vercel\.app` |
   | `JALDRISHTI_SECRET` | a long random string (keeps people signed in across restarts) |
   | `JALDRISHTI_PUBLIC_WEB_URL` | your Vercel URL |
   | `JALDRISHTI_SEED_PASSWORD`, `JALDRISHTI_NOTIFY_WEBHOOK`, `JALDRISHTI_NOTIFY_SECRET`, `JALDRISHTI_NOTIFY_RECIPIENTS` | as in Option A |
   | `GEMINI_API_KEY` etc. | optional |

4. Click **Create Web Service**.

### Check the backend

Open these in a browser. Replace the host with your own.

| URL | Expected |
|---|---|
| `https://<your-api>.onrender.com/api/health` | `{"ok": true, "locations": 112, ...}`. Right after boot, `ok` can be `false` for about 30–60 s while the first refresh runs. |
| `https://<your-api>.onrender.com/api/official/summary` | `stations_read_directly` in the hundreds, plus live `danger` and `warning` counts |
| `https://<your-api>.onrender.com/docs` | Interactive API documentation |

In **Logs** you should see these lines, in order:

1. `created 148 sign-in accounts` (first boot) and `restored N alert recipients`
2. `startup refresh ok: run N, 112 locations`
3. `keep-alive: pinging https://<your-api>.onrender.com/api/health every 10 min`
4. `travel matrix: 14336 road pairs from OSRM` (response-plan road times, about 30 s after boot)
5. `gauge sweep: 9xx gauges reporting`

---

## 2. Frontend on Vercel

1. Open the Vercel dashboard, then **Add New… → Project**. Import **jaldhristi** from GitHub.
2. Configure the project:

   | Field | Value |
   |---|---|
   | Project Name | `jaldrishti`. The domain becomes `jaldrishti.vercel.app`; if you pick another name, see step 3. |
   | Framework Preset | Vite |
   | **Root Directory** | `frontend` (click **Edit** and select the folder; this setting is required) |
   | Build Command | `npm run build` (from [`frontend/vercel.json`](../frontend/vercel.json)) |
   | Output Directory | `dist` |

3. Under **Environment Variables**, add:

   | Key | Value | Environments |
   |---|---|---|
   | `VITE_API_BASE` | `https://jaldrishti-api.onrender.com` (your Render URL, **no trailing slash**) | Production, Preview, Development |

4. Click **Deploy**. It takes about 1 minute. Vercel then gives you a URL such as `https://jaldrishti.vercel.app`.

> `VITE_API_BASE` is built into the JavaScript bundle. If you change it later, **redeploy**: go to Deployments, open the ⋯ menu and choose Redeploy. Saving the variable alone does not update the site.

---

## 2b. Turn on the CWC relay

1. Make a random token of at least 16 characters, e.g. run
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. **Vercel** → your project → **Settings → Environment Variables** → add:

   | Key | Value | Environments |
   |---|---|---|
   | `CWC_RELAY_TOKEN` | the token | Production, Preview |

   Then go to **Deployments → ⋯ → Redeploy**, so the function receives it.
3. Check that the function runs in Mumbai: **Settings → Functions → Function Region** should show **Mumbai, India (bom1)**. `vercel.json` sets it; if the dashboard shows another region, select Mumbai there and redeploy.
4. **Render** → jaldrishti-api → **Environment** → add:

   | Key | Value |
   |---|---|
   | `JALDRISHTI_CWC_RELAY` | `https://<your-app>.vercel.app/api/cwc` |
   | `JALDRISHTI_CWC_RELAY_TOKEN` | the same token |

   Click **Save and deploy**.
5. Verify:
   - Open `https://<your-app>.vercel.app/api/cwc`. It should answer `{"error":"unauthorised"}`, which means the function is deployed and locked.
   - About 1 minute after Render restarts, `https://<your-api>.onrender.com/api/official/summary` should show `stations_read_directly` in the hundreds.
   - Render **Logs** should show `gauge sweep: 9xx gauges reporting`.

---

## 3. Connect the two (CORS)

The backend only answers browsers loading the site from origins it knows.

1. In Render, open **jaldrishti-api → Environment**.
2. Set `JALDRISHTI_CORS` to your exact Vercel production URL(s), separated by commas and without trailing slashes:
   ```
   https://jaldrishti.vercel.app
   ```
   If you add a custom domain, add it here as well, e.g. `https://jaldrishti.vercel.app,https://jaldrishti.in`.
3. `JALDRISHTI_CORS_REGEX` also allows Vercel **preview** deployments. They are named `<project>-<hash>-<team>.vercel.app` or `<project>-git-<branch>-<team>.vercel.app`. If your project is not called `jaldrishti`, change the pattern to match, for example:
   ```
   https://myproject(-[a-z0-9-]+)?\.vercel\.app
   ```
4. **Save Changes**. Render restarts the service automatically.

### Final check

Open the Vercel URL. The masthead should show **LIVE · x min ago**, and the map should show town circles.

If the page stays on "Cannot reach the JalDrishti API":

1. Open the browser's DevTools and look at the Console.
   - A **CORS** error means step 3 is wrong. The origin must match exactly: `https`, no trailing slash.
   - `ERR_NAME_NOT_RESOLVED` or 404 on `/api/...` means `VITE_API_BASE` is wrong, or you did not redeploy after setting it.
2. The free Render instance **sleeps after 15 minutes idle** unless it is kept awake (see "Keep the backend awake" below). A sleeping instance takes 30–60 s to wake on the first request. The app shows "warming up" and retries on its own.

---

## 4. Keep the backend awake

Render's free plan stops an instance after 15 minutes with no inbound traffic, and
that stops JalDrishti's background work too: the 15-minute gauge sweep, the
90-minute refresh, re-planning and automatic alerts. Two layers keep it running:

1. **Built in, nothing to set up.** The backend requests its own public URL
   (`RENDER_EXTERNAL_URL`, set by Render) at `/api/health` every 10 minutes. The
   request comes in through Render's proxy, so it counts as traffic. To point it
   elsewhere, set `JALDRISHTI_KEEPALIVE_URL`.
2. **External backup (recommended).** The self-ping cannot wake an instance that is
   already asleep, for example if Render restarted it and it went idle before the
   first ping. Add one outside pinger on `https://<your-api>.onrender.com/api/health`
   every 5–10 minutes. Either of these works:
   - **viaSocket** (the sponsor): a new flow with a **Schedule** trigger every 10
     minutes and one **HTTP Request** step, `GET` on that URL.
   - **UptimeRobot** (free): add an HTTP(s) monitor with a 5-minute interval. It
     also emails you if the API goes down.

Check it: the Render **Events** tab should show no "Instance spun down" after the
first deploy, and `/api/health` should answer in well under a second at any time.

## 5. Know the free-tier limits

| Topic | What happens | What to do |
|---|---|---|
| Sleep on idle (Render Free) | Without traffic for 15 min the instance stops: no gauge sweep, refresh, re-planning or alerts until the next visit | Handled: the backend pings itself every 10 min. Add an external monitor as a backup (below), or upgrade to Starter ($7/mo) |
| No persistent disk (Render Free) | The SQLite store and caches reset on each deploy or restart. The 30-year river climatology is rebuilt in the background after boot, using the Open-Meteo quota, and the scores are still valid meanwhile. | On Starter or above, uncomment the `disk:` block in `render.yaml` and set `JALDRISHTI_DB=/var/data/jaldrishti.db` and `JALDRISHTI_CACHE_DIR=/var/data/cache` |
| 750 free instance hours a month (per workspace) | Keeping one service awake uses ~720–744 h, so it fits only if it is your only free service | Keep other free services off, or upgrade |
| 512 MB RAM | PyTorch does not fit, so the **Chronos AI river forecast** is off. The station view still shows the CWC observations and marks. | On a ≥2 GB instance, change the build command to `pip install -r requirements-ml.txt` |
| Vercel Hobby function usage | The relay makes about 11 calls per 15-minute sweep, plus one per station graph opened: roughly 1–2k calls a day, well inside the free allowance | Nothing to do |
| Shared outbound IPs | Open-Meteo or Overpass may occasionally return HTTP 429 | The backend backs off and keeps the previous snapshot; nothing to do |

---

## 6. Updating

- **Push to the deployed branch.** Render and Vercel both redeploy automatically.
- **Open a pull request.** Vercel builds a **preview** URL for it. Previews reach the API because of `JALDRISHTI_CORS_REGEX`.
- **Rotate an API key.** Change it in Render → Environment → Save. No code change is needed.

---

## 7. Local production test (optional)

This runs the same setup as the hosted one: the frontend calls the API across origins, with no Vite proxy.

```bash
# terminal 1: API
cd backend
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# terminal 2: production build pointed at that API
cd frontend
VITE_API_BASE=http://127.0.0.1:8000 npm run build      # PowerShell: $env:VITE_API_BASE="http://127.0.0.1:8000"; npm run build
npx vite preview --port 4173                            # http://localhost:4173
```

`localhost` on any port is always allowed by the backend's CORS setting.
