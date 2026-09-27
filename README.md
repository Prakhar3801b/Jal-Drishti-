# JalDrishti · जलदृष्टि

**Hyperlocal Rainfall Early Warning & Inundation Prediction — a working prototype for India**

**Live demo: [hack-eosin-two.vercel.app](https://hack-eosin-two.vercel.app)**. Use
**Quick demo** on the sign-in page to enter as an official (central, state, district) or
a citizen, no password needed.

An AI/ML early-warning system that integrates **observational weather**, **numerical
weather prediction** rainfall forecasts, **satellite-derived terrain and hydrological
reanalysis**, and **official gauge observations and alerts** into one warning level per
place. It scores 112 locations covering all 36 states and union territories, maps
street-level inundation on an 800 m grid, states how long the warning holds (72 h town
trajectory, 48 h ponding timeline, hours-to-danger per river gauge), explains every
score in English and Hindi, communicates its own uncertainty, and can be back-tested
against real past floods.

> **This is a prototype for research and demonstration.** It is **not** an official
> Government of India service and **not** a public flood warning system. For
> operational warnings, follow IMD, the Central Water Commission, and your State
> Disaster Management Authority.

---

## Quick start

Two terminals. No API keys, no signups, no database server.

```bash
# 1 — backend
cd backend
pip install -r requirements.txt        # or requirements-ml.txt for AI river forecasts (PyTorch)
python -m uvicorn app.main:app --reload --port 8000

# 2 — frontend
cd frontend
npm install
npm run dev            # http://localhost:5173
```


**Optional ML bootstrap** (one-off, ~20 minutes, resumable):

```bash
python backend/scripts/bootstrap_ml.py   # builds climatology + trains the classifier
```

The backend scores all 112 locations within about ten seconds of booting, then
builds a 30-year river climatology in the background and re-scores with proper
seasonal context. The dashboard is usable immediately and gets sharper a couple of
minutes later; the confidence badge tells you which state it is in.


### Signing in

Every user sees one area. The sign-in screen has two doors: **Official (admin)** for
control rooms and **Citizen** for residents. **Quick demo** enters any role in one
click; officials' accounts are created on first boot, and citizens create their own.

| Role | Kind | Sees | Username | Example |
|---|---|---|---|---|
| Central | Admin | All of India | `central` | `central` |
| State | Admin | One state | the state name, lower-case with hyphens | `bihar`, `uttar-pradesh` |
| District | Admin | One district | `state.district` | `bihar.patna` |
| Citizen | Public | Their home district | the email or mobile number they registered | `9876543210` |

Admins get the control-room tools: My area with ready-to-send advisories, Notifications,
the risk map, State monitor, Time machine, what-if simulator, advisory generator and
event replay. Citizens get **My locality** (their district's level, what to do, roads to
avoid, the next 3 days, warnings and helplines), the street map, rivers and official
alerts. The server enforces this: officials-only endpoints return 403 for a citizen.

All seeded admin accounts use the password `jaldrishti@2026`. Set `JALDRISHTI_SEED_PASSWORD`
before first boot to change it, `JALDRISHTI_DEMO_LOGIN=0` to turn off one-click demo
sign-in, and `JALDRISHTI_SECRET` to fix the token signing key across restarts of a
multi-instance deployment.

After sign-in each user lands on **My area**: the area's status, automatic alerts
with ready-to-send advisories and SMS text, what is coming next, a daily brief and
what changed since the last visit. The detailed screens sit under **Advanced tools**,
filtered to the user's area.

Scope is enforced by the server on every data endpoint: places, the risk map,
street-level grids, river gauges, official alerts, rivers, the flood-event
register and time-machine presets all answer for the signed-in area only, and a
place outside it returns 403. Gauges and official alerts carry no district, so a
district sees those within 40 km of its town (or naming it). A river is shown to
a state or district if one of its gauges is in the area, with its whole
upstream-to-downstream profile, since upstream water is what arrives next. The
CAP 1.2 feed and the health check stay public.

**Deploying** (backend on Render, frontend on Vercel): see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## What it does

### Three screens, matching how flood response is actually organised

The drill-down mirrors the national → state → district → station structure that
CWC and NDMA use, so the navigation is familiar to anyone who has used
FloodWatch India or a state EOC dashboard.

| Screen | What you see |
|---|---|
| **National** | India choropleth coloured by state risk, alert counts, a scrolling advisory ticker, roll-ups by state and by CWC river basin, and a ranked national watchlist |
| **State** | The state's district boundaries with monitored locations sized by population, and a sortable list |
| **Hyperlocal** | Risk dial, confidence badge, factor breakdown, 72-hour trajectory with an uncertainty band, river discharge against its seasonal normal, plain-language explanation, NDMA response actions, observed data with provenance, past flood events, and event replay |

### The four things the problem statement asks for

**It adapts rather than replaying a fixed scenario.** Ingestion runs on a timer
(90 minutes by default) and the risk engine recomputes from scratch each pass. The
masthead shows the age of the data on screen. Pressing **Refresh now** triggers a
live re-ingestion and then shows a panel listing exactly which locations moved and
by how much — that panel is the proof the numbers are not hardcoded.

**It estimates how risk evolves.** Each location gets a 24/48/72-hour trajectory,
re-scored against forecast rainfall and forecast discharge rather than
extrapolated from the current value.

**It communicates confidence.** The GloFAS ensemble's interquartile spread, the
forecast lead time and input completeness combine into a High/Medium/Low badge
with its reasons written out. The trajectory chart's shaded band is the p25–p75
ensemble members re-scored, so a wide band on screen is literally the forecast
models disagreeing about that river.

**It explains the factors.** Ten named features, each normalised against a
published threshold, each with its weight and its actual point contribution shown.
The narrative sentence is generated from the same top contributions that drive the
bars, so the prose and the chart can never disagree.

### AI / ML features

| Feature | Method | Needs |
|---|---|---|
| **AI Copilot** — ask "Where is it worst?", "असम की स्थिति क्या है?", "Why is Patna Orange?" | LLM grounded in a table of the live snapshot; told never to introduce numbers not in it. Offline rule-based answerer when no key is set | Optional Gemini / Groq (free) or Claude key |
| **Public advisory generator** — bilingual advisory + 160-char SMS with real helplines (112, 1078) | LLM with a strict output format, falling back to a template filled from the same data | Optional LLM key |
| **What-if simulator** — cloudburst, dam release, cyclone presets or sliders | Perturbs the *real* hourly rain and daily discharge series and re-runs the full engine + ML | Nothing |
| **Historical analog search** — "today most resembles Silchar, 2022-06-20" | Weighted k-nearest-neighbours over ~2,500 real scored location-days; the flood share among the nearest 15 is an independent probability | ML bootstrap |
| **Anomaly detection** — flags rare *combinations* no single threshold catches | Isolation Forest fitted on non-flood days (z-score fallback) | ML bootstrap for the forest |
| **Calibrated classifier + attribution** | Logistic regression on date-matched samples; exact per-feature log-odds shown | ML bootstrap |
| **Multi-model forecast consensus** | Compares Open-Meteo's next-24 h rain with an independent OpenWeatherMap forecast; conflict lowers confidence with a written reason | Optional OpenWeatherMap key (free) |
| **"Where the models disagree"** | Ranks locations where the k-NN probability and the rule score diverge most | ML bootstrap |

### Beyond the brief

- **Event replay** — re-run the model on any past date since 1994 and compare its
  verdict with the historical register. This is the most convincing part of a
  demo because it does not depend on rain falling during your presentation.
- **Bilingual throughout** — English and Hindi, written rather than
  machine-translated, including the risk narratives and NDMA action text.
- **Back-testing** — `scripts/backtest.py` scores every event in the register and
  reports hit rate *against the same-day false-alarm rate*, which is the only
  honest way to report it.
- **River-channel snapping** — see below; it is the single biggest correctness win
  in the project.
- **Source health panel** — per-source status and latency, so a degraded feed is
  visible rather than silently changing the numbers.

---

## Response planning (Challenge 2)

**Response plan** (officials only) allocates rescue teams, boats, dewatering pumps and
barricade sets across every place at risk, and re-solves on its own whenever a new
scoring run lands, stock changes, or units are dispatched or released
(`app/planning.py`, `app/resources.py`, `app/travel.py`).

**How a plan is made.** A mixed-integer program (SciPy / HiGHS) maximises expected
people reached, and it can never allocate more than a depot has available:

| Input | Where it comes from |
|---|---|
| Current severity | The live score, including the official gauge floor |
| Future risk | The worst point on the 72 h trajectory, or a flood wave from an upstream gauge above danger at its arrival time |
| Chance of flooding | The observed flood rate per IMD band in the back-test: Green 0.05%, Yellow 2.6%, Orange 11%, Red 34% |
| Population / exposure | Census population; people in the flood area = 5% + 25% × score/100 |
| Asset impact | In the 22 cities with a street grid: hospitals and schools in flood-prone 800 m cells (OpenStreetMap) count as 1,000 and 300 people-equivalents; each needs a pump, and each flood-prone underpass needs 2 barricade sets |
| Travel time | Real road drive times from OSRM (OpenStreetMap), 14,336 depot-place pairs, cached a week; straight-line estimate as fallback, flagged |
| Timing | A unit counts in full only if it arrives before the peak (within 12 h for a flood already under way); roads into Red areas are 1.5× slower |
| Diminishing returns | Each place's need is split into thirds worth 100 / 70 / 40% per unit, so scarce units spread across places |

**Resources.** The 16 NDRF battalion bases and their 18 teams each are public figures.
SDRF, boat, pump and barricade counts are **demo values**, marked as such: India's
inventory (IDRN) is open to officials only. Officials enter real counts on the
**Resources** page, and the plan re-optimises. SDRF and district stock stays in its
state. The island UTs are flagged as needing sea or air lift rather than trusting
ferry routing.

**Explainable.** Every order says why this place (score now → peak, people, chance of
flooding) and why this depot (drive time + mobilisation vs the expected peak). The
plan also shows what changed since the last plan and why, which places are still
short and why, and where one more unit helps most (LP shadow prices).

**Street level.** For a city with a street grid, **Street-level deployment** takes the
pumps and barricades the national plan gives it and places them on 800 m cells
(`app/city_plan.py`):
- **Pumps** go where the ensemble expects flooding and hospitals or schools stand.
- **Barricades** close flood-prone underpasses first, then named roads.
- **Timing:** each placement says whether it arrives before the water.

In Lucknow on 27 Sep 2026, 19 pumps covered 11 of the 13 flood-prone hospitals,
against 4 for the same number of pumps placed by terrain alone.

**Deployment orders.** Dispatching units sends a `deployment` event through the
viaSocket webhook to every opted-in official whose area covers the destination. It
lists the units, their depot and arrival time, and asks for an ACK.

**Better than severity-only.** The baseline ranks places by current score and fills
each from its nearest depots, using the same stock and scored on the same yardstick.
On the live data of 27 Sep 2026 the plan reaches ~11% more people (expected) with
rescue teams and boats, and gets 1,103 units on site before the peak against 815.
The back-test `python backend/scripts/backtest_planning.py` replays 67 real flood
dates with the same national stock:

| On 70 real flood place-days | Severity-only | JalDrishti |
|---|---|---|
| Flooded places reached in time | 59 | **64** |
| Flooded places reached at all | 63 | **66** |
| People reached in places that flooded | 4.30 M | 4.28 M (−0.5%) |

The planner reaches more of the places that really flooded, and on time, while total
people reached is on par. Timing in the back-test is approximate, and the register
does not record rescue counts.

## Official Government of India data

| Source | What is used | Access |
|---|---|---|
| **Central Water Commission** — Flood Forecasting portal ([ffs.india-water.gov.in](https://ffs.india-water.gov.in)) | 1,036 gauges with published warning level, danger level and highest flood level; hourly water level per gauge; coordinates | Unauthenticated JSON used by the portal's own web app. Endpoints and query format were read from its JavaScript bundle — **not a documented public API**, can change without notice |
| **NDMA SACHET** — Common Alerting Protocol ([sachet.ndma.gov.in](https://sachet.ndma.gov.in)) | Active alerts issued by IMD regional centres, CWC and State Disaster Management Authorities, with centroid, area, colour and message | Public JSON feed |
| **IMD** district warning / nowcast APIs | — | **Not used**: they answer "IP needs to be whitelisted" (access is on request). IMD warnings arrive via SACHET instead |

**How it is used.** Every refresh reads the latest hourly level of the CWC gauge
nearest each town (within 35 km), then every catalogued gauge in the background
(~1 minute). Gauge status is derived from those readings against the station's own
warning and danger marks — the portal's summary endpoint periodically returns an
empty list, so it is only a fallback.

Official observations set a **floor** under the modelled score: a gauge above danger
means Red (higher the further above), above warning means Orange, and an official
red/orange/yellow flood-related alert covering the town sets the matching floor. The
detail panel always shows both numbers — *"raised by official data from the model's 11"*
— so the model is never passed off as an observation.

**Hugging Face — river-level forecasting.** Each gauge's hydrograph can be
forecast 48 h ahead with [`amazon/chronos-bolt-small`](https://huggingface.co/amazon/chronos-bolt-small),
a pretrained time-series model run locally on CPU (~0.25 s per forecast, zero-shot, with
p10/p50/p90 bands), giving *time to cross / fall below the danger mark*. It
extrapolates the level's own shape and knows nothing of upstream rain or dam
releases, and the UI says so.

### Pages

**Live Dashboard** (map, national/state rails, hyperlocal detail) · **Official Alerts &
Gauges** (every gauge above warning/danger with its marks and record level, plus the
SACHET alert feed) · **State Monitor** (all 36 states/UTs, model score beside official
gauge counts) · **Time Machine** (replay the whole country on any date since 1994).

### Model calibration (fixed after back-testing)

The first scoring model averaged ten features, which diluted a river in record spate
with dry-weather features beside it. Back-tested on 70 real flood days
(`scripts/evaluate_cached.py`, no network needed) it reached Red on **0%** of them.
The score is now the worse of the weighted evidence and a *dominant-hazard* term
(riverine or pluvial, scaled by terrain susceptibility):

| On 70 real flood days | Before | After |
|---|---|---|
| Reached Orange or Red | 64% | **79%** |
| Reached Red | 4% | **37%** |
| Same-day non-flood towns at Orange+ | 5% | 11% |
| Same-day non-flood towns at Red | 0% | 1.9% |
| ROC AUC | 0.934 | 0.926 |

The "false alarm" rows are upper bounds: many of those towns sat under the same
monsoon system and simply are not in the hand-compiled register.

---

## Data sources

Everything runs on Tier-1 free, keyless APIs, so the project has no
approval-waitlist risk.

The four input families the system integrates:

| Family | In this project |
|---|---|
| Observational weather | Open-Meteo hourly rainfall and soil moisture on a ~5 km analysis grid |
| Numerical weather prediction | Open-Meteo forecast API (ICON / GFS) rainfall out to 7 days — the forward-looking input |
| Satellite-derived and reanalysis | GloFAS v4 discharge (Copernicus EMS, satellite-informed) and Copernicus DEM GLO-90 (TanDEM-X) terrain |
| Official observations and warnings | CWC gauge levels against warning and danger marks; NDMA SACHET CAP alerts from IMD, CWC and State DMAs |

**Radar.** Live Doppler radar is *not* ingested: IMD and ISRO publish no open radar
API. The prototype proves the same pipeline on open satellite-informed data (GloFAS
reanalysis and forecast) plus NWP rainfall; radar nowcasting is the production upgrade
once data sharing is arranged.

| Source | Gives | Licence |
|---|---|---|
| [Open-Meteo Weather](https://open-meteo.com/en/docs) | Hourly observed and forecast rainfall, soil moisture, ~5 km | CC BY 4.0, no key |
| [Open-Meteo Flood (GloFAS v4)](https://open-meteo.com/en/docs/flood-api) | River discharge m³/s, 30-member ensemble, 1984–present + forecast | CC BY 4.0, no key |
| [Copernicus DEM GLO-90](https://dataspace.copernicus.eu/) | Elevation, and slope derived from it | Free and open (ESA) |
| [OpenStreetMap / Overpass](https://www.openstreetmap.org/copyright) | Drainage density, distance to rivers and water bodies | ODbL 1.0 |
| IMD | The rainfall class boundaries and the four-colour warning scale the app scores against | Published protocol |
| CWC | Basin definitions and the station-based drill-down this UI mirrors | Portal only, no public API |
| NDMA | The response-action tier each alert level maps to | Published guidance |

**On the Indian government sources.** IMD, CWC, India-WRIS and NDMA do not expose
free public REST APIs. Rather than scrape them, this project uses them the way
they are actually usable: IMD's rainfall categories and colour convention are the
classification standard the scoring curve bends around, CWC's basin structure
drives the drill-down and the basin roll-up, and NDMA's tiering supplies the
recommended actions. Live numbers come from Open-Meteo and GloFAS. Every figure
on screen carries its source.

### What is real vs. what was hand-compiled

Being precise about this matters more than it looks:

- **Derived from real data, by script** — elevation, slope, drainage density,
  distance to water, water-body fraction and the GloFAS channel coordinate are all
  produced by `scripts/enrich_locations.py` from the DEM and OpenStreetMap. None of
  them is a hand-written plausible-looking number.
- **Hand-compiled** — `app/data/historical_floods.json` is a register of 58 real,
  dated flood events assembled by hand from CWC/NDMA situation reports, IMD monthly
  summaries and contemporaneous news archives. It is honest but it is *not* an
  official government extract, and events whose exact peak day is uncertain are
  marked `date_precision: "month"`. It is used for the historical-frequency
  feature, for back-testing, and for replay presets.
- **Reference data** — city coordinates from public gazetteers, populations from
  Census of India 2011, boundaries from the 2011 Census district shapefiles via
  [udit-001/india-maps-data](https://github.com/udit-001/india-maps-data).

---

## API keys

All optional; put them in `backend/.env` (never committed). `/api/ai/status` and the
**AI & API keys** tab in the app show which are active.

| Variable | Service | Cost | Enables |
|---|---|---|---|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) | Free tier, no card | Copilot + advisories |
| `GROQ_API_KEY` | [Groq](https://console.groq.com/keys) | Free tier, no card | Copilot + advisories |
| `ANTHROPIC_API_KEY` | [Anthropic](https://console.anthropic.com/) | Paid | Copilot + advisories via Claude Opus 5 (official SDK, server-side refusal fallback, cached system prompt) |
| `OPENWEATHER_API_KEY` | [OpenWeatherMap](https://home.openweathermap.org/api_keys) | Free, 1,000 calls/day | Second rainfall forecast for consensus |

With several LLM keys set they are tried in order (Claude, Gemini, Groq — override with
`JALDRISHTI_LLM_PROVIDER`) and each failure falls through to the next, ending at the
offline answerer.

---

## The risk model

A hybrid: a weighted rule score that carries the majority of the decision, blended
with a logistic classifier that calibrates it.

That split is deliberate. A single deep model would score the "explain the
factors" requirement badly. An unvalidated rule set would score "data-backed"
badly. So the rules stay legible and defensible, and the trained model pulls them
toward what actually happened in past events.

### Features and weights

| Feature | Weight | Normalised against |
|---|---|---|
| Rainfall, last 24 h | 0.16 | IMD 24-hour rainfall class boundaries |
| Forecast rain, next 24 h | 0.14 | same IMD boundaries |
| River level vs. seasonal normal | 0.15 | this location's own 1994–2024 GloFAS percentiles for this day-of-year |
| Terrain & drainage | 0.10 | DEM elevation/slope + OSM drainage density and river proximity |
| Rainfall, last 72 h | 0.09 | multi-day accumulation thresholds |
| River discharge multiple | 0.09 | ratio to the seasonal median |
| River rising/falling | 0.08 | rate of change as a fraction of the median per day |
| Soil already saturated | 0.07 | volumetric water content, top ~27 cm |
| Forecast rain, next 72 h | 0.07 | multi-day accumulation thresholds |
| Historical flood frequency | 0.05 | severity- and recency-weighted event count |

Normalisation is piecewise-linear between **published threshold knots**, not
against an arbitrary maximum. The curve bends exactly where IMD's rainfall classes
change, so a rainfall sub-score of 68 means "at the top of IMD's *very heavy*
band" rather than "0.68 of something".

### Percentiles, not just ratios

Asking "is this river high?" needs a reference. The engine fetches the full
1994–2024 GloFAS reanalysis for each location once, groups it by day-of-year with
a ±10-day window, and caches the percentiles. That is what lets the app say *"the
river is at the 97th percentile for this time of year"* — a statement a district
officer can act on — instead of a bare cumecs figure.

### River-channel snapping

Querying GloFAS at a town's centroid frequently lands on a hillslope cell. Patna's
centroid reads about **10 m³/s**; the Ganga beside it carries **~45,000 m³/s**.
Scored naively, the most flood-exposed cities in India look dry.

So `scripts/enrich_locations.py` probes a 5×5 grid of GloFAS cells around each
town and keeps the one with the largest long-run mean discharge — the main
channel. The resulting values are physically sensible: Brahmaputra at Guwahati
~18,000 m³/s, at Dhubri ~22,000 m³/s, Godavari at Rajahmundry ~6,300 m³/s, and
Mumbai's Mithi ~20 m³/s, which is correct for a small urban river.

The snapped coordinate is recorded with the climatology it produced. If a location
is ever re-snapped, the stale baseline is **discarded rather than reused** — the
first version of this code compared a hillside's 30-year history against a main
channel's present-day flow and cheerfully reported "3943× the seasonal median".

### Alert tiers and confidence

Scores map to IMD's operational four-colour scale (Green &lt;25, Yellow 25–50,
Orange 50–75, Red ≥75), and each tier carries an NDMA-aligned action block.

Confidence is reported separately from risk, because they are different questions.
It starts at 1.0 and is reduced by: a wide GloFAS ensemble (IQR/median above 15%),
a missing or short climatological baseline, unavailable discharge, and missing
rainfall or soil inputs. Every deduction appears in the UI as a written reason.

### Hazard and exposure are kept apart

The score is a **hazard** score. Population is carried separately as exposure and
as a marker-size channel on the map. A Red alert over Mumbai and a Red alert over
Kalpetta are the same hazard and very different problems; conflating them into one
number would hide exactly that.

### State roll-up uses the maximum, not the mean

A state with one district at Red and nine at Green is a state with an emergency.
Averaging would erase the signal the map exists to show, so the choropleth uses the
worst location in each state and reports the mean alongside it. States with no
monitored location are drawn as *absent data* — hatched, never green.

---

## Training and validation

```bash
# Fit the logistic classifier against the historical register
python backend/scripts/train_model.py

# Back-test the score over every dated event
python backend/scripts/backtest.py
python backend/scripts/backtest.py --limit 10 --csv results.csv
```

**The sampling design is the substance here.** The naive dataset — positives on
flood dates, negatives on random dates — produces a model that learns "it is the
monsoon" and posts an impressive AUC while being useless, because every Indian city
is wet in July.

So negatives are drawn from **the same calendar dates as the positives**. On each
date in the register, every monitored location is scored: the one that actually
flooded is the positive and the others, which saw the same season and often the
same weather system, are negatives. Locations with a recorded event within ±7 days
are excluded rather than labelled negative, because the register is not exhaustive.

That forces the model to learn what distinguished Silchar on 2022-06-20 from
Lucknow on 2022-06-20 — which is the question the dashboard is actually asking.

Coefficients are written to `app/data/risk_model.json` as readable JSON rather
than a pickle, so a reviewer can see exactly what the model weights. If that file
is absent the engine runs on rules alone and says so in the UI.

`backtest.py` reports hit rate **next to the same-day false-alarm rate** on the
control locations. A model returning 100 for everything catches every flood; the
two columns together are what make the number mean something.

---

## Architecture

```
Open-Meteo Weather ─┐
Open-Meteo Flood ───┼─→ ingestion ─→ features ─→ risk engine ─→ FastAPI ─→ React
Copernicus DEM ─────┤    (2 calls)     (10 named   (rules +       (JSON)    (Leaflet
OpenStreetMap ──────┘   every 90 min    features)   logistic)               + Recharts)
Historical register ┘                       │
                                            ├─ tier (IMD 4-colour)
                                            ├─ confidence (ensemble spread)
                                            ├─ trajectory (+24/48/72 h, p25–p75 band)
                                            └─ explanation (EN + HI)

SQLite ← runs, per-location assessments, observations, 30-year climatology, source health
```

A full refresh costs **two HTTP requests**, not eighty: Open-Meteo accepts many
coordinates per call and returns an array. The free tier bills per coordinate
against per-minute and per-hour budgets, so the clients batch, pace themselves, and
back off on 429.

### Layout

```
backend/
  app/
    main.py        FastAPI app, lifespan, asyncio refresh loop
    config.py      IMD thresholds, model weights, alert tiers, citations
    sources.py     Open-Meteo + GloFAS + archive clients, batched and paced
    features.py    raw series → named, interpretable features
    risk.py        normalisation, scoring, confidence, projection
    explain.py     bilingual plain-language narrative + NDMA actions
    engine.py      orchestration, snapshots, state roll-up, replay, what-if
    ml.py          k-NN analogs, Isolation Forest anomalies, model attribution
    llm.py         Claude (SDK) / Gemini / Groq provider chain
    copilot.py     grounded Q&A, offline answerer, advisory generator
    consensus.py   OpenWeatherMap second-forecast agreement
    api.py         REST endpoints
    store.py       SQLite persistence and migrations
    data/          locations, enriched locations, historical register, model
  scripts/
    enrich_locations.py   DEM + OSM + GloFAS-snap enrichment (run once)
    train_model.py        fit the logistic classifier
    backtest.py           validate against the historical register
frontend/
  src/
    App.jsx               shell, view state, polling, refresh
    components/           map, panels, charts, gauge, chrome, replay
    lib/                  api client, formatting, bilingual strings
  public/geo/             India state and district GeoJSON
```

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/country/summary` | National roll-up for the choropleth |
| GET | `/api/locations` | All monitored locations with current scores |
| GET | `/api/state/{state}/locations` | State drill-down |
| GET | `/api/location/{id}/detail` | Full hyperlocal assessment |
| GET | `/api/location/{id}/timeline` | 72-hour trajectory + river series |
| GET | `/api/location/{id}/replay?target=YYYY-MM-DD` | Score a past date |
| GET | `/api/events` | The historical flood register |
| GET | `/api/system` | Model card, feature weights, source health, run log |
| POST | `/api/refresh` | Re-ingest and re-score now, with a change report |
| POST | `/api/copilot` | Grounded Q&A over the live snapshot |
| POST | `/api/location/{id}/advisory` | Bilingual advisory + SMS |
| POST | `/api/location/{id}/simulate` | What-if scenario on live inputs |
| GET | `/api/insights` | Anomalies, analog ranking, model disagreements |
| GET | `/api/ai/status` | Active keys, LLM provider and ML models |
| GET | `/api/official/summary` | CWC gauge and SACHET alert counts |
| GET | `/api/official/stations` | Gauges with danger marks and live status |
| GET | `/api/official/alerts` | Active SACHET CAP alerts |
| GET | `/api/official/station/{code}` | Hydrograph + CWC forecast + Chronos AI forecast |
| GET | `/api/*?date=YYYY-MM-DD` | Time Machine: any read endpoint on a past date |

---

## Design notes

**Why it looks the way it does.** The visual language follows Indian public-service
portals on purpose — white surfaces, a navy utility strip with A-/A/A+ text sizing and
a skip link (GIGW accessibility conventions), the tricolour rule, a saffron advisory
band, a navy footer, the Ashoka Chakra, Devanagari and Latin paired throughout, IMD's
four-colour scale, and lakh/crore number formatting.

What it deliberately does **not** do is borrow anyone's identity. There is no State
Emblem of India (its use is restricted by the State Emblem of India Act, 2005), no
ministry name and no departmental logo. A "Prototype" badge sits in the masthead
and the disclaimer is in the footer on every screen. The design should read as
*built for Indian emergency response*, never as *issued by the Government of
India*.

The identity palette (saffron, India green, chakra navy) and the semantic palette
(IMD Green/Yellow/Orange/Red) are kept strictly separate in
`tailwind.config.js`. If something is orange in this app, it means IMD Orange —
"be prepared" — and never decoration. That separation is what stops a
saffron-heavy government aesthetic from accidentally reading as a nationwide flood
warning.

**Keyboard:** `/` focuses search, arrows and Enter select, `Escape` steps back up
the drill-down.

---

## Configuration

Environment variables, all optional:

| Variable | Default | Meaning |
|---|---|---|
| `JALDRISHTI_REFRESH_MINUTES` | `90` | Scheduled re-ingestion interval |
| `JALDRISHTI_REFRESH_ON_STARTUP` | `1` | Score immediately on boot |
| `JALDRISHTI_DB` | `backend/jaldrishti.db` | SQLite path |
| `JALDRISHTI_ML_WEIGHT` | `0.35` | Blend weight for the trained model |
| `JALDRISHTI_CLIMO_START` / `_END` | `1994` / `2024` | Climatology period |
| `JALDRISHTI_CORS` | localhost:5173, :4173 | Allowed origins, comma separated |
| `JALDRISHTI_CORS_REGEX` | *(none)* | Extra origin pattern, e.g. Vercel previews (localhost is always allowed) |
| `JALDRISHTI_CACHE_DIR` | `backend/.cache` | Archive and hotspot caches; point at a persistent disk in production |
| `JALDRISHTI_CWC_RELAY` / `_TOKEN` | *(direct)* | Route CWC requests through `frontend/api/cwc.js` on Vercel Mumbai when the API runs outside India |
| `VITE_API_BASE` | *(proxy)* | Frontend build-time API URL, e.g. `https://jaldrishti-api.onrender.com` |

## Known limits

- **Open-Meteo free-tier quotas** are per-coordinate and enforced per minute *and
  per hour*. Building the 30-year climatology for 112 locations can exhaust the
  hourly budget; the engine falls back to a short recent-window baseline, drops the
  confidence badge, and states the reason. `ensure_climatology()` fills the gaps on
  the next boot.
- **GloFAS is a model, not a gauge.** It simulates discharge at ~5 km; it is not a
  CWC station reading. Snapping puts it on the right channel but it remains a
  reanalysis product.
- **112 locations, not every settlement.** The location set covers all 36 states and
  UTs and is chosen for basin and coastal diversity; extending it is a matter of
  adding rows to `locations.json` and re-running the enrichment script.
- **No live radar.** See the note under [Data sources](#data-sources): radar
  nowcasting needs IMD/ISRO data sharing that no public API offers today.
- **The historical register is hand-compiled** and not exhaustive. It is adequate
  for a recency-weighted frequency feature and for back-testing, and is not a
  substitute for an official disaster database.
- **No rate limiting** on the API, including citizen sign-up. It is a prototype.
- **Open-Meteo's free daily quota** (per IP) can run out after many restarts or
  climatology builds. When it does, JalDrishti pauses all Open-Meteo calls until the
  quota resets (00:05 UTC) instead of retrying. It keeps re-scoring on the last good
  weather, or on the last run's model scores, with live CWC gauges and SACHET alerts
  on top. The masthead shows "Gauges live · weather paused", with the weather's age
  and the resume time.

---

## Licence and attribution

Prototype built for a hackathon. Data is used under each source's own licence:
Open-Meteo CC BY 4.0, OpenStreetMap ODbL 1.0 (© OpenStreetMap contributors),
Copernicus DEM free and open, boundary GeoJSON from the 2011 Census district
shapefiles. IMD, CWC and NDMA are referenced for their published protocols and are
not affiliated with this project in any way.
