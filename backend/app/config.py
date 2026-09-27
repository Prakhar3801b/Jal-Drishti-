"""
Central configuration for the JalDrishti risk engine.

Every threshold in this file is traceable to a published source rather than being
tuned by eye, because the whole point of the dashboard is that a reviewer can ask
"why 64.5 mm?" and get an answer.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "JalDrishti"
APP_TAGLINE_EN = "Hyperlocal Rainfall Early Warning & Inundation Prediction"
APP_TAGLINE_HI = "अति-स्थानीय वर्षा पूर्व चेतावनी एवं जलभराव पूर्वानुमान"
VERSION = "1.0.0"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def _load_dotenv(path: Path) -> None:
    """
    Minimal .env reader so API keys live in backend/.env rather than in code.
    Real environment variables always win over the file.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BASE_DIR.parent / ".env")

# ------------------------------------------------------------ optional API keys
#
# Every one of these is optional. With none set, the app runs entirely on keyless
# sources and the AI features use deterministic, data-grounded fallbacks. Each key
# lights up one capability; /api/ai/status reports which are active.

# Free tier, no card: https://aistudio.google.com/apikey
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Free tier, no card: https://console.groq.com/keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Paid (Anthropic). Uses the official SDK; highest-quality copilot answers.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5")

# Which LLM to prefer when several keys are present: auto | anthropic | gemini | groq
LLM_PROVIDER = os.getenv("JALDRISHTI_LLM_PROVIDER", "auto").lower()

# Free tier, no card (1,000 calls/day): https://home.openweathermap.org/api_keys
# Used as an independent second rainfall forecast for multi-model consensus.
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
DB_PATH = Path(os.getenv("JALDRISHTI_DB", BASE_DIR.parent / "jaldrishti.db"))

# ---------------------------------------------------------------- scheduling

# The problem statement asks the system to adapt to changing conditions rather
# than replay a fixed scenario, so ingestion runs on a timer and the UI shows the
# age of the data it is displaying.
REFRESH_MINUTES = int(os.getenv("JALDRISHTI_REFRESH_MINUTES", "90"))
REFRESH_ON_STARTUP = os.getenv("JALDRISHTI_REFRESH_ON_STARTUP", "1") == "1"

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "JALDRISHTI_CORS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
    ).split(",")
    if o.strip()
]
# Hosted frontends get a new URL per preview deployment (e.g. Vercel's
# jaldrishti-git-branch-user.vercel.app), so a regex can allow the family.
_LOCAL_ORIGINS = r"http://(localhost|127\.0\.0\.1):\d+"
_EXTRA_ORIGINS = os.getenv("JALDRISHTI_CORS_REGEX", "").strip()
CORS_ORIGIN_REGEX = f"(?:{_LOCAL_ORIGINS})|(?:{_EXTRA_ORIGINS})" if _EXTRA_ORIGINS else _LOCAL_ORIGINS

# Relay on Vercel's Mumbai region (frontend/api/cwc.js). The CWC portal does not
# answer servers outside India, and Open-Meteo rate limits busy shared IPs; both
# are read through the relay when it is configured.
CWC_RELAY = os.getenv("JALDRISHTI_CWC_RELAY", "").strip().rstrip("/")
CWC_RELAY_TOKEN = os.getenv("JALDRISHTI_CWC_RELAY_TOKEN", "").strip()

# Where regenerable caches (archive replays, hotspot grids) live. Point it at a
# persistent disk in production; the default sits beside the code.
CACHE_DIR = Path(os.getenv("JALDRISHTI_CACHE_DIR", BASE_DIR.parent / ".cache"))

# ---------------------------------------------------------------- accounts

# Password for the seeded central/state/district accounts. Change it in any
# deployment that is not a demo.
SEED_PASSWORD = os.getenv("JALDRISHTI_SEED_PASSWORD", "jaldrishti@2026")
# One-click sign-in by role, without a password, for judges and demos.
DEMO_LOGIN = os.getenv("JALDRISHTI_DEMO_LOGIN", "1") == "1"
TOKEN_HOURS = float(os.getenv("JALDRISHTI_TOKEN_HOURS", "12"))

# ---------------------------------------------------------- notifications

# Outbound events (new alerts, escalations, flood waves, daily brief, all clear)
# are posted as JSON to this webhook - e.g. a viaSocket flow with a Webhook
# trigger, which then sends email / WhatsApp / SMS / calls. Empty = off.
NOTIFY_WEBHOOK_URL = os.getenv("JALDRISHTI_NOTIFY_WEBHOOK", "").strip()
# Shared secret the automation platform must send (header X-JalDrishti-Secret)
# to call the inbound endpoint, e.g. for the WhatsApp question bot.
NOTIFY_INBOUND_SECRET = os.getenv("JALDRISHTI_NOTIFY_SECRET", "").strip()
# Hour (IST, 0-23) the daily brief goes out.
DAILY_BRIEF_HOUR = int(os.getenv("JALDRISHTI_DAILY_BRIEF_HOUR", "8"))

