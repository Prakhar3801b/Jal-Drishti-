import { useEffect, useState } from 'react';
import { api, capLinks } from '../lib/api';
import { compactPopulation, cumecs, inNumber, longDateIST, mm, ordinal, pct, stateName, tierColour } from '../lib/format';
import { pick, t } from '../lib/i18n';
import { href } from '../lib/router';
import { AdvisoryGenerator, AIAssessmentCard, WhatIfSimulator } from '../components/AIPanels';
import { RiverChart, ScoreHistoryChart, TrajectoryChart } from '../components/Charts';
import FactorBars from '../components/FactorBars';
import { UpstreamCard } from '../components/FloodWave';
import { OfficialCard } from '../components/Official';
import { ConfidenceChip, DataRow, DirectionBadge, SectionHead, Spinner, TierChip } from '../components/Primitives';
import ReplayPanel from '../components/ReplayPanel';
import RiskGauge from '../components/RiskGauge';

/**
 * Full hyperlocal assessment for one monitored location, as its own page.
 *
 * Three columns read left to right the way a duty officer triages:
 *   1. the verdict   - score, official gauge reading, why, what to do
 *   2. the evidence  - how risk evolves over 72 h, the river against its seasonal
 *                      normal, the ranked contributing factors, the raw inputs
 *   3. the tools     - independent ML reads, what-if scenarios, the advisory
 *                      draft, replaying past floods here
 */

const hi = (lang) => (lang === 'hi' ? 'font-devanagari' : '');

