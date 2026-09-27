import { useState } from 'react';
import { api } from '../lib/api';
import { cumecs, longDateIST, mm, tierColour } from '../lib/format';
import { pick, pickPlain, t } from '../lib/i18n';
import { TierChip } from './Primitives';

/**
 * Event replay.
 *
 * This is the single most persuasive thing in the app, and the reason is that it
 * does not depend on the weather cooperating during a demo. It re-runs the exact
 * same scoring path against the Open-Meteo archive and the GloFAS reanalysis for a
 * past date, then compares the verdict with the historical register. If the model
 * scores Mumbai at Red on 2005-07-26, that is a real back-test, not a screenshot.
 *
 * Its honesty is the point: `miss` and `false_alarm` verdicts are rendered as
 * plainly as `hit`. A back-test that could only succeed would be worthless.
 */

const VERDICT_STYLE = {
  hit: { colour: '#0B8A3D', icon: '✓', en: 'Correctly flagged', hi: 'सही चिह्नित' },
  miss: { colour: '#C1121F', icon: '✕', en: 'Under-called', hi: 'कम आँका' },
  false_alarm: { colour: '#E8B10B', icon: '!', en: 'No event recorded', hi: 'कोई घटना दर्ज नहीं' },
  quiet: { colour: '#4A5E7D', icon: '·', en: 'Quiet day', hi: 'शांत दिन' },
};

export default function ReplayPanel({ lang, locationId, events = [] }) {
  const [open, setOpen] = useState(false);
  const [date, setDate] = useState(events[0]?.date ?? '');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function run(target) {
    if (!target) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.replay(locationId, target));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const verdict = result?.verdict ? VERDICT_STYLE[result.verdict.key] : null;
  const a = result?.assessment;

  return (
    <section className="panel shrink-0">
      <button
        type="button"
        className="panel-head w-full text-left transition hover:bg-ink-850/50"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <h3 className={`panel-title flex items-center gap-2 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M3 12a9 9 0 1 0 2.64-6.36M3 3v6h6"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          {t(lang, 'replay')}
        </h3>
        <span className={`text-ink-500 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
            <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
          </svg>
        </span>
      </button>

      {open && (
        <div className="animate-fade-up p-3">
          <p className={`mb-2.5 text-[11px] leading-snug text-ink-400 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
            {t(lang, 'replayHelp')}
          </p>

          {/* one-tap presets for this location's own recorded events */}
          {events.length > 0 && (
            <div className="mb-2.5 flex flex-wrap gap-1.5">
              {events.slice(0, 5).map((e) => (
                <button
                  key={e.date}
                  type="button"
                  onClick={() => {
                    setDate(e.date);
                    run(e.date);
                  }}
                  disabled={busy}
                  className={`chip border-ink-600/70 bg-ink-850/70 text-ink-300 transition hover:border-saffron-500/60 hover:text-saffron-200 ${
                    date === e.date ? 'border-saffron-500/70 text-saffron-300' : ''
                  }`}
                  title={e.headline}
                >
                  {longDateIST(e.date)}
                </button>
              ))}
            </div>
          )}

          <div className="flex gap-2">
            <input
              type="date"
              value={date}
              max={new Date(Date.now() - 86400000).toISOString().slice(0, 10)}
              min="1994-01-01"
              onChange={(e) => setDate(e.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-ink-700/70 bg-ink-850 px-2.5 py-2 font-mono text-[11px] text-ink-100"
            />
            <button
              type="button"
              className="btn btn-primary shrink-0"
              onClick={() => run(date)}
              disabled={busy || !date}
            >
              {busy ? (
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" />
              ) : (
                <span className={lang === 'hi' ? 'font-devanagari' : ''}>{t(lang, 'runReplay')}</span>
              )}
            </button>
          </div>

          {error && <p className="mt-2.5 text-[11px] text-risk-orange">{error}</p>}

          {result && a && (
            <div className="mt-3 animate-fade-up space-y-2.5">
              {/* verdict */}
              <div
                className="flex items-start gap-2.5 rounded-lg border p-2.5"
                style={{ borderColor: `${verdict.colour}66`, background: `${verdict.colour}12` }}
              >
                <span
                  className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-[12px] font-bold text-white"
                  style={{ background: verdict.colour }}
                  aria-hidden="true"
                >
                  {verdict.icon}
                </span>
                <div className="min-w-0">
                  <div
                    className={`text-[11px] font-bold uppercase tracking-wider ${
                      lang === 'hi' ? 'font-devanagari' : ''
                    }`}
                    style={{ color: verdict.colour }}
                  >
                    {lang === 'hi' ? verdict.hi : verdict.en}
                  </div>
                  <p className={`mt-0.5 text-[11.5px] leading-snug text-ink-200 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
                    {pickPlain(lang, result.verdict)}
                  </p>
                </div>
              </div>

              {/* what the model saw that day */}
              <div className="panel-tight p-2.5">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="font-mono text-[10.5px] text-ink-400">
                    {longDateIST(result.target_date)}
                  </span>
                  <div className="flex items-center gap-2">
                    <TierChip tier={a.risk.tier.key} lang={lang} />
                    <span
                      className="font-mono text-lg font-bold tabular-nums"
                      style={{ color: tierColour(a.risk.tier.key) }}
                    >
                      {a.risk.score.toFixed(0)}
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-x-3">
                  <div className="data-row">
                    <span className="data-label">{t(lang, 'rain24')}</span>
                    <span className="data-value">{mm(a.observations.rain_24h_mm)}</span>
                  </div>
                  <div className="data-row">
                    <span className="data-label">{t(lang, 'rain72')}</span>
                    <span className="data-value">{mm(a.observations.rain_72h_mm)}</span>
                  </div>
                  <div className="data-row">
                    <span className="data-label">{t(lang, 'currentDischarge')}</span>
                    <span className="data-value">{cumecs(a.river?.current_cumecs)}</span>
                  </div>
                  <div className="data-row">
                    <span className="data-label">{t(lang, 'percentileSeason')}</span>
                    <span className="data-value">
                      {a.river?.percentile_for_season !== null &&
                      a.river?.percentile_for_season !== undefined
                        ? `${a.river.percentile_for_season.toFixed(0)}`
                        : '—'}
                    </span>
                  </div>
                </div>

                <p className={`mt-2 border-t border-ink-800 pt-2 text-[11px] leading-snug text-ink-300 ${
                  lang === 'hi' ? 'font-devanagari' : ''
                }`}>
                  {pick(lang, a.explanation, 'narrative')}
                </p>
              </div>

              {/* the recorded event, if there is one */}
              {result.recorded_events?.length > 0 && (
                <div className="panel-tight p-2.5">
                  <div className="kicker mb-1.5">
                    {lang === 'hi' ? 'दर्ज घटना' : 'Recorded event'}
                  </div>
                  {result.recorded_events.map((e) => (
                    <div key={e.date} className="text-[11px] leading-snug text-ink-200">
                      <span className="font-mono text-saffron-300">{longDateIST(e.date)}</span>
                      {' — '}
                      {e.headline}
                    </div>
                  ))}
                </div>
              )}

              <p className="text-[9.5px] leading-snug text-ink-600">
                {lang === 'hi'
                  ? 'पुनरावृत्ति ओपन-मेटियो संग्रह एवं ग्लोफास पुनर्विश्लेषण से समान स्कोरिंग पथ चलाती है।'
                  : 'Replay runs the identical scoring path against the Open-Meteo archive and GloFAS reanalysis for that date.'}
              </p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