# ------------------------------------------------------------------- CAP 1.2

# Warnings are also published as OASIS CAP 1.2, the format NDMA SACHET, IMD and
# CWC exchange. This is a research prototype, so messages are never "Actual":
# only Exercise (the default) or Test, which CAP consumers do not relay to the public.
CAP_STATUS = os.getenv("JALDRISHTI_CAP_STATUS", "Exercise").strip().title()
if CAP_STATUS not in ("Exercise", "Test"):
    CAP_STATUS = "Exercise"
CAP_SENDER = os.getenv("JALDRISHTI_CAP_SENDER", "jaldrishti.prototype").strip()
# Public dashboard URL, used for each alert's <web> link. Optional.
PUBLIC_WEB_URL = os.getenv("JALDRISHTI_PUBLIC_WEB_URL", "").strip().rstrip("/")
# Radius of the warning area around each monitored place.
CAP_AREA_RADIUS_KM = float(os.getenv("JALDRISHTI_CAP_RADIUS_KM", "10"))

# ---------------------------------------------------------------- data sources

OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FLOOD = "https://flood-api.open-meteo.com/v1/flood"
OPEN_METEO_ELEVATION = "https://api.open-meteo.com/v1/elevation"

TIMEZONE = "Asia/Kolkata"

# Open-Meteo's free tier counts every coordinate in a batch as one call against a
# per-minute budget, so batches stay modest and the client paces itself.
BATCH_COORDS = 40
COORDS_PER_MIN = 400
HTTP_TIMEOUT = 60.0

# Climatology window used to answer "is this river unusually high *for this time of
# year*". GloFAS reanalysis starts in 1984; 30 years is plenty and keeps the
# payload small.
CLIMATOLOGY_START_YEAR = int(os.getenv("JALDRISHTI_CLIMO_START", "1994"))
CLIMATOLOGY_END_YEAR = int(os.getenv("JALDRISHTI_CLIMO_END", "2024"))
CLIMATOLOGY_WINDOW_DAYS = 10  # +/- days around the day-of-year

SOURCE_CITATIONS = {
    "open_meteo_weather": {
        "name": "Open-Meteo Weather API",
        "name_hi": "ओपन-मेटियो मौसम एपीआई",
        "gives": "Observed and forecast rainfall at ~5 km resolution",
        "url": "https://open-meteo.com/en/docs",
        "licence": "CC BY 4.0, free for non-commercial use, no key required",
    },
    "open_meteo_flood": {
        "name": "Open-Meteo Flood API (GloFAS v4)",
        "name_hi": "ओपन-मेटियो बाढ़ एपीआई (ग्लोफास v4)",
        "gives": "Simulated river discharge (m3/s) with a 30-member ensemble forecast",
        "url": "https://open-meteo.com/en/docs/flood-api",
        "licence": "CC BY 4.0, derived from Copernicus Emergency Management Service",
    },
    "copernicus_dem": {
        "name": "Copernicus DEM GLO-90",
        "name_hi": "कोपरनिकस डीईएम GLO-90",
        "gives": "Elevation and derived local slope",
        "url": "https://dataspace.copernicus.eu/",
        "licence": "Free and open, ESA / Copernicus",
    },
    "osm": {
        "name": "OpenStreetMap (Overpass API)",
        "name_hi": "ओपनस्ट्रीटमैप",
        "gives": "Drainage network density, distance to rivers and water bodies",
        "url": "https://www.openstreetmap.org/copyright",
        "licence": "ODbL 1.0, (c) OpenStreetMap contributors",
    },
    "imd_protocol": {
        "name": "IMD rainfall categories & colour-coded warnings",
        "name_hi": "भारत मौसम विज्ञान विभाग वर्षा श्रेणियाँ",
        "gives": "The rainfall class boundaries and the Green/Yellow/Orange/Red scale this app scores against",
        "url": "https://mausam.imd.gov.in/",
        "licence": "Published operational protocol, used as a classification standard",
    },
    "cwc": {
        "name": "Central Water Commission — Flood Forecasting",
        "name_hi": "केंद्रीय जल आयोग",
        "gives": "Basin definitions and the station-based forecasting model this UI mirrors",
        "url": "https://aff.india-water.gov.in/",
        "licence": "Portal only, no public REST API; used for structure and validation",
    },
    "ndma": {
        "name": "NDMA response guidelines",
        "name_hi": "राष्ट्रीय आपदा प्रबंधन प्राधिकरण",
        "gives": "The response-action tiers each alert level is mapped to",
        "url": "https://ndma.gov.in/",
        "licence": "Published guidance documents",
    },
    "historical_register": {
        "name": "JalDrishti historical flood register",
        "name_hi": "ऐतिहासिक बाढ़ रजिस्टर",
        "gives": "58 dated past flood events used for the frequency feature and back-testing",
        "url": "backend/app/data/historical_floods.json",
        "licence": "Hand-compiled for this prototype from CWC/NDMA/IMD reports and news archives",
    },
}