export default function LocationPage({ lang, id, replayDate, onOpenStation, locationsById, admin = true }) {
  const [detail, setDetail] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    setDetail(null);
    setError(null);
    Promise.all([api.detail(id, replayDate), api.timeline(id, replayDate)])
      .then(([d, tl]) => {
        if (!alive) return;
        setDetail(d);
        setTimeline(tl);
      })
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [id, replayDate]);

  if (error) return <div className="p-6 text-risk-red">{error}</div>;
  if (!detail) return <div className="p-10"><Spinner lang={lang} /></div>;

  const a = detail.assessment;
  const loc = a.location;
  const risk = a.risk;
  const river = a.river ?? {};
  const obs = a.observations ?? {};
  const colour = tierColour(risk.tier.key);

  return (
    <div id="main-content" className="mx-auto w-full max-w-[1600px] space-y-4 p-4">
      {/* ------------------------------------------------------------ title */}
      <div className="flex flex-wrap items-end justify-between gap-3 border-b-2 border-saffron-500 pb-3">
        <div>
          <nav className={`text-[11.5px] text-ink-500 ${hi(lang)}`}>
            <a href={href('/map')} className="text-saffron-300 hover:underline">{t(lang, 'india')}</a>
            {' / '}
            <a href={href(`/state/${loc.state}`)} className="text-saffron-300 hover:underline">{stateName(loc.state, lang)}</a>
            {' / '}
            {lang === 'hi' && loc.name_hi ? loc.name_hi : loc.name}
          </nav>
          <h1 className={`text-2xl font-extrabold tracking-tight text-chakra-500 ${hi(lang)}`}>
            {lang === 'hi' && loc.name_hi ? loc.name_hi : loc.name}
            <span className="ml-2 text-[13px] font-semibold text-ink-500">
              {loc.district} · {loc.river ?? '—'} · {loc.cwc_basin} {lang === 'hi' ? 'बेसिन' : 'basin'}
            </span>
          </h1>
        </div>
        <div className="flex flex-wrap gap-2">
          {!replayDate && (
            <a href={href(`/hotspots/${loc.id}`)} className="btn btn-primary">
              {lang === 'hi' ? 'गली-स्तर हॉटस्पॉट →' : 'Street-level hotspots →'}
            </a>
          )}
          <a href={href('/rivers')} className="btn">{lang === 'hi' ? 'नदी स्थिति →' : 'River status →'}</a>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        {/* ============================================================ col 1 */}
        <div className="space-y-4">
          <section data-tour="loc-risk" className="panel overflow-hidden">
            <div className="h-1.5" style={{ background: colour }} />
            <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-3">
              <TierChip tier={risk.tier.key} lang={lang} showAction size="lg" />
              <div className="flex items-center gap-2">
                <ConfidenceChip level={a.confidence.level} label={pick(lang, a.confidence, 'label')} lang={lang} />
                <DirectionBadge direction={risk.direction} lang={lang} />
              </div>
            </div>
            <div className="flex justify-center">
              <RiskGauge score={risk.score} tier={risk.tier.key} size={250} label={t(lang, 'riskScore')} lang={lang} />
            </div>
            <div className="grid grid-cols-3 border-t border-ink-800 text-center">
              {[
                [lang === 'hi' ? 'मॉडल' : 'Model', risk.model_score?.toFixed(0) ?? '—'],
                [lang === 'hi' ? 'प्रशिक्षित मॉडल' : 'Trained ML', risk.ml_probability != null ? `${(risk.ml_probability * 100).toFixed(0)}%` : '—'],
                [lang === 'hi' ? 'शिखर' : 'Peak', risk.peak ? `${risk.peak.score.toFixed(0)} @ +${risk.peak.hours}h` : '—'],
              ].map(([k, v]) => (
                <div key={k} className="border-r border-ink-800 px-2 py-2 last:border-0">
                  <div className={`text-[9.5px] font-bold uppercase tracking-wider text-ink-500 ${hi(lang)}`}>{k}</div>
                  <div className="font-mono text-[15px] font-bold text-chakra-500">{v}</div>
                </div>
              ))}
            </div>
            {risk.official_floor_applied && (
              <p className={`bg-risk-red/10 px-4 py-2 text-center text-[11.5px] font-semibold text-risk-red ${hi(lang)}`}>
                {lang === 'hi'
                  ? `आधिकारिक आँकड़ों ने स्कोर मॉडल के ${risk.model_score.toFixed(0)} से बढ़ाया`
                  : `Raised by official data from the model's ${risk.model_score.toFixed(0)}`}
              </p>
            )}
          </section>

          <div data-tour="loc-official">
            <OfficialCard lang={lang} official={a.official} onOpenStation={onOpenStation} replay={!!replayDate} />
          </div>

          {!replayDate && <UpstreamCard lang={lang} threats={detail.upstream ?? []} onOpenStation={onOpenStation} />}

          <section data-tour="loc-why" className="panel">
            <SectionHead title={t(lang, 'whyThisScore')} lang={lang} />
            <div className="p-4">
              <p className={`text-[13px] leading-relaxed text-ink-100 ${hi(lang)}`}>{pick(lang, a.explanation, 'narrative')}</p>
              <p className="mt-3 border-t border-ink-800 pt-2 text-[10.5px] text-ink-500">{pick(lang, a.explanation, 'method_note')}</p>
            </div>
          </section>

          <section data-tour="loc-actions" className="panel overflow-hidden" style={{ borderColor: `${colour}55` }}>
            <SectionHead title={t(lang, 'responseActions')} lang={lang} />
            <div className="space-y-2 p-4">
              <p className={`text-[12px] text-ink-300 ${hi(lang)}`}><b className="text-chakra-500">IMD · </b>{pick(lang, a.actions, 'imd_meaning')}</p>
              <p className={`text-[12.5px] font-semibold ${hi(lang)}`} style={{ color: colour }}><b className="text-chakra-500">NDMA · </b>{pick(lang, a.actions, 'ndma_action')}</p>
              {!replayDate && risk.tier.key !== 'green' && (
                <a href={capLinks.alert(loc.id)} target="_blank" rel="noreferrer" className="inline-block pt-1 text-[11px] font-semibold text-chakra-500 underline-offset-2 hover:underline">
                  {lang === 'hi' ? 'CAP 1.2 संदेश (XML) देखें ↗' : 'View as CAP 1.2 alert (XML) ↗'}
                </a>
              )}
            </div>
          </section>
        </div>

        {/* ============================================================ col 2 */}
        <div className="space-y-4">
          <section data-tour="loc-trajectory" className="panel">
            <SectionHead title={t(lang, 'trajectory')} lang={lang} right={<span className="text-[10px] text-ink-500">{t(lang, 'uncertaintyBand')}</span>} />
            <TrajectoryChart trajectory={timeline?.trajectory ?? a.trajectory} lang={lang} height={230} />
          </section>

          {river.available && (
            <section data-tour="loc-river" className="panel">
              <SectionHead title={t(lang, 'riverState')} lang={lang} right={<span className="font-mono text-[10px] text-ink-500">GloFAS · m³/s</span>} />
              <RiverChart river={timeline?.river ?? river} lang={lang} height={210} />
              <div className="grid grid-cols-2 gap-x-6 px-4 pb-3">
                <DataRow lang={lang} label={t(lang, 'currentDischarge')} value={cumecs(river.current_cumecs)} />
                <DataRow lang={lang} label={t(lang, 'seasonalMedian')} value={cumecs(river.seasonal_median_cumecs)} />
                <DataRow lang={lang} label={t(lang, 'percentileSeason')} value={river.percentile_for_season != null ? ordinal(river.percentile_for_season) : '—'} />
                <DataRow lang={lang} label={lang === 'hi' ? 'एन्सेम्बल प्रसार' : 'Ensemble spread'} value={river.relative_ensemble_spread != null ? pct(river.relative_ensemble_spread * 100) : '—'} />
              </div>
            </section>
          )}

          <section data-tour="loc-factors" className="panel">
            <SectionHead title={t(lang, 'contributingFactors')} lang={lang} />
            <FactorBars factors={a.factors} lang={lang} ruleScore={risk.rule_score} />
          </section>

          <section data-tour="loc-raw" className="panel">
            <SectionHead title={t(lang, 'rawData')} lang={lang} />
            <div className="grid grid-cols-1 gap-x-6 px-4 py-2 sm:grid-cols-2">
              <DataRow lang={lang} label={t(lang, 'rain24')} value={mm(obs.rain_24h_mm)} />
              <DataRow lang={lang} label={t(lang, 'rain72')} value={mm(obs.rain_72h_mm)} />
              <DataRow lang={lang} label={t(lang, 'rainNext24')} value={mm(obs.rain_next_24h_mm)} />
              <DataRow lang={lang} label={t(lang, 'rainNext72')} value={mm(obs.rain_next_72h_mm)} />
              <DataRow lang={lang} label={t(lang, 'imdClass')} value={obs.imd_class ? pick(lang, obs.imd_class, 'label') : '—'} />
              <DataRow lang={lang} label={t(lang, 'soilMoisture')} value={obs.soil_moisture != null ? `${obs.soil_moisture.toFixed(3)} m³/m³` : '—'} />
              <DataRow lang={lang} label={t(lang, 'elevation')} value={loc.elevation_m != null ? `${loc.elevation_m.toFixed(0)} m` : '—'} />
              <DataRow lang={lang} label={t(lang, 'population')} value={`${compactPopulation(loc.population)} (${inNumber(loc.population)})`} />
            </div>
          </section>

          {detail.score_history?.length > 1 && (
            <section data-tour="loc-history" className="panel">
              <SectionHead title={t(lang, 'scoreHistory')} lang={lang} />
              <ScoreHistoryChart history={detail.score_history} lang={lang} height={120} />
            </section>
          )}
        </div>

        {/* ============================================================ col 3 */}
        <div className="space-y-4">
          <div data-tour="loc-ai">
            <AIAssessmentCard lang={lang} assessment={a} locationsById={locationsById} />
          </div>
          {/* What-if, advisory drafts and replay are control-room tools (the server refuses them for citizens). */}
          {admin && !replayDate && (
            <div data-tour="loc-whatif">
              <WhatIfSimulator lang={lang} locationId={loc.id} baselineScore={risk.score} />
            </div>
          )}
          {admin && !replayDate && (
            <div data-tour="loc-advisory">
              <AdvisoryGenerator lang={lang} locationId={loc.id} />
            </div>
          )}
          {admin && (
            <div data-tour="loc-replay">
              <ReplayPanel lang={lang} locationId={loc.id} events={a.history?.events ?? []} />
            </div>
          )}
          {a.history?.events?.length > 0 && (
            <section data-tour="loc-events" className="panel">
              <SectionHead title={t(lang, 'pastEvents')} lang={lang} right={<span className="text-[10px] text-ink-500">{a.history.count}</span>} />
              <ul className="divide-y divide-ink-800">
                {a.history.events.map((e) => (
                  <li key={e.date} className="px-4 py-2">
                    <div className="font-mono text-[11.5px] font-bold text-saffron-300">{longDateIST(e.date)}</div>
                    <p className="text-[12px] text-ink-200">{e.headline}</p>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
