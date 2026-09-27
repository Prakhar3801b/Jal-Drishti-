import { useMemo, useState } from 'react';
import {
  compactPopulation,
  cumecs,
  dateIST,
  inNumber,
  longDateIST,
  mm,
  ordinal,
  pct,
  stateName,
  tierColour,
} from '../lib/format';
import { pick, t } from '../lib/i18n';
import { RiverChart, ScoreHistoryChart, TrajectoryChart } from './Charts';
import FactorBars from './FactorBars';
import {
  ConfidenceChip,
  DataRow,
  DirectionBadge,
  EmptyState,
  SectionHead,
  Spinner,
  TierChip,
} from './Primitives';
import { AdvisoryGenerator, AIAssessmentCard, WhatIfSimulator } from './AIPanels';
import { OfficialCard } from './Official';
import ReplayPanel from './ReplayPanel';
import RiskGauge from './RiskGauge';

/**
 * Screen 3 — the hyperlocal assessment.
 *
 * Reading order is deliberate and matches how a duty officer triages: what is the
 * level, how much should I trust it, why is it that level, where is it heading,
 * what do I do, and only then the raw numbers and the provenance. The gauge and
 * the narrative are above the fold; the evidence is below it.
 */

function Collapsible({ title, lang, children, defaultOpen = false, count }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="panel">
      <button
        type="button"
        className="panel-head w-full text-left transition hover:bg-ink-850/50"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <h3 className={`panel-title ${lang === 'hi' ? 'font-devanagari' : ''}`}>
          {title}
          {count !== undefined && <span className="ml-1.5 text-ink-600">({count})</span>}
        </h3>
        <span
          className={`text-ink-500 transition-transform ${open ? 'rotate-180' : ''}`}
          aria-hidden="true"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
            <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
          </svg>
        </span>
      </button>
      {open && <div className="animate-fade-up">{children}</div>}
    </section>
  );
}

