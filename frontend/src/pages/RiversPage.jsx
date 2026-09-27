import { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../lib/api';
import { stateName } from '../lib/format';
import { go } from '../lib/router';
import { TownsInPath } from '../components/FloodWave';
import { GovBadge } from '../components/Official';
import { SectionHead, Spinner } from '../components/Primitives';

/**
 * India's rivers, coloured by what the CWC gauges on them are reading right now.
 *
 * Deliberately a separate page from the town-risk map: rivers are read along
 * their length (where is the flood wave, is it moving downstream towards a city),
 * which a map of scored towns cannot show. Reaches animate in the downstream
 * direction when that direction could be inferred from the gauges' datum levels.
 */

const hi = (lang) => (lang === 'hi' ? 'font-devanagari' : '');

export const RIVER_STATUS = {
  DANGER: { colour: '#C1121F', en: 'Above danger', hi: 'खतरे से ऊपर', weight: 5 },
  WARNING: { colour: '#E4701E', en: 'Above warning', hi: 'चेतावनी से ऊपर', weight: 4 },
  NORMAL: { colour: '#0B8A3D', en: 'Normal', hi: 'सामान्य', weight: 3 },
  UNMONITORED: { colour: '#94A3B8', en: 'No gauge', hi: 'गेज नहीं', weight: 2 },
};

export default function RiversPage({ lang, river: routeRiver, onOpenStation }) {
  const [data, setData] = useState(null);
  const [gauges, setGauges] = useState([]);
  const [error, setError] = useState(null);
  const [showNormalGauges, setShowNormalGauges] = useState(false);
  const selected = routeRiver ? decodeURIComponent(routeRiver) : null;

  const hostRef = useRef(null);
  const mapRef = useRef(null);
  const reachRef = useRef(null);
  const gaugeRef = useRef(null);

  useEffect(() => {
    Promise.all([api.rivers(), api.officialStations(false)])
      .then(([r, s]) => {
        setData(r);
        setGauges(s.stations);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (mapRef.current || !hostRef.current) return undefined;
    const map = L.map(hostRef.current, { zoomSnap: 0.5, minZoom: 4 });
    map.zoomControl.setPosition('bottomright');
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Basemap &copy; Esri · Rivers: Natural Earth · Gauges: Central Water Commission',
      maxZoom: 16,
    }).addTo(map);
    fetch('/geo/india-states.geojson')
      .then((r) => r.json())
      .then((gj) =>
        L.geoJSON(gj, { style: { color: '#B4BFCC', weight: 0.8, fill: false }, interactive: false }).addTo(map),
      )
      .catch(() => {});
    map.fitBounds([[6.5, 68], [36.5, 97.5]]);
    reachRef.current = L.layerGroup().addTo(map);
    gaugeRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    setTimeout(() => map.invalidateSize(), 100);
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // reaches
  useEffect(() => {
    const group = reachRef.current;
    if (!group || !data) return;
    group.clearLayers();
    const bounds = [];
    for (const f of data.reaches.features) {
      const st = RIVER_STATUS[f.properties.status];
      const dim = selected && f.properties.river !== selected;
      const animate = f.properties.direction === 'downstream' && f.properties.status !== 'UNMONITORED' && !dim;
      const layer = L.geoJSON(f, {
        style: {
          color: st.colour,
          weight: dim ? 1.5 : st.weight,
          opacity: dim ? 0.25 : 0.95,
          dashArray: f.properties.status === 'UNMONITORED' ? '4 6' : null,
          lineCap: 'round',
          className: animate ? `jd-flow jd-flow-${f.properties.status.toLowerCase()}` : '',
        },
      });
      layer.bindTooltip(
        `<strong>${lang === 'hi' ? f.properties.river_hi : f.properties.river}</strong><br/><span style="color:${st.colour};font-weight:700">${lang === 'hi' ? st.hi : st.en}</span>`,
        { sticky: true },
      );
      layer.on('click', () => go(`/rivers/${encodeURIComponent(f.properties.river)}`));
      layer.addTo(group);
      if (selected && f.properties.river === selected) bounds.push(layer.getBounds());
    }
    if (bounds.length && mapRef.current) {
      const b = bounds.reduce((acc, x) => acc.extend(x), L.latLngBounds(bounds[0].getSouthWest(), bounds[0].getNorthEast()));
      mapRef.current.flyToBounds(b, { padding: [30, 30], duration: 0.7 });
    } else if (!selected && data.scope && data.scope !== 'central' && mapRef.current) {
      // A state or district user opens on their own area, not all of India.
      const pts = gauges.filter((g) => g.lat != null).map((g) => [g.lat, g.lon]);
      if (pts.length) mapRef.current.fitBounds(L.latLngBounds(pts).pad(0.3), { maxZoom: 9 });
    }
  }, [data, selected, lang, gauges]);

  // gauges
  useEffect(() => {
    const group = gaugeRef.current;
    if (!group) return;
    group.clearLayers();
    for (const g of gauges) {
      const alerting = g.status !== 'NORMAL';
      if (!alerting && !showNormalGauges) continue;
      const st = RIVER_STATUS[g.status] ?? RIVER_STATUS.NORMAL;
      // Small, and hollow below danger, so the coloured reach underneath stays
      // readable where gauges cluster (the Ganga plain has dozens).
      const danger = g.status === 'DANGER';
      const m = L.circleMarker([g.lat, g.lon], {
        radius: danger ? 4.5 : alerting ? 3.5 : 2.5,
        color: danger ? '#ffffff' : st.colour,
        weight: danger ? 1 : 1.8,
        fillColor: danger ? st.colour : '#ffffff',
        fillOpacity: 1,
      });
      m.bindTooltip(
        `<strong>${g.name}</strong> · ${g.state ?? ''}<br/>${g.level_m ?? '—'} m · danger ${g.danger_level ?? '—'} m${g.above_danger_m != null ? ` (${g.above_danger_m > 0 ? '+' : ''}${g.above_danger_m})` : ''}`,
        { direction: 'top' },
      );
      m.on('click', () => onOpenStation(g.code));
      m.addTo(group);
    }
  }, [gauges, showNormalGauges, onOpenStation]);

  const current = useMemo(() => data?.rivers.find((r) => r.name === selected), [data, selected]);
  const mainPart = useMemo(() => {
    if (!current) return [];
    const counts = {};
    current.profile.forEach((p) => (counts[p.part] = (counts[p.part] || 0) + 1));
    const part = Number(Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? 0);
    return current.profile.filter((p) => p.part === part && p.vs_danger_m != null);
  }, [current]);

  const totals = useMemo(() => {
    if (!data) return null;
    return {
      danger: data.rivers.filter((r) => r.status === 'DANGER').length,
      warning: data.rivers.filter((r) => r.status === 'WARNING').length,
      gauges: data.gauges_on_rivers,
      rivers: data.rivers.length,
    };
  }, [data]);

  return (
    <div id="main-content" className="mx-auto w-full max-w-[1700px] space-y-4 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b-2 border-saffron-500 pb-3">
        <div>
          <h1 className={`text-2xl font-extrabold tracking-tight text-chakra-500 ${hi(lang)}`}>
            {data?.scope && data.scope !== 'central'
              ? lang === 'hi' ? 'आपके क्षेत्र की नदियाँ — जल स्तर स्थिति' : 'Rivers in your area — live water-level status'
              : lang === 'hi' ? 'भारत की नदियाँ — जल स्तर स्थिति' : 'India Rivers — live water-level status'}
          </h1>
          <p className={`text-[12px] text-ink-400 ${hi(lang)}`}>
            {lang === 'hi'
              ? 'प्रत्येक नदी खंड का रंग उस पर लगे केंद्रीय जल आयोग गेज के वास्तविक स्तर से; बहती रेखाएँ प्रवाह की दिशा दिखाती हैं'
              : 'Each reach is coloured by the real readings of the Central Water Commission gauges on it; moving dashes show the downstream direction of flow'}
          </p>
        </div>
        <GovBadge>CWC · Natural Earth</GovBadge>
      </div>

      {error && <p className="text-risk-red">{error}</p>}

      {totals && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            [lang === 'hi' ? 'खतरे पर नदियाँ' : 'Rivers with a reach above danger', totals.danger, '#C1121F'],
            [lang === 'hi' ? 'चेतावनी पर नदियाँ' : 'Rivers above warning', totals.warning, '#E4701E'],
            [lang === 'hi' ? 'नदियों पर गेज' : 'Gauges placed on rivers', totals.gauges, '#0B2A5B'],
            [lang === 'hi' ? 'दर्शाई गई नदियाँ' : 'Rivers mapped', totals.rivers, '#0B2A5B'],
          ].map(([k, v, c]) => (
            <div key={k} className="panel px-4 py-3">
              <div className={`text-[10px] font-bold uppercase tracking-wider text-ink-500 ${hi(lang)}`}>{k}</div>
              <div className="font-mono text-3xl font-extrabold" style={{ color: c }}>{v}</div>
            </div>
          ))}
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[300px_1fr]">
        <section className="panel flex max-h-[640px] flex-col" data-tour="rv-list">
          <SectionHead title={lang === 'hi' ? 'नदियाँ' : 'Rivers'} lang={lang} right={selected && <button type="button" className="text-[11px] font-bold text-saffron-300" onClick={() => go('/rivers')}>{lang === 'hi' ? 'सभी' : 'All'}</button>} />
          {!data ? (
            <Spinner lang={lang} />
          ) : (
            <ul className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">
              {data.rivers.map((r) => {
                const st = RIVER_STATUS[r.status];
                return (
                  <li key={r.name}>
                    <button
                      type="button"
                      onClick={() => go(`/rivers/${encodeURIComponent(r.name)}`)}
                      className={`flex w-full items-center gap-3 border-b border-ink-800 px-4 py-2.5 text-left hover:bg-saffron-50 ${selected === r.name ? 'bg-saffron-50' : ''}`}
                    >
                      <span className="h-8 w-1.5 shrink-0 rounded-full" style={{ background: st.colour }} />
                      <span className="min-w-0 flex-1">
                        <span className={`block truncate text-[13px] font-bold text-chakra-500 ${hi(lang)}`}>{lang === 'hi' ? r.name_hi : r.name}</span>
                        <span className={`block text-[10.5px] ${hi(lang)}`} style={{ color: st.colour }}>{lang === 'hi' ? st.hi : st.en}</span>
                      </span>
                      <span className="shrink-0 text-right font-mono text-[10.5px]">
                        {r.counts.DANGER > 0 && <span className="block font-bold text-risk-red">{r.counts.DANGER} D</span>}
                        {r.counts.WARNING > 0 && <span className="block font-bold text-risk-orange">{r.counts.WARNING} W</span>}
                        <span className="block text-ink-500">{r.gauges} {lang === 'hi' ? 'गेज' : 'gauges'}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <div className="space-y-4">
          <section className="panel relative isolate h-[640px] overflow-hidden" data-tour="rv-map">
            <div ref={hostRef} className="jd-map h-full w-full" />
            <div className="absolute bottom-3 left-3 z-[500] rounded-lg border border-ink-700 bg-white px-3 py-2 shadow-panel">
              <div className={`mb-1.5 text-[10px] font-bold uppercase tracking-wider text-ink-500 ${hi(lang)}`}>{lang === 'hi' ? 'नदी खंड' : 'River reach'}</div>
              {Object.entries(RIVER_STATUS).map(([k, st]) => (
                <div key={k} className={`flex items-center gap-2 text-[11px] text-ink-200 ${hi(lang)}`}>
                  <svg width="30" height="8" aria-hidden="true">
                    <line x1="0" y1="4" x2="30" y2="4" stroke={st.colour} strokeWidth={st.weight} strokeDasharray={k === 'UNMONITORED' ? '4 4' : undefined} strokeLinecap="round" />
                  </svg>
                  {lang === 'hi' ? st.hi : st.en}
                </div>
              ))}
              <label className={`mt-1.5 flex items-center gap-1.5 border-t border-ink-800 pt-1.5 text-[11px] text-ink-300 ${hi(lang)}`}>
                <input type="checkbox" checked={showNormalGauges} onChange={(e) => setShowNormalGauges(e.target.checked)} className="accent-saffron-500" />
                {lang === 'hi' ? 'सामान्य गेज भी दिखाएँ' : 'Also show normal gauges'}
              </label>
            </div>
          </section>

          <section className="panel" data-tour="rv-profile">
            <SectionHead
              title={current ? `${lang === 'hi' ? current.name_hi : current.name} — ${lang === 'hi' ? 'ऊपर से नीचे तक खतरा प्रोफ़ाइल' : 'upstream → downstream danger profile'}` : lang === 'hi' ? 'नदी प्रोफ़ाइल' : 'River profile'}
              lang={lang}
            />
            {!current ? (
              <p className={`p-6 text-center text-[12.5px] text-ink-500 ${hi(lang)}`}>
                {lang === 'hi' ? 'प्रोफ़ाइल देखने के लिए सूची या नक्शे पर कोई नदी चुनें।' : 'Pick a river in the list or on the map to see where along it the water is above its danger marks.'}
              </p>
            ) : mainPart.length === 0 ? (
              <p className="p-6 text-center text-[12.5px] text-ink-500">{lang === 'hi' ? 'इस नदी पर हाल के स्तर वाले गेज नहीं।' : 'No gauges with recent readings on this river.'}</p>
            ) : (
              <div className="p-3">
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={mainPart} margin={{ top: 10, right: 16, bottom: 30, left: 0 }}>
                      <CartesianGrid stroke="#E5EAF0" vertical={false} />
                      <XAxis dataKey="name" tick={{ fontSize: 9.5, fill: '#526071' }} angle={-40} textAnchor="end" interval={0} height={60} />
                      <YAxis tick={{ fontSize: 10, fill: '#6E7C8D' }} width={46} tickFormatter={(v) => `${v > 0 ? '+' : ''}${v}`} label={{ value: lang === 'hi' ? 'खतरे के निशान से (मी)' : 'vs danger mark (m)', angle: -90, position: 'insideLeft', fontSize: 10, fill: '#6E7C8D' }} />
                      <ReferenceLine y={0} stroke="#C1121F" strokeWidth={2} label={{ value: lang === 'hi' ? 'खतरे का निशान' : 'danger mark', position: 'insideTopRight', fontSize: 10, fill: '#C1121F' }} />
                      <Tooltip
                        formatter={(v) => [`${v > 0 ? '+' : ''}${v} m`, lang === 'hi' ? 'खतरे से' : 'vs danger']}
                        labelFormatter={(name) => {
                          const p = mainPart.find((x) => x.name === name);
                          return p ? `${p.name} · ${stateName(p.state, lang)} · km ${p.chainage_km} · ${p.level_m} m` : name;
                        }}
                      />
                      <Bar dataKey="vs_danger_m" onClick={(d) => onOpenStation(d.code)} cursor="pointer">
                        {mainPart.map((p) => (
                          <Cell key={p.code} fill={RIVER_STATUS[p.status]?.colour ?? '#0B8A3D'} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <p className={`text-[11px] text-ink-500 ${hi(lang)}`}>
                  {lang === 'hi'
                    ? 'बाएँ से दाएँ = ऊपरी से निचली धारा। शून्य रेखा से ऊपर के बार = खतरे के निशान से ऊपर का जल। किसी बार पर क्लिक कर गेज का ग्राफ़ व एआई पूर्वानुमान देखें।'
                    : 'Left to right = upstream to downstream. Bars above the zero line = water above that gauge’s danger mark. Click a bar for its hydrograph and AI forecast.'}
                </p>
              </div>
            )}
          </section>
          {data && <TownsInPath lang={lang} rows={data.towns_in_path ?? []} onOpenStation={onOpenStation} />}
          {data && <p className="text-[10.5px] text-ink-500">{data.method}</p>}
        </div>
      </div>
    </div>
  );
}
