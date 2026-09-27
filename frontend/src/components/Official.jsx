import { useEffect, useRef, useState } from 'react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { api } from '../lib/api';
import { dateIST, stateName } from '../lib/format';
import { SectionHead } from './Primitives';

/**
 * Official Government of India data in the UI.
 *
 *   OfficialCard   the CWC gauge beside a town and any NDMA/IMD/CWC alert covering it
 *   StationModal   a gauge's real hourly hydrograph against its warning, danger and
 *                  highest-flood marks, with CWC's issued forecast where one exists
 *                  and a Chronos-Bolt AI forecast band
 *
 * These are observations and official warnings, and are labelled as such. The
 * model's own estimate is never presented as if it were one of them.
 */

const hi = (lang) => (lang === 'hi' ? 'font-devanagari' : '');

export const STATUS_STYLE = {
  DANGER: { colour: '#C1121F', en: 'Above danger', hi: 'खतरे से ऊपर' },
  WARNING: { colour: '#E4701E', en: 'Above warning', hi: 'चेतावनी से ऊपर' },
  NORMAL: { colour: '#0B8A3D', en: 'Below warning', hi: 'चेतावनी से नीचे' },
};

export const ALERT_COLOUR = { red: '#C1121F', orange: '#E4701E', yellow: '#C99700' };

export function GovBadge({ children }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-chakra-500/30 bg-navy-50 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-chakra-500">
      <svg width="9" height="9" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M12 2l8 4v6c0 5-3.5 9-8 10-4.5-1-8-5-8-10V6l8-4z" fill="currentColor" />
      </svg>
      {children}
    </span>
  );
}

/** A level bar: where the reading sits between warning, danger and the record. */
function LevelLadder({ station }) {
  const { level_m: level, warning_level: warn, danger_level: danger, hfl } = station;
  if (level == null || !danger) return null;
  const lo = Math.min(warn ?? danger - 1, level) - 0.5;
  const hiV = Math.max(hfl ?? danger + 1, level) + 0.3;
  const pos = (v) => `${((v - lo) / (hiV - lo)) * 100}%`;
  return (
    <div className="mt-2">
      <div className="relative h-2.5 overflow-hidden rounded-full bg-gradient-to-r from-indiagreen-500/30 via-risk-orange/35 to-risk-red/45">
        {warn != null && <span className="absolute inset-y-0 w-0.5 bg-risk-orange" style={{ left: pos(warn) }} />}
        <span className="absolute inset-y-0 w-0.5 bg-risk-red" style={{ left: pos(danger) }} />
        {hfl != null && <span className="absolute inset-y-0 w-0.5 bg-chakra-500" style={{ left: pos(hfl) }} />}
      </div>
      <div className="relative h-4">
        <span
          className="absolute -top-[13px] h-3.5 w-3.5 -translate-x-1/2 rounded-full border-2 border-white bg-chakra-500 shadow"
          style={{ left: pos(level) }}
        />
      </div>
      <div className="flex justify-between font-mono text-[9.5px] text-ink-500">
        <span className="text-risk-orange">W {warn ?? '—'}</span>
        <span className="text-risk-red">D {danger}</span>
        <span className="text-chakra-500">HFL {hfl ?? '—'}</span>
      </div>
    </div>
  );
}

