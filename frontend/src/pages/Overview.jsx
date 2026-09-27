import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { canonicalState, stateName, tierColour } from '../lib/format';
import { pick, t } from '../lib/i18n';
import { go, href } from '../lib/router';
import { TierLegend } from '../components/Chrome';
import IndiaMap from '../components/IndiaMap';
import NationalPanel, { StatePanel } from '../components/NationalPanel';
import { STATUS_STYLE } from '../components/Official';
import { ConfidenceChip, DirectionBadge, Spinner, TierChip } from '../components/Primitives';

/**
 * Overview: the national picture, and nothing more.
 *
 * The earlier single-screen dashboard stacked towns, ~1,000 gauges, official alerts
 * and a full assessment on one map and one rail, and it read as noise. Here the map
 * shows the model's towns by default; gauges and alerts are opt-in layers with their
 * own dedicated pages (Rivers, Alerts), and the right rail is a short summary that
 * links to the full assessment and street-level hotspot pages.
 */

const hi = (lang) => (lang === 'hi' ? 'font-devanagari' : '');

function LocationSummary({ lang, id, replayDate, onOpenStation }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!id) return undefined;
    let alive = true;
    setData(null);
    setError(null);
    api
      .detail(id, replayDate)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [id, replayDate]);

  if (!id) {
    return (
      <div className={`panel grid h-full place-items-center p-6 text-center text-[12px] text-ink-500 ${hi(lang)}`}>
        {t(lang, 'selectPrompt')}
      </div>
    );
  }
  if (error) return <div className="panel p-4 text-[12px] text-risk-red">{error}</div>;
  if (!data) return <div className="panel"><Spinner lang={lang} /></div>;

  const a = data.assessment;
  const loc = a.location;
  const risk = a.risk;
  const colour = tierColour(risk.tier.key);
  const g = a.official?.gauge;

  return (
    <div className="flex flex-col gap-3 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:pr-0.5 scrollbar-thin">
      <section className="panel overflow-hidden">
        <div className="h-1.5" style={{ background: colour }} />
        <div className="p-4">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <h2 className={`truncate text-xl font-extrabold text-chakra-500 ${hi(lang)}`}>
                {lang === 'hi' && loc.name_hi ? loc.name_hi : loc.name}
              </h2>
              <p className={`text-[11.5px] text-ink-500 ${hi(lang)}`}>
                {stateName(loc.state, lang)} · {loc.river ?? '—'}
              </p>
            </div>
            <div className="text-right">
              <div className="font-mono text-4xl font-extrabold leading-none" style={{ color: colour }}>
                {risk.score.toFixed(0)}
              </div>
              <div className="text-[10px] text-ink-500">/ 100</div>
            </div>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <TierChip tier={risk.tier.key} lang={lang} showAction />
            <ConfidenceChip level={a.confidence.level} label={pick(lang, a.confidence, 'label')} lang={lang} />
            <DirectionBadge direction={risk.direction} lang={lang} />
          </div>

          {risk.official_floor_applied && (
            <p className={`mt-2 rounded bg-risk-red/10 px-2 py-1 text-[11px] font-semibold text-risk-red ${hi(lang)}`}>
              {lang === 'hi'
                ? `आधिकारिक आँकड़ों ने मॉडल के ${risk.model_score.toFixed(0)} से बढ़ाया`
                : `Raised by official data from the model's ${risk.model_score.toFixed(0)}`}
            </p>
          )}

          <ul className="mt-3 space-y-1.5">
            {(lang === 'hi' ? a.explanation.bullets_hi : a.explanation.bullets_en).slice(0, 3).map((b, i) => (
              <li key={i} className={`flex gap-2 text-[12px] leading-snug text-ink-200 ${hi(lang)}`}>
                <span className="mt-[6px] h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: colour }} />
                {b}
              </li>
            ))}
          </ul>

          <p className={`mt-3 rounded-lg border-l-4 bg-ink-850 px-3 py-2 text-[11.5px] font-medium ${hi(lang)}`} style={{ borderColor: colour }}>
            {pick(lang, a.actions, 'ndma_action')}
          </p>
        </div>
      </section>

      {g && (
        <button
          type="button"
          onClick={() => onOpenStation(g.code)}
          className="panel flex items-center gap-3 p-3 text-left transition hover:border-chakra-500"
        >
          <span className="h-3 w-3 shrink-0 rounded-full" style={{ background: STATUS_STYLE[g.status].colour }} />
          <span className="min-w-0 flex-1">
            <span className={`block text-[10px] font-bold uppercase tracking-wider text-ink-500 ${hi(lang)}`}>
              {lang === 'hi' ? 'निकटतम CWC नदी गेज' : 'Nearest CWC river gauge'}
            </span>
            <span className="block truncate text-[13px] font-bold text-chakra-500">{g.name}</span>
            <span className="block font-mono text-[11px] text-ink-400">
              {g.level_m != null ? `${g.level_m} m · ` : ''}
              {lang === 'hi' ? 'खतरा' : 'danger'} {g.danger_level} m
              {g.above_danger_m != null ? ` · ${g.above_danger_m > 0 ? '+' : ''}${g.above_danger_m} m` : ''}
            </span>
          </span>
          <span className="text-[11px] font-bold text-saffron-300">{lang === 'hi' ? 'ग्राफ़ →' : 'Graph →'}</span>
        </button>
      )}

      <div className="grid gap-2">
        <a href={href(`/location/${loc.id}`)} className="btn btn-primary justify-between px-4 py-3 text-[13px]">
          <span className={hi(lang)}>{lang === 'hi' ? 'पूरा आकलन देखें' : 'Full risk assessment'}</span>
          <span aria-hidden="true">→</span>
        </a>
        {!replayDate && (
          <a href={href(`/hotspots/${loc.id}`)} className="btn justify-between px-4 py-3 text-[13px]">
            <span className={hi(lang)}>{lang === 'hi' ? 'गली-स्तर जलभराव हॉटस्पॉट' : 'Street-level waterlogging hotspots'}</span>
            <span aria-hidden="true">→</span>
          </a>
        )}
        <a href={href('/rivers')} className="btn justify-between px-4 py-3 text-[13px]">
          <span className={hi(lang)}>{lang === 'hi' ? 'भारत की नदियों की स्थिति' : 'India rivers status'}</span>
          <span aria-hidden="true">→</span>
        </a>
      </div>
    </div>
  );
}