# ------------------------------------------------------- IMD rainfall classes

# India Meteorological Department 24-hour rainfall categories, in mm.
# These are the real operational class boundaries, which is why the risk curve
# bends where it does.
IMD_RAIN_CLASSES = [
    {"key": "none", "label_en": "No rain", "label_hi": "वर्षा नहीं", "min": 0.0, "max": 0.1},
    {"key": "very_light", "label_en": "Very light", "label_hi": "अति हल्की", "min": 0.1, "max": 2.5},
    {"key": "light", "label_en": "Light", "label_hi": "हल्की", "min": 2.5, "max": 15.6},
    {"key": "moderate", "label_en": "Moderate", "label_hi": "मध्यम", "min": 15.6, "max": 64.5},
    {"key": "heavy", "label_en": "Heavy", "label_hi": "भारी", "min": 64.5, "max": 115.6},
    {"key": "very_heavy", "label_en": "Very heavy", "label_hi": "अति भारी", "min": 115.6, "max": 204.5},
    {"key": "extremely_heavy", "label_en": "Extremely heavy", "label_hi": "अत्यधिक भारी", "min": 204.5, "max": 10_000},
]

# Piecewise-linear map from 24 h rainfall (mm) to a 0-100 sub-score. The knots are
# the IMD class boundaries above, so "65" on this axis means "IMD heavy rainfall".
RAIN_24H_KNOTS = [(0.0, 0.0), (15.6, 15.0), (64.5, 45.0), (115.6, 68.0), (204.5, 88.0), (350.0, 100.0)]
RAIN_72H_KNOTS = [(0.0, 0.0), (50.0, 15.0), (150.0, 45.0), (300.0, 70.0), (500.0, 90.0), (800.0, 100.0)]

# ------------------------------------------------------ discharge normalisation

# Current discharge as a multiple of the climatological median for this time of
# year. 1.0 is a normal river; CWC treats sustained multiples of the seasonal
# normal as the trigger for warning stages, so the curve rises steeply above 1.5.
DISCHARGE_RATIO_KNOTS = [(0.0, 0.0), (1.0, 18.0), (1.5, 45.0), (2.0, 65.0), (3.0, 85.0), (5.0, 100.0)]

# Where the current value sits in the location's own historical distribution for
# this calendar window. A 99th-percentile river is alarming regardless of ratio.
DISCHARGE_PCTL_KNOTS = [(0.0, 0.0), (50.0, 20.0), (75.0, 40.0), (90.0, 62.0), (97.0, 82.0), (99.5, 100.0)]

# Rate of change, as fraction of the median per day. A rising limb matters even
# before the absolute level is high.
DISCHARGE_TREND_KNOTS = [(-1.0, 0.0), (0.0, 10.0), (0.25, 40.0), (0.6, 70.0), (1.5, 100.0)]

# ---------------------------------------------------------------- model weights

# Hybrid rule-weighted model. Weights sum to 1.0 and are deliberately visible
# here so they can be defended and tuned; scripts/backtest.py scores them against
# the historical register.
WEIGHTS = {
    "rain_24h": 0.16,
    "rain_72h": 0.09,
    "rain_forecast_24h": 0.14,
    "rain_forecast_72h": 0.07,
    "discharge_percentile": 0.15,
    "discharge_ratio": 0.09,
    "discharge_trend": 0.08,
    "soil_saturation": 0.07,
    "terrain_susceptibility": 0.10,
    "historical_frequency": 0.05,
}

FACTOR_LABELS = {
    "rain_24h": ("Rainfall, last 24 h", "पिछले 24 घंटे की वर्षा"),
    "rain_72h": ("Rainfall, last 72 h", "पिछले 72 घंटे की वर्षा"),
    "rain_forecast_24h": ("Forecast rain, next 24 h", "अगले 24 घंटे का वर्षा पूर्वानुमान"),
    "rain_forecast_72h": ("Forecast rain, next 72 h", "अगले 72 घंटे का वर्षा पूर्वानुमान"),
    "discharge_percentile": ("River level vs. seasonal normal", "मौसमी सामान्य की तुलना में नदी स्तर"),
    "discharge_ratio": ("River discharge multiple", "नदी प्रवाह गुणक"),
    "discharge_trend": ("River rising/falling", "नदी का बढ़ना/घटना"),
    "soil_saturation": ("Soil already saturated", "मिट्टी की संतृप्तता"),
    "terrain_susceptibility": ("Terrain & drainage", "भूभाग एवं जल निकासी"),
    "historical_frequency": ("Historical flood frequency", "ऐतिहासिक बाढ़ आवृत्ति"),
}

