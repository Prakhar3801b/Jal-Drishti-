"""
Orchestration: one refresh pass over every monitored location.

    ingest (2 HTTP calls)  ->  features  ->  score  ->  explain  ->  persist

The engine holds the last completed result set in memory so the API never blocks
on SQLite or on the network, and swaps it atomically at the end of a run. A refresh
that fails leaves the previous good snapshot serving, which is what you want when
somebody is demoing over conference wifi.
"""

from __future__ import annotations

import asyncio
import copy
import json
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from . import consensus, explain, features, risk, sources, store
from .ml import ml
from .official import official
from .config import (
    CACHE_DIR,
    DATA_DIR,
    REFRESH_MINUTES,
    SOURCE_CITATIONS,
    VERSION,
    tier_for_score,
)

# --------------------------------------------------------------- static inputs


def _load_locations() -> list[dict]:
    """Prefer the enriched file; fall back to the seed so the app still boots."""
    enriched = DATA_DIR / "locations.enriched.json"
    seed = DATA_DIR / "locations.json"
    path = enriched if enriched.exists() else seed
    payload = json.loads(path.read_text(encoding="utf-8"))
    locs = payload["locations"]
    for loc in locs:
        loc.setdefault("glofas_lat", loc["lat"])
        loc.setdefault("glofas_lon", loc["lon"])
    return locs


def _load_events() -> list[dict]:
    payload = json.loads((DATA_DIR / "historical_floods.json").read_text(encoding="utf-8"))
    return payload["events"]


LOCATIONS: list[dict] = _load_locations()
EVENTS: list[dict] = _load_events()
LOCATIONS_BY_ID: dict[str, dict] = {l["id"]: l for l in LOCATIONS}
ENRICHED = (DATA_DIR / "locations.enriched.json").exists()
REPLAY_CACHE = CACHE_DIR / "archive"
# Raw weather + river series from the last successful fetch, so a restarted server
# whose weather source is rate limited can still re-score on live gauges.
INPUTS_CACHE = CACHE_DIR / "last_inputs.json.gz"


# ------------------------------------------------------------- in-memory state


class Snapshot:
    """One complete scoring pass, ready to serve."""

    def __init__(
        self,
        run_id: int,
        assessments: list[dict],
        started: datetime,
        duration_ms: int,
        trigger: str,
        degraded: list[str],
    ):
        self.run_id = run_id
        self.assessments = assessments
        self.by_id = {a["location"]["id"]: a for a in assessments}
        self.computed_at = started
        self.duration_ms = duration_ms
        self.trigger = trigger
        self.degraded = degraded
        self.replay_date: str | None = None
        # When the weather inputs behind this run were fetched (older than
        # computed_at when the weather source was unavailable and gauges drove it).
        self.weather_as_of: datetime = started
        self.weather_mode: str = "live"  # live | cached | official_only

    @property
    def tier_counts(self) -> dict[str, int]:
        counts = Counter(a["risk"]["tier"]["key"] for a in self.assessments)
        return {k: counts.get(k, 0) for k in ("red", "orange", "yellow", "green")}

    def worst(self, n: int = 5) -> list[dict]:
        return sorted(self.assessments, key=lambda a: a["risk"]["score"], reverse=True)[:n]