export default function Overview({
  lang,
  country,
  locations,
  selectedState,
  replayDate,
  gauges,
  alerts,
  onOpenStation,
}) {
  const [selectedId, setSelectedId] = useState(null);
  const [stateData, setStateData] = useState(null);
  const [basemap, setBasemap] = useState('light');
  // Towns only by default: gauges and alerts have their own pages and made this map unreadable.
  const [layers, setLayers] = useState({ towns: true, gauges: false, alerts: false });
  const [showDistricts, setShowDistricts] = useState(true);

  useEffect(() => {
    if (!selectedId && locations.length) setSelectedId(locations[0].id);
  }, [locations, selectedId]);

  useEffect(() => {
    if (!selectedState) {
      setStateData(null);
      return undefined;
    }
    let alive = true;
    api
      .state(selectedState, replayDate)
      .then((d) => {
        if (!alive) return;
        setStateData(d);
        if (d.locations?.[0]) setSelectedId(d.locations[0].location.id);
      })
      .catch(() => alive && setStateData(null));
    return () => {
      alive = false;
    };
  }, [selectedState, replayDate, country?.meta?.run_id]);

  useEffect(() => {
    const id = setTimeout(() => window.dispatchEvent(new Event('resize')), 80);
    return () => clearTimeout(id);
  }, []);

  const selectLocation = (id) => {
    setSelectedId(id);
    const loc = locations.find((l) => l.id === id);
    if (loc && canonicalState(loc.state) !== selectedState) go(`/state/${canonicalState(loc.state)}`);
  };

  const crumbs = useMemo(() => {
    const out = [{ label: t(lang, 'india'), to: selectedState ? '/map' : null }];
    if (selectedState) out.push({ label: stateName(selectedState, lang), to: null });
    return out;
  }, [lang, selectedState]);

  return (
    <main
      id="main-content"
      className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3 scrollbar-thin lg:grid lg:grid-cols-[minmax(270px,20rem)_1fr_minmax(300px,23rem)] lg:overflow-hidden"
    >
      <aside className="shrink-0 lg:min-h-0 lg:overflow-hidden" data-tour="ov-left">
        {selectedState && stateData ? (
          <StatePanel lang={lang} state={stateData} onBack={() => go('/map')} onSelectLocation={setSelectedId} selectedLocationId={selectedId} />
        ) : (
          <NationalPanel
            lang={lang}
            country={country}
            locations={locations}
            onSelectState={(name) => go(`/state/${canonicalState(name)}`)}
            onSelectLocation={selectLocation}
            selectedLocationId={selectedId}
          />
        )}
      </aside>

      <section className="panel relative isolate h-[62vh] min-h-[360px] overflow-hidden lg:h-auto lg:min-h-0" data-tour="ov-map">
        <IndiaMap
          lang={lang}
          states={country?.states ?? []}
          locations={locations}
          selectedState={selectedState}
          selectedLocationId={selectedId}
          onSelectState={(name) => go(`/state/${canonicalState(name)}`)}
          onSelectLocation={selectLocation}
          onSelectGauge={onOpenStation}
          basemap={basemap}
          showDistricts={showDistricts}
          gauges={replayDate ? [] : gauges}
          alerts={replayDate ? [] : alerts}
          layers={layers}
        />

        <div className="absolute left-3 top-3 z-[500] flex items-center gap-1.5 rounded-lg border border-ink-700 bg-white px-2.5 py-1.5 shadow-panel">
          {crumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1.5">
              {i > 0 && <span className="text-ink-600">/</span>}
              {c.to ? (
                <a href={href(c.to)} className={`text-[11.5px] font-semibold text-saffron-300 hover:underline ${hi(lang)}`}>{c.label}</a>
              ) : (
                <span className={`text-[11.5px] font-semibold text-ink-100 ${hi(lang)}`}>{c.label}</span>
              )}
            </span>
          ))}
          {!selectedState && <span className={`ml-1 hidden text-[10.5px] text-ink-500 sm:inline ${hi(lang)}`}>— {t(lang, 'clickState')}</span>}
        </div>

        <div className="absolute right-3 top-3 z-[500] flex flex-col items-end gap-1.5" data-tour="ov-layers">
          <div className="flex items-center rounded-lg border border-ink-700 bg-white p-0.5 shadow-panel">
            {[
              ['light', lang === 'hi' ? 'सरल' : 'Light'],
              ['streets', lang === 'hi' ? 'सड़कें' : 'Streets'],
              ['satellite', t(lang, 'basemapSatellite')],
            ].map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setBasemap(key)}
                className={`rounded-md px-2 py-1 text-[10.5px] font-semibold ${basemap === key ? 'bg-saffron-500 text-white' : 'text-ink-400 hover:text-ink-100'} ${hi(lang)}`}
              >
                {label}
              </button>
            ))}
          </div>
          {!replayDate && (
            <div className="rounded-lg border border-ink-700 bg-white p-2 shadow-panel">
              <div className={`mb-1 text-[9.5px] font-bold uppercase tracking-wider text-ink-500 ${hi(lang)}`}>
                {lang === 'hi' ? 'परतें' : 'Layers'}
              </div>
              {[
                ['towns', lang === 'hi' ? 'शहर जोखिम स्कोर' : 'Town risk scores', <span key="d" className="h-2.5 w-2.5 rounded-full bg-risk-orange ring-2 ring-white" />],
                ['gauges', lang === 'hi' ? 'CWC गेज (चेतावनी/खतरा)' : 'CWC gauges above warning', <span key="g" className="h-2.5 w-2.5 rounded-full border-2 border-white bg-risk-red shadow" />],
                ['alerts', lang === 'hi' ? 'आधिकारिक चेतावनियाँ' : 'Official alerts', <span key="a" className="h-2 w-2 rotate-45 bg-risk-orange" />],
              ].map(([key, label, icon]) => (
                <label key={key} className={`flex cursor-pointer items-center gap-2 py-0.5 text-[11px] text-ink-200 ${hi(lang)}`}>
                  <input type="checkbox" checked={layers[key]} onChange={() => setLayers((l) => ({ ...l, [key]: !l[key] }))} className="accent-saffron-500" />
                  {icon}
                  {label}
                </label>
              ))}
            </div>
          )}
          {selectedState && (
            <button
              type="button"
              onClick={() => setShowDistricts((v) => !v)}
              className={`rounded-lg border border-ink-700 bg-white px-2 py-1 text-[10.5px] font-semibold shadow-panel ${showDistricts ? 'text-saffron-300' : 'text-ink-400'} ${hi(lang)}`}
            >
              {t(lang, 'showDistricts')}
            </button>
          )}
        </div>

        <div className="absolute bottom-3 left-3 z-[500] rounded-lg border border-ink-700 bg-white px-3 py-2 shadow-panel" data-tour="ov-legend">
          <div className={`kicker mb-1.5 ${hi(lang)}`}>{t(lang, 'mapLegend')}</div>
          <TierLegend lang={lang} counts={country?.counts} />
          <p className={`mt-1.5 border-t border-ink-800 pt-1.5 text-[10px] text-ink-500 ${hi(lang)}`}>
            {lang === 'hi' ? 'राज्य का रंग = उसके सबसे अधिक जोखिम वाले शहर का स्तर' : 'State colour = level of its highest-risk town'}
          </p>
        </div>
      </section>

      <aside className="shrink-0 lg:min-h-0 lg:overflow-hidden" data-tour="ov-right">
        <LocationSummary lang={lang} id={selectedId} replayDate={replayDate} onOpenStation={onOpenStation} />
      </aside>
    </main>
  );
}
