import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { longDateIST, mm, tierColour, TIER_LABELS } from '../lib/format';
import { SectionHead } from './Primitives';

/**
 * The AI/ML layer of the hyperlocal panel.
 *
 *   AIAssessmentCard   what three independent ML reads say about this place
 *   WhatIfSimulator    perturb the live inputs and re-score through the real engine
 *   AdvisoryGenerator  a bilingual public advisory + SMS, LLM-written or templated
 *
 * Each is honest about where its answer came from: every card names its method
 * (Isolation Forest, k-NN over N real days, logistic model, which LLM provider or
 * "offline template"), because a model the reader cannot identify is a model the
 * reader cannot weigh.
 */

const hi = (lang) => (lang === 'hi' ? 'font-devanagari' : '');

function Badge({ children, tone = 'navy' }) {
  const tones = {
    navy: 'border-chakra-500/25 bg-navy-50 text-chakra-500',
    saffron: 'border-saffron-500/40 bg-saffron-50 text-saffron-300',
    green: 'border-indiagreen-500/30 bg-indiagreen-500/[0.07] text-indiagreen-300',
    grey: 'border-ink-700 bg-ink-850 text-ink-400',
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[9.5px] font-bold uppercase tracking-wider ${tones[tone]}`}>
      {children}
    </span>
  );
}

function Meter({ value, colour = '#F26A1B' }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-800">
      <div
        className="h-full rounded-full transition-[width] duration-700 ease-out"
        style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: colour }}
      />
    </div>
  );
}

const ANOMALY_TONE = {
  normal: '#0B8A3D',
  elevated: '#C99700',
  high: '#E4701E',
  extreme: '#C1121F',
};

const ANOMALY_LABEL = {
  normal: ['Normal', 'सामान्य'],
  elevated: ['Elevated', 'बढ़ा हुआ'],
  high: ['Highly unusual', 'अत्यधिक असामान्य'],
  extreme: ['Extreme', 'चरम'],
};

/* ------------------------------------------------------------ AI assessment */

export function AIAssessmentCard({ lang, assessment, locationsById = {} }) {
  const ai = assessment?.ai;
  if (!ai) return null;
  const { analogs, anomaly, model_attribution: attribution, forecast_consensus: consensus } = ai;
  const risk = assessment.risk;
  const maxAttr = Math.max(...(attribution ?? []).map((r) => Math.abs(r.log_odds)), 0.01);

  return (
    <section className="panel shrink-0 overflow-hidden">
      <div className="h-1 w-full bg-gradient-to-r from-chakra-500 via-saffron-500 to-indiagreen-500" />
      <SectionHead
        title={lang === 'hi' ? 'एआई / एमएल आकलन' : 'AI / ML assessment'}
        lang={lang}
        right={<Badge tone="navy">{lang === 'hi' ? '3 स्वतंत्र मॉडल' : '3 independent models'}</Badge>}
      />

      <div className="grid gap-3 p-3">
        {/* model agreement strip */}
        <div className="grid grid-cols-3 gap-1.5">
          <div className="panel-tight px-2 py-1.5 text-center">
            <div className={`text-[9.5px] font-semibold uppercase tracking-wide text-ink-500 ${hi(lang)}`}>
              {lang === 'hi' ? 'नियम स्कोर' : 'Rule score'}
            </div>
            <div className="font-mono text-lg font-bold text-chakra-500">{risk.rule_score.toFixed(0)}</div>
          </div>
          <div className="panel-tight px-2 py-1.5 text-center">
            <div className={`text-[9.5px] font-semibold uppercase tracking-wide text-ink-500 ${hi(lang)}`}>
              {lang === 'hi' ? 'लॉजिस्टिक' : 'Logistic'}
            </div>
            <div className="font-mono text-lg font-bold text-chakra-500">
              {risk.ml_probability !== null && risk.ml_probability !== undefined
                ? `${(risk.ml_probability * 100).toFixed(0)}%`
                : '—'}
            </div>
          </div>
          <div className="panel-tight px-2 py-1.5 text-center">
            <div className={`text-[9.5px] font-semibold uppercase tracking-wide text-ink-500 ${hi(lang)}`}>
              {lang === 'hi' ? 'एनालॉग k-NN' : 'Analog k-NN'}
            </div>
            <div className="font-mono text-lg font-bold text-chakra-500">
              {analogs?.available ? `${(analogs.knn_flood_probability * 100).toFixed(0)}%` : '—'}
            </div>
          </div>
        </div>

        {/* anomaly */}
        {anomaly?.available && (
          <div>
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <span className={`text-[11.5px] font-semibold text-ink-200 ${hi(lang)}`}>
                {lang === 'hi' ? 'असामान्यता पहचान' : 'Anomaly detection'}
              </span>
              <span className="font-mono text-[11px] font-bold" style={{ color: ANOMALY_TONE[anomaly.level] }}>
                {anomaly.score.toFixed(0)} · {ANOMALY_LABEL[anomaly.level][lang === 'hi' ? 1 : 0]}
              </span>
            </div>
            <Meter value={anomaly.score} colour={ANOMALY_TONE[anomaly.level]} />
            <p className={`mt-1 text-[10.5px] leading-snug text-ink-400 ${hi(lang)}`}>
              {anomaly.unusual_features?.length
                ? (lang === 'hi' ? 'सामान्य दिनों की तुलना में असामान्य: ' : 'Unusual vs. normal days: ') +
                  anomaly.unusual_features.map((f) => (lang === 'hi' ? f.label_hi : f.label_en)).join(', ')
                : lang === 'hi'
                  ? 'इन परिस्थितियों का संयोजन सामान्य दिनों जैसा है।'
                  : 'This combination of conditions looks like an ordinary day.'}
            </p>
            <p className="mt-0.5 text-[9.5px] text-ink-500">
              {anomaly.method === 'isolation_forest'
                ? lang === 'hi'
                  ? 'आइसोलेशन फ़ॉरेस्ट, गैर-बाढ़ ऐतिहासिक दिनों पर प्रशिक्षित'
                  : 'Isolation Forest trained on historical non-flood days'
                : lang === 'hi'
                  ? 'आज के राष्ट्रीय वितरण के सापेक्ष z-स्कोर'
                  : 'z-score against today’s national spread'}
            </p>
          </div>
        )}

        {/* analogs */}
        {analogs?.available && analogs.matches?.length > 0 && (
          <div>
            <div className="mb-1.5 flex items-baseline justify-between gap-2">
              <span className={`text-[11.5px] font-semibold text-ink-200 ${hi(lang)}`}>
                {lang === 'hi' ? 'सबसे मिलती-जुलती पिछली बाढ़' : 'Most similar past floods'}
              </span>
              <span className="text-[9.5px] text-ink-500">
                k-NN · {analogs.training_days} {lang === 'hi' ? 'वास्तविक दिन' : 'real days'}
              </span>
            </div>
            <ul className="space-y-1.5">
              {analogs.matches.map((m) => {
                const place = locationsById[m.location_id];
                const name = place ? (lang === 'hi' && place.name_hi ? place.name_hi : place.name) : m.location_id;
                return (
                  <li key={`${m.location_id}-${m.date}`} className="panel-tight px-2.5 py-1.5">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className={`truncate text-[11.5px] font-semibold text-chakra-500 ${hi(lang)}`}>
                        {name} · <span className="font-mono text-saffron-300">{longDateIST(m.date)}</span>
                      </span>
                      <span className="shrink-0 font-mono text-[11px] font-bold text-ink-200">
                        {(m.similarity * 100).toFixed(0)}%
                      </span>
                    </div>
                    {m.headline && <p className="mt-0.5 line-clamp-2 text-[10.5px] leading-snug text-ink-400">{m.headline}</p>}
                    <div className="mt-1">
                      <Meter value={m.similarity * 100} colour="#0B2A5B" />
                    </div>
                  </li>
                );
              })}
            </ul>
            <p className={`mt-1 text-[10px] text-ink-500 ${hi(lang)}`}>
              {lang === 'hi'
                ? `सबसे निकट ${analogs.k} ऐतिहासिक दिनों में से ${analogs.neighbours_that_flooded} में बाढ़ आई थी।`
                : `${analogs.neighbours_that_flooded} of the ${analogs.k} most similar historical days were flood days.`}
            </p>
          </div>
        )}
        {analogs && !analogs.available && (
          <p className="text-[10.5px] text-ink-500">
            {lang === 'hi' ? 'एनालॉग खोज हेतु मॉडल प्रशिक्षण आवश्यक।' : 'Analog search activates once the ML bootstrap has run.'}
          </p>
        )}

        {/* forecast consensus */}
        <div className="panel-tight px-2.5 py-2">
          <div className="flex items-baseline justify-between gap-2">
            <span className={`text-[11.5px] font-semibold text-ink-200 ${hi(lang)}`}>
              {lang === 'hi' ? 'बहु-मॉडल पूर्वानुमान सहमति' : 'Multi-model forecast consensus'}
            </span>
            {consensus?.available ? (
              <Badge tone={consensus.level === 'strong' ? 'green' : consensus.level === 'conflict' ? 'saffron' : 'grey'}>
                {consensus.level}
              </Badge>
            ) : (
              <Badge tone="grey">{lang === 'hi' ? 'कुंजी नहीं' : 'no key'}</Badge>
            )}
          </div>
          {consensus?.available ? (
            <p className="mt-1 font-mono text-[10.5px] text-ink-400">
              Open-Meteo {mm(consensus.open_meteo_mm)} · OpenWeatherMap {mm(consensus.openweathermap_mm)} ·{' '}
              {(consensus.agreement * 100).toFixed(0)}%
            </p>
          ) : (
            <p className={`mt-1 text-[10.5px] text-ink-500 ${hi(lang)}`}>
              {lang === 'hi'
                ? 'मुफ़्त OPENWEATHER_API_KEY जोड़ने पर दूसरा स्वतंत्र वर्षा पूर्वानुमान सक्रिय होगा।'
                : 'Add a free OPENWEATHER_API_KEY to cross-check rainfall against a second, independent forecast.'}
            </p>
          )}
        </div>

        {/* model attribution */}
        {attribution && (
          <div>
            <div className={`mb-1.5 text-[11.5px] font-semibold text-ink-200 ${hi(lang)}`}>
              {lang === 'hi' ? 'प्रशिक्षित मॉडल क्या देख रहा है' : 'What the trained model is weighing'}
            </div>
            <ul className="space-y-1">
              {attribution.slice(0, 5).map((r) => (
                <li key={r.key} className="grid grid-cols-[1fr_90px_42px] items-center gap-2">
                  <span className={`truncate text-[10.5px] text-ink-300 ${hi(lang)}`}>
                    {lang === 'hi' ? r.label_hi : r.label_en}
                  </span>
                  <span className="relative h-1.5 rounded-full bg-ink-800">
                    <span
                      className="absolute inset-y-0 rounded-full"
                      style={{
                        left: r.log_odds >= 0 ? '50%' : `${50 - (Math.abs(r.log_odds) / maxAttr) * 50}%`,
                        width: `${(Math.abs(r.log_odds) / maxAttr) * 50}%`,
                        background: r.log_odds >= 0 ? '#C1121F' : '#0B8A3D',
                      }}
                    />
                    <span className="absolute inset-y-[-2px] left-1/2 w-px bg-ink-500" />
                  </span>
                  <span className="text-right font-mono text-[10px] text-ink-400">
                    {r.log_odds > 0 ? '+' : ''}
                    {r.log_odds.toFixed(2)}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-1 text-[9.5px] text-ink-500">
              {lang === 'hi'
                ? 'लॉग-ऑड्स योगदान: लाल जोखिम बढ़ाता है, हरा घटाता है'
                : 'Exact log-odds contributions: red raises flood probability, green lowers it'}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ what-if */

const SLIDERS = [
  { key: 'extra_rain_past_24h', en: 'Extra rain, last 24 h', hi: 'पिछले 24 घंटे में अतिरिक्त वर्षा', min: 0, max: 300, step: 5, unit: 'mm', def: 0 },
  { key: 'extra_rain_next_24h', en: 'Extra rain, next 24 h', hi: 'अगले 24 घंटे में अतिरिक्त वर्षा', min: 0, max: 300, step: 5, unit: 'mm', def: 0 },
  { key: 'discharge_multiplier', en: 'River discharge ×', hi: 'नदी प्रवाह गुणक ×', min: 0.5, max: 4, step: 0.1, unit: '×', def: 1 },
];

const PRESETS = [
  { en: 'Cloudburst', hi: 'बादल फटना', v: { extra_rain_past_24h: 150, extra_rain_next_24h: 60, discharge_multiplier: 1.4 } },
  { en: 'Dam release', hi: 'बाँध से जल छोड़ना', v: { extra_rain_past_24h: 0, extra_rain_next_24h: 0, discharge_multiplier: 3 } },
  { en: 'Cyclone landfall', hi: 'चक्रवात', v: { extra_rain_past_24h: 90, extra_rain_next_24h: 220, discharge_multiplier: 1.8 } },
];

export function WhatIfSimulator({ lang, locationId, baselineScore }) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState({ extra_rain_past_24h: 0, extra_rain_next_24h: 0, discharge_multiplier: 1 });
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    setValues({ extra_rain_past_24h: 0, extra_rain_next_24h: 0, discharge_multiplier: 1 });
    setResult(null);
  }, [locationId]);

  useEffect(() => {
    if (!open) return;
    clearTimeout(timer.current);
    // Debounced: the engine re-scores the whole assessment on every call.
    timer.current = setTimeout(async () => {
      setBusy(true);
      setError(null);
      try {
        setResult(await api.simulate(locationId, values));
      } catch (err) {
        setError(err.message);
      } finally {
        setBusy(false);
      }
    }, 280);
    return () => clearTimeout(timer.current);
  }, [values, open, locationId]);

  const scen = result?.scenario;
  const tier = scen?.risk?.tier?.key;

  return (
    <section className="panel shrink-0">
      <button
        type="button"
        className="panel-head w-full text-left transition hover:bg-ink-850"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <h3 className={`panel-title flex items-center gap-2 ${hi(lang)}`}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
          </svg>
          {lang === 'hi' ? 'क्या-यदि सिम्युलेटर' : 'What-if simulator'}
        </h3>
        <Badge tone="saffron">{lang === 'hi' ? 'लाइव इंजन' : 'live engine'}</Badge>
      </button>

      {open && (
        <div className="animate-fade-up space-y-3 p-3">
          <p className={`text-[10.5px] leading-snug text-ink-400 ${hi(lang)}`}>
            {lang === 'hi'
              ? 'वास्तविक वर्षा व नदी श्रृंखला को बदलकर उसी जोखिम इंजन व एमएल मॉडल से पुनः स्कोर करें।'
              : 'Perturb the real rainfall and river series and re-score them through the same engine and ML models.'}
          </p>

          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((p) => (
              <button key={p.en} type="button" className="chip border-ink-700 bg-ink-850 text-ink-300 hover:border-saffron-500 hover:text-saffron-300" onClick={() => setValues(p.v)}>
                <span className={hi(lang)}>{lang === 'hi' ? p.hi : p.en}</span>
              </button>
            ))}
            <button type="button" className="chip border-transparent text-ink-500 hover:text-ink-200" onClick={() => setValues({ extra_rain_past_24h: 0, extra_rain_next_24h: 0, discharge_multiplier: 1 })}>
              {lang === 'hi' ? 'रीसेट' : 'Reset'}
            </button>
          </div>

          {SLIDERS.map((s) => (
            <label key={s.key} className="block">
              <span className="mb-1 flex items-baseline justify-between">
                <span className={`text-[11px] text-ink-300 ${hi(lang)}`}>{lang === 'hi' ? s.hi : s.en}</span>
                <span className="font-mono text-[11px] font-bold text-chakra-500">
                  {s.unit === '×' ? `${values[s.key].toFixed(1)}×` : `+${values[s.key]} mm`}
                </span>
              </span>
              <input
                type="range"
                min={s.min}
                max={s.max}
                step={s.step}
                value={values[s.key]}
                onChange={(e) => setValues((v) => ({ ...v, [s.key]: Number(e.target.value) }))}
                className="w-full accent-saffron-500"
              />
            </label>
          ))}

          {error && <p className="text-[11px] text-risk-red">{error}</p>}

          {scen && (
            <div className="panel-tight p-2.5" style={{ borderColor: `${tierColour(tier)}66` }}>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className={`text-[10px] font-semibold uppercase tracking-wide text-ink-500 ${hi(lang)}`}>
                    {lang === 'hi' ? 'परिदृश्य स्कोर' : 'Scenario score'}
                  </div>
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-3xl font-extrabold" style={{ color: tierColour(tier) }}>
                      {scen.risk.score.toFixed(0)}
                    </span>
                    <span className={`text-[11px] font-semibold ${hi(lang)}`} style={{ color: tierColour(tier) }}>
                      {lang === 'hi' ? TIER_LABELS[tier].hi : TIER_LABELS[tier].en}
                    </span>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] text-ink-500">{lang === 'hi' ? 'वर्तमान' : 'Now'} {baselineScore?.toFixed(0)}</div>
                  <div className={`font-mono text-lg font-bold ${result.delta > 0 ? 'text-risk-red' : result.delta < 0 ? 'text-indiagreen-300' : 'text-ink-400'}`}>
                    {result.delta > 0 ? '+' : ''}
                    {result.delta?.toFixed(1)}
                  </div>
                </div>
              </div>
              <p className={`mt-1.5 text-[10.5px] leading-snug text-ink-300 ${hi(lang)}`}>
                {lang === 'hi' ? scen.actions.ndma_action_hi : scen.actions.ndma_action_en}
              </p>
              <div className="mt-1.5 flex flex-wrap gap-x-3 text-[10px] text-ink-500">
                <span>
                  {lang === 'hi' ? 'शीर्ष कारक' : 'Top driver'}: <b className="text-ink-300">{lang === 'hi' ? scen.factors[0].label_hi : scen.factors[0].label_en}</b>
                </span>
                {scen.risk.ml_probability != null && (
                  <span>
                    {lang === 'hi' ? 'मॉडल' : 'Model'}: <b className="text-ink-300">{(scen.risk.ml_probability * 100).toFixed(0)}%</b>
                  </span>
                )}
                {scen.ai?.analogs?.available && (
                  <span>
                    k-NN: <b className="text-ink-300">{(scen.ai.analogs.knn_flood_probability * 100).toFixed(0)}%</b>
                  </span>
                )}
              </div>
            </div>
          )}
          {busy && <div className="h-0.5 overflow-hidden rounded bg-ink-800"><div className="h-full w-1/3 animate-sheen bg-saffron-500" /></div>}
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------------------------ advisory */

function CopyButton({ text, lang }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="btn btn-ghost px-2 py-1 text-[10px]"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1600);
        } catch {
          /* clipboard blocked; the text is still selectable */
        }
      }}
    >
      {done ? (lang === 'hi' ? 'कॉपी हुआ ✓' : 'Copied ✓') : lang === 'hi' ? 'कॉपी' : 'Copy'}
    </button>
  );
}

export function AdvisoryGenerator({ lang, locationId }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [view, setView] = useState(lang);

  useEffect(() => {
    setData(null);
    setError(null);
  }, [locationId]);
  useEffect(() => setView(lang), [lang]);

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      setData(await api.advisory(locationId));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const doc = data?.[view];

  return (
    <section className="panel shrink-0">
      <SectionHead
        title={lang === 'hi' ? 'एआई जन-सलाह जनरेटर' : 'AI public advisory generator'}
        lang={lang}
        right={data && <Badge tone={data.provider === 'offline' ? 'grey' : 'green'}>{data.provider === 'offline' ? 'template' : data.provider}</Badge>}
      />
      <div className="p-3">
        {!data && (
          <>
            <p className={`mb-2.5 text-[10.5px] leading-snug text-ink-400 ${hi(lang)}`}>
              {lang === 'hi'
                ? 'इस स्थान के वर्तमान आँकड़ों से हिंदी व अंग्रेज़ी में जन-सलाह और एसएमएस तैयार करें।'
                : 'Draft a bilingual public advisory and SMS from this location’s current data, ready for review.'}
            </p>
            <button type="button" className="btn btn-primary w-full" onClick={generate} disabled={busy}>
              {busy ? (
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" />
              ) : (
                <span className={hi(lang)}>{lang === 'hi' ? 'सलाह तैयार करें' : 'Generate advisory'}</span>
              )}
            </button>
          </>
        )}
        {error && <p className="mt-2 text-[11px] text-risk-red">{error}</p>}

        {doc && (
          <div className="animate-fade-up space-y-2">
            <div className="flex items-center gap-1">
              {['en', 'hi'].map((k) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => setView(k)}
                  className={`rounded px-2 py-0.5 text-[10.5px] font-semibold ${view === k ? 'bg-chakra-500 text-white' : 'text-ink-400 hover:bg-ink-800'} ${k === 'hi' ? 'font-devanagari' : ''}`}
                >
                  {k === 'en' ? 'English' : 'हिंदी'}
                </button>
              ))}
              <button type="button" className="btn btn-ghost ml-auto px-2 py-1 text-[10px]" onClick={generate} disabled={busy}>
                {lang === 'hi' ? 'पुनः बनाएँ' : 'Regenerate'}
              </button>
            </div>

            <div className="rounded-lg border-l-4 border-saffron-500 bg-saffron-50 p-2.5">
              <div className="flex items-start justify-between gap-2">
                <h4 className={`text-[12.5px] font-bold text-chakra-500 ${view === 'hi' ? 'font-devanagari' : ''}`}>{doc.title}</h4>
                <CopyButton text={`${doc.title}\n\n${doc.body}`} lang={lang} />
              </div>
              <p className={`mt-1 whitespace-pre-line text-[11.5px] leading-relaxed text-ink-200 ${view === 'hi' ? 'font-devanagari' : ''}`}>
                {doc.body}
              </p>
            </div>

            <div className="panel-tight p-2.5">
              <div className="mb-1 flex items-center justify-between">
                <span className="kicker">SMS · {doc.sms.length}/160</span>
                <CopyButton text={doc.sms} lang={lang} />
              </div>
              <p className={`font-mono text-[11px] text-ink-200 ${view === 'hi' ? 'font-devanagari' : ''}`}>{doc.sms}</p>
            </div>

            <p className={`text-[9.5px] leading-snug text-ink-500 ${hi(lang)}`}>
              {lang === 'hi'
                ? 'मसौदा — जारी करने से पहले अधिकृत अधिकारी द्वारा सत्यापन आवश्यक।'
                : 'Draft only — must be verified by an authorised officer before release.'}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