class Engine:
    def __init__(self) -> None:
        self.snapshot: Snapshot | None = None
        self.climatology: dict[str, dict] = {}
        self.refreshing = False
        self.last_error: str | None = None
        self._lock = asyncio.Lock()
        # Raw inputs from the last refresh, kept so the what-if simulator can
        # perturb the real series instead of inventing a synthetic scenario.
        self.raw: dict[str, tuple[dict, dict]] = {}
        self.raw_as_of: datetime | None = None
        self.owm: dict[str, float] = {}
        self._replay_cache: dict[str, Snapshot] = {}

    # --------------------------------------------------------------- scoring

    def assess(
        self,
        loc: dict,
        weather: dict,
        flood: dict,
        reference: datetime | None = None,
        owm_next24: float | None = None,
        fusion: bool = False,
    ) -> dict:
        """Score one location. Pure function of its inputs — replay and the simulator reuse it."""
        fv = features.build_feature_vector(
            loc, weather, flood, self.climatology.get(loc["id"]), EVENTS, reference
        )
        norm = risk.normalise_features(fv)
        scored = risk.score_from_normalised(norm)

        # Official observations (CWC gauges, NDMA/IMD/CWC alerts) set a floor under
        # the modelled score. Live only: there is no archive of past gauge readings
        # or alerts, so replays stay model-only and say so.
        official_block = official.fuse(loc["lat"], loc["lon"]) if fusion else None
        scored["model_score"] = scored["score"]
        if official_block and official_block["floor"] > scored["score"]:
            scored["score"] = official_block["floor"]
        tier = tier_for_score(scored["score"])
        factors = risk.rank_factors(scored)
        agreement = consensus.compare(fv["rain"].get("rain_next_24h_mm"), owm_next24)
        confidence = risk.assess_confidence(fv, norm, agreement)
        if official_block and official_block["gauge"]:
            g = official_block["gauge"]
            confidence["value"] = round(min(1.0, confidence["value"] + 0.15), 3)
            confidence["reasons_en"].insert(0, f"Observed river level from CWC gauge {g['name']} ({g['distance_km']} km)")
            confidence["reasons_hi"].insert(0, f"केंद्रीय जल आयोग गेज {g['name']} ({g['distance_km']} किमी) से प्रेक्षित नदी स्तर")
            from .config import confidence_for as _cf
            lvl = _cf(confidence["value"])
            confidence.update(level=lvl["key"], label_en=lvl["label_en"], label_hi=lvl["label_hi"])
        trajectory = risk.project_trajectory(fv, norm)
        direction = risk.trajectory_direction(trajectory)
        peak = risk.peak_window(trajectory)
        narrative = explain.build_explanation(
            loc, fv, scored, factors, tier, confidence, trajectory, peak
        )
        if official_block and official_block["reasons_en"]:
            lead_en = "Official data: " + "; ".join(official_block["reasons_en"]) + ". "
            lead_hi = "आधिकारिक आँकड़े: " + "; ".join(official_block["reasons_hi"]) + "। "
            if scored["score"] > scored["model_score"]:
                lead_en += f"This raises the score from the model's {scored['model_score']:.0f} to {scored['score']:.0f}. "
                lead_hi += f"इससे स्कोर मॉडल के {scored['model_score']:.0f} से बढ़कर {scored['score']:.0f} हो जाता है। "
            narrative["narrative_en"] = lead_en + narrative["narrative_en"]
            narrative["narrative_hi"] = lead_hi + narrative["narrative_hi"]
            narrative["bullets_en"] = official_block["reasons_en"] + narrative["bullets_en"]
            narrative["bullets_hi"] = official_block["reasons_hi"] + narrative["bullets_hi"]

        # Exposure is kept separate from hazard on purpose: a high score in a
        # village and in a metro are the same hazard but very different problems,
        # and conflating them would hide that.
        pop = loc.get("population") or 0
        exposure = {
            "population": pop,
            "population_label": _compact_population(pop),
            "impact_index": round(min(100.0, (scored["score"] / 100.0) * _pop_weight(pop)), 1),
        }

        return {
            "location": {
                "id": loc["id"],
                "name": loc["name"],
                "name_hi": loc.get("name_hi"),
                "state": loc["state"],
                "district": loc.get("district"),
                "lat": loc["lat"],
                "lon": loc["lon"],
                "river": loc.get("river"),
                "basin": loc.get("basin"),
                "cwc_basin": loc.get("cwc_basin"),
                "coastal": bool(loc.get("coastal")),
                "population": pop,
                "elevation_m": loc.get("elevation_m"),
                "glofas_cell": [loc.get("glofas_lat"), loc.get("glofas_lon")],
                "glofas_snap_km": loc.get("glofas_snap_km"),
            },
            "risk": {
                "score": scored["score"],
                "model_score": scored["model_score"],
                "official_floor_applied": bool(official_block and official_block["floor"] > scored["model_score"]),
                "rule_score": scored["rule_score"],
                "weighted_score": scored["weighted_score"],
                "dominant": scored["dominant"],
                "ml_probability": scored["ml_probability"],
                "ml_blend_weight": scored["ml_blend_weight"],
                "tier": {
                    "key": tier["key"],
                    "label_en": tier["label_en"],
                    "label_hi": tier["label_hi"],
                    "colour": tier["colour"],
                },
                "direction": direction,
                "peak": peak,
                "normalised": norm,
            },
            "ai": {
                "analogs": ml.analogs(norm, exclude_location=loc["id"]),
                "anomaly": ml.anomaly(norm) if ml.forest is not None else {"available": False},
                "model_attribution": ml.attribution(norm),
                "forecast_consensus": agreement,
            },
            "official": official_block,
            "confidence": confidence,
            "factors": factors,
            "trajectory": trajectory,
            "explanation": narrative,
            "actions": explain.response_actions(tier),
            "observations": {
                "rain_24h_mm": fv["rain"].get("rain_24h_mm"),
                "rain_72h_mm": fv["rain"].get("rain_72h_mm"),
                "rain_7d_mm": fv["rain"].get("rain_7d_mm"),
                "rain_next_24h_mm": fv["rain"].get("rain_next_24h_mm"),
                "rain_next_72h_mm": fv["rain"].get("rain_next_72h_mm"),
                "rain_peak_hour_mm": fv["rain"].get("rain_peak_hour_mm"),
                "soil_moisture": fv["rain"].get("soil_moisture"),
                "as_of_hour": fv["rain"].get("as_of_hour"),
                "imd_class": fv["imd_class"],
            },
            "current_weather": current_weather(weather.get("current")),
            "river": {k: v for k, v in fv["river"].items() if k != "seasonal_bands"} | {
                "seasonal_bands": fv["river"].get("seasonal_bands")
            },
            "terrain": fv["terrain"],
            "history": fv["history"],
            "exposure": exposure,
        }

    # -------------------------------------------------------------- refresh

    async def refresh(self, trigger: str = "manual") -> Snapshot:
        async with self._lock:
            self.refreshing = True
            started_wall = datetime.now(timezone.utc)
            t0 = time.perf_counter()
            run_id = store.start_run(trigger)
            degraded: list[str] = []
            try:
                async with sources.make_client() as client:
                    weather_task = sources.fetch_weather(client, LOCATIONS)
                    flood_task = sources.fetch_flood(client, LOCATIONS)
                    owm_task = consensus.fetch_owm_next24(LOCATIONS)
                    weather, flood, owm, _ = await asyncio.gather(
                        weather_task, flood_task, owm_task, official.refresh(), return_exceptions=True
                    )
                self.owm = owm if isinstance(owm, dict) else {}
                try:
                    near = official.nearest_codes([(l["lat"], l["lon"]) for l in LOCATIONS])
                    await official.refresh_readings(near + list(official.above.keys()))
                except Exception as exc:
                    degraded.append(f"cwc readings: {str(exc)[:80]}")

                weather_mode, weather_as_of = "live", started_wall
                if isinstance(weather, BaseException):
                    if not self.raw:
                        self._load_inputs()
                    if self.raw:
                        # Weather source down or over quota: re-score on the last good
                        # weather series (its forecast part now stands in for the hours
                        # since) with live gauges and alerts on top.
                        weather_mode, weather_as_of = "cached", self.raw_as_of or started_wall
                        degraded.append(f"weather from {weather_as_of:%d %b %H:%M} UTC: {str(weather)[:80]}")
                        weather = {k: v[0] for k, v in self.raw.items()}
                        if isinstance(flood, BaseException):
                            flood = {k: v[1] for k, v in self.raw.items()}
                    elif self.snapshot is not None:
                        snap = self._official_only(run_id, started_wall, t0, trigger, str(weather))
                        return snap
                    else:
                        raise RuntimeError(f"weather source failed: {weather}")
                if isinstance(flood, BaseException):
                    degraded.append("open_meteo_flood")
                    flood = {}

                assessments: list[dict] = []
                for loc in LOCATIONS:
                    w = weather.get(loc["id"])
                    if not w:
                        degraded.append(f"no weather for {loc['id']}")
                        continue
                    f = flood.get(loc["id"], {})
                    self.raw[loc["id"]] = (w, f)
                    assessments.append(self.assess(loc, w, f, owm_next24=self.owm.get(loc["id"]), fusion=True))
                if weather_mode == "live":
                    self.raw_as_of = started_wall
                    self._save_inputs()

                # Without a trained Isolation Forest, anomaly detection falls back to
                # how far each location sits outside today's national spread.
                if ml.forest is None:
                    population = [a["risk"]["normalised"] for a in assessments]
                    for a in assessments:
                        a["ai"]["anomaly"] = ml.anomaly(a["risk"]["normalised"], population)

                duration_ms = int((time.perf_counter() - t0) * 1000)
                snap = Snapshot(run_id, assessments, started_wall, duration_ms, trigger, degraded)
                snap.weather_as_of, snap.weather_mode = weather_as_of, weather_mode

                store.save_assessments(run_id, assessments)
                store.save_observations(run_id, _observation_rows(assessments))
                store.finish_run(
                    run_id,
                    "partial" if degraded else "ok",
                    len(assessments),
                    duration_ms,
                    "; ".join(degraded[:5]),
                )
                self.snapshot = snap
                self.last_error = None
                return snap
            except Exception as exc:
                duration_ms = int((time.perf_counter() - t0) * 1000)
                store.finish_run(run_id, "failed", 0, duration_ms, str(exc)[:400])
                self.last_error = str(exc)[:400]
                raise
            finally:
                self.refreshing = False

    def _save_inputs(self) -> None:
        import gzip

        try:
            INPUTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
            body = {"as_of": self.raw_as_of.isoformat(), "raw": {k: [w, f] for k, (w, f) in self.raw.items()}}
            with gzip.open(INPUTS_CACHE, "wt", encoding="utf-8") as fh:
                json.dump(body, fh)
        except Exception as exc:  # a cache, never a reason to fail a refresh
            import logging

            logging.getLogger("jaldrishti.engine").warning("could not save last inputs: %s", exc)

    def _load_inputs(self) -> None:
        import gzip

        try:
            with gzip.open(INPUTS_CACHE, "rt", encoding="utf-8") as fh:
                body = json.load(fh)
        except (OSError, ValueError):
            return
        self.raw = {k: (v[0], v[1]) for k, v in body.get("raw", {}).items()}
        self.raw_as_of = datetime.fromisoformat(body["as_of"]) if body.get("as_of") else None

    def _official_only(self, run_id: int, started_wall: datetime, t0: float, trigger: str, why: str) -> Snapshot:
        """
        No weather at all (source over quota and no cached series): keep the last
        run's modelled scores and re-apply the live official record - CWC gauges
        and SACHET alerts - on top, so river-driven changes still show up.
        """
        base = self.snapshot
        assessments = []
        for a in base.assessments:
            a = copy.deepcopy(a)
            loc = a["location"]
            block = official.fuse(loc["lat"], loc["lon"])
            model = a["risk"].get("model_score", a["risk"]["score"])
            score = max(model, block["floor"]) if block else model
            tier = tier_for_score(score)
            a["official"] = block
            a["risk"]["score"] = score
            a["risk"]["official_floor_applied"] = bool(block and block["floor"] > model)
            a["risk"]["tier"] = {k: tier[k] for k in ("key", "label_en", "label_hi", "colour")}
            a["actions"] = explain.response_actions(tier)
            assessments.append(a)
        as_of = getattr(base, "weather_as_of", base.computed_at)
        degraded = [f"weather from {as_of:%d %b %H:%M} UTC, gauges and alerts live: {why[:80]}"]
        duration_ms = int((time.perf_counter() - t0) * 1000)
        snap = Snapshot(run_id, assessments, started_wall, duration_ms, trigger, degraded)
        snap.weather_as_of, snap.weather_mode = as_of, "official_only"
        store.save_assessments(run_id, assessments)
        store.finish_run(run_id, "partial", len(assessments), duration_ms, degraded[0][:400])
        self.snapshot = snap
        self.last_error = None
        return snap

    def _expected_cells(self) -> dict[str, tuple[float, float]]:
        return {
            l["id"]: (float(l.get("glofas_lat", l["lat"])), float(l.get("glofas_lon", l["lon"])))
            for l in LOCATIONS
        }

    def simulate(
        self,
        location_id: str,
        *,
        extra_rain_past_24h: float = 0.0,
        extra_rain_next_24h: float = 0.0,
        discharge_multiplier: float = 1.0,
        soil_moisture: float | None = None,
    ) -> dict:
        """
        What-if scenario on the live inputs.

        Rather than a synthetic scenario, the real hourly rainfall and daily
        discharge series from the last refresh are copied and perturbed, then run
        through the exact same assess() path. "Add 120 mm over the next day" is
        therefore scored with the same curves, climatology and ML model as reality.
        """
        loc = LOCATIONS_BY_ID.get(location_id)
        if loc is None or location_id not in self.raw:
            raise KeyError(location_id)
        weather, flood = (copy.deepcopy(x) for x in self.raw[location_id])

        hourly = weather.setdefault("hourly", {})
        times = hourly.get("time") or []
        precip = hourly.get("precipitation") or []
        i = features._now_index(times, None)
        if precip:
            if extra_rain_past_24h:
                for h in range(max(0, i - 23), i + 1):
                    precip[h] = (precip[h] or 0.0) + extra_rain_past_24h / 24.0
            if extra_rain_next_24h:
                for h in range(i + 1, min(len(precip), i + 25)):
                    precip[h] = (precip[h] or 0.0) + extra_rain_next_24h / 24.0
        if soil_moisture is not None:
            for key in ("soil_moisture_0_to_1cm", "soil_moisture_3_to_9cm", "soil_moisture_9_to_27cm"):
                if hourly.get(key):
                    hourly[key] = [soil_moisture for _ in hourly[key]]

        if discharge_multiplier != 1.0:
            daily = flood.get("daily") or {}
            today = date.today().isoformat()
            for key, series in daily.items():
                if key.startswith("river_discharge") and isinstance(series, list):
                    for j, t in enumerate(daily.get("time") or []):
                        # scale today and the forecast; history stays as observed,
                        # so the trend feature sees a genuine rise
                        if t >= today and j < len(series) and series[j] is not None:
                            series[j] = series[j] * discharge_multiplier

        baseline = self.snapshot.by_id.get(location_id) if self.snapshot else None
        scenario = self.assess(loc, weather, flood, owm_next24=self.owm.get(location_id), fusion=True)
        return {
            "inputs": {
                "extra_rain_past_24h": extra_rain_past_24h,
                "extra_rain_next_24h": extra_rain_next_24h,
                "discharge_multiplier": discharge_multiplier,
                "soil_moisture": soil_moisture,
            },
            "baseline": {
                "score": baseline["risk"]["score"],
                "tier": baseline["risk"]["tier"]["key"],
            } if baseline else None,
            "scenario": scenario,
            "delta": round(scenario["risk"]["score"] - baseline["risk"]["score"], 1) if baseline else None,
        }

    async def snapshot_for_date(self, target: date) -> "Snapshot":
        """
        A whole-country snapshot as the engine would have scored it on a past date.

        This is the national Time Machine: every location re-scored from the
        Open-Meteo archive and GloFAS reanalysis through the same assess() path as
        the live feed. Archive responses are cached per date on disk (shared with
        scripts/train_model.py) and built snapshots are kept in memory, so
        revisiting a famous flood day is instant and costs no API quota.
        """
        key = target.isoformat()
        if key in self._replay_cache:
            return self._replay_cache[key]

        cache_file = REPLAY_CACHE / f"{key}.json"
        weather: dict = {}
        flood: dict = {}
        if cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            weather, flood = cached.get("weather", {}), cached.get("flood", {})

        missing = [l for l in LOCATIONS if l["id"] not in weather]
        if missing:
            start, end = target - timedelta(days=10), target + timedelta(days=1)
            async with sources.make_client() as client:
                w, f = await sources.fetch_archive(client, missing, start, end)
            weather.update(w)
            flood.update(f)
            if w:
                REPLAY_CACHE.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps({"weather": weather, "flood": flood}), encoding="utf-8")

        t0 = time.perf_counter()
        reference = datetime.combine(target, datetime.min.time()).replace(hour=8)
        assessments = [
            self.assess(loc, weather[loc["id"]], flood.get(loc["id"], {}), reference)
            for loc in LOCATIONS
            if loc["id"] in weather
        ]
        if not assessments:
            raise RuntimeError("archive returned no data for that date (quota or network)")
        if ml.forest is None:
            population = [a["risk"]["normalised"] for a in assessments]
            for a in assessments:
                a["ai"]["anomaly"] = ml.anomaly(a["risk"]["normalised"], population)

        degraded = [f"no archive for {l['id']}" for l in LOCATIONS if l["id"] not in weather]
        snap = Snapshot(
            0, assessments, datetime.now(timezone.utc),
            int((time.perf_counter() - t0) * 1000), "replay", degraded,
        )
        snap.replay_date = key
        if len(self._replay_cache) >= 12:
            self._replay_cache.pop(next(iter(self._replay_cache)))
        self._replay_cache[key] = snap
        return snap

    def restore_last(self) -> Snapshot | None:
        """
        Serve the last stored run while the first live pass is in flight or failing
        (e.g. Open-Meteo rate limiting a restarted server). The masthead shows its
        age, so stale data is visible as stale rather than hidden behind a spinner.
        """
        run = store.latest_run()
        if run is None:
            return None
        assessments = store.load_assessments(run["id"])
        if not assessments:
            return None
        started = datetime.fromisoformat(run["started_at"])
        snap = Snapshot(run["id"], assessments, started, run.get("duration_ms") or 0, "restored", ["restored from last stored run"])
        # A partial run carries its weather age in its note; otherwise the run time is it.
        note = run.get("notes") or ""
        if "weather from" in note:
            try:
                stamp = note.split("weather from ", 1)[1][:12]
                snap.weather_as_of = datetime.strptime(f"{started.year} {stamp}", "%Y %d %b %H:%M").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        self._load_inputs()
        if self.snapshot is None:
            self.snapshot = snap
        return snap

    async def load_climatology(self) -> int:
        # Only accept baselines built at the cell we are currently reading from.
        self.climatology = store.load_climatology(self._expected_cells())
        return len(self.climatology)

    async def ensure_climatology(self) -> int:
        """
        Build the 30-year GloFAS baseline once, in the background.

        Until it exists the engine scores against a short recent window and the
        confidence layer says so, so the app is useful from the first second and
        gets sharper a couple of minutes later.
        """
        await self.load_climatology()
        missing = [l for l in LOCATIONS if l["id"] not in self.climatology]
        if not missing:
            return 0
        async with sources.make_client() as client:
            built = await sources.build_climatology(client, missing)
        await self.load_climatology()
        return built

    # ---------------------------------------------------------------- replay

    async def replay(self, location_id: str, target: date) -> dict:
        """
        Re-run the engine as it would have run on a past date.

        This is the most convincing thing in the demo: it does not depend on rain
        falling during the presentation. The same assess() path runs, with the
        archive standing in for the live feed, so nothing is special-cased.
        """
        loc = LOCATIONS_BY_ID.get(location_id)
        if loc is None:
            raise KeyError(location_id)

        start, end = sources.window_for_replay(target)
        async with sources.make_client() as client:
            weather, flood = await sources.fetch_archive(client, [loc], start, end)

        w = weather.get(location_id) or {}
        f = flood.get(location_id) or {}
        reference = datetime.combine(target, datetime.min.time()).replace(hour=8)
        assessment = self.assess(loc, w, f, reference)

        matched = [
            e
            for e in EVENTS
            if e["location_id"] == location_id and abs((date.fromisoformat(e["date"]) - target).days) <= 5
        ]
        return {
            "target_date": target.isoformat(),
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "assessment": assessment,
            "recorded_events": matched,
            "verdict": _replay_verdict(assessment, matched),
        }