# Volumetric soil water content (m3/m3) in the top ~27 cm. Saturated mineral soil
# sits near 0.45; once the profile is full, new rainfall runs off instead of
# infiltrating, which is why an already-wet catchment floods on less rain.
SOIL_SATURATION_KNOTS = [(0.15, 0.0), (0.25, 20.0), (0.33, 45.0), (0.40, 75.0), (0.45, 100.0)]

# When the ML classifier is available its probability is blended with the rule
# score. The rule score keeps the majority share so the system stays explainable
# and never hides behind the model.
ML_BLEND_WEIGHT = float(os.getenv("JALDRISHTI_ML_WEIGHT", "0.35"))
ML_MODEL_PATH = DATA_DIR / "risk_model.json"

# ------------------------------------------------------------------ alert tiers

# Colours follow IMD's operational warning convention; the actions follow the
# tiering used in NDMA guidance.
ALERT_TIERS = [
    {
        "key": "green",
        "min": 0,
        "max": 25,
        "label_en": "Green — No warning",
        "label_hi": "हरा — कोई चेतावनी नहीं",
        "colour": "#0B8A3D",
        "imd_meaning_en": "No action needed. Conditions are normal.",
        "imd_meaning_hi": "किसी कार्रवाई की आवश्यकता नहीं। स्थिति सामान्य है।",
        "ndma_action_en": "Routine monitoring. Nothing to activate.",
        "ndma_action_hi": "नियमित निगरानी। कुछ सक्रिय करने की आवश्यकता नहीं।",
    },
    {
        "key": "yellow",
        "min": 25,
        "max": 50,
        "label_en": "Yellow — Be aware",
        "label_hi": "पीला — सतर्क रहें",
        "colour": "#E8B10B",
        "imd_meaning_en": "Be updated. Watch for localised waterlogging.",
        "imd_meaning_hi": "अद्यतन रहें। स्थानीय जलभराव पर नज़र रखें।",
        "ndma_action_en": "District control room on watch; clear storm drains and pumps.",
        "ndma_action_hi": "जिला नियंत्रण कक्ष सतर्क; नालों और पंपों की सफाई करें।",
    },
    {
        "key": "orange",
        "min": 50,
        "max": 75,
        "label_en": "Orange — Be prepared",
        "label_hi": "नारंगी — तैयार रहें",
        "colour": "#E4701E",
        "imd_meaning_en": "Be prepared for disruption to traffic and low-lying areas.",
        "imd_meaning_hi": "यातायात एवं निचले क्षेत्रों में व्यवधान के लिए तैयार रहें।",
        "ndma_action_en": "Pre-position SDRF teams and boats; ready relief shelters; issue public advisory.",
        "ndma_action_hi": "एसडीआरएफ दल एवं नावें तैनात करें; राहत शिविर तैयार रखें; जन सूचना जारी करें।",
    },
    {
        "key": "red",
        "min": 75,
        "max": 101,
        "label_en": "Red — Take action",
        "label_hi": "लाल — कार्रवाई करें",
        "colour": "#C1121F",
        "imd_meaning_en": "Take action. Significant flooding is likely.",
        "imd_meaning_hi": "कार्रवाई करें। महत्वपूर्ण बाढ़ की संभावना है।",
        "ndma_action_en": "Evacuate low-lying wards; deploy NDRF/SDRF; open relief camps; activate EOC round the clock.",
        "ndma_action_hi": "निचले वार्डों से निकासी; एनडीआरएफ/एसडीआरएफ तैनात करें; राहत शिविर खोलें; ईओसी चौबीसों घंटे सक्रिय करें।",
    },
]


def tier_for_score(score: float) -> dict:
    for tier in ALERT_TIERS:
        if tier["min"] <= score < tier["max"]:
            return tier
    return ALERT_TIERS[-1] if score >= 75 else ALERT_TIERS[0]


# -------------------------------------------------------------- confidence

# Ensemble spread, expressed as the interquartile range divided by the median,
# is the primary uncertainty signal. Lead time and input completeness adjust it.
CONFIDENCE_LEVELS = [
    {"key": "high", "label_en": "High confidence", "label_hi": "उच्च विश्वसनीयता", "min": 0.70},
    {"key": "medium", "label_en": "Medium confidence", "label_hi": "मध्यम विश्वसनीयता", "min": 0.45},
    {"key": "low", "label_en": "Low confidence", "label_hi": "निम्न विश्वसनीयता", "min": 0.0},
]


def confidence_for(value: float) -> dict:
    for level in CONFIDENCE_LEVELS:
        if value >= level["min"]:
            return level
    return CONFIDENCE_LEVELS[-1]
