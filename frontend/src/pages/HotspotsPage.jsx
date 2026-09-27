import { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import { Area, Bar, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../lib/api';
import { stateName } from '../lib/format';
import { go, href } from '../lib/router';
import { SectionHead, Spinner } from '../components/Primitives';

/**
 * Street-level water-accumulation hotspots for one city.
 *
 * City-level weather does not say which streets
 * flood. The backend scores an 800 m grid from terrain, drains, urban form and
 * hourly rain; this page lets an officer scrub through the next 24 hours, stress
 * the city with a design storm, change drainage performance, and work down a
 * ranked list of places to act on.
 */

const hi = (lang) => (lang === 'hi' ? 'font-devanagari' : '');

// Water-accumulation scale (distinct from the susceptibility scale below, so the two
// layers are never confused for one another).
function riskColour(v) {
  if (v >= 85) return '#7F0D18';
  if (v >= 65) return '#C1121F';
  if (v >= 40) return '#E4701E';
  if (v >= 15) return '#E8B10B';
  return null;
}
function suscColour(v) {
  const stops = [
    [20, '#EEF3FA'],
    [35, '#BFD3EE'],
    [50, '#7FA6DA'],
    [65, '#3F6FB8'],
    [100, '#1B3A6B'],
  ];
  return stops.find(([s]) => v <= s)?.[1] ?? '#1B3A6B';
}

// Spread view: when water arrives. Hot = soon; the ensemble probability sets opacity.
const ETA_STOPS = [
  [0, '#7F0D18'],
  [1, '#C1121F'],
  [3, '#E4701E'],
  [6, '#E8B10B'],
  [12, '#9FC3E8'],
  [24, '#D6E4F5'],
];
function etaColour(c) {
  if (!c.eta_h || c.prob_flood < 0.1) return null;
  const h = c.flooded_now ? 0 : c.eta_h.p50;
  return ETA_STOPS.find(([s]) => h <= s)?.[1] ?? '#D6E4F5';
}

const DRIVER = {
  upstream: { en: 'fed from upslope', hi: 'ऊपर से बहकर आया पानी', colour: '#1B5FA8' },
  mixed: { en: 'rain + upslope water', hi: 'वर्षा + ऊपर से आया पानी', colour: '#6B4FA8' },
  rain: { en: 'local rain', hi: 'स्थानीय वर्षा', colour: '#6E7C8D' },
};
const EVIDENCE = {
  strong: { en: 'strong evidence', hi: 'मज़बूत साक्ष्य', colour: '#0B8A3D' },
  moderate: { en: 'moderate evidence', hi: 'मध्यम साक्ष्य', colour: '#C99700' },
  weak: { en: 'weak evidence', hi: 'कमज़ोर साक्ष्य', colour: '#C1121F' },
};

function etaText(eta, lang) {
  if (!eta) return '—';
  const range = eta.p10 === eta.p90 ? '' : ` (${eta.p10}–${eta.p90} h)`;
  if (eta.p50 <= 0) return lang === 'hi' ? `अभी${range}` : `now${range}`;
  return lang === 'hi' ? `~${eta.p50} घं में${range}` : `in ~${eta.p50} h${range}`;
}

const STORMS = [
  { key: null, en: 'Live forecast', hi: 'लाइव पूर्वानुमान' },
  { key: 20, en: '20 mm/h shower', hi: '20 मिमी/घं बौछार' },
  { key: 50, en: '50 mm/h heavy', hi: '50 मिमी/घं भारी' },
  { key: 90, en: '90 mm/h cloudburst', hi: '90 मिमी/घं बादल फटना' },
];

export default function HotspotsPage({ lang, id, locations }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [storm, setStorm] = useState(null);
  const [capacity, setCapacity] = useState(1.0);
  const [mode, setMode] = useState('peak'); // hour | peak | susceptibility
  const [hour, setHour] = useState(null);
  const [playing, setPlaying] = useState(false);
  const [focus, setFocus] = useState(null);
  const [showFlow, setShowFlow] = useState(true);

  const hostRef = useRef(null);
  const mapRef = useRef(null);
  const gridRef = useRef(null);
  const flowRef = useRef(null);
  const markRef = useRef(null);

  const cityId = id || locations?.[0]?.id;
  const [osmPoll, setOsmPoll] = useState(0);
  const quietRef = useRef(false);

  useEffect(() => {
    if (!cityId) return undefined;
    let alive = true;
    const quiet = quietRef.current;
    quietRef.current = false;
    if (!quiet) setBusy(true);
    setError(null);
    const q = new URLSearchParams({ capacity: String(capacity) });
    if (storm) {
      q.set('scenario_mm_h', String(storm));
      q.set('scenario_hours', '3');
    }
    api
      .hotspots(cityId, q)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setHour((h) => (h == null || h >= d.hours.length ? d.now_index : h));
      })
      .catch((e) => alive && !quiet && setError(e.message))
      .finally(() => alive && setBusy(false));
    return () => {
      alive = false;
    };
  }, [cityId, storm, capacity, osmPoll]);

  // First visit to a city without a bundled grid answers from terrain and rain
  // while OpenStreetMap drains and roads finish loading on the server; pick
  // them up quietly once they land.
  useEffect(() => {
    if (!data?.grid?.osm_pending) return undefined;
    const t = setTimeout(() => {
      quietRef.current = true;
      setOsmPoll((n) => n + 1);
    }, 20_000);
    return () => clearTimeout(t);
  }, [data]);

  // map setup
  useEffect(() => {
    if (mapRef.current || !hostRef.current) return undefined;
    const map = L.map(hostRef.current, { zoomControl: true, zoomSnap: 0.5 });
    map.zoomControl.setPosition('bottomright');
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 18,
      opacity: 0.85,
    }).addTo(map);
    gridRef.current = L.layerGroup().addTo(map);
    flowRef.current = L.layerGroup().addTo(map);
    markRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // fit to city
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !data) return;
    const [s, w, n, e] = data.grid.bbox;
    map.fitBounds([[s, w], [n, e]], { padding: [10, 10] });
    setTimeout(() => map.invalidateSize(), 80);
  }, [data?.location?.id]);

  // draw grid
  useEffect(() => {
    const group = gridRef.current;
    if (!group || !data) return;
    group.clearLayers();
    const half = data.grid.step_deg / 2;
    for (const c of data.cells) {
      if (c.sea) continue;
      let v;
      let fill;
      let opacity = 0.62;
      if (mode === 'susceptibility') {
        v = c.susceptibility;
        fill = suscColour(v);
        opacity = 0.55;
      } else if (mode === 'spread') {
        v = c.peak_risk;
        fill = etaColour(c);
        opacity = 0.2 + 0.55 * c.prob_flood;
      } else {
        v = mode === 'peak' ? c.peak_risk : data.risk_by_hour[hour ?? data.now_index][c.k];
        fill = riskColour(v);
      }
      const isFocus = focus === c.k;
      // Weak propagation evidence is drawn dashed, so an uncertain prediction
      // never looks as solid as a well-supported one.
      const weak = mode === 'spread' && fill && c.evidence === 'weak';
      const rect = L.rectangle(
        [[c.lat - half, c.lon - half], [c.lat + half, c.lon + half]],
        {
          color: isFocus ? '#0B2A5B' : weak ? '#4B5563' : '#ffffff',
          weight: isFocus ? 3 : weak ? 1.4 : 0.4,
          dashArray: weak && !isFocus ? '3 3' : null,
          fillColor: fill ?? '#ffffff',
          fillOpacity: fill ? opacity : 0.02,
        },
      );
      rect.bindTooltip(
        `<div style="min-width:190px">
          <strong>${lang === 'hi' ? 'ग्रिड कोशिका' : 'Grid cell'} ${c.i}-${c.j}</strong>
          <div style="font-size:10.5px;margin-top:3px;font-family:ui-monospace,monospace;line-height:1.5">
            ${lang === 'hi' ? 'जलभराव जोखिम' : 'Water risk'}: ${mode === 'susceptibility' ? c.peak_risk : v}/100<br/>
            ${lang === 'hi' ? '24 घं शिखर जलभराव' : '24 h peak ponding'}: ${c.peak_ponding_mm} mm (${c.peak_low_mm}–${c.peak_high_mm})<br/>
            ${lang === 'hi' ? 'संवेदनशीलता' : 'Susceptibility'}: ${c.susceptibility}<br/>
            ${lang === 'hi' ? 'ऊँचाई' : 'Elevation'} ${c.elev} m · ${lang === 'hi' ? 'गड्ढा' : 'sink'} ${c.sink_m} m · ${lang === 'hi' ? 'ऊपरी कोशिकाएँ' : 'upslope'} ${c.acc}<br/>
            ${lang === 'hi' ? 'नालियाँ' : 'Mapped drains'}: ${c.drains} · ${lang === 'hi' ? 'क्षमता' : 'capacity'} ${c.capacity_mm_h} mm/h
          </div>
          ${c.prob_flood > 0 ? `<div style="font-size:10.5px;margin-top:3px;border-top:1px solid #E5EAF0;padding-top:3px">
            ${lang === 'hi' ? 'बाढ़ संभावना' : 'Flood probability'}: <b>${Math.round(c.prob_flood * 100)}%</b> · ${lang === 'hi' ? 'पहुँच' : 'arrives'} ${etaText(c.eta_h, lang)}<br/>
            ${lang === 'hi' ? DRIVER[c.driver].hi : DRIVER[c.driver].en}${c.inflow_share > 0 ? ` (${Math.round(c.inflow_share * 100)}% ${lang === 'hi' ? 'ऊपर से' : 'from upslope'})` : ''} · <span style="color:${EVIDENCE[c.evidence].colour}">${lang === 'hi' ? EVIDENCE[c.evidence].hi : EVIDENCE[c.evidence].en}</span>
          </div>` : ''}
          ${c.tunnels.length ? `<div style="font-size:10.5px;color:#C1121F;margin-top:2px">⚠ ${c.tunnels.join(', ')}</div>` : ''}
          ${c.hospitals.length ? `<div style="font-size:10.5px;color:#0B2A5B;margin-top:2px">✚ ${c.hospitals.slice(0, 2).join(', ')}</div>` : ''}
        </div>`,
        { sticky: true, opacity: 1 },
      );
      rect.on('click', () => setFocus(c.k));
      rect.addTo(group);
    }

    // Water flow between cells: an arrow from each cell to its main downslope
    // neighbour, as thick as the water it passes on. At a chosen hour it shows
    // that hour's flow; otherwise the total over the next 24 h.
    const flows = flowRef.current;
    flows.clearLayers();
    if (showFlow && mode !== 'susceptibility') {
      const out = data.propagation.outflow_by_hour;
      const at = hour ?? data.now_index;
      const volume = (k) =>
        mode === 'hour' ? out[at][k] : out.slice(data.now_index).reduce((sum, row) => sum + row[k], 0);
      const byK = Object.fromEntries(data.cells.map((c) => [c.k, c]));
      const edges = data.cells
        .filter((c) => !c.sea && c.downstream_k >= 0)
        .map((c) => ({ c, d: byK[c.downstream_k], v: volume(c.k) }))
        .filter((e) => e.v >= (mode === 'hour' ? 0.5 : 2))
        .sort((a, b) => b.v - a.v)
        .slice(0, 160);
      const vmax = edges[0]?.v || 1;
      for (const { c, d, v } of edges) {
        const tip = [c.lat + (d.lat - c.lat) * 0.8, c.lon + (d.lon - c.lon) * 0.8];
        const w = 1.2 + 4 * Math.sqrt(v / vmax);
        L.polyline([[c.lat, c.lon], tip], { color: '#1B5FA8', weight: w, opacity: 0.85, interactive: false }).addTo(flows);
        // arrowhead: a small triangle at the tip, pointing downslope
        const ang = Math.atan2(d.lat - c.lat, d.lon - c.lon);
        const size = data.grid.step_deg * 0.22;
        const left = [tip[0] - size * Math.sin(ang + 0.5), tip[1] - size * Math.cos(ang + 0.5)];
        const right = [tip[0] - size * Math.sin(ang - 0.5), tip[1] - size * Math.cos(ang - 0.5)];
        L.polygon([tip, left, right], { color: '#1B5FA8', weight: 1, fillColor: '#1B5FA8', fillOpacity: 0.95, interactive: false }).addTo(flows);
      }
    }

    // facilities in the top-priority cells
    const marks = markRef.current;
    marks.clearLayers();
    for (const p of data.priorities.slice(0, 8)) {
      const badge = L.divIcon({
        className: '',
        html: `<div style="width:22px;height:22px;border-radius:99px;background:#0B2A5B;color:#fff;font:700 11px/22px Inter,sans-serif;text-align:center;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.4)">${p.rank}</div>`,
        iconSize: [22, 22],
        iconAnchor: [11, 11],
      });
      L.marker([p.lat, p.lon], { icon: badge, zIndexOffset: 800 })
        .bindTooltip(`<strong>#${p.rank} ${p.label}</strong>`, { direction: 'top' })
        .on('click', () => setFocus(p.k))
        .addTo(marks);
    }
  }, [data, mode, hour, focus, lang, showFlow]);

  // play through the hours
  useEffect(() => {
    if (!playing || !data) return undefined;
    const t = setInterval(() => {
      setHour((h) => {
        const next = (h ?? 0) + 1;
        if (next >= data.hours.length) {
          setPlaying(false);
          return data.now_index;
        }
        return next;
      });
    }, 550);
    return () => clearInterval(t);
  }, [playing, data]);

  const focusCell = useMemo(() => data?.cells.find((c) => c.k === focus), [data, focus]);
  const hourLabel = (iso) =>
    new Date(iso).toLocaleString('en-IN', { weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false });

  const cities = useMemo(() => [...(locations ?? [])].sort((a, b) => a.name.localeCompare(b.name)), [locations]);

  return (
    <div id="main-content" className="mx-auto w-full max-w-[1700px] space-y-4 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b-2 border-saffron-500 pb-3">
        <div>
          <h1 className={`text-2xl font-extrabold tracking-tight text-chakra-500 ${hi(lang)}`}>
            {lang === 'hi' ? 'गली-स्तर जलभराव हॉटस्पॉट' : 'Street-level waterlogging hotspots'}
          </h1>
          <p className={`text-[12px] text-ink-400 ${hi(lang)}`}>
            {lang === 'hi'
              ? 'शहर-स्तरीय मौसम हर गली की स्थिति नहीं बताता — 800 मीटर ग्रिड पर भूभाग, नालियाँ, शहरी घनत्व व प्रति घंटा वर्षा से जलभराव का अनुमान'
              : 'City-level weather cannot say which streets flood. An 800 m grid combines terrain, drains, urban form and hourly rain to estimate where water accumulates, hour by hour.'}
          </p>
        </div>
        <label className="flex items-center gap-2 text-[12px] font-semibold text-ink-300" data-tour="hs-city">
          {lang === 'hi' ? 'शहर' : 'City'}
          <select
            value={cityId ?? ''}
            onChange={(e) => {
              setFocus(null);
              go(`/hotspots/${e.target.value}`);
            }}
            className="rounded-lg border border-ink-700 bg-white px-3 py-2 text-[13px] font-bold text-chakra-500"
          >
            {cities.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name} — {l.state}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <p className="panel p-3 text-[12px] text-risk-red">{error}</p>}
      {!error && data && !data.scenario && data.rain_source && data.rain_source !== 'live' && (
        <p className="panel border-l-4 border-l-risk-orange p-3 text-[12px] text-ink-200">
          {{
            cached: lang === 'hi'
              ? 'मौसम सेवा अभी व्यस्त है — इस शहर का पिछला वर्षा पूर्वानुमान दिखाया जा रहा है।'
              : 'Weather service is busy right now — showing this city’s last fetched rain forecast.',
            town: lang === 'hi'
              ? 'मौसम सेवा अभी व्यस्त है — शहर-केंद्र की वर्षा पूरे ग्रिड पर लागू की गई है।'
              : 'Weather service is busy right now — using the town-centre rain series across the whole grid.',
            none: lang === 'hi'
              ? 'लाइव वर्षा अभी उपलब्ध नहीं है — रैंकिंग केवल भू-भाग पर आधारित है। वर्षा परिदृश्य (20/50/90 मिमी/घं) पूरी तरह काम करते हैं।'
              : 'Live rain is unavailable right now, so ranking is by terrain only. The 20 / 50 / 90 mm/h storm scenarios work fully.',
          }[data.rain_source]}
        </p>
      )}

      <div className="grid gap-4 xl:grid-cols-[1fr_400px]">
        {/* ------------------------------------------------------------- map */}
        <div className="space-y-3">
          <div className="panel flex flex-wrap items-center gap-3 p-3">
            <div className="flex rounded-lg border border-ink-700 p-0.5" data-tour="hs-mode">
              {[
                ['hour', lang === 'hi' ? 'चुने घंटे पर जलभराव' : 'Water at selected hour'],
                ['peak', lang === 'hi' ? 'अगले 24 घंटे का शिखर' : 'Peak in next 24 h'],
                ['spread', lang === 'hi' ? 'फैलाव व पहुँच समय' : 'Spread & arrival'],
                ['susceptibility', lang === 'hi' ? 'स्थायी संवेदनशीलता' : 'Terrain susceptibility'],
              ].map(([k, label]) => (
                <button key={k} type="button" onClick={() => setMode(k)} className={`rounded-md px-2.5 py-1.5 text-[11.5px] font-bold ${mode === k ? 'bg-chakra-500 text-white' : 'text-ink-400 hover:bg-ink-800'} ${hi(lang)}`}>
                  {label}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap gap-1" data-tour="hs-storm">
              {STORMS.map((s) => (
                <button
                  key={String(s.key)}
                  type="button"
                  onClick={() => {
                    setStorm(s.key);
                    if (s.key) setMode('spread');
                  }}
                  className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${storm === s.key ? 'border-saffron-500 bg-saffron-500 text-white' : 'border-ink-700 text-ink-300 hover:border-saffron-500'} ${hi(lang)}`}
                >
                  {lang === 'hi' ? s.hi : s.en}
                </button>
              ))}
            </div>
            <label className={`flex items-center gap-1.5 text-[11.5px] font-semibold text-ink-300 ${hi(lang)}`} data-tour="hs-flow">
              <input type="checkbox" checked={showFlow} onChange={(e) => setShowFlow(e.target.checked)} className="accent-saffron-500" />
              <span className="text-[#1B5FA8]">➜</span>
              {lang === 'hi' ? 'जल प्रवाह' : 'Water flow'}
            </label>
            <label className={`ml-auto flex items-center gap-2 text-[11.5px] text-ink-300 ${hi(lang)}`} data-tour="hs-drain">
              {lang === 'hi' ? 'नाली क्षमता' : 'Drain capacity'}
              <input type="range" min="0.4" max="2" step="0.1" value={capacity} onChange={(e) => setCapacity(Number(e.target.value))} className="w-28 accent-saffron-500" />
              <b className="w-10 font-mono text-chakra-500">{capacity.toFixed(1)}×</b>
            </label>
          </div>

          <div className="panel relative isolate h-[560px] overflow-hidden" data-tour="hs-map">
            <div ref={hostRef} className="jd-map h-full w-full" />
            {(busy || !data) && (
              <div className="absolute inset-0 z-[600] grid place-items-center bg-white/60">
                <div className={`rounded-lg bg-white px-4 py-2 text-[12px] font-semibold text-chakra-500 shadow-panel ${hi(lang)}`}>
                  {lang === 'hi' ? 'ऊँचाई व वर्षा आँकड़े ला रहे हैं… (पहली बार ~10 से. तक)' : 'Fetching elevation and rainfall… (up to ~10 s the first time)'}
                </div>
              </div>
            )}
            <div className="absolute bottom-3 left-3 z-[500] rounded-lg border border-ink-700 bg-white px-3 py-2 shadow-panel">
              <div className={`mb-1 text-[10px] font-bold uppercase tracking-wider text-ink-500 ${hi(lang)}`}>
                {mode === 'susceptibility'
                  ? lang === 'hi' ? 'भूभाग संवेदनशीलता' : 'Terrain susceptibility'
                  : mode === 'spread'
                    ? lang === 'hi' ? 'पानी कब पहुँचेगा' : 'When water arrives'
                    : lang === 'hi' ? 'जलभराव जोखिम' : 'Water-accumulation risk'}
              </div>
              <div className="flex items-center gap-2 text-[10.5px]">
                {(mode === 'susceptibility'
                  ? [[35, 'low'], [50, ''], [65, ''], [100, 'high']].map(([v, l]) => [suscColour(v), l])
                  : mode === 'spread'
                    ? ETA_STOPS.map(([h, c]) => [c, h === 0 ? (lang === 'hi' ? 'अभी' : 'now') : `≤${h}h`])
                    : [[15, '15'], [40, '40'], [65, '65'], [85, '85+']].map(([v, l]) => [riskColour(v), l])
                ).map(([c, l], i) => (
                  <span key={i} className="flex items-center gap-1">
                    <span className="h-3 w-5 rounded-sm" style={{ background: c }} />
                    {l}
                  </span>
                ))}
              </div>
              {mode === 'spread' && (
                <p className={`mt-1 text-[10px] text-ink-500 ${hi(lang)}`}>
                  {lang === 'hi'
                    ? 'गहरा रंग = अधिक संभावना · धराशायी किनारा = कमज़ोर साक्ष्य'
                    : 'Stronger colour = more likely · dashed outline = weak evidence'}
                </p>
              )}
              <p className={`mt-1 text-[10px] text-ink-500 ${hi(lang)}`}>
                {showFlow && mode !== 'susceptibility' && (lang === 'hi' ? '➜ = ढलान पर बहता पानी · ' : '➜ = water flowing downslope · ')}
                {lang === 'hi' ? '① ② = प्राथमिकता क्रम' : '① ② = response priority rank'}
              </p>
            </div>
          </div>

          {data && (
            <div className="panel p-3" data-tour="hs-time">
              <div className="flex flex-wrap items-center gap-3">
                <button type="button" className="btn btn-primary" onClick={() => { setMode('hour'); setPlaying((p) => !p); }}>
                  {playing ? '❚❚' : '▶'} {lang === 'hi' ? 'समय चलाएँ' : 'Play 48 h'}
                </button>
                <input
                  type="range"
                  min="0"
                  max={data.hours.length - 1}
                  value={hour ?? data.now_index}
                  onChange={(e) => {
                    setMode('hour');
                    setHour(Number(e.target.value));
                  }}
                  className="min-w-[200px] flex-1 accent-saffron-500"
                />
                <span className="font-mono text-[12px] font-bold text-chakra-500">
                  {hourLabel(data.hours[hour ?? data.now_index])}
                  {(hour ?? data.now_index) === data.now_index ? (lang === 'hi' ? ' (अभी)' : ' (now)') : (hour ?? 0) > data.now_index ? (lang === 'hi' ? ' पूर्वानुमान' : ' forecast') : (lang === 'hi' ? ' बीता' : ' past')}
                </span>
              </div>
              <div className="mt-2 h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart
                    data={data.timeline.map((x, i) => ({
                      ...x,
                      i,
                      bandBase: x.cells_flooded_band?.[0] ?? 0,
                      bandSpan: (x.cells_flooded_band?.[2] ?? 0) - (x.cells_flooded_band?.[0] ?? 0),
                    }))}
                    margin={{ top: 6, right: 10, bottom: 0, left: -12 }}
                  >
                    <CartesianGrid stroke="#E5EAF0" vertical={false} />
                    <XAxis dataKey="i" tick={{ fontSize: 10, fill: '#6E7C8D' }} tickFormatter={(i) => new Date(data.timeline[i].time).toLocaleTimeString('en-IN', { hour: '2-digit', hour12: false })} interval={5} />
                    <YAxis yAxisId="r" tick={{ fontSize: 10, fill: '#6E7C8D' }} width={40} />
                    <YAxis yAxisId="c" orientation="right" tick={{ fontSize: 10, fill: '#6E7C8D' }} width={34} />
                    <Tooltip labelFormatter={(i) => hourLabel(data.timeline[i].time)} />
                    <ReferenceLine x={data.now_index} yAxisId="r" stroke="#0B2A5B" strokeDasharray="4 3" label={{ value: lang === 'hi' ? 'अभी' : 'now', fontSize: 10, fill: '#0B2A5B', position: 'top' }} />
                    <ReferenceLine x={hour ?? data.now_index} yAxisId="r" stroke="#F26A1B" />
                    <Bar yAxisId="r" dataKey="rain_mm_h" name={lang === 'hi' ? 'वर्षा मिमी/घं' : 'Rain mm/h'} fill="#7FA6DA" />
                    <Area yAxisId="c" dataKey="bandBase" stackId="band" stroke="none" fill="transparent" isAnimationActive={false} legendType="none" tooltipType="none" />
                    <Area yAxisId="c" dataKey="bandSpan" stackId="band" stroke="none" fill="#1B5FA8" fillOpacity={0.15} isAnimationActive={false} name={lang === 'hi' ? 'बाढ़ग्रस्त कोशिकाएँ: 10–90% सीमा' : 'Flooded cells: 10–90% range'} tooltipType="none" />
                    <Line yAxisId="c" dataKey="cells_flooded" name={lang === 'hi' ? 'बाढ़ग्रस्त कोशिकाएँ' : 'Flooded cells'} stroke="#1B5FA8" strokeWidth={2} dot={false} />
                    <Line yAxisId="c" dataKey="cells_elevated" name={lang === 'hi' ? 'सतर्क कोशिकाएँ (≥40)' : 'Cells ≥40'} stroke="#E4701E" strokeWidth={2} dot={false} />
                    <Line yAxisId="c" dataKey="cells_high" name={lang === 'hi' ? 'उच्च कोशिकाएँ (≥65)' : 'Cells ≥65'} stroke="#C1121F" strokeWidth={2} dot={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <p className={`text-[10.5px] text-ink-500 ${hi(lang)}`}>
                {lang === 'hi'
                  ? 'नीले बार = शहर में औसत वर्षा (मिमी/घंटा) · नारंगी/लाल रेखा = जलभराव वाली कोशिकाएँ · गहरी नीली रेखा व छाया = बाढ़ग्रस्त कोशिकाएँ और 20 रन की 10–90% सीमा'
                  : 'Blue bars = rainfall across the city (mm/h) · orange/red lines = cells accumulating water · dark blue line and shading = flooded cells and the 10–90% range across 20 ensemble runs'}
              </p>
            </div>
          )}
        </div>

        {/* ------------------------------------------------------- side rail */}
        <div className="space-y-4">
          {data && (
            <section className="panel p-4" data-tour="hs-summary">
              <div className="flex items-start justify-between">
                <div>
                  <div className={`text-lg font-extrabold text-chakra-500 ${hi(lang)}`}>{lang === 'hi' && data.location.name_hi ? data.location.name_hi : data.location.name}</div>
                  <div className={`text-[11px] text-ink-500 ${hi(lang)}`}>{stateName(data.location.state, lang)} · {data.grid.n}×{data.grid.n} · {data.grid.cell_m} m {lang === 'hi' ? 'कोशिकाएँ' : 'cells'}</div>
                </div>
                <a href={href(`/location/${data.location.id}`)} className="text-[11.5px] font-bold text-saffron-300 hover:underline">{lang === 'hi' ? 'शहर आकलन →' : 'City assessment →'}</a>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                {[
                  [lang === 'hi' ? 'शिखर पर उच्च' : 'High at peak', Math.max(...data.timeline.filter((x) => x.is_forecast).map((x) => x.cells_high), 0), '#C1121F'],
                  [lang === 'hi' ? 'शिखर पर सतर्क' : 'Elevated at peak', Math.max(...data.timeline.filter((x) => x.is_forecast).map((x) => x.cells_elevated), 0), '#E4701E'],
                  [lang === 'hi' ? 'अधिकतम जलभराव' : 'Max ponding', `${Math.max(...data.timeline.map((x) => x.max_ponding_mm), 0).toFixed(0)} mm`, '#0B2A5B'],
                ].map(([k, v, c]) => (
                  <div key={k} className="panel-tight px-2 py-2">
                    <div className="font-mono text-xl font-extrabold" style={{ color: c }}>{v}</div>
                    <div className={`text-[9.5px] font-bold uppercase tracking-wide text-ink-500 ${hi(lang)}`}>{k}</div>
                  </div>
                ))}
              </div>
              {data.scenario && (
                <p className={`mt-2 rounded bg-saffron-50 px-2 py-1 text-[11px] font-semibold text-saffron-200 ${hi(lang)}`}>
                  {lang === 'hi' ? `परिदृश्य: ${data.scenario.mm_h} मिमी/घं × ${data.scenario.hours} घं — पूर्वानुमान नहीं` : `Scenario: ${data.scenario.mm_h} mm/h for ${data.scenario.hours} h — a planning test, not a forecast`}
                </p>
              )}
            </section>
          )}

          {focusCell && (
            <section className="panel border-chakra-500/50 p-4">
              <div className="flex items-center justify-between">
                <div className="text-[13px] font-bold text-chakra-500">{lang === 'hi' ? 'चयनित कोशिका' : 'Selected cell'} {focusCell.i}-{focusCell.j}</div>
                <button type="button" className="text-[11px] text-ink-500" onClick={() => setFocus(null)}>✕</button>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-x-4 font-mono text-[11px] text-ink-300">
                <span>peak {focusCell.peak_risk}/100</span>
                <span>{focusCell.peak_ponding_mm} mm ({focusCell.peak_low_mm}–{focusCell.peak_high_mm})</span>
                <span>elev {focusCell.elev} m</span>
                <span>sink {focusCell.sink_m} m</span>
                <span>upslope {focusCell.acc}</span>
                <span>drains {focusCell.drains}</span>
              </div>
              {!focusCell.sea && (
                <div className={`mt-3 space-y-1.5 border-t border-ink-800 pt-2 text-[11.5px] text-ink-200 ${hi(lang)}`}>
                  <div>
                    {lang === 'hi' ? 'बाढ़ संभावना' : 'Flood probability'}: <b>{Math.round(focusCell.prob_flood * 100)}%</b>
                    {focusCell.eta_h && <> · {lang === 'hi' ? 'पहुँच' : 'arrives'} <b>{etaText(focusCell.eta_h, lang)}</b></>}
                  </div>
                  {focusCell.prob_flood > 0 && (
                    <div>
                      <span style={{ color: DRIVER[focusCell.driver].colour }} className="font-semibold">
                        {lang === 'hi' ? DRIVER[focusCell.driver].hi : DRIVER[focusCell.driver].en}
                      </span>
                      {focusCell.inflow_share > 0 && ` · ${Math.round(focusCell.inflow_share * 100)}% ${lang === 'hi' ? 'शिखर जल ऊपर से' : 'of peak water from upslope'}`}
                    </div>
                  )}
                  {focusCell.source_k != null && (
                    <button type="button" className="font-semibold text-[#1B5FA8] hover:underline" onClick={() => setFocus(focusCell.source_k)}>
                      ↖ {lang === 'hi' ? 'पानी आता है' : 'Water comes from'} {data.cells[focusCell.source_k].i}-{data.cells[focusCell.source_k].j}
                    </button>
                  )}
                  {focusCell.downstream_k >= 0 && (
                    <button type="button" className="block font-semibold text-[#1B5FA8] hover:underline" onClick={() => setFocus(focusCell.downstream_k)}>
                      ↘ {lang === 'hi' ? 'अतिरिक्त पानी जाता है' : 'Overflow goes to'} {data.cells[focusCell.downstream_k].i}-{data.cells[focusCell.downstream_k].j}
                    </button>
                  )}
                  {focusCell.prob_flood > 0 && (
                    <div>
                      <span className="font-semibold" style={{ color: EVIDENCE[focusCell.evidence].colour }}>
                        {lang === 'hi' ? EVIDENCE[focusCell.evidence].hi : EVIDENCE[focusCell.evidence].en}
                      </span>
                      {focusCell.evidence_reasons.length > 0 && <span className="text-ink-400"> — {focusCell.evidence_reasons.join('; ')}</span>}
                    </div>
                  )}
                </div>
              )}
            </section>
          )}

          {data && (
            <section className="panel" data-tour="hs-next">
              <SectionHead
                title={lang === 'hi' ? 'आगे प्रभावित होने की संभावना' : 'Likely affected next'}
                lang={lang}
                right={
                  <span className="text-[10px] text-ink-500">
                    {lang === 'hi'
                      ? `अभी प्रभावित: ${data.propagation.affected_now.length}`
                      : `affected now: ${data.propagation.affected_now.length}`}
                  </span>
                }
              />
              {data.propagation.next_affected.length === 0 ? (
                <p className={`px-4 py-4 text-[12px] text-ink-400 ${hi(lang)}`}>
                  {lang === 'hi'
                    ? 'अगले 24 घंटों में किसी और कोशिका में बाढ़ का पूर्वानुमान नहीं है। पानी कैसे फैलेगा, यह देखने के लिए कोई वर्षा परिदृश्य चुनें।'
                    : 'No further cell is forecast to flood in the next 24 hours. Pick a storm scenario to see how water would spread.'}
                </p>
              ) : (
                <ol className="max-h-[420px] divide-y divide-ink-800 overflow-y-auto scrollbar-thin">
                  {data.propagation.next_affected.map((e) => (
                    <li key={e.k}>
                      <button
                        type="button"
                        onClick={() => {
                          setFocus(e.k);
                          setMode('spread');
                          mapRef.current?.flyTo([e.lat, e.lon], 15, { duration: 0.6 });
                        }}
                        className={`w-full px-4 py-2.5 text-left hover:bg-saffron-50 ${focus === e.k ? 'bg-saffron-50' : ''}`}
                      >
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="truncate text-[12.5px] font-bold text-ink-100">{e.label}</span>
                          <span className="shrink-0 font-mono text-[12px] font-bold text-chakra-500">{Math.round(e.prob * 100)}%</span>
                        </div>
                        <div className={`mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10.5px] ${hi(lang)}`}>
                          <span className="font-mono font-semibold text-risk-red">{etaText(e.eta_h, lang)}</span>
                          <span style={{ color: DRIVER[e.driver].colour }} className="font-semibold">{lang === 'hi' ? DRIVER[e.driver].hi : DRIVER[e.driver].en}</span>
                          <span className="font-semibold" style={{ color: EVIDENCE[e.evidence].colour }}>● {lang === 'hi' ? EVIDENCE[e.evidence].hi : EVIDENCE[e.evidence].en}</span>
                        </div>
                        {e.path.length > 0 && (
                          <div className="mt-0.5 truncate text-[10.5px] text-[#1B5FA8]">
                            {[...e.path].reverse().map((p) => p.label).join(' → ')} → <b>{lang === 'hi' ? 'यहाँ' : 'here'}</b>
                          </div>
                        )}
                        {e.evidence === 'weak' && e.evidence_reasons.length > 0 && (
                          <div className="mt-0.5 text-[10px] text-ink-500">{e.evidence_reasons.join('; ')}</div>
                        )}
                      </button>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          )}

          <section className="panel" data-tour="hs-priority">
            <SectionHead title={lang === 'hi' ? 'प्रतिक्रिया प्राथमिकता सूची' : 'Response priority list'} lang={lang} right={<span className="text-[10px] text-ink-500">{lang === 'hi' ? 'जोखिम × प्रभाव' : 'risk × impact'}</span>} />
            {!data ? (
              <Spinner lang={lang} />
            ) : (
              <ol className="max-h-[720px] divide-y divide-ink-800 overflow-y-auto scrollbar-thin">
                {data.priorities.map((p) => (
                  <li key={p.k}>
                    <button
                      type="button"
                      onClick={() => {
                        setFocus(p.k);
                        mapRef.current?.flyTo([p.lat, p.lon], 15, { duration: 0.6 });
                      }}
                      className={`w-full px-4 py-3 text-left hover:bg-saffron-50 ${focus === p.k ? 'bg-saffron-50' : ''}`}
                    >
                      <div className="flex items-start gap-3">
                        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-chakra-500 text-[12px] font-bold text-white">{p.rank}</span>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-baseline justify-between gap-2">
                            <span className="truncate text-[13px] font-bold text-ink-100">{p.label}</span>
                            <span className="shrink-0 font-mono text-[13px] font-bold" style={{ color: riskColour(p.peak_risk) ?? '#0B8A3D' }}>{p.peak_risk}</span>
                          </div>
                          <div className="font-mono text-[10.5px] text-ink-500">
                            {p.peak_ponding_mm} mm ({p.band_mm[0]}–{p.band_mm[1]}) · {new Date(p.peak_hour).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })}
                          </div>
                          <p className="mt-1 text-[11px] leading-snug text-ink-300">{p.why.join(' · ')}</p>
                          {(p.facilities.hospitals.length > 0 || p.facilities.tunnels.length > 0) && (
                            <p className="mt-1 text-[10.5px] text-chakra-500">
                              {p.facilities.tunnels.length > 0 && `⚠ ${p.facilities.tunnels[0]}  `}
                              {p.facilities.hospitals.length > 0 && `✚ ${p.facilities.hospitals[0]}`}
                            </p>
                          )}
                          <ul className="mt-1.5 space-y-0.5">
                            {(lang === 'hi' ? p.actions_hi : p.actions_en).slice(0, 3).map((a) => (
                              <li key={a} className={`text-[11px] font-medium text-saffron-200 ${hi(lang)}`}>→ {a}</li>
                            ))}
                          </ul>
                        </div>
                      </div>
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </section>

          {data && (
            <section className="panel p-4" data-tour="hs-confidence">
              <div className={`text-[11px] font-bold uppercase tracking-wider text-chakra-500 ${hi(lang)}`}>
                {lang === 'hi' ? 'विश्वसनीयता' : 'Confidence'}: {data.confidence.level}
              </div>
              <ul className="mt-2 space-y-1">
                {data.confidence.reasons.map((r) => (
                  <li key={r} className="text-[11px] text-ink-300">• {r}</li>
                ))}
              </ul>
              <p className={`mt-2 border-t border-ink-800 pt-2 text-[10.5px] text-ink-500 ${hi(lang)}`}>{lang === 'hi' ? data.method.hi : data.method.en}</p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