def _replay_verdict(assessment: dict, matched: Sequence[dict]) -> dict:
    """Did the model flag the day a real flood happened?"""
    score = assessment["risk"]["score"]
    tier = assessment["risk"]["tier"]["key"]
    flagged = tier in ("orange", "red")
    if matched and flagged:
        return {
            "key": "hit",
            "en": f"The model scored {score:.0f}/100 ({tier.title()}) — it would have flagged this event.",
            "hi": f"मॉडल ने {score:.0f}/100 ({tier}) दिया — यह घटना चिह्नित हुई होती।",
        }
    if matched and not flagged:
        return {
            "key": "miss",
            "en": f"The model scored only {score:.0f}/100 ({tier.title()}) — it would have under-called this event.",
            "hi": f"मॉडल ने केवल {score:.0f}/100 ({tier}) दिया — यह घटना कम आँकी गई होती।",
        }
    if flagged:
        return {
            "key": "false_alarm",
            "en": f"The model scored {score:.0f}/100 ({tier.title()}) but no event is recorded within 5 days.",
            "hi": f"मॉडल ने {score:.0f}/100 ({tier}) दिया, परंतु 5 दिनों में कोई घटना दर्ज नहीं।",
        }
    return {
        "key": "quiet",
        "en": f"The model scored {score:.0f}/100 ({tier.title()}) on a day with no recorded event.",
        "hi": f"बिना दर्ज घटना वाले दिन मॉडल ने {score:.0f}/100 ({tier}) दिया।",
    }