export default function DetailPanel({ lang, detail, timeline, loading, error, locationsById = {}, onOpenStation, replay = false }) {
  if (loading && !detail) return <Spinner lang={lang} />;
  if (error) {
    return (
      <EmptyState lang={lang}>
        <span className="text-risk-orange">{error}</span>
      </EmptyState>
    );
  }
  if (!detail) {
    return (
      <EmptyState lang={lang}>
        <div className="max-w-[18rem]">
          <svg
            width="40"
            height="40"
            viewBox="0 0 24 24"
            fill="none"
            className="mx-auto mb-3 text-ink-700"
            aria-hidden="true"
          >
            <path
              d="M12 21s7-5.5 7-11a7 7 0 1 0-14 0c0 5.5 7 11 7 11z"
              stroke="currentColor"
              strokeWidth="1.7"
            />
            <circle cx="12" cy="10" r="2.5" stroke="currentColor" strokeWidth="1.7" />
          </svg>
          {t(lang, 'selectPrompt')}
        </div>
      </EmptyState>
    );
  }

  const a = detail.assessment;
  const loc = a.location;
  const risk = a.risk;
  const river = a.river ?? {};
  const obs = a.observations ?? {};
  const colour = tierColour(risk.tier.key);
  const traj = timeline?.trajectory ?? a.trajectory ?? [];

  return (
    <div className="flex flex-col gap-3 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:pr-0.5 lg:scrollbar-thin">
      {/* ------------------------------------------------------------ header */}
      <section className="panel shrink-0 overflow-hidden">
        {/* a thin bar in the alert colour, so the tier is legible before reading */}
        <div className="h-1 w-full" style={{ background: colour }} />

        <div className="p-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="truncate text-[19px] font-bold leading-tight tracking-tight text-chakra-500">
                {lang === 'hi' && loc.name_hi ? loc.name_hi : loc.name}
              </h2>
              <p className="mt-0.5 truncate text-[11px] text-ink-400">
                {loc.district && `${loc.district} · `}
                {stateName(loc.state, lang)}
              </p>
              <p className="mt-0.5 truncate text-[10.5px] text-ink-500">
                {loc.river && `${loc.river} · `}
                {loc.cwc_basin} {lang === 'hi' ? 'बेसिन' : 'basin'}
                {loc.coastal && ` · ${lang === 'hi' ? 'तटीय' : 'coastal'}`}
              </p>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1.5">
              <TierChip tier={risk.tier.key} lang={lang} showAction size="lg" />
              <ConfidenceChip
                level={a.confidence.level}
                label={pick(lang, a.confidence, 'label')}
                lang={lang}
                value={a.confidence.value}
              />
            </div>
          </div>

          <div className="mt-2 flex items-center justify-center">
            <RiskGauge
              score={risk.score}
              tier={risk.tier.key}
              size={214}
              label={t(lang, 'riskScore')}
              lang={lang}
            />
          </div>

          {risk.official_floor_applied && (
            <div className={`mb-2 rounded-lg bg-risk-red/10 px-2.5 py-1.5 text-center text-[11px] font-semibold text-risk-red ${lang === 'hi' ? 'font-devanagari' : ''}`}>
              {lang === 'hi'
                ? `आधिकारिक आँकड़ों ने स्कोर मॉडल के ${risk.model_score.toFixed(0)} से बढ़ाया`
                : `Raised by official data from the model's ${risk.model_score.toFixed(0)}`}
            </div>
          )}
          <div className="flex items-center justify-center gap-3 border-t border-ink-800 pt-2.5">
            <DirectionBadge direction={risk.direction} lang={lang} />
            {risk.ml_probability !== null && risk.ml_probability !== undefined && (
              <span
                className="font-mono text-[10px] text-ink-500"
                title={
                  lang === 'hi'
                    ? 'नियम स्कोर और प्रशिक्षित मॉडल की संभावना'
                    : 'rule score vs. trained-model probability'
                }
              >
                rule {risk.rule_score.toFixed(0)} · model{' '}
                {(risk.ml_probability * 100).toFixed(0)}%
              </span>
            )}
          </div>
        </div>
      </section>

      {/* ------------------------------------------- official government data */}
      <OfficialCard lang={lang} official={a.official} onOpenStation={onOpenStation} replay={replay} />

      {/* -------------------------------------------------------- narrative */}
      <section className="panel shrink-0">
        <SectionHead title={t(lang, 'whyThisScore')} lang={lang} />
        <div className="p-3">
          <p
            className={`text-[12.5px] leading-relaxed text-ink-100 text-balance ${
              lang === 'hi' ? 'font-devanagari' : ''
            }`}
          >
            {pick(lang, a.explanation, 'narrative')}
          </p>

          <ul className="mt-2.5 space-y-1.5">
            {(lang === 'hi' ? a.explanation.bullets_hi : a.explanation.bullets_en).map((b, i) => (
              <li
                key={i}
                className={`flex gap-2 text-[11.5px] leading-snug text-ink-300 ${
                  lang === 'hi' ? 'font-devanagari' : ''
                }`}
              >
                <span
                  className="mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ background: colour }}
                />
                {b}
              </li>
            ))}
          </ul>

          <p className="mt-2.5 border-t border-ink-800 pt-2 text-[10px] leading-snug text-ink-600">
            {pick(lang, a.explanation, 'method_note')}
          </p>
        </div>
      </section>

      {/* ------------------------------------------------- recommended action */}
      <section
        className="panel shrink-0 overflow-hidden"
        style={{ borderColor: `${colour}55`, background: `${colour}0d` }}
      >
        <SectionHead title={t(lang, 'responseActions')} lang={lang} />
        <div className="space-y-2 p-3">
          <div>
            <div className="kicker mb-0.5">IMD</div>
            <p className={`text-[11.5px] leading-snug text-ink-200 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
              {pick(lang, a.actions, 'imd_meaning')}
            </p>
          </div>
          <div>
            <div className="kicker mb-0.5">NDMA</div>
            <p
              className={`text-[11.5px] font-medium leading-snug ${
                lang === 'hi' ? 'font-devanagari' : ''
              }`}
              style={{ color: colour }}
            >
              {pick(lang, a.actions, 'ndma_action')}
            </p>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------ factor bars */}
      <section className="panel shrink-0">
        <SectionHead
          title={t(lang, 'contributingFactors')}
          lang={lang}
          right={
            <span className="font-mono text-[10px] text-ink-500">
              {t(lang, 'riskScore').toLowerCase()} {risk.rule_score.toFixed(1)}
            </span>
          }
        />
        <FactorBars factors={a.factors} lang={lang} ruleScore={risk.rule_score} limit={5} />
      </section>

      {/* ------------------------------------------------------ AI / ML read */}
      <AIAssessmentCard lang={lang} assessment={a} locationsById={locationsById} />

      {/* ------------------------------------------------------- trajectory */}
      <section className="panel shrink-0">
        <SectionHead
          title={t(lang, 'trajectory')}
          lang={lang}
          right={
            <span className="flex items-center gap-1.5 text-[9.5px] text-ink-600">
              <span className="h-2 w-3 rounded-sm bg-saffron-500/25" />
              {t(lang, 'uncertaintyBand')}
            </span>
          }
        />
        <TrajectoryChart trajectory={traj} lang={lang} />
        {risk.peak && (
          <p className={`px-3 pb-2.5 text-[10.5px] text-ink-400 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
            {pick(lang, risk.peak, 'label')}
            {risk.peak.score !== undefined && ` · ${risk.peak.score.toFixed(0)}/100`}
          </p>
        )}
      </section>

      {/* ----------------------------------------------------- river chart */}
      {river.available && (
        <section className="panel shrink-0">
          <SectionHead
            title={t(lang, 'riverState')}
            lang={lang}
            right={
              <span className="font-mono text-[10px] text-ink-500">
                {loc.river ?? '—'} · m³/s
              </span>
            }
          />
          <RiverChart river={timeline?.river ?? river} lang={lang} />
          <div className="px-3 pb-3">
            <DataRow lang={lang} label={t(lang, 'currentDischarge')} value={cumecs(river.current_cumecs)} />
            <DataRow lang={lang} label={t(lang, 'seasonalMedian')} value={cumecs(river.seasonal_median_cumecs)} />
            <DataRow
              lang={lang}
              label={t(lang, 'percentileSeason')}
              value={
                river.percentile_for_season !== null && river.percentile_for_season !== undefined
                  ? `${ordinal(river.percentile_for_season)}`
                  : '—'
              }
            />
            <DataRow
              lang={lang}
              label={t(lang, 'trend')}
              value={
                river.trend_cumecs_per_day !== null && river.trend_cumecs_per_day !== undefined
                  ? `${river.trend_cumecs_per_day > 0 ? '+' : ''}${cumecs(
                      river.trend_cumecs_per_day,
                    )}/day`
                  : '—'
              }
            />
            {river.relative_ensemble_spread !== null &&
              river.relative_ensemble_spread !== undefined && (
                <DataRow
                  lang={lang}
                  label={lang === 'hi' ? 'एन्सेम्बल प्रसार (IQR/माध्यिका)' : 'Ensemble spread (IQR/median)'}
                  value={pct(river.relative_ensemble_spread * 100)}
                />
              )}
            {river.climatology_years && (
              <DataRow
                lang={lang}
                label={lang === 'hi' ? 'आधार रेखा अवधि' : 'Baseline period'}
                value={`${river.climatology_years} · ±${river.climatology_window_days}d`}
              />
            )}
          </div>
        </section>
      )}

      {/* ------------------------------------------------- confidence detail */}
      <Collapsible title={t(lang, 'confidence')} lang={lang}>
        <div className="p-3">
          <div className="mb-2 flex items-center gap-2">
            <ConfidenceChip
              level={a.confidence.level}
              label={pick(lang, a.confidence, 'label')}
              lang={lang}
            />
            <span className="font-mono text-[10px] text-ink-500">
              {(a.confidence.value * 100).toFixed(0)}/100
            </span>
          </div>
          <ul className="space-y-1.5">
            {(lang === 'hi' ? a.confidence.reasons_hi : a.confidence.reasons_en).map((r, i) => (
              <li
                key={i}
                className={`flex gap-2 text-[11px] leading-snug text-ink-300 ${
                  lang === 'hi' ? 'font-devanagari' : ''
                }`}
              >
                <span className="mt-[5px] h-1 w-1 shrink-0 rounded-full bg-ink-500" />
                {r}
              </li>
            ))}
          </ul>
        </div>
      </Collapsible>

      {/* ------------------------------------------------------ observed data */}
      <Collapsible title={t(lang, 'rawData')} lang={lang} defaultOpen>
        <div className="p-3">
          <DataRow lang={lang} label={t(lang, 'rain24')} value={mm(obs.rain_24h_mm)} />
          <DataRow lang={lang} label={t(lang, 'rain72')} value={mm(obs.rain_72h_mm)} />
          <DataRow lang={lang} label={t(lang, 'rain7d')} value={mm(obs.rain_7d_mm)} />
          <DataRow lang={lang} label={t(lang, 'rainNext24')} value={mm(obs.rain_next_24h_mm)} />
          <DataRow lang={lang} label={t(lang, 'rainNext72')} value={mm(obs.rain_next_72h_mm)} />
          <DataRow lang={lang} label={t(lang, 'peakHour')} value={mm(obs.rain_peak_hour_mm)} />
          <DataRow
            lang={lang}
            label={t(lang, 'imdClass')}
            value={obs.imd_class ? (lang === 'hi' ? obs.imd_class.label_hi : obs.imd_class.label_en) : '—'}
          />
          <DataRow
            lang={lang}
            label={t(lang, 'soilMoisture')}
            value={obs.soil_moisture !== null && obs.soil_moisture !== undefined ? `${obs.soil_moisture.toFixed(3)} m³/m³` : '—'}
          />
          <DataRow
            lang={lang}
            label={t(lang, 'elevation')}
            value={loc.elevation_m !== null && loc.elevation_m !== undefined ? `${loc.elevation_m.toFixed(0)} m` : '—'}
          />
          <DataRow
            lang={lang}
            label={t(lang, 'population')}
            value={`${compactPopulation(loc.population)} (${inNumber(loc.population)})`}
          />
          <DataRow
            lang={lang}
            label={t(lang, 'gaugeCell')}
            value={
              loc.glofas_cell?.[0]
                ? `${loc.glofas_cell[0].toFixed(2)}, ${loc.glofas_cell[1].toFixed(2)} (+${loc.glofas_snap_km ?? 0} km)`
                : '—'
            }
          />
          {obs.as_of_hour && (
            <DataRow
              lang={lang}
              label={lang === 'hi' ? 'आँकड़ा घंटा (IST)' : 'Data hour (IST)'}
              value={obs.as_of_hour.replace('T', ' ')}
            />
          )}
        </div>
      </Collapsible>

      {/* ----------------------------------------------- terrain breakdown */}
      {a.terrain?.components && (
        <Collapsible
          title={lang === 'hi' ? 'भूभाग एवं जल निकासी' : 'Terrain & drainage'}
          lang={lang}
        >
          <div className="p-3">
            {Object.entries(a.terrain.components).map(([key, value]) => (
              <DataRow
                key={key}
                lang={lang}
                label={key.replace(/_/g, ' ')}
                value={value.toFixed(0)}
              />
            ))}
            <div className="mt-2 border-t border-ink-800 pt-2">
              <DataRow
                lang={lang}
                label={lang === 'hi' ? 'जल निकासी घनत्व' : 'Drainage density'}
                value={
                  a.terrain.inputs.drainage_density_km_per_km2 !== null &&
                  a.terrain.inputs.drainage_density_km_per_km2 !== undefined
                    ? `${a.terrain.inputs.drainage_density_km_per_km2} km/km²`
                    : '—'
                }
              />
              <DataRow
                lang={lang}
                label={lang === 'hi' ? 'निकटतम जलस्रोत' : 'Nearest water'}
                value={
                  a.terrain.inputs.dist_to_water_km !== null &&
                  a.terrain.inputs.dist_to_water_km !== undefined
                    ? `${a.terrain.inputs.dist_to_water_km} km${
                        a.terrain.inputs.nearest_water_name
                          ? ` · ${a.terrain.inputs.nearest_water_name}`
                          : ''
                      }`
                    : '—'
                }
              />
              <DataRow
                lang={lang}
                label={lang === 'hi' ? 'ढलान' : 'Local slope'}
                value={
                  a.terrain.inputs.slope_deg !== null && a.terrain.inputs.slope_deg !== undefined
                    ? `${a.terrain.inputs.slope_deg}°`
                    : '—'
                }
              />
            </div>
          </div>
        </Collapsible>
      )}

      {/* -------------------------------------------------- score history */}
      {detail.score_history?.length > 1 && (
        <Collapsible title={t(lang, 'scoreHistory')} lang={lang} count={detail.score_history.length}>
          <ScoreHistoryChart history={detail.score_history} lang={lang} />
        </Collapsible>
      )}

      {/* --------------------------------------------------- past events */}
      {a.history?.events?.length > 0 && (
        <Collapsible title={t(lang, 'pastEvents')} lang={lang} count={a.history.count}>
          <ul className="divide-y divide-ink-800/70">
            {a.history.events.map((e) => (
              <li key={`${e.date}-${e.driver}`} className="px-3 py-2">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-mono text-[11px] font-semibold text-saffron-300">
                    {longDateIST(e.date)}
                    {e.date_precision === 'month' && (
                      <span className="ml-1 text-ink-600" title="approximate peak day">
                        ~
                      </span>
                    )}
                  </span>
                  <span className="flex shrink-0 items-center gap-1" title={`severity ${e.severity}`}>
                    {[1, 2, 3].map((s) => (
                      <span
                        key={s}
                        className="h-1.5 w-1.5 rounded-full"
                        style={{
                          background: s <= e.severity ? tierColour('orange') : '#D8DFE7',
                        }}
                      />
                    ))}
                  </span>
                </div>
                <p className="mt-0.5 text-[11px] leading-snug text-ink-300">{e.headline}</p>
                <p className="mt-0.5 text-[9.5px] uppercase tracking-wider text-ink-600">
                  {e.driver.replace(/_/g, ' ')} · {e.years_ago} y ago
                </p>
              </li>
            ))}
          </ul>
        </Collapsible>
      )}

      {/* ----------------------------------------------- simulator + advisory */}
      {!replay && <WhatIfSimulator lang={lang} locationId={loc.id} baselineScore={risk.score} />}
      {!replay && <AdvisoryGenerator lang={lang} locationId={loc.id} />}

      {/* ------------------------------------------------------ event replay */}
      <ReplayPanel lang={lang} locationId={loc.id} events={a.history?.events ?? []} />
    </div>
  );
}