export function OfficialCard({ lang, official, onOpenStation, replay }) {
  if (replay) {
    return (
      <section className="panel shrink-0 p-3">
        <p className={`text-[11px] text-ink-500 ${hi(lang)}`}>
          {lang === 'hi'
            ? 'ऐतिहासिक पुनरावृत्ति में आधिकारिक गेज व चेतावनियाँ उपलब्ध नहीं — स्कोर केवल मॉडल आधारित है।'
            : 'Historical replay: CWC gauge readings and official alerts are not archived, so this score is model-only.'}
        </p>
      </section>
    );
  }
  if (!official) return null;
  const g = official.gauge;
  const style = g ? STATUS_STYLE[g.status] ?? STATUS_STYLE.NORMAL : null;

  return (
    <section className="panel shrink-0 overflow-hidden" style={g && g.status !== 'NORMAL' ? { borderColor: `${style.colour}66` } : undefined}>
      <SectionHead
        title={lang === 'hi' ? 'आधिकारिक सरकारी आँकड़े' : 'Official government data'}
        lang={lang}
        right={<GovBadge>CWC · NDMA</GovBadge>}
      />
      <div className="space-y-3 p-3">
        {g ? (
          <div>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-[12.5px] font-bold text-chakra-500">{g.name}</div>
                <div className={`text-[10.5px] text-ink-500 ${hi(lang)}`}>
                  {lang === 'hi' ? 'केंद्रीय जल आयोग नदी गेज' : 'CWC river gauge'} · {g.distance_km} km · {stateName(g.state, lang)}
                </div>
              </div>
              <span
                className={`chip shrink-0 ${hi(lang)}`}
                style={{ color: style.colour, borderColor: `${style.colour}66`, background: `${style.colour}14` }}
              >
                {lang === 'hi' ? style.hi : style.en}
              </span>
            </div>
            {g.level_m != null ? (
              <>
                <div className="mt-2 flex items-baseline gap-2">
                  <span className="font-mono text-2xl font-extrabold" style={{ color: style.colour }}>
                    {g.level_m} m
                  </span>
                  {g.above_danger_m != null && (
                    <span className="font-mono text-[11px] font-bold" style={{ color: g.above_danger_m > 0 ? '#C1121F' : '#526071' }}>
                      {g.above_danger_m > 0 ? '+' : ''}
                      {g.above_danger_m} m {lang === 'hi' ? 'खतरे के निशान से' : 'vs danger'}
                    </span>
                  )}
                  {g.trend && <span className="text-[10.5px] text-ink-400">· {g.trend.toLowerCase()}</span>}
                </div>
                <LevelLadder station={g} />
              </>
            ) : (
              <p className={`mt-1.5 text-[11px] text-ink-400 ${hi(lang)}`}>
                {lang === 'hi'
                  ? `चेतावनी स्तर (${g.warning_level ?? '—'} मी) से नीचे · खतरा ${g.danger_level} मी`
                  : `Below its warning level (${g.warning_level ?? '—'} m) · danger mark ${g.danger_level} m`}
              </p>
            )}
            <button type="button" className="btn mt-2 w-full" onClick={() => onOpenStation(g.code)}>
              <span className={hi(lang)}>
                {lang === 'hi' ? 'जल-स्तर ग्राफ़ व एआई पूर्वानुमान' : 'Hydrograph & AI level forecast'}
              </span>
            </button>
          </div>
        ) : (
          <p className={`text-[11px] text-ink-500 ${hi(lang)}`}>
            {lang === 'hi' ? '35 किमी में खतरे के निशान वाला कोई CWC गेज नहीं।' : 'No CWC gauge with a danger mark within 35 km.'}
          </p>
        )}

        {official.alerts?.length > 0 && (
          <div className="space-y-1.5 border-t border-ink-800 pt-2.5">
            <div className={`kicker ${hi(lang)}`}>{lang === 'hi' ? 'सक्रिय आधिकारिक चेतावनियाँ' : 'Active official alerts'}</div>
            {official.alerts.slice(0, 3).map((a) => (
              <div key={a.id} className="rounded-lg border-l-4 bg-ink-850 px-2.5 py-1.5" style={{ borderColor: ALERT_COLOUR[a.colour] ?? '#6E7C8D' }}>
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-[11.5px] font-semibold text-ink-100">{a.type}</span>
                  <span className="shrink-0 text-[9.5px] font-bold uppercase" style={{ color: ALERT_COLOUR[a.colour] }}>
                    {a.colour}
                  </span>
                </div>
                <div className="text-[10px] text-ink-500">{a.source}</div>
                <p className="mt-0.5 line-clamp-3 text-[10.5px] leading-snug text-ink-300">{a.message}</p>
              </div>
            ))}
          </div>
        )}

        {official.fetched_at && (
          <p className="text-[9.5px] text-ink-500">
            {lang === 'hi' ? 'स्रोत' : 'Source'}: ffs.india-water.gov.in · sachet.ndma.gov.in ·{' '}
            {new Date(official.fetched_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' })} IST
          </p>
        )}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ station modal */

function hoursLabel(h, lang) {
  if (h == null) return lang === 'hi' ? '48 घंटे में नहीं' : 'not within 48 h';
  return lang === 'hi' ? `~${h} घंटे` : `~${h} h`;
}

export function StationModal({ lang, code, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  // The parent passes a new onClose every render; depending on it here would
  // re-fetch the station and blank the chart on each re-render.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!code) return undefined;
    let alive = true;
    setData(null);
    setError(null);
    api
      .station(code)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e.message));
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onCloseRef.current();
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => {
      alive = false;
      document.removeEventListener('keydown', onKey, true);
    };
  }, [code]);

  if (!code) return null;
  const st = data?.station;
  const ai = data?.ai_forecast;

  const rows = [];
  for (const o of data?.observed ?? []) rows.push({ t: o.time, observed: o.level_m });
  if (ai) {
    ai.times.forEach((t, i) =>
      rows.push({ t, p50: ai.p50[i], bandBase: ai.p10[i], bandSpan: Math.max(ai.p90[i] - ai.p10[i], 0) }),
    );
  }
  for (const f of data?.cwc_forecast ?? []) rows.push({ t: f.time, cwc: f.level_m });
  rows.sort((a, b) => (a.t < b.t ? -1 : 1));

  const values = rows.flatMap((r) => [r.observed, r.p50, r.bandBase != null ? r.bandBase + r.bandSpan : null, r.cwc]).filter((v) => v != null);
  const marks = [st?.warning_level, st?.danger_level, st?.hfl].filter((v) => v != null);
  const yMin = Math.floor(Math.min(...values, ...marks) - 0.5);
  const yMax = Math.ceil(Math.max(...values, ...marks) + 0.3);
  const o = ai?.outlook ?? {};

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-navy-800/45 p-4" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="panel flex max-h-[90vh] w-full max-w-4xl animate-fade-up flex-col overflow-hidden" role="dialog" aria-modal="true">
        <div className="tricolour-rule h-[3px]" />
        <header className="flex items-start gap-3 border-b border-ink-700 px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-bold text-chakra-500">{st?.name ?? code}</h2>
              <GovBadge>CWC gauge {code}</GovBadge>
              {st && (
                <span className={`chip ${hi(lang)}`} style={{ color: STATUS_STYLE[st.status].colour, borderColor: `${STATUS_STYLE[st.status].colour}66` }}>
                  {lang === 'hi' ? STATUS_STYLE[st.status].hi : STATUS_STYLE[st.status].en}
                </span>
              )}
            </div>
            <p className="text-[11px] text-ink-500">
              {stateName(st?.state, lang)} · {lang === 'hi' ? 'चेतावनी' : 'warning'} {st?.warning_level ?? '—'} m · {lang === 'hi' ? 'खतरा' : 'danger'}{' '}
              {st?.danger_level ?? '—'} m · HFL {st?.hfl ?? '—'} m {st?.hfl_date ? `(${st.hfl_date})` : ''}
            </p>
          </div>
          <button type="button" className="btn btn-ghost px-2 py-1" onClick={onClose} aria-label="Close">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
              <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
            </svg>
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-4 scrollbar-thin">
          {error && <p className="text-[12px] text-risk-red">{error}</p>}
          {!data && !error && (
            <p className={`py-10 text-center text-[12px] text-ink-500 ${hi(lang)}`}>
              {lang === 'hi' ? 'CWC से जल-स्तर व एआई पूर्वानुमान ला रहे हैं…' : 'Fetching hourly levels from CWC and running the AI forecast…'}
            </p>
          )}

          {data && (
            <>
              <div className="grid gap-2 sm:grid-cols-4">
                {[
                  [lang === 'hi' ? 'वर्तमान स्तर' : 'Current level', data.observed.length ? `${data.observed[data.observed.length - 1].level_m} m` : '—'],
                  [
                    st?.level_m != null && st.danger_level && st.level_m >= st.danger_level
                      ? lang === 'hi' ? 'खतरे से नीचे आने में' : 'Back below danger in'
                      : lang === 'hi' ? 'खतरे तक पहुँचने में (p50)' : 'Reaches danger (p50)',
                    hoursLabel(o.hours_to_below_danger ?? o.hours_to_danger_p50, lang),
                  ],
                  [lang === 'hi' ? '48 घंटे शिखर (p90)' : '48 h peak (p90)', o.peak_p90_m != null ? `${o.peak_p90_m} m` : '—'],
                  [lang === 'hi' ? '24 घंटे में बदलाव' : '24 h change (p50)', o.change_24h_p50_m != null ? `${o.change_24h_p50_m > 0 ? '+' : ''}${o.change_24h_p50_m} m` : '—'],
                ].map(([k, v]) => (
                  <div key={k} className="panel-tight px-3 py-2">
                    <div className={`text-[9.5px] font-semibold uppercase tracking-wide text-ink-500 ${hi(lang)}`}>{k}</div>
                    <div className="font-mono text-lg font-bold text-chakra-500">{v}</div>
                  </div>
                ))}
              </div>

              <div className="mt-3 h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={rows} margin={{ top: 10, right: 14, bottom: 0, left: -6 }}>
                    <CartesianGrid stroke="#E5EAF0" vertical={false} />
                    <XAxis
                      dataKey="t"
                      tick={{ fontSize: 10, fill: '#6E7C8D' }}
                      tickFormatter={(t) => dateIST(t)}
                      minTickGap={40}
                    />
                    {/* allowDataOverflow: the stacked band's zero baseline must not drag the axis to 0 m */}
                    <YAxis domain={[yMin, yMax]} allowDataOverflow tick={{ fontSize: 10, fill: '#6E7C8D' }} width={48} tickFormatter={(v) => v.toFixed(1)} />
                    <Tooltip
                      formatter={(v, name) => [typeof v === 'number' ? `${v.toFixed(2)} m` : v, name]}
                      labelFormatter={(t) => new Date(t).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                    />
                    {st?.warning_level != null && (
                      <ReferenceLine y={st.warning_level} stroke="#E4701E" strokeDasharray="5 4" label={{ value: `warning ${st.warning_level}`, fontSize: 10, fill: '#E4701E', position: 'insideTopLeft' }} />
                    )}
                    {st?.danger_level != null && (
                      <ReferenceLine y={st.danger_level} stroke="#C1121F" strokeDasharray="5 4" label={{ value: `danger ${st.danger_level}`, fontSize: 10, fill: '#C1121F', position: 'insideTopLeft' }} />
                    )}
                    {st?.hfl != null && (
                      <ReferenceLine y={st.hfl} stroke="#0B2A5B" strokeDasharray="2 4" label={{ value: `HFL ${st.hfl}`, fontSize: 10, fill: '#0B2A5B', position: 'insideTopRight' }} />
                    )}
                    <Area dataKey="bandBase" stackId="b" stroke="none" fill="transparent" isAnimationActive={false} name="p10" />
                    <Area dataKey="bandSpan" stackId="b" stroke="none" fill="#F26A1B" fillOpacity={0.2} isAnimationActive={false} name="p10–p90 band" />
                    <Line dataKey="observed" stroke="#0B2A5B" strokeWidth={2.2} dot={false} name={lang === 'hi' ? 'प्रेक्षित' : 'observed (CWC)'} isAnimationActive={false} />
                    <Line dataKey="p50" stroke="#F26A1B" strokeWidth={2.2} strokeDasharray="6 3" dot={false} name="AI forecast p50" isAnimationActive={false} />
                    <Line dataKey="cwc" stroke="#0B8A3D" strokeWidth={2} dot={{ r: 3 }} name="CWC official forecast" isAnimationActive={false} connectNulls />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>

              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[10.5px] text-ink-400">
                <span><b className="text-chakra-500">━</b> {lang === 'hi' ? 'प्रेक्षित स्तर (CWC, प्रति घंटा)' : 'Observed hourly level (CWC)'}</span>
                <span><b className="text-saffron-500">┅</b> {lang === 'hi' ? 'एआई पूर्वानुमान माध्यिका' : 'AI forecast median'}</span>
                <span><b className="text-saffron-500">▒</b> p10–p90</span>
                {data.cwc_forecast?.length > 0 && <span><b className="text-indiagreen-400">●</b> {lang === 'hi' ? 'CWC आधिकारिक पूर्वानुमान' : 'CWC official forecast'}</span>}
              </div>

              <p className={`mt-3 rounded-lg bg-ink-850 p-3 text-[10.5px] leading-relaxed text-ink-400 ${hi(lang)}`}>
                {lang === 'hi'
                  ? `एआई पूर्वानुमान: Hugging Face का ${data.model} (Amazon Chronos-Bolt), एक पूर्व-प्रशिक्षित टाइम-सीरीज़ मॉडल, जो पिछले 7 दिनों के प्रति घंटा स्तर से अगले 48 घंटे का अनुमान लगाता है। यह ऊपरी वर्षा या बाँध से छोड़े गए पानी को नहीं जानता, इसलिए इसे CWC के आधिकारिक पूर्वानुमान के साथ पढ़ें।`
                  : `AI forecast: ${data.model} (Amazon Chronos-Bolt on Hugging Face), a pretrained time-series model forecasting the next 48 h zero-shot from the last 7 days of hourly levels. It does not know about upstream rain or dam releases, so read it next to CWC's official forecast, never instead of it.`}
                {data.ai_note ? ` (${data.ai_note})` : ''}
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