# ------------------------------------------------------------------ aggregation


def state_rollup(snapshot: Snapshot) -> list[dict]:
    """
    State-level risk for the country choropleth.

    Uses the *maximum* location score in the state, not the mean. A state with one
    district at Red and nine at Green is a state with an emergency, and averaging
    would hide exactly the signal the map exists to show. The mean is returned
    alongside so the UI can show both.
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for a in snapshot.assessments:
        grouped[a["location"]["state"]].append(a)

    out = []
    for state, items in grouped.items():
        scores = [a["risk"]["score"] for a in items]
        counts = Counter(a["risk"]["tier"]["key"] for a in items)
        worst = max(items, key=lambda a: a["risk"]["score"])
        peak_score = max(scores)
        out.append(
            {
                "state": state,
                "score": round(peak_score, 1),
                "mean_score": round(sum(scores) / len(scores), 1),
                "tier": tier_for_score(peak_score)["key"],
                "colour": tier_for_score(peak_score)["colour"],
                "locations": len(items),
                "counts": {k: counts.get(k, 0) for k in ("red", "orange", "yellow", "green")},
                "population_at_risk": sum(
                    a["location"]["population"] or 0
                    for a in items
                    if a["risk"]["tier"]["key"] in ("orange", "red")
                ),
                "worst": {
                    "id": worst["location"]["id"],
                    "name": worst["location"]["name"],
                    "name_hi": worst["location"].get("name_hi"),
                    "score": worst["risk"]["score"],
                    "tier": worst["risk"]["tier"]["key"],
                    "river": worst["location"].get("river"),
                },
                "direction": worst["risk"]["direction"],
                "weather": _state_weather(items),
            }
        )
    out.sort(key=lambda s: s["score"], reverse=True)
    return out


def current_weather(cur: dict | None) -> dict | None:
    """Open-Meteo's `current` block, renamed for the UI. None for replays, which have no 'now'."""
    if not cur or cur.get("temperature_2m") is None:
        return None
    return {
        "time": cur.get("time"),
        "temp_c": cur.get("temperature_2m"),
        "feels_like_c": cur.get("apparent_temperature"),
        "humidity_pct": cur.get("relative_humidity_2m"),
        "precip_mm": cur.get("precipitation"),
        "code": cur.get("weather_code"),
        "cloud_pct": cur.get("cloud_cover"),
        "wind_kmh": cur.get("wind_speed_10m"),
        "wind_dir_deg": cur.get("wind_direction_10m"),
        "is_day": bool(cur.get("is_day", 1)),
    }


