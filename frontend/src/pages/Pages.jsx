import { useEffect, useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api, capLinks } from '../lib/api';
import IndiaMap from '../components/IndiaMap';
import {
  canonicalState,
  compactPopulation,
  compass,
  directionGlyph,
  longDateIST,
  stateName,
  tierColour,
  TIER_LABELS,
  TIER_ORDER,
  weatherInfo,
} from '../lib/format';
import { ALERT_COLOUR, GovBadge, STATUS_STYLE } from '../components/Official';

/**
 * Full-page views beyond the map dashboard.
 *
 *   OfficialPage   what the government is reporting right now: CWC gauges above
 *                  warning/danger and NDMA SACHET alerts, searchable and filterable
 *   StateMonitor   every state and UT at a glance, with official gauge counts next
 *                  to the model's assessment
 *   TimeMachine    replay the whole country on any past date since 1994
 */

const hi = (lang) => (lang === 'hi' ? 'font-devanagari' : '');

function PageShell({ title, subtitle, right, children }) {
  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-4 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b-2 border-saffron-500 pb-3">
        <div>
          <h2 className="text-xl font-extrabold tracking-tight text-chakra-500">{title}</h2>
          {subtitle && <p className="mt-0.5 text-[12px] text-ink-400">{subtitle}</p>}
        </div>
        {right}
      </div>
      {children}
    </div>
  );
}

function Stat({ label, value, colour = '#0B2A5B', sub }) {
  return (
    <div className="panel px-4 py-3">
      <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500">{label}</div>
      <div className="font-mono text-3xl font-extrabold" style={{ color: colour }}>{value}</div>
      {sub && <div className="text-[10.5px] text-ink-500">{sub}</div>}
    </div>
  );
}

/* ================================================================ OFFICIAL */

