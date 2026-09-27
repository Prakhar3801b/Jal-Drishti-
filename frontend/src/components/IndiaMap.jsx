import { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import { loadGeo } from '../lib/api';
import { canonicalState, compactPopulation, tierColour, TIER_LABELS } from '../lib/format';
import { t } from '../lib/i18n';

/**
 * The India map: a state choropleth that drills down to districts and monitored
 * locations.
 *
 * Leaflet is driven imperatively from effects rather than through react-leaflet.
 * That is a deliberate choice — the layers here need fine control (per-feature
 * restyling on every refresh without rebuilding the layer, fitBounds on
 * drill-down, custom divIcon markers that pulse only at Red) and wrapping all of
 * that in a component tree costs more than it saves.
 *
 * Layer order, bottom to top:
 *   basemap tiles -> state fills -> district outlines -> state outlines -> markers
 */

const INDIA_CENTER = [22.4, 80.0];
const INDIA_BOUNDS = L.latLngBounds([5.5, 67.0], [37.6, 97.8]);

// All keyless. (CARTO's basemaps now serve an "API KEY REQUIRED" watermark tile
// with a 200 status, which is why they are not used.)
const BASEMAPS = {
  light: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Basemap &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors',
    maxZoom: 16,
    opacity: 1,
  },
  streets: {
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 18,
    opacity: 0.9,
  },
  satellite: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics',
    maxZoom: 17,
    opacity: 0.82,
  },
};

/** Marker radius grows with population, because a Red alert over 1.2 crore people
 *  is not the same event as a Red alert over 30,000. */
function markerRadius(population, tier) {
  // Compact: 4-8 px. At national zoom 112 towns plus ~100 alerting gauges share
  // the map, so size carries population only faintly and severity adds a little.
  const base = population ? 3.2 + 1.1 * Math.log10(Math.max(population, 1000) / 1000) : 4;
  const bump = tier === 'red' ? 1.5 : tier === 'orange' ? 0.8 : 0;
  return Math.max(4, Math.min(8, base + bump));
}

function markerIcon(loc, { selected }) {
  const size = markerRadius(loc.population, loc.tier) * 2;
  const colour = tierColour(loc.tier);
  const box = 28;
  const pulse = loc.tier === 'red';
  const html = `
    <div class="jd-marker ${selected ? 'jd-marker-selected' : ''}"
         style="width:${box}px;height:${box}px;color:${colour}">
      ${pulse ? '<span class="jd-marker-ring"></span>' : ''}
      <span class="jd-marker-dot"
            style="width:${size}px;height:${size}px;background:${colour}"></span>
    </div>`;
  return L.divIcon({
    html,
    className: '',
    iconSize: [box, box],
    iconAnchor: [box / 2, box / 2],
  });
}

function tooltipHtml(loc, lang) {
  const tier = TIER_LABELS[loc.tier] ?? TIER_LABELS.green;
  const name = lang === 'hi' && loc.name_hi ? loc.name_hi : loc.name;
  const factor = lang === 'hi' ? loc.top_factor_hi : loc.top_factor;
  return `
    <div style="min-width:172px">
      <div style="display:flex;align-items:baseline;justify-content:space-between;gap:10px">
        <strong style="font-size:12px">${name}</strong>
        <span style="font-family:ui-monospace,monospace;font-weight:700;color:${tierColour(loc.tier)}">
          ${loc.score.toFixed(0)}
        </span>
      </div>
      <div style="color:#526071;font-size:10px;margin-top:1px">${loc.state}${
        loc.river ? ` · ${loc.river}` : ''
      }</div>
      <div style="margin-top:5px;display:flex;align-items:center;gap:5px">
        <span style="width:7px;height:7px;border-radius:99px;background:${tierColour(loc.tier)}"></span>
        <span style="font-size:10px;font-weight:600">${lang === 'hi' ? tier.hi : tier.en} · ${
          lang === 'hi' ? tier.action_hi : tier.action_en
        }</span>
      </div>
      ${
        factor
          ? `<div style="color:#6E7C8D;font-size:10px;margin-top:4px">${factor}</div>`
          : ''
      }
      <div style="color:#6E7C8D;font-size:10px;margin-top:3px">
        ${compactPopulation(loc.population)} · ${loc.confidence} confidence
      </div>
    </div>`;
}