def _state_weather(items: Sequence[dict]) -> dict | None:
    """
    Current conditions at the state's most populous monitored place, plus the
    temperature spread and wettest reading across all its places - one town's sky
    is a fair headline, but a state spans too much ground for it to be the whole story.
    """
    with_wx = [a for a in items if a.get("current_weather")]
    if not with_wx:
        return None
    lead = max(with_wx, key=lambda a: a["location"]["population"] or 0)
    temps = [a["current_weather"]["temp_c"] for a in with_wx]
    wettest = max(with_wx, key=lambda a: a["current_weather"].get("precip_mm") or 0)
    return {
        **lead["current_weather"],
        "place": lead["location"]["name"],
        "place_hi": lead["location"].get("name_hi"),
        "temp_min_c": min(temps),
        "temp_max_c": max(temps),
        "raining_places": sum(1 for a in with_wx if (a["current_weather"].get("precip_mm") or 0) > 0),
        "wettest": {
            "name": wettest["location"]["name"],
            "name_hi": wettest["location"].get("name_hi"),
            "precip_mm": wettest["current_weather"].get("precip_mm") or 0,
        },
    }


def _observation_rows(assessments: Sequence[dict]) -> list[tuple[str, str, str, float | None, str]]:
    rows: list[tuple[str, str, str, float | None, str]] = []
    today = date.today().isoformat()
    for a in assessments:
        lid = a["location"]["id"]
        obs = a["observations"]
        rows.append((lid, today, "rain_24h_mm", obs.get("rain_24h_mm"), "observed"))
        rows.append((lid, today, "rain_next_24h_mm", obs.get("rain_next_24h_mm"), "forecast"))
        rows.append((lid, today, "soil_moisture", obs.get("soil_moisture"), "observed"))
        if a["river"].get("available"):
            rows.append((lid, today, "discharge_cumecs", a["river"].get("current_cumecs"), "observed"))
    return rows


def _pop_weight(pop: int) -> float:
    """Log-scaled exposure multiplier: 30k -> ~45, 1M -> ~75, 12M -> ~100."""
    import math

    if pop <= 0:
        return 40.0
    return max(20.0, min(100.0, 20.0 + 26.0 * math.log10(max(pop, 1) / 1000.0)))


def _compact_population(pop: int) -> str:
    """Indian numbering, because the audience reads lakh/crore faster than millions."""
    if pop <= 0:
        return "—"
    if pop >= 10_000_000:
        return f"{pop/10_000_000:.2f} crore"
    if pop >= 100_000:
        return f"{pop/100_000:.1f} lakh"
    if pop >= 1000:
        return f"{pop/1000:.0f}k"
    return str(pop)


def source_manifest() -> list[dict]:
    """What the app is built on, for the sources panel and the README."""
    health = {h["source"]: h for h in store.load_source_health()}
    rows = []
    for key, meta in SOURCE_CITATIONS.items():
        h = health.get(key)
        rows.append({"key": key, **meta, "health": h})
    return rows


engine = Engine()
