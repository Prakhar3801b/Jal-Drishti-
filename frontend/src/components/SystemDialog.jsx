import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { relativeAge, tierColour, TIER_ORDER } from '../lib/format';
import { t } from '../lib/i18n';
import { AshokaChakra } from './Chrome';

/**
 * "How this is calculated" — the model card, the alert scale, the data sources
 * with their licences, and the run log.
 *
 * A dashboard that scores places and recommends evacuations owes the reader this
 * page. It is also the fastest way to answer the two questions every reviewer
 * asks: where did the numbers come from, and what exactly is the model.
 */

const TABS = [
  ['model', 'modelCard'],
  ['ai', 'aiKeys'],
  ['scale', 'alertLevels'],
  ['sources', 'dataSources'],
  ['runs', 'runLog'],
];

export default function SystemDialog({ lang, system, open, onClose }) {
  const [tab, setTab] = useState('model');
  const [ai, setAi] = useState(null);

  useEffect(() => {
    if (open) api.aiStatus().then(setAi).catch(() => {});
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [open, onClose]);

  const maxWeight = useMemo(
    () => Math.max(...(system?.model?.features ?? [{ weight: 1 }]).map((f) => f.weight), 0.01),
    [system],
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-navy-800/45 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={t(lang, 'howItWorks')}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="panel flex max-h-[88vh] w-full max-w-3xl animate-fade-up flex-col overflow-hidden">
        {/* header */}
        <div className="flex shrink-0 items-center gap-3 border-b border-ink-700/70 px-4 py-3">
          <span className="text-chakra-300">
            <AshokaChakra size={22} />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className={`text-sm font-bold text-chakra-500 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
              {t(lang, 'howItWorks')}
            </h2>
            <p className="truncate text-[10.5px] text-ink-500">
              {system?.coverage?.locations} locations · {system?.coverage?.states} states ·{' '}
              {system?.coverage?.historical_events} historical events
            </p>
          </div>
          <button type="button" className="btn btn-ghost px-2 py-1" onClick={onClose} aria-label={t(lang, 'close')}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
              <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* tabs */}
        <div className="flex shrink-0 gap-1 border-b border-ink-700/70 px-3 py-2">
          {TABS.map(([key, labelKey]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={`rounded-md px-2.5 py-1 text-[11px] font-semibold transition ${
                tab === key ? 'bg-saffron-500 text-white' : 'text-ink-400 hover:text-ink-100'
              } ${lang === 'hi' ? 'font-devanagari' : ''}`}
            >
              {labelKey === 'aiKeys' ? (lang === 'hi' ? 'एआई व एपीआई कुंजियाँ' : 'AI & API keys') : t(lang, labelKey)}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4 scrollbar-thin">
          {/* ------------------------------------------------------- model */}
          {tab === 'model' && system?.model && (
            <div className="space-y-4">
              <p
                className={`text-[12px] leading-relaxed text-ink-200 ${
                  lang === 'hi' ? 'font-devanagari' : ''
                }`}
              >
                {lang === 'hi'
                  ? 'जोखिम स्कोर दस नामित कारकों का भारित योग है, जिन्हें IMD की वर्षा श्रेणियों एवं CWC के चेतावनी गुणकों पर सामान्यीकृत किया गया है। ऐतिहासिक घटनाओं पर प्रशिक्षित एक लॉजिस्टिक मॉडल इसे अंशांकित करता है, परंतु नियम-आधारित भाग बहुमत रखता है ताकि प्रत्येक संख्या समझाई जा सके।'
                  : 'The risk score is a weighted sum of named features, each normalised against published thresholds — IMD rainfall classes and CWC warning multiples — rather than against an arbitrary maximum. A logistic model trained on the historical register calibrates the result, but the rules keep the majority share so every number can be explained.'}
              </p>

              <div>
                <div className="kicker mb-2">{t(lang, 'featureWeights')}</div>
                <ul className="space-y-1.5">
                  {system.model.features.map((f) => (
                    <li key={f.key} className="flex items-center gap-2.5">
                      <span
                        className={`w-52 shrink-0 truncate text-[11px] text-ink-300 ${
                          lang === 'hi' ? 'font-devanagari' : ''
                        }`}
                      >
                        {lang === 'hi' ? f.label_hi : f.label_en}
                      </span>
                      <span className="h-[7px] flex-1 overflow-hidden rounded-full bg-ink-800">
                        <span
                          className="block h-full rounded-full bg-gradient-to-r from-saffron-600 to-saffron-400"
                          style={{ width: `${(f.weight / maxWeight) * 100}%` }}
                        />
                      </span>
                      <span className="w-10 shrink-0 text-right font-mono text-[10.5px] text-ink-200">
                        {f.weight.toFixed(2)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>

              {system.model.trained_model ? (
                <div className="panel-tight p-3">
                  <div className="kicker mb-1.5">
                    {lang === 'hi' ? 'प्रशिक्षित वर्गीकारक' : 'Trained classifier'}
                  </div>
                  <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
                    <div className="data-row">
                      <span className="data-label">kind</span>
                      <span className="data-value">{system.model.trained_model.kind}</span>
                    </div>
                    <div className="data-row">
                      <span className="data-label">samples</span>
                      <span className="data-value">{system.model.trained_model.n_samples}</span>
                    </div>
                    {Object.entries(system.model.trained_model.metrics ?? {}).map(([k, v]) => (
                      <div className="data-row" key={k}>
                        <span className="data-label">{k}</span>
                        <span className="data-value">
                          {typeof v === 'number' ? v.toFixed(3) : String(v)}
                        </span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-2 text-[10px] text-ink-600">
                    {lang === 'hi'
                      ? 'गुणांक JSON में संग्रहीत हैं ताकि समीक्षा योग्य रहें।'
                      : 'Coefficients are stored as reviewable JSON, not a pickle.'}
                  </p>
                </div>
              ) : (
                <div className="panel-tight p-3 text-[11px] text-ink-400">
                  {lang === 'hi'
                    ? 'कोई प्रशिक्षित मॉडल लोड नहीं — स्कोर पूर्णतः नियम-आधारित है। प्रशिक्षण हेतु scripts/train_model.py चलाएँ।'
                    : 'No trained model loaded — the score is purely rule-based. Run scripts/train_model.py to fit one against the historical register.'}
                </div>
              )}

              <div>
                <div className="kicker mb-2">
                  {lang === 'hi' ? 'IMD वर्षा श्रेणियाँ (24 घंटे)' : 'IMD rainfall classes (24 h)'}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {system.model.imd_rain_classes.map((c) => (
                    <span key={c.key} className="chip border-ink-600/70 bg-ink-850/70 text-ink-300">
                      <span className={lang === 'hi' ? 'font-devanagari' : ''}>
                        {lang === 'hi' ? c.label_hi : c.label_en}
                      </span>
                      <span className="font-mono text-[9.5px] text-ink-500">
                        {c.min}–{c.max > 1000 ? '∞' : c.max} mm
                      </span>
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ---------------------------------------------------------- ai */}
          {tab === 'ai' && (
            <div className="space-y-3">
              <p className={`text-[12px] leading-relaxed text-ink-300 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
                {lang === 'hi'
                  ? 'सभी कुंजियाँ वैकल्पिक हैं। बिना कुंजी के भी डैशबोर्ड वास्तविक सार्वजनिक आँकड़ों पर चलता है। backend/.env में कुंजी जोड़ें और सर्वर पुनः आरंभ करें।'
                  : 'Every key is optional — without any, the dashboard still runs on real public data and the AI features use data-grounded fallbacks. Add keys to backend/.env and restart the backend.'}
              </p>
              {[
                ['GEMINI_API_KEY', 'Google Gemini', lang === 'hi' ? 'मुफ़्त · सहायक व सलाह' : 'Free tier · Copilot + advisories', 'https://aistudio.google.com/apikey', ai?.llm?.active?.includes('gemini')],
                ['GROQ_API_KEY', 'Groq (Llama)', lang === 'hi' ? 'मुफ़्त · सहायक व सलाह' : 'Free tier · Copilot + advisories', 'https://console.groq.com/keys', ai?.llm?.active?.includes('groq')],
                ['ANTHROPIC_API_KEY', 'Anthropic Claude', lang === 'hi' ? 'सशुल्क · सर्वोत्तम उत्तर' : 'Paid · highest-quality answers', 'https://console.anthropic.com/', ai?.llm?.active?.includes('anthropic')],
                ['OPENWEATHER_API_KEY', 'OpenWeatherMap', lang === 'hi' ? 'मुफ़्त · दूसरा वर्षा पूर्वानुमान' : 'Free · second rainfall forecast for consensus', 'https://home.openweathermap.org/api_keys', ai?.openweathermap?.enabled],
              ].map(([env, name, what, url, on]) => (
                <div key={env} className="panel-tight flex items-center gap-3 p-3">
                  <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${on ? 'bg-indiagreen-400' : 'bg-ink-600'}`} />
                  <div className="min-w-0 flex-1">
                    <div className="text-[12px] font-semibold text-ink-100">{name}</div>
                    <div className={`text-[10.5px] text-ink-400 ${lang === 'hi' ? 'font-devanagari' : ''}`}>{what}</div>
                    <code className="text-[10px] text-chakra-500">{env}</code>
                  </div>
                  <span className={`chip ${on ? 'border-indiagreen-500/40 bg-indiagreen-500/10 text-indiagreen-300' : 'border-ink-700 bg-white text-ink-500'}`}>
                    {on ? (lang === 'hi' ? 'सक्रिय' : 'active') : (lang === 'hi' ? 'सेट नहीं' : 'not set')}
                  </span>
                  <a href={url} target="_blank" rel="noreferrer noopener" className="btn btn-ghost px-2 py-1 text-[10px]">↗</a>
                </div>
              ))}
              {ai && (
                <div className="panel-tight p-3">
                  <div className="kicker mb-1.5">{lang === 'hi' ? 'एमएल मॉडल' : 'ML models'}</div>
                  <div className="data-row"><span className="data-label">Logistic classifier</span><span className="data-value">{ai.classifier ? `${ai.classifier.n_samples} samples` : 'not trained'}</span></div>
                  <div className="data-row"><span className="data-label">k-NN analog search</span><span className="data-value">{ai.analogs.enabled ? `${ai.analogs.training_days} days` : 'off'}</span></div>
                  <div className="data-row"><span className="data-label">Anomaly detection</span><span className="data-value">{ai.anomaly.method}</span></div>
                  <div className="data-row"><span className="data-label">LLM in use</span><span className="data-value">{ai.llm.preferred ?? 'offline fallback'}</span></div>
                </div>
              )}
            </div>
          )}

          {/* ------------------------------------------------------- scale */}
          {tab === 'scale' && system?.model && (
            <ul className="space-y-2.5">
              {system.model.alert_tiers.map((tier) => (
                <li
                  key={tier.key}
                  className="panel-tight overflow-hidden"
                  style={{ borderColor: `${tier.colour}55` }}
                >
                  <div className="flex items-center gap-2.5 px-3 py-2" style={{ background: `${tier.colour}16` }}>
                    <span
                      className="h-3.5 w-3.5 shrink-0 rounded-sm"
                      style={{ background: tier.colour }}
                    />
                    <span
                      className={`text-[12px] font-bold ${lang === 'hi' ? 'font-devanagari' : ''}`}
                      style={{ color: tier.colour }}
                    >
                      {lang === 'hi' ? tier.label_hi : tier.label_en}
                    </span>
                    <span className="ml-auto font-mono text-[10.5px] text-ink-400">
                      {tier.min}–{tier.max > 100 ? 100 : tier.max}
                    </span>
                  </div>
                  <div className="space-y-1.5 px-3 py-2">
                    <p className={`text-[11px] text-ink-300 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
                      <span className="kicker mr-1.5">IMD</span>
                      {lang === 'hi' ? tier.imd_meaning_hi : tier.imd_meaning_en}
                    </p>
                    <p className={`text-[11px] text-ink-300 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
                      <span className="kicker mr-1.5">NDMA</span>
                      {lang === 'hi' ? tier.ndma_action_hi : tier.ndma_action_en}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {/* ----------------------------------------------------- sources */}
          {tab === 'sources' && (
            <ul className="space-y-2">
              {(system?.sources ?? []).map((s) => (
                <li key={s.key} className="panel-tight p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-[12px] font-semibold text-ink-100">{s.name}</span>
                        {s.health && (
                          <span
                            className={`chip px-1.5 py-0.5 text-[9px] ${
                              s.health.ok
                                ? 'border-indiagreen-500/45 bg-indiagreen-500/10 text-indiagreen-300'
                                : 'border-risk-orange/45 bg-risk-orange/10 text-risk-orange'
                            }`}
                            title={s.health.detail}
                          >
                            {s.health.ok ? 'ok' : 'degraded'}
                            {s.health.latency_ms ? ` · ${(s.health.latency_ms / 1000).toFixed(1)}s` : ''}
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 text-[11px] leading-snug text-ink-400">{s.gives}</p>
                      <p className="mt-1 text-[10px] text-ink-600">{s.licence}</p>
                    </div>
                    {s.url?.startsWith('http') && (
                      <a
                        href={s.url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="btn btn-ghost shrink-0 px-2 py-1 text-[10px]"
                      >
                        ↗
                      </a>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}

          {/* -------------------------------------------------------- runs */}
          {tab === 'runs' && (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-ink-700/70 text-left">
                  {['#', 'started', 'trigger', 'status', 'loc', 'ms'].map((h) => (
                    <th key={h} className="kicker pb-1.5 font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="font-mono text-ink-300">
                {(system?.runs ?? []).map((r) => (
                  <tr key={r.id} className="border-b border-ink-800/70">
                    <td className="py-1.5">{r.id}</td>
                    <td className="py-1.5 text-ink-400">
                      {new Date(r.started_at).toLocaleString('en-IN', {
                        timeZone: 'Asia/Kolkata',
                        day: '2-digit',
                        month: 'short',
                        hour: '2-digit',
                        minute: '2-digit',
                        hour12: false,
                      })}
                    </td>
                    <td className="py-1.5 text-ink-400">{r.trigger}</td>
                    <td className="py-1.5">
                      <span
                        className={
                          r.status === 'ok'
                            ? 'text-indiagreen-300'
                            : r.status === 'failed'
                              ? 'text-risk-red'
                              : 'text-risk-yellow'
                        }
                      >
                        {r.status}
                      </span>
                    </td>
                    <td className="py-1.5">{r.locations}</td>
                    <td className="py-1.5 text-ink-500">{r.duration_ms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* footer disclaimer */}
        <div className="shrink-0 border-t border-ink-700/70 px-4 py-2.5">
          <p className={`text-[10px] leading-snug text-ink-500 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
            {lang === 'hi' ? system?.app?.disclaimer_hi : system?.app?.disclaimer_en}
          </p>
        </div>
      </div>
    </div>
  );
}