export default function IndiaMap({
  lang,
  states = [],
  locations = [],
  selectedState,
  selectedLocationId,
  onSelectState,
  onSelectLocation,
  onSelectGauge,
  basemap = 'light',
  showDistricts = true,
  gauges = [],
  alerts = [],
  layers = { towns: true, gauges: true, alerts: true },
}) {
  const hostRef = useRef(null);
  const mapRef = useRef(null);
  const tileRef = useRef(null);
  const stateLayerRef = useRef(null);
  const districtLayerRef = useRef(null);
  const outlineLayerRef = useRef(null);
  const markerLayerRef = useRef(null);
  const markersRef = useRef(new Map());
  const gaugeLayerRef = useRef(null);
  const alertLayerRef = useRef(null);
  const canvasRef = useRef(null);

  const [geo, setGeo] = useState({ states: null, districts: null });
  const [geoError, setGeoError] = useState(null);

  const stateScores = useMemo(() => {
    const map = new Map();
    for (const s of states) map.set(canonicalState(s.state), s);
    return map;
  }, [states]);

  // Keep the newest props reachable from Leaflet event handlers without
  // re-binding every handler on each render.
  const handlers = useRef({ onSelectState, onSelectLocation, onSelectGauge, lang, stateScores });
  handlers.current = { onSelectState, onSelectLocation, onSelectGauge, lang, stateScores };

  /* ------------------------------------------------------------- map setup */

  useEffect(() => {
    if (mapRef.current || !hostRef.current) return;
    const map = L.map(hostRef.current, {
      center: INDIA_CENTER,
      zoom: 5,
      minZoom: 3.5,
      maxZoom: 13,
      zoomControl: true,
      attributionControl: true,
      preferCanvas: false,
      // Half-step zoom lets fitBounds settle closer to the extent of India than
      // whole steps, without the stale-tile seams quarter steps left behind
      // (old-zoom tiles lingering as a visible rectangle on the basemap).
      zoomSnap: 0.5,
      zoomDelta: 0.5,
      maxBounds: INDIA_BOUNDS.pad(0.35),
      maxBoundsViscosity: 0.7,
      worldCopyJump: false,
    });
    map.zoomControl.setPosition('bottomright');
    mapRef.current = map;

    outlineLayerRef.current = L.layerGroup().addTo(map);
    // Canvas renderer for the ~1,000 CWC gauges: SVG would create a DOM node each.
    canvasRef.current = L.canvas({ padding: 0.3 });
    alertLayerRef.current = L.layerGroup().addTo(map);
    gaugeLayerRef.current = L.layerGroup().addTo(map);
    markerLayerRef.current = L.layerGroup().addTo(map);

    map.fitBounds(INDIA_BOUNDS, { padding: [6, 6] });

    // Leaflet mis-measures its container when it is created inside a flex layout
    // that has not settled yet; one deferred invalidate fixes the grey gutters.
    const settle = setTimeout(() => map.invalidateSize(), 120);
    const onResize = () => map.invalidateSize();
    window.addEventListener('resize', onResize);

    return () => {
      clearTimeout(settle);
      window.removeEventListener('resize', onResize);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  /* ------------------------------------------------------------- geometry */

  useEffect(() => {
    let alive = true;
    Promise.all([loadGeo('india-states.geojson'), loadGeo('india-districts.geojson')])
      .then(([s, d]) => alive && setGeo({ states: s, districts: d }))
      .catch((err) => alive && setGeoError(err.message));
    return () => {
      alive = false;
    };
  }, []);

  /* -------------------------------------------------------------- basemap */

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (tileRef.current) {
      map.removeLayer(tileRef.current);
      tileRef.current = null;
    }
    const conf = BASEMAPS[basemap];
    if (!conf) return; // 'none' — boundaries only
    const layer = L.tileLayer(conf.url, {
      attribution: conf.attribution,
      maxZoom: conf.maxZoom,
      subdomains: 'abcd',
      opacity: conf.opacity ?? 0.8,
      crossOrigin: true,
    });
    layer.addTo(map);
    layer.bringToBack();
    tileRef.current = layer;
  }, [basemap]);

  /* --------------------------------------------------- state choropleth */

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !geo.states) return;

    const styleState = (feature) => {
      const name = feature.properties.st_nm;
      const row = handlers.current.stateScores.get(name);
      const isSelected = selectedState && name === canonicalState(selectedState);
      const dimmed = selectedState && !isSelected;
      if (!row) {
        // A state with no monitored location is drawn as absent data, never as
        // "green". Claiming safety where nothing is measured would be a lie.
        return {
          fillColor: '#E5EAF0',
          fillOpacity: dimmed ? 0.25 : 0.55,
          color: '#B4BFCC',
          weight: 0.8,
          dashArray: '2 3',
        };
      }
      return {
        fillColor: tierColour(row.tier),
        fillOpacity: dimmed ? 0.16 : isSelected ? 0.62 : 0.5,
        // White keylines between states, navy for the selected one - the
        // conventional choropleth treatment on a light basemap.
        color: isSelected ? '#0B2A5B' : '#FFFFFF',
        weight: isSelected ? 2.4 : 1.1,
        dashArray: null,
      };
    };

    if (stateLayerRef.current) {
      map.removeLayer(stateLayerRef.current);
      stateLayerRef.current = null;
    }

    const layer = L.geoJSON(geo.states, {
      style: styleState,
      onEachFeature: (feature, lyr) => {
        const name = feature.properties.st_nm;
        lyr.on({
          mouseover: () => {
            const row = handlers.current.stateScores.get(name);
            lyr.setStyle({ weight: 2.2, color: '#0B2A5B', fillOpacity: row ? 0.66 : 0.6 });
            lyr.bringToFront();
            const lg = handlers.current.lang;
            lyr
              .bindTooltip(
                row
                  ? `<div style="min-width:150px">
                       <div style="display:flex;justify-content:space-between;gap:10px">
                         <strong style="font-size:12px">${name}</strong>
                         <span style="font-family:ui-monospace,monospace;font-weight:700;color:${tierColour(
                           row.tier,
                         )}">${row.score.toFixed(0)}</span>
                       </div>
                       <div style="color:#526071;font-size:10px;margin-top:2px">
                         ${row.locations} ${t(lg, 'locationsWord')} ·
                         ${row.counts.red}R ${row.counts.orange}O ${row.counts.yellow}Y ${row.counts.green}G
                       </div>
                       <div style="color:#6E7C8D;font-size:10px;margin-top:3px">
                         ${t(lg, 'highestRisk')}: ${row.worst.name}
                       </div>
                     </div>`
                  : `<div><strong style="font-size:12px">${name}</strong>
                       <div style="color:#6E7C8D;font-size:10px;margin-top:2px">${t(
                         lg,
                         'noMonitored',
                       )}</div></div>`,
                { sticky: true, direction: 'top', opacity: 1 },
              )
              .openTooltip();
          },
          mouseout: () => {
            layer.resetStyle(lyr);
            lyr.closeTooltip();
          },
          click: () => {
            if (handlers.current.stateScores.get(name)) {
              handlers.current.onSelectState?.(name);
            }
          },
        });
      },
    });
    layer.addTo(map);
    layer.bringToBack();
    if (tileRef.current) tileRef.current.bringToBack();
    stateLayerRef.current = layer;

    return () => {
      if (stateLayerRef.current) {
        map.removeLayer(stateLayerRef.current);
        stateLayerRef.current = null;
      }
    };
  }, [geo.states, states, selectedState]);

  /* ----------------------------------------------- district outlines */

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !geo.districts) return;

    if (districtLayerRef.current) {
      map.removeLayer(districtLayerRef.current);
      districtLayerRef.current = null;
    }
    if (!showDistricts) return;

    // Only the drilled-into state's districts are drawn. All 760 at once is
    // noise at national zoom and costs a lot of SVG.
    const wanted = selectedState ? canonicalState(selectedState) : null;
    if (!wanted) return;

    const subset = {
      type: 'FeatureCollection',
      features: geo.districts.features.filter((f) => f.properties.st_nm === wanted),
    };

    const layer = L.geoJSON(subset, {
      style: {
        fillColor: '#FFFFFF',
        fillOpacity: 0.05,
        color: '#0B2A5B',
        weight: 0.6,
        opacity: 0.45,
        dashArray: '3 3',
      },
      onEachFeature: (feature, lyr) => {
        lyr.bindTooltip(
          `<span style="font-size:11px">${feature.properties.district}</span>`,
          { sticky: true, direction: 'top', opacity: 1 },
        );
        lyr.on({
          mouseover: () => lyr.setStyle({ fillOpacity: 0.25, color: '#0B2A5B', weight: 1.2, opacity: 0.9 }),
          mouseout: () => layer.resetStyle(lyr),
        });
      },
    });
    layer.addTo(map);
    districtLayerRef.current = layer;

    return () => {
      if (districtLayerRef.current) {
        map.removeLayer(districtLayerRef.current);
        districtLayerRef.current = null;
      }
    };
  }, [geo.districts, selectedState, showDistricts]);

  /* ------------------------------------------------- drill-down framing */

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !geo.states) return;

    if (!selectedState) {
      map.flyToBounds(INDIA_BOUNDS, { padding: [6, 6], duration: 0.7 });
      return;
    }
    const wanted = canonicalState(selectedState);
    const feature = geo.states.features.find((f) => f.properties.st_nm === wanted);
    if (!feature) return;
    const bounds = L.geoJSON(feature).getBounds();
    map.flyToBounds(bounds, { padding: [48, 48], duration: 0.8, maxZoom: 9 });
  }, [selectedState, geo.states]);

  /* ---------------------------------------------------------- markers */

  useEffect(() => {
    const group = markerLayerRef.current;
    if (!group) return;

    const visible = !layers.towns
      ? []
      : selectedState
        ? locations.filter((l) => canonicalState(l.state) === canonicalState(selectedState))
        : locations;

    const seen = new Set();
    for (const loc of visible) {
      seen.add(loc.id);
      const selected = loc.id === selectedLocationId;
      let marker = markersRef.current.get(loc.id);
      if (!marker) {
        marker = L.marker([loc.lat, loc.lon], {
          icon: markerIcon(loc, { selected }),
          riseOnHover: true,
          // Red alerts must sit above everything else in the stack.
          zIndexOffset: loc.tier === 'red' ? 600 : loc.tier === 'orange' ? 400 : 100,
          keyboard: true,
          title: loc.name,
        });
        marker.on('click', () => handlers.current.onSelectLocation?.(loc.id));
        marker.addTo(group);
        markersRef.current.set(loc.id, marker);
      } else {
        marker.setLatLng([loc.lat, loc.lon]);
        marker.setIcon(markerIcon(loc, { selected }));
        if (!group.hasLayer(marker)) marker.addTo(group);
      }
      marker.bindTooltip(tooltipHtml(loc, lang), {
        direction: 'top',
        offset: [0, -10],
        opacity: 1,
      });
    }

    // Drop markers that are no longer in view (e.g. after drilling into a state).
    for (const [id, marker] of markersRef.current) {
      if (!seen.has(id)) {
        group.removeLayer(marker);
        markersRef.current.delete(id);
      }
    }
  }, [locations, selectedState, selectedLocationId, lang, layers.towns]);

  /* ------------------------------------------------- CWC river gauges */

  useEffect(() => {
    const group = gaugeLayerRef.current;
    const map = mapRef.current;
    if (!group || !map) return;
    group.clearLayers();
    if (!layers.gauges) return;

    const lg = lang;
    for (const g of gauges) {
      const alerting = g.status === 'DANGER' || g.status === 'WARNING';
      // Normal gauges are drawn only when drilled into a state, and faintly: the
      // national view should show exceedances, not a grey carpet of 1,000 dots.
      if (!alerting && !selectedState) continue;
      if (selectedState && g.state && canonicalState(g.state) !== canonicalState(selectedState) && !alerting) continue;

      const colour = g.status === 'DANGER' ? '#C1121F' : g.status === 'WARNING' ? '#E4701E' : '#6E7C8D';
      const m = L.circleMarker([g.lat, g.lon], {
        renderer: canvasRef.current,
        radius: g.status === 'DANGER' ? 5 : g.status === 'WARNING' ? 4 : 2.5,
        color: '#FFFFFF',
        weight: alerting ? 1.5 : 0.8,
        fillColor: colour,
        fillOpacity: alerting ? 0.95 : 0.6,
      });
      const lvl = g.level_m != null ? `${g.level_m} m` : '—';
      m.bindTooltip(
        `<div style="min-width:180px">
           <div style="display:flex;justify-content:space-between;gap:8px">
             <strong style="font-size:12px">${g.name}</strong>
             <span style="font-size:10px;font-weight:700;color:${colour}">${g.status}</span>
           </div>
           <div style="color:#526071;font-size:10px">${lg === 'hi' ? 'केंद्रीय जल आयोग गेज' : 'CWC river gauge'} · ${g.state ?? ''}</div>
           <div style="margin-top:4px;font-size:10.5px;font-family:ui-monospace,monospace">
             ${lg === 'hi' ? 'स्तर' : 'Level'} ${lvl}${g.trend ? ` · ${g.trend.toLowerCase()}` : ''}<br/>
             ${lg === 'hi' ? 'चेतावनी' : 'Warning'} ${g.warning_level ?? '—'} m · ${lg === 'hi' ? 'खतरा' : 'Danger'} ${g.danger_level ?? '—'} m<br/>
             HFL ${g.hfl ?? '—'} m${g.hfl_date ? ` (${g.hfl_date.slice(0, 4)})` : ''}
           </div>
           ${g.above_danger_m > 0 ? `<div style="margin-top:3px;color:#C1121F;font-weight:700;font-size:10.5px">+${g.above_danger_m} m ${lg === 'hi' ? 'खतरे के निशान से ऊपर' : 'above danger'}</div>` : ''}
         </div>`,
        { direction: 'top', opacity: 1 },
      );
      m.on('click', () => handlers.current.onSelectGauge?.(g.code));
      m.addTo(group);
    }
  }, [gauges, layers.gauges, selectedState, lang]);

  /* --------------------------------------------- NDMA SACHET official alerts */

  useEffect(() => {
    const group = alertLayerRef.current;
    if (!group) return;
    group.clearLayers();
    if (!layers.alerts) return;

    for (const a of alerts) {
      if (!a.flood_related || a.lat == null) continue;
      const colour = a.colour === 'red' ? '#C1121F' : a.colour === 'orange' ? '#E4701E' : '#C99700';
      // A small diamond at the alert centroid; the covered area is only drawn
      // on hover, so alerts never smother the town markers.
      const icon = L.divIcon({
        className: '',
        html: `<div style="width:8px;height:8px;transform:rotate(45deg);background:${colour};border:1.5px solid #fff;box-shadow:0 1px 3px rgba(15,26,42,.45)"></div>`,
        iconSize: [8, 8],
        iconAnchor: [4, 4],
      });
      const marker = L.marker([a.lat, a.lon], { icon, zIndexOffset: 200 });
      const area = L.circle([a.lat, a.lon], {
        radius: Math.min(a.radius_km, 150) * 1000,
        color: colour,
        weight: 1,
        dashArray: '4 4',
        fillColor: colour,
        fillOpacity: 0.08,
        interactive: false,
      });
      marker.bindTooltip(
        `<div style="max-width:260px;white-space:normal">
           <div style="display:flex;gap:6px;align-items:center">
             <span style="width:8px;height:8px;background:${colour};transform:rotate(45deg);display:inline-block"></span>
             <strong style="font-size:11.5px">${a.type}</strong>
           </div>
           <div style="color:#526071;font-size:10px;margin-top:2px">${a.source} · ${a.colour.toUpperCase()}</div>
           <div style="font-size:10.5px;margin-top:3px">${a.area.slice(0, 120)}</div>
           <div style="color:#526071;font-size:10px;margin-top:3px">${a.message.slice(0, 180)}</div>
         </div>`,
        { direction: 'top', opacity: 1 },
      );
      marker.on('mouseover', () => area.addTo(group));
      marker.on('mouseout', () => group.removeLayer(area));
      marker.addTo(group);
    }
  }, [alerts, layers.alerts]);

  /* ------------------------------------------------ pan to selection */

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedLocationId) return;
    const loc = locations.find((l) => l.id === selectedLocationId);
    if (!loc) return;
    if (!map.getBounds().pad(-0.18).contains([loc.lat, loc.lon])) {
      map.panTo([loc.lat, loc.lon], { animate: true, duration: 0.5 });
    }
  }, [selectedLocationId, locations]);

  return (
    <div className="jd-map relative h-full w-full overflow-hidden">
      <div ref={hostRef} className="h-full w-full" />

      {geoError && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <div className="panel max-w-sm px-4 py-3 text-center text-xs text-risk-orange">
            {geoError}
          </div>
        </div>
      )}

      {!geo.states && !geoError && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <div className="flex items-center gap-2 rounded-full border border-ink-700 bg-ink-900 px-3.5 py-1.5 text-[11px] text-ink-300 shadow-panel">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-saffron-500" />
            Loading India boundaries…
          </div>
        </div>
      )}
    </div>
  );
}