export function OfficialPage({ lang, onOpenStation, onViewState }) {
  const [summary, setSummary] = useState(null);
  const [stations, setStations] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [tab, setTab] = useState('gauges');
  const [query, setQuery] = useState('');
  const [colour, setColour] = useState('all');
  const [floodOnly, setFloodOnly] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([api.officialSummary(), api.officialStations(true), api.officialAlerts(false)])
      .then(([s, st, al]) => {
        setSummary(s);
        setStations(st.stations);
        setAlerts(al.alerts);
      })
      .catch((e) => setError(e.message));
  }, []);

  const q = query.trim().toLowerCase();
  const gaugeRows = stations.filter(
    (g) => !q || [g.name, g.state, g.code].some((x) => x && String(x).toLowerCase().includes(q)),
  );
  const alertRows = alerts.filter(
    (a) =>
      (!floodOnly || a.flood_related) &&
      (colour === 'all' || a.colour === colour) &&
      (!q || [a.area, a.source, a.type, a.message].some((x) => x && x.toLowerCase().includes(q))),
  );

  return (
    <PageShell
      title={lang === 'hi' ? 'आधिकारिक चेतावनियाँ एवं नदी गेज' : 'Official Alerts & River Gauges'}
      subtitle={
        lang === 'hi'
          ? 'केंद्रीय जल आयोग (CWC) के प्रति घंटा नदी स्तर और NDMA SACHET पर IMD, CWC व राज्य आपदा प्राधिकरणों की चेतावनियाँ — सीधे स्रोत से'
          : 'Hourly river levels from the Central Water Commission and the CAP alerts IMD, CWC and State Disaster Management Authorities publish on NDMA SACHET — straight from source'
      }
      right={
        <div className="flex flex-wrap items-center gap-2">
          <GovBadge>ffs.india-water.gov.in · sachet.ndma.gov.in</GovBadge>
          <a
            data-tour="al-cap"
            href={capLinks.feed}
            target="_blank"
            rel="noreferrer"
            className="btn px-2.5 py-1 text-[11px]"
            title={lang === 'hi' ? 'JalDrishti की चेतावनियाँ OASIS CAP 1.2 प्रारूप में (अभ्यास स्थिति, आधिकारिक नहीं)' : "JalDrishti's own warnings in OASIS CAP 1.2 (status Exercise, not official)"}
          >
            {lang === 'hi' ? 'हमारा CAP 1.2 फ़ीड ↗' : 'Our CAP 1.2 feed ↗'}
          </a>
        </div>
      }
    >
      {error && <p className="text-risk-red">{error}</p>}
      {summary && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5" data-tour="al-stats">
          <Stat label={lang === 'hi' ? 'खतरे से ऊपर गेज' : 'Gauges above danger'} value={summary.gauges.danger} colour="#C1121F" />
          <Stat label={lang === 'hi' ? 'चेतावनी से ऊपर गेज' : 'Gauges above warning'} value={summary.gauges.warning} colour="#E4701E" />
          <Stat label={lang === 'hi' ? 'निगरानी गेज' : 'Gauges monitored'} value={summary.gauges.catalogued} sub={lang === 'hi' ? 'खतरे के निशान सहित' : 'with published danger marks'} />
          <Stat label={lang === 'hi' ? 'बाढ़ संबंधी चेतावनियाँ' : 'Flood-related alerts'} value={summary.alerts.flood_related} colour="#E4701E" sub={`${summary.alerts.total} ${lang === 'hi' ? 'कुल' : 'total active'}`} />
          <Stat
            label={lang === 'hi' ? 'अद्यतन' : 'Fetched'}
            value={summary.fetched_at ? new Date(summary.fetched_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' }) : '—'}
            sub="IST"
          />
        </div>
      )}

      <div className="panel">
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-700 p-3" data-tour="al-tabs">
          {[
            ['gauges', lang === 'hi' ? `नदी गेज (${gaugeRows.length})` : `River gauges (${gaugeRows.length})`],
            ['alerts', lang === 'hi' ? `चेतावनियाँ (${alertRows.length})` : `Alerts (${alertRows.length})`],
          ].map(([k, label]) => (
            <button key={k} type="button" onClick={() => setTab(k)} className={`rounded-md px-3 py-1.5 text-[12px] font-bold ${tab === k ? 'bg-chakra-500 text-white' : 'text-ink-400 hover:bg-ink-800'} ${hi(lang)}`}>
              {label}
            </button>
          ))}
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={lang === 'hi' ? 'स्टेशन, राज्य, क्षेत्र खोजें…' : 'Search station, state, area…'}
            className="ml-auto w-64 rounded-lg border border-ink-700 bg-ink-850 px-3 py-1.5 text-[12px]"
          />
          {tab === 'alerts' && (
            <>
              <select value={colour} onChange={(e) => setColour(e.target.value)} className="rounded-lg border border-ink-700 bg-white px-2 py-1.5 text-[12px]">
                <option value="all">{lang === 'hi' ? 'सभी रंग' : 'All levels'}</option>
                <option value="red">Red</option>
                <option value="orange">Orange</option>
                <option value="yellow">Yellow</option>
              </select>
              <label className="flex items-center gap-1.5 text-[12px] text-ink-300">
                <input type="checkbox" checked={floodOnly} onChange={(e) => setFloodOnly(e.target.checked)} className="accent-saffron-500" />
                {lang === 'hi' ? 'केवल बाढ़/वर्षा' : 'Flood & rain only'}
              </label>
            </>
          )}
        </div>

        {tab === 'gauges' ? (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead className="bg-ink-850 text-left text-[10px] uppercase tracking-wider text-ink-500">
                <tr>
                  {['Status', 'Station', 'State', 'Level (m)', 'Warning', 'Danger', 'vs danger', 'Trend', 'HFL (year)', ''].map((h) => (
                    <th key={h} className="px-3 py-2 font-bold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {gaugeRows.map((g) => (
                  <tr key={g.code} className="border-t border-ink-800 hover:bg-saffron-50">
                    <td className="px-3 py-2">
                      <span className="chip" style={{ color: STATUS_STYLE[g.status].colour, borderColor: `${STATUS_STYLE[g.status].colour}55`, background: `${STATUS_STYLE[g.status].colour}12` }}>
                        {g.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-semibold text-chakra-500">{g.name}</td>
                    <td className={`px-3 py-2 ${hi(lang)}`}>{stateName(g.state, lang)}</td>
                    <td className="px-3 py-2 font-mono font-bold">{g.level_m ?? '—'}</td>
                    <td className="px-3 py-2 font-mono text-risk-orange">{g.warning_level ?? '—'}</td>
                    <td className="px-3 py-2 font-mono text-risk-red">{g.danger_level ?? '—'}</td>
                    <td className={`px-3 py-2 font-mono font-bold ${g.above_danger_m > 0 ? 'text-risk-red' : 'text-ink-400'}`}>
                      {g.above_danger_m != null ? `${g.above_danger_m > 0 ? '+' : ''}${g.above_danger_m}` : '—'}
                    </td>
                    <td className="px-3 py-2 text-ink-400">{g.trend?.toLowerCase() ?? '—'}</td>
                    <td className="px-3 py-2 font-mono text-ink-400">{g.hfl ?? '—'} {g.hfl_date ? `(${g.hfl_date.slice(0, 4)})` : ''}</td>
                    <td className="px-3 py-2 text-right">
                      <button type="button" data-tour="al-graph" className="btn px-2 py-1 text-[11px]" onClick={() => onOpenStation(g.code)}>
                        {lang === 'hi' ? 'ग्राफ़ + एआई' : 'Graph + AI'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {gaugeRows.length === 0 && <p className="p-6 text-center text-ink-500">{lang === 'hi' ? 'कोई गेज चेतावनी स्तर से ऊपर नहीं' : 'No gauge above warning level'}</p>}
          </div>
        ) : (
          <ul className="grid gap-3 p-3 md:grid-cols-2 xl:grid-cols-3">
            {alertRows.map((a) => (
              <li key={a.id} className="rounded-xl border border-ink-700 border-l-4 bg-white p-3 shadow-sm" style={{ borderLeftColor: ALERT_COLOUR[a.colour] ?? '#6E7C8D' }}>
                <div className="flex items-start justify-between gap-2">
                  <div className="text-[13px] font-bold text-ink-100">{a.type}</div>
                  <span className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase text-white" style={{ background: ALERT_COLOUR[a.colour] ?? '#6E7C8D' }}>
                    {a.colour || a.severity}
                  </span>
                </div>
                <div className="mt-0.5 text-[11px] font-semibold text-chakra-500">{a.source}</div>
                <div className="mt-1 text-[11.5px] text-ink-300">{a.area}</div>
                <p className="mt-1.5 text-[11.5px] leading-snug text-ink-200">{a.message}</p>
                <div className="mt-2 text-[10px] text-ink-500">
                  {a.start} → {a.end}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </PageShell>
  );
}

/* =========================================================== STATE MONITOR */

export function StateMonitor({ lang, country, locations = [], alerts = [], onViewState, onOpenLocation, onOpenStation, replayDate }) {
  const [gauges, setGauges] = useState([]);
  const [sort, setSort] = useState('risk');
  const [tier, setTier] = useState('all');
  const [query, setQuery] = useState('');
  const [picked, setPicked] = useState(null);
  const [layers, setLayers] = useState({ towns: true, gauges: true, alerts: false });

  useEffect(() => {
    if (replayDate) return undefined;
    const load = () => api.officialStations(true).then((d) => setGauges(d.stations)).catch(() => {});
    load();
    const id = setInterval(load, 120_000);
    return () => clearInterval(id);
  }, [replayDate]);

  const gaugeByState = useMemo(() => {
    const out = {};
    for (const g of gauges) {
      if (!g.state) continue;
      out[g.state] ??= { danger: 0, warning: 0, worst: null };
      if (g.status === 'DANGER') out[g.state].danger += 1;
      if (g.status === 'WARNING') out[g.state].warning += 1;
      if (!out[g.state].worst || (g.above_danger_m ?? -99) > (out[g.state].worst.above_danger_m ?? -99)) out[g.state].worst = g;
    }
    return out;
  }, [gauges]);

  const rows = useMemo(() => {
    let list = [...(country?.states ?? [])];
    if (picked) list = list.filter((s) => canonicalState(s.state) === canonicalState(picked));
    const q = query.trim().toLowerCase();
    if (q) list = list.filter((s) => s.state.toLowerCase().includes(q) || stateName(s.state, 'hi').includes(query.trim()));
    if (tier !== 'all') list = list.filter((s) => s.tier === tier);
    if (sort === 'name') list.sort((a, b) => a.state.localeCompare(b.state));
    else if (sort === 'gauges') list.sort((a, b) => (gaugeByState[b.state]?.danger ?? 0) - (gaugeByState[a.state]?.danger ?? 0) || b.score - a.score);
    else if (sort === 'population') list.sort((a, b) => b.population_at_risk - a.population_at_risk);
    else if (sort === 'rain') list.sort((a, b) => (b.weather?.wettest?.precip_mm ?? 0) - (a.weather?.wettest?.precip_mm ?? 0) || b.score - a.score);
    else list.sort((a, b) => b.score - a.score);
    return list;
  }, [country, sort, tier, query, gaugeByState, picked]);

  const counts = TIER_ORDER.reduce((acc, t) => ({ ...acc, [t]: (country?.states ?? []).filter((s) => s.tier === t).length }), {});

  return (
    <PageShell
      title={lang === 'hi' ? 'राज्य निगरानी' : 'State Monitor'}
      subtitle={
        lang === 'hi'
          ? `सभी ${country?.states?.length ?? 36} राज्य/केंद्र शासित प्रदेश — मॉडल आकलन और आधिकारिक CWC गेज साथ-साथ`
          : `All ${country?.states?.length ?? 36} states & union territories — the model's assessment beside official CWC gauge readings`
      }
      right={
        <div className="flex flex-wrap items-center gap-2" data-tour="sm-filters">
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={lang === 'hi' ? 'राज्य खोजें…' : 'Find a state…'} className="w-44 rounded-lg border border-ink-700 bg-white px-3 py-1.5 text-[12px]" />
          <select value={tier} onChange={(e) => setTier(e.target.value)} className="rounded-lg border border-ink-700 bg-white px-2 py-1.5 text-[12px]">
            <option value="all">{lang === 'hi' ? 'सभी स्तर' : 'All levels'}</option>
            {TIER_ORDER.map((t) => (
              <option key={t} value={t}>{lang === 'hi' ? TIER_LABELS[t].hi : TIER_LABELS[t].en} ({counts[t]})</option>
            ))}
          </select>
          <select value={sort} onChange={(e) => setSort(e.target.value)} className="rounded-lg border border-ink-700 bg-white px-2 py-1.5 text-[12px]">
            <option value="risk">{lang === 'hi' ? 'जोखिम अनुसार' : 'Sort: risk'}</option>
            <option value="gauges">{lang === 'hi' ? 'खतरे वाले गेज अनुसार' : 'Sort: gauges above danger'}</option>
            <option value="population">{lang === 'hi' ? 'जनसंख्या अनुसार' : 'Sort: people at risk'}</option>
            {!replayDate && <option value="rain">{lang === 'hi' ? 'अभी बारिश अनुसार' : 'Sort: raining now'}</option>}
            <option value="name">{lang === 'hi' ? 'नाम अनुसार' : 'Sort: name'}</option>
          </select>
        </div>
      }
    >
      <div data-tour="sm-map">
      <StateCasesMap
        lang={lang}
        country={country}
        locations={locations}
        gauges={replayDate ? [] : gauges}
        alerts={replayDate ? [] : alerts}
        gaugeByState={gaugeByState}
        replayDate={replayDate}
        picked={picked}
        onPick={setPicked}
        layers={layers}
        onLayers={setLayers}
        onOpenLocation={onOpenLocation}
        onOpenStation={onOpenStation}
      />
      </div>

      {picked && (
        <div className="flex items-center gap-2 text-[12px] text-ink-300">
          {lang === 'hi' ? 'दिखाया जा रहा है' : 'Showing'}: <b className="text-chakra-500">{stateName(picked, lang)}</b>
          <button type="button" className="btn btn-ghost px-2 py-0.5 text-[11px]" onClick={() => setPicked(null)}>
            {lang === 'hi' ? 'सभी राज्य' : 'Show all states'} ✕
          </button>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4" data-tour="sm-cards">
        {rows.map((s) => {
          const g = gaugeByState[s.state];
          const colour = tierColour(s.tier);
          return (
            <button
              key={s.state}
              type="button"
              onClick={() => onViewState(s.state)}
              className="panel group overflow-hidden text-left transition hover:-translate-y-0.5 hover:shadow-lg"
            >
              <div className="h-1.5" style={{ background: colour }} />
              <div className="p-3.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className={`truncate text-[15px] font-bold text-chakra-500 ${hi(lang)}`}>{stateName(s.state, lang)}</div>
                    <div className="text-[10.5px] text-ink-500">
                      {s.locations} {lang === 'hi' ? 'निगरानी स्थान' : 'monitored places'}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="font-mono text-3xl font-extrabold leading-none" style={{ color: colour }}>{s.score.toFixed(0)}</div>
                    <div className={`text-[10px] font-bold ${hi(lang)}`} style={{ color: colour }}>
                      {lang === 'hi' ? TIER_LABELS[s.tier].hi : TIER_LABELS[s.tier].en} <span className="text-ink-500">{directionGlyph(s.direction?.key)}</span>
                    </div>
                  </div>
                </div>

                <div className="mt-2.5 flex h-2 overflow-hidden rounded-full bg-ink-800">
                  {TIER_ORDER.map((t) =>
                    s.counts[t] ? <span key={t} style={{ width: `${(100 * s.counts[t]) / s.locations}%`, background: tierColour(t) }} /> : null,
                  )}
                </div>

                <div className={`mt-2 truncate text-[11px] text-ink-300 ${hi(lang)}`}>
                  {lang === 'hi' ? 'सर्वाधिक' : 'Highest'}: <b className="text-ink-100">{lang === 'hi' && s.worst.name_hi ? s.worst.name_hi : s.worst.name}</b>
                  {s.worst.river ? ` · ${s.worst.river}` : ''}
                </div>

                <div className="mt-2 grid grid-cols-3 gap-1.5 border-t border-ink-800 pt-2 text-center">
                  <div>
                    <div className="font-mono text-base font-bold text-risk-red">{replayDate ? '—' : g?.danger ?? 0}</div>
                    <div className="text-[9px] uppercase tracking-wide text-ink-500">{lang === 'hi' ? 'खतरा गेज' : 'CWC danger'}</div>
                  </div>
                  <div>
                    <div className="font-mono text-base font-bold text-risk-orange">{replayDate ? '—' : g?.warning ?? 0}</div>
                    <div className="text-[9px] uppercase tracking-wide text-ink-500">{lang === 'hi' ? 'चेतावनी गेज' : 'CWC warning'}</div>
                  </div>
                  <div>
                    <div className="font-mono text-base font-bold text-chakra-500">{compactPopulation(s.population_at_risk)}</div>
                    <div className="text-[9px] uppercase tracking-wide text-ink-500">{lang === 'hi' ? 'जोखिम में' : 'at risk'}</div>
                  </div>
                </div>
                {!replayDate && <StateWeather lang={lang} wx={s.weather} />}
                {g?.worst?.above_danger_m > 0 && (
                  <div className="mt-2 rounded bg-risk-red/10 px-2 py-1 text-[10.5px] font-semibold text-risk-red">
                    {g.worst.name}: +{g.worst.above_danger_m} m {lang === 'hi' ? 'खतरे के निशान से ऊपर' : 'above danger'}
                  </div>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </PageShell>
  );
}

/**
 * Current conditions on a state card: the sky at its most populous monitored
 * place, then the spread across the state so one town doesn't stand in for all.
 */
function StateWeather({ lang, wx }) {
  if (!wx) return null;
  const L = (en, hiText) => (lang === 'hi' ? hiText : en);
  const info = weatherInfo(wx.code, wx.is_day);
  const place = lang === 'hi' && wx.place_hi ? wx.place_hi : wx.place;
  const wettest = lang === 'hi' && wx.wettest?.name_hi ? wx.wettest.name_hi : wx.wettest?.name;
  return (
    <div className="mt-2 rounded-lg border border-ink-800 bg-ink-850 px-2.5 py-2" data-tour="sm-weather">
      <div className="flex items-center gap-2">
        <span className="text-2xl leading-none" aria-hidden>{info.icon}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-1.5">
            <span className="font-mono text-lg font-bold text-ink-100">{Math.round(wx.temp_c)}°C</span>
            <span className={`truncate text-[11px] font-semibold text-ink-300 ${hi(lang)}`}>{L(info.en, info.hi)}</span>
          </div>
          <div className={`truncate text-[10px] text-ink-500 ${hi(lang)}`}>
            {L('Now at', 'अभी')} {place}
            {wx.feels_like_c != null && ` · ${L('feels', 'महसूस')} ${Math.round(wx.feels_like_c)}°`}
          </div>
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[10.5px] text-ink-400">
        <span title={L('Relative humidity', 'सापेक्ष आर्द्रता')}>💧 {wx.humidity_pct ?? '—'}%</span>
        <span title={L('Wind', 'हवा')}>💨 {wx.wind_kmh != null ? Math.round(wx.wind_kmh) : '—'} km/h {compass(wx.wind_dir_deg)}</span>
        <span title={L('Temperature range across monitored places', 'निगरानी स्थानों में तापमान सीमा')}>
          🌡️ {Math.round(wx.temp_min_c)}–{Math.round(wx.temp_max_c)}°
        </span>
      </div>
      {wx.raining_places > 0 && (
        <div className={`mt-1 truncate text-[10.5px] font-semibold text-chakra-500 ${hi(lang)}`}>
          🌧️ {L(`Raining at ${wx.raining_places} place${wx.raining_places > 1 ? 's' : ''}`, `${wx.raining_places} स्थानों पर बारिश`)}
          {` · ${L('heaviest', 'सर्वाधिक')} ${wettest} ${wx.wettest.precip_mm} mm ${L('in 15 min', '15 मिनट में')}`}
        </div>
      )}
    </div>
  );
}

/**
 * State Monitor's map: every town as a small risk circle and every CWC gauge that
 * is above warning or danger, beside the case counts per state. Clicking a state
 * (on the map or its bar) narrows the cards below to it.
 */
const shortLabel = (name) => (name.length > 18 ? `${name.slice(0, 17)}…` : name);

function StateCasesMap({ lang, country, locations, gauges, alerts, gaugeByState, replayDate, picked, onPick, layers, onLayers, onOpenLocation, onOpenStation }) {
  const states = country?.states ?? [];
  const L = (en, hiText) => (lang === 'hi' ? hiText : en);

  const totals = useMemo(() => {
    const t = { red: 0, orange: 0, yellow: 0, green: 0 };
    for (const l of locations) t[l.tier] = (t[l.tier] ?? 0) + 1;
    return {
      ...t,
      danger: gauges.filter((g) => g.status === 'DANGER').length,
      warning: gauges.filter((g) => g.status === 'WARNING').length,
      alerts: alerts.length,
    };
  }, [locations, gauges, alerts]);

  // Cases per state: towns at Red/Orange from the model, gauges above
  // danger/warning from CWC. States with gauges over danger first.
  const chart = useMemo(() => {
    const rows = {};
    const row = (state) => {
      const k = canonicalState(state);
      rows[k] ??= { state, townsRed: 0, townsOrange: 0, danger: 0, warning: 0 };
      return rows[k];
    };
    for (const l of locations) {
      if (l.tier === 'red') row(l.state).townsRed += 1;
      if (l.tier === 'orange') row(l.state).townsOrange += 1;
    }
    for (const [state, g] of Object.entries(gaugeByState)) {
      const r = row(state);
      r.danger += g.danger;
      r.warning += g.warning;
    }
    return Object.values(rows)
      .map((r) => ({ ...r, total: r.townsRed + r.townsOrange + r.danger + r.warning, label: shortLabel(stateName(r.state, lang)) }))
      .filter((r) => r.total > 0)
      .sort((a, b) => b.danger - a.danger || b.total - a.total)
      .slice(0, 12);
  }, [locations, gaugeByState, lang]);

  const counts = [
    [totals.red, L('Towns red', 'लाल शहर'), '#C62828'],
    [totals.orange, L('Towns orange', 'नारंगी शहर'), '#E4701E'],
    [totals.yellow, L('Towns yellow', 'पीले शहर'), '#C99700'],
    [replayDate ? '—' : totals.danger, L('CWC above danger', 'खतरे से ऊपर गेज'), '#C62828'],
    [replayDate ? '—' : totals.warning, L('CWC above warning', 'चेतावनी से ऊपर गेज'), '#E4701E'],
    [replayDate ? '—' : totals.alerts, L('Flood alerts', 'बाढ़ चेतावनियाँ'), '#0B2A5B'],
  ];

  const pickBar = (d) => d?.state && onPick(d.state);

  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <section className="panel relative isolate h-[440px] overflow-hidden sm:h-[560px]">
        <IndiaMap
          lang={lang}
          states={states}
          locations={locations}
          selectedState={picked}
          onSelectState={(name) => onPick(picked && canonicalState(name) === canonicalState(picked) ? null : name)}
          onSelectLocation={onOpenLocation}
          onSelectGauge={onOpenStation}
          showDistricts={false}
          gauges={gauges}
          alerts={alerts}
          layers={layers}
        />
        <div className="absolute right-3 top-3 z-[500] rounded-lg border border-ink-700 bg-white p-2.5 text-[11.5px] shadow-panel">
          <div className="mb-1 text-[9.5px] font-bold uppercase tracking-wider text-ink-500">{L('Layers', 'परतें')}</div>
          {[
            ['towns', L('Town risk circles', 'शहर जोखिम'), '#E4701E'],
            ['gauges', L('CWC gauges above warning', 'चेतावनी से ऊपर CWC गेज'), '#C62828'],
            ['alerts', L('Official alerts', 'आधिकारिक चेतावनियाँ'), '#F26A1B'],
          ].map(([key, label, c]) => (
            <label key={key} className={`flex cursor-pointer items-center gap-2 py-0.5 ${hi(lang)}`}>
              <input type="checkbox" className="accent-saffron-500" checked={layers[key]} onChange={() => onLayers((x) => ({ ...x, [key]: !x[key] }))} />
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} />
              {label}
            </label>
          ))}
        </div>
        <div className="absolute bottom-3 left-3 z-[500] rounded-lg border border-ink-700 bg-white px-2.5 py-1.5 text-[11px] text-ink-300 shadow-panel">
          {picked ? (
            <button type="button" className="font-bold text-saffron-300" onClick={() => onPick(null)}>
              ← {L('All India', 'पूरा भारत')}
            </button>
          ) : (
            <span className={hi(lang)}>{L('Click a state to filter the cards', 'कार्ड छाँटने हेतु राज्य पर क्लिक करें')}</span>
          )}
        </div>
      </section>

      <section className="panel flex min-w-0 flex-col p-3.5">
        <div className="flex items-center justify-between gap-2">
          <h3 className={`panel-title ${hi(lang)}`}>{L('Cases right now', 'वर्तमान स्थिति')}</h3>
          {replayDate && <span className="text-[10.5px] text-ink-500">{L('Gauges are not archived for replays', 'पुनरावृत्ति में गेज उपलब्ध नहीं')}</span>}
        </div>
        <div className="mt-2 grid grid-cols-3 gap-2">
          {counts.map(([value, label, colour]) => (
            <div key={label} className="rounded-lg border border-ink-700 bg-white px-3 py-2">
              <div className="font-mono text-2xl font-extrabold leading-none" style={{ color: colour }}>{value}</div>
              <div className={`mt-1 text-[9.5px] font-bold uppercase tracking-wide text-ink-500 ${hi(lang)}`}>{label}</div>
            </div>
          ))}
        </div>

        <h4 className={`mt-4 text-[11px] font-bold uppercase tracking-wider text-chakra-500 ${hi(lang)}`}>{L('Cases by state', 'राज्यवार मामले')}</h4>
        <p className={`text-[10.5px] text-ink-500 ${hi(lang)}`}>
          {L('Top bar: CWC river gauges over the mark. Bottom bar: towns at Orange/Red. Click to filter.', 'ऊपर: निशान से ऊपर CWC गेज। नीचे: नारंगी/लाल शहर। छाँटने हेतु क्लिक करें।')}
        </p>
        {chart.length === 0 ? (
          <div className="grid flex-1 place-items-center py-8 text-[12px] text-ink-500">{L('No state has an active case.', 'किसी राज्य में सक्रिय मामला नहीं।')}</div>
        ) : (
          <div className="mt-1">
            <ResponsiveContainer width="100%" height={Math.max(260, chart.length * 34 + 60)}>
              <BarChart data={chart} layout="vertical" margin={{ top: 4, right: 12, bottom: 0, left: 0 }} barCategoryGap={5} barGap={1}>
                <CartesianGrid horizontal={false} stroke="#E3E8EF" />
                <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10, fill: '#526071' }} />
                <YAxis type="category" dataKey="label" width={118} tick={{ fontSize: 10.5, fill: '#0F1A2A' }} interval={0} />
                <Tooltip cursor={{ fill: 'rgba(242,106,27,0.08)' }} contentStyle={{ fontSize: 11, borderRadius: 8 }} />
                <Legend wrapperStyle={{ fontSize: 10.5 }} iconSize={9} />
                <Bar dataKey="danger" stackId="g" name={L('Gauges > danger', 'गेज > खतरा')} fill="#C62828" onClick={pickBar} cursor="pointer" />
                <Bar dataKey="warning" stackId="g" name={L('Gauges > warning', 'गेज > चेतावनी')} fill="#F4A259" onClick={pickBar} cursor="pointer" />
                <Bar dataKey="townsRed" stackId="t" name={L('Towns red', 'लाल शहर')} fill="#8E1B1B" onClick={pickBar} cursor="pointer" />
                <Bar dataKey="townsOrange" stackId="t" name={L('Towns orange', 'नारंगी शहर')} fill="#E4701E" onClick={pickBar} cursor="pointer" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>
    </div>
  );
}

/* ============================================================ TIME MACHINE */

export function TimeMachine({ lang, replayDate, onReplay, onExit }) {
  const [presets, setPresets] = useState([]);
  const [date, setDate] = useState(replayDate ?? '');
  const [busy, setBusy] = useState(null);

  useEffect(() => {
    api.presets().then((d) => setPresets(d.presets)).catch(() => {});
  }, []);

  async function go(d) {
    setBusy(d);
    try {
      await onReplay(d);
    } finally {
      setBusy(null);
    }
  }

  return (
    <PageShell
      title={lang === 'hi' ? 'टाइम मशीन — ऐतिहासिक बाढ़ पुनरावृत्ति' : 'Time Machine — replay historic floods'}
      subtitle={
        lang === 'hi'
          ? 'पूरे भारत को किसी भी पिछली तिथि (1994 से) पर उसी जोखिम इंजन से स्कोर करें — ओपन-मेटियो संग्रह व ग्लोफास पुनर्विश्लेषण से। देखें कि मॉडल ने वास्तविक बाढ़ को चिह्नित किया होता या नहीं।'
          : 'Score the whole country on any past date since 1994 through the same engine, from the Open-Meteo archive and GloFAS reanalysis — and see whether it would have flagged real floods.'
      }
      right={
        replayDate && (
          <button type="button" className="btn btn-primary" onClick={onExit}>
            {lang === 'hi' ? 'लाइव पर लौटें' : 'Back to live'}
          </button>
        )
      }
    >
      <div className="panel flex flex-wrap items-end gap-3 p-4" data-tour="tm-date">
        <label className="block">
          <span className="text-[11px] font-semibold text-ink-400">{lang === 'hi' ? 'कोई भी तिथि चुनें' : 'Pick any date'}</span>
          <input
            type="date"
            min="1994-01-01"
            max={new Date(Date.now() - 86400000).toISOString().slice(0, 10)}
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="mt-1 block rounded-lg border border-ink-700 bg-white px-3 py-2 font-mono text-[13px]"
          />
        </label>
        <button type="button" className="btn btn-primary px-5 py-2.5" disabled={!date || busy} onClick={() => go(date)}>
          {busy === date ? '…' : lang === 'hi' ? 'पूरे भारत को पुनः चलाएँ' : 'Replay all India'}
        </button>
        <p className={`text-[11px] text-ink-500 ${hi(lang)}`}>
          {lang === 'hi'
            ? 'पहली बार किसी तिथि में 1–3 मिनट लगते हैं (112 स्थानों का संग्रह डेटा), फिर तुरंत।'
            : 'First load of a date takes 1–3 minutes while archive data for 112 locations is fetched; after that it is instant.'}
        </p>
      </div>

      <h3 className={`pt-2 text-[13px] font-bold uppercase tracking-wider text-chakra-500 ${hi(lang)}`}>
        {lang === 'hi' ? 'आपके क्षेत्र की प्रमुख दर्ज बाढ़ें' : 'Major recorded floods in your area'}
      </h3>
      {presets.length === 0 && (
        <p className={`text-[12.5px] text-ink-400 ${hi(lang)}`}>
          {lang === 'hi'
            ? 'आपके क्षेत्र में कोई बड़ी दर्ज बाढ़ नहीं है — ऊपर कोई भी तारीख़ चुनें।'
            : 'No major recorded flood in your area — pick any date above.'}
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" data-tour="tm-presets">
        {presets.map((p) => (
          <button
            key={p.date}
            type="button"
            disabled={!!busy}
            onClick={() => go(p.date)}
            className={`panel group p-3.5 text-left transition hover:-translate-y-0.5 hover:border-saffron-500 ${replayDate === p.date ? 'ring-2 ring-saffron-500' : ''}`}
          >
            <div className="font-mono text-[12px] font-bold text-saffron-300">{longDateIST(p.date)}</div>
            <div className={`mt-0.5 text-[14px] font-bold text-chakra-500 ${hi(lang)}`}>
              {lang === 'hi' && p.location_name_hi ? p.location_name_hi : p.location_name}
              <span className="text-[11px] font-medium text-ink-500"> · {stateName(p.state, lang)}</span>
            </div>
            <p className="mt-1 line-clamp-2 text-[11.5px] leading-snug text-ink-300">{p.headline}</p>
            <div className="mt-2 text-[11px] font-bold text-saffron-300 group-hover:underline">
              {busy === p.date ? (lang === 'hi' ? 'लोड हो रहा है…' : 'Loading…') : lang === 'hi' ? 'इस दिन को पुनः चलाएँ →' : 'Replay this day →'}
            </div>
          </button>
        ))}
      </div>
    </PageShell>
  );
}
