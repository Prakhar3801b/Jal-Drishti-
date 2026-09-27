import { useMemo, useState } from 'react';
import {
  compactPopulation,
  inNumber,
  mm,
  ordinal,
  stateName,
  tierColour,
  TIER_LABELS,
  TIER_ORDER,
} from '../lib/format';
import { pickPlain, t } from '../lib/i18n';
import { NationalInsights } from './Copilot';
import { DirectionBadge, SectionHead, StatTile, TierChip } from './Primitives';

/**
 * The left rail in country view: national counts, the ranked watchlist, and
 * roll-ups by state and by river basin.
 *
 * The tier tiles double as filters. That is the cheapest possible interaction
 * that answers the question an operations room actually asks first — "show me
 * only the Red ones" — without adding a filter UI.
 */

export default function NationalPanel({
  lang,
  country,
  locations = [],
  onSelectState,
  onSelectLocation,
  selectedLocationId,
}) {
  const [tierFilter, setTierFilter] = useState(null);
  const [grouping, setGrouping] = useState('state');

  const counts = country?.counts ?? { red: 0, orange: 0, yellow: 0, green: 0 };

  const watchlist = useMemo(() => {
    const rows = tierFilter ? locations.filter((l) => l.tier === tierFilter) : locations;
    return rows.slice(0, tierFilter ? 60 : 14);
  }, [locations, tierFilter]);

  return (
    // One scrolling column: three panels competing for a fixed height used to
    // crush the watchlist header when a tier filter was on.
    <div className="flex flex-col gap-3 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:pr-1 scrollbar-thin">
      {/* ------------------------------------------------ national situation */}
      <section data-tour="ov-national" className="panel shrink-0">
        <SectionHead
          title={t(lang, 'nationalSituation')}
          lang={lang}
          right={
            country && (
              <span className="font-mono text-[10px] text-ink-500">
                {country.total_locations} {t(lang, 'monitored').toLowerCase()}
              </span>
            )
          }
        />
        <div className="p-3">
          <p
            className={`mb-3 text-[12px] leading-relaxed text-ink-200 text-balance ${
              lang === 'hi' ? 'font-devanagari' : ''
            }`}
          >
            {pickPlain(lang, country?.summary)}
          </p>

          <div className="grid grid-cols-4 gap-1.5">
            {TIER_ORDER.map((tier) => (
              <StatTile
                key={tier}
                tone={tier}
                label={lang === 'hi' ? TIER_LABELS[tier].hi : TIER_LABELS[tier].en}
                value={counts[tier] ?? 0}
                onClick={() => setTierFilter((cur) => (cur === tier ? null : tier))}
                active={tierFilter === tier}
              />
            ))}
          </div>

          {country?.population_at_risk > 0 && (
            <div className="mt-2.5 flex items-center justify-between rounded-lg border border-risk-orange/35 bg-risk-orange/[0.07] px-2.5 py-2">
              <span
                className={`text-[10.5px] leading-tight text-ink-300 ${
                  lang === 'hi' ? 'font-devanagari' : ''
                }`}
              >
                {t(lang, 'peopleExposed')}
              </span>
              <span className="font-mono text-base font-bold text-risk-orange">
                {compactPopulation(country.population_at_risk)}
              </span>
            </div>
          )}

          {tierFilter && (
            <button
              type="button"
              className="btn btn-ghost mt-2 w-full py-1 text-[10.5px]"
              onClick={() => setTierFilter(null)}
            >
              {lang === 'hi' ? 'फ़िल्टर हटाएँ' : 'Clear filter'} ·{' '}
              {lang === 'hi' ? TIER_LABELS[tierFilter].hi : TIER_LABELS[tierFilter].en}
            </button>
          )}
        </div>
      </section>

      {/* ------------------------------------------------------- watchlist */}
      <section data-tour="ov-watchlist" className="panel flex shrink-0 flex-col">
        <SectionHead
          title={tierFilter
            ? `${lang === 'hi' ? TIER_LABELS[tierFilter].hi : TIER_LABELS[tierFilter].en} · ${watchlist.length}`
            : t(lang, 'highestRisk')}
          lang={lang}
        />
        <ul className="max-h-[min(58vh,30rem)] overflow-y-auto scrollbar-thin">
          {watchlist.length === 0 && (
            <li className="px-4 py-6 text-center text-[11px] text-ink-500">
              {lang === 'hi' ? 'इस श्रेणी में कोई स्थान नहीं' : 'No locations at this level'}
            </li>
          )}
          {watchlist.map((loc, i) => {
            const selected = loc.id === selectedLocationId;
            return (
              <li key={loc.id}>
                <button
                  type="button"
                  onClick={() => onSelectLocation(loc.id)}
                  className={`group flex w-full items-center gap-2.5 border-b border-ink-800/70 px-3 py-2 text-left transition ${
                    selected ? 'bg-saffron-500/10' : 'hover:bg-ink-800/60'
                  }`}
                >
                  <span className="w-4 shrink-0 font-mono text-[10px] text-ink-600">{i + 1}</span>
                  <span
                    className="h-7 w-[3px] shrink-0 rounded-full"
                    style={{ background: tierColour(loc.tier) }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-1.5">
                      <span
                        className={`truncate text-[12.5px] font-semibold text-ink-100 ${
                          lang === 'hi' ? 'font-devanagari' : ''
                        }`}
                      >
                        {lang === 'hi' && loc.name_hi ? loc.name_hi : loc.name}
                      </span>
                      <DirectionBadge direction={loc.direction} lang={lang} />
                    </span>
                    <span className="flex items-center gap-1.5 truncate text-[10px] text-ink-500">
                      {stateName(loc.state, lang)}
                      {loc.river && <span className="text-ink-700">·</span>}
                      {loc.river}
                      {loc.percentile_for_season !== null &&
                        loc.percentile_for_season !== undefined && (
                          <>
                            <span className="text-ink-700">·</span>
                            <span className="text-ink-400">
                              {ordinal(loc.percentile_for_season)} pct
                            </span>
                          </>
                        )}
                    </span>
                  </span>
                  <span className="shrink-0 text-right">
                    <span
                      className="block font-mono text-sm font-bold tabular-nums"
                      style={{ color: tierColour(loc.tier) }}
                    >
                      {loc.score.toFixed(0)}
                    </span>
                    <span className="block text-[9.5px] text-ink-600">
                      {mm(loc.rain_24h_mm)}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      {/* -------------------------------------------- state / basin roll-up */}
      <section data-tour="ov-rollup" className="panel flex shrink-0 flex-col">
        <div className="panel-head">
          <div className="flex items-center rounded-md border border-ink-700/70 bg-ink-850/70 p-0.5">
            {[
              ['state', t(lang, 'byState')],
              ['basin', t(lang, 'byBasin')],
              ['ai', lang === 'hi' ? 'एआई अंतर्दृष्टि' : 'AI insights'],
            ].map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setGrouping(key)}
                className={`rounded px-2 py-0.5 text-[10px] font-semibold transition ${
                  grouping === key
                    ? 'bg-saffron-500 text-white'
                    : 'text-ink-400 hover:text-ink-100'
                } ${lang === 'hi' ? 'font-devanagari' : ''}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {grouping === 'ai' ? (
          <NationalInsights lang={lang} onSelectLocation={onSelectLocation} runId={country?.meta?.run_id} />
        ) : (
        <ul className="max-h-[min(42vh,22rem)] overflow-y-auto scrollbar-thin">
          {(grouping === 'state' ? (country?.states ?? []) : (country?.basins ?? [])).map((row) => {
            const name = grouping === 'state' ? stateName(row.state, lang) : row.basin;
            const clickable = grouping === 'state';
            return (
              <li key={name}>
                <button
                  type="button"
                  disabled={!clickable}
                  onClick={() => clickable && onSelectState(row.state)}
                  className={`flex w-full items-center gap-2.5 border-b border-ink-800/70 px-3 py-1.5 text-left ${
                    clickable ? 'transition hover:bg-ink-800/60' : 'cursor-default'
                  }`}
                >
                  <span
                    className="h-2 w-2 shrink-0 rounded-sm"
                    style={{ background: tierColour(row.tier ?? 'green') }}
                  />
                  <span className="min-w-0 flex-1 truncate text-[11.5px] text-ink-200">{name}</span>
                  <span className="shrink-0 font-mono text-[9.5px] text-ink-600">
                    {row.counts.red > 0 && <span className="text-risk-red">{row.counts.red}R </span>}
                    {row.counts.orange > 0 && (
                      <span className="text-risk-orange">{row.counts.orange}O </span>
                    )}
                    {row.counts.yellow > 0 && (
                      <span className="text-risk-yellow">{row.counts.yellow}Y</span>
                    )}
                  </span>
                  <span
                    className="w-7 shrink-0 text-right font-mono text-[11px] font-bold tabular-nums"
                    style={{ color: tierColour(row.tier ?? 'green') }}
                  >
                    {row.score.toFixed(0)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        )}
      </section>
    </div>
  );
}

/* ------------------------------------------------------------ state view rail */

export function StatePanel({
  lang,
  state,
  onBack,
  onSelectLocation,
  selectedLocationId,
}) {
  const [sort, setSort] = useState('score');

  const rows = useMemo(() => {
    const items = [...(state?.locations ?? [])];
    if (sort === 'name') {
      items.sort((a, b) => a.location.name.localeCompare(b.location.name));
    } else if (sort === 'population') {
      items.sort((a, b) => (b.location.population ?? 0) - (a.location.population ?? 0));
    } else if (sort === 'rain') {
      items.sort(
        (a, b) => (b.observations.rain_24h_mm ?? 0) - (a.observations.rain_24h_mm ?? 0),
      );
    } else {
      items.sort((a, b) => b.risk.score - a.risk.score);
    }
    return items;
  }, [state, sort]);

  if (!state) return null;

  return (
    <div className="flex flex-col gap-3 lg:h-full lg:min-h-0 lg:overflow-y-auto lg:pr-1 scrollbar-thin">
      <section className="panel shrink-0">
        <div className="panel-head">
          <button type="button" className="btn btn-ghost px-2 py-1 text-[10.5px]" onClick={onBack}>
            <span aria-hidden="true">←</span>
            <span className={lang === 'hi' ? 'font-devanagari' : ''}>{t(lang, 'backToIndia')}</span>
          </button>
          <TierChip tier={state.counts.red ? 'red' : state.counts.orange ? 'orange' : state.counts.yellow ? 'yellow' : 'green'} lang={lang} />
        </div>
        <div className="p-3">
          <h2 className="text-lg font-bold tracking-tight text-chakra-500">{stateName(state.state, lang)}</h2>
          <p className="mt-0.5 text-[10.5px] text-ink-500">
            {state.locations.length} {t(lang, 'monitored').toLowerCase()}
            {state.districts?.length ? ` · ${state.districts.length} ${t(lang, 'district').toLowerCase()}` : ''}
          </p>

          <div className="mt-3 grid grid-cols-4 gap-1.5">
            {TIER_ORDER.map((tier) => (
              <StatTile
                key={tier}
                tone={tier}
                label={lang === 'hi' ? TIER_LABELS[tier].hi : TIER_LABELS[tier].en}
                value={state.counts[tier] ?? 0}
              />
            ))}
          </div>

          {state.population_at_risk > 0 && (
            <div className="mt-2.5 flex items-center justify-between rounded-lg border border-risk-orange/35 bg-risk-orange/[0.07] px-2.5 py-2">
              <span className={`text-[10.5px] text-ink-300 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
                {t(lang, 'peopleExposed')}
              </span>
              <span className="font-mono text-base font-bold text-risk-orange">
                {compactPopulation(state.population_at_risk)}
              </span>
            </div>
          )}
        </div>
      </section>

      <section className="panel flex shrink-0 flex-col">
        <div className="panel-head">
          <h3 className={`panel-title ${lang === 'hi' ? 'font-devanagari' : ''}`}>
            {t(lang, 'monitored')}
          </h3>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="rounded-md border border-ink-700/70 bg-ink-850 px-1.5 py-1 text-[10px] text-ink-300"
            aria-label="Sort"
          >
            <option value="score">{lang === 'hi' ? 'जोखिम' : 'Risk'}</option>
            <option value="rain">{lang === 'hi' ? 'वर्षा' : 'Rainfall'}</option>
            <option value="population">{lang === 'hi' ? 'जनसंख्या' : 'Population'}</option>
            <option value="name">{lang === 'hi' ? 'नाम' : 'Name'}</option>
          </select>
        </div>

        <ul className="max-h-[min(62vh,34rem)] overflow-y-auto scrollbar-thin">
          {rows.map((a) => {
            const loc = a.location;
            const selected = loc.id === selectedLocationId;
            return (
              <li key={loc.id}>
                <button
                  type="button"
                  onClick={() => onSelectLocation(loc.id)}
                  className={`flex w-full items-start gap-2.5 border-b border-ink-800/70 px-3 py-2 text-left transition ${
                    selected ? 'bg-saffron-500/10' : 'hover:bg-ink-800/60'
                  }`}
                >
                  <span
                    className="mt-0.5 h-8 w-[3px] shrink-0 rounded-full"
                    style={{ background: tierColour(a.risk.tier.key) }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline gap-1.5">
                      <span
                        className={`truncate text-[12.5px] font-semibold text-ink-100 ${
                          lang === 'hi' ? 'font-devanagari' : ''
                        }`}
                      >
                        {lang === 'hi' && loc.name_hi ? loc.name_hi : loc.name}
                      </span>
                      <DirectionBadge direction={a.risk.direction} lang={lang} />
                    </span>
                    <span className="block truncate text-[10px] text-ink-500">
                      {loc.district}
                      {loc.river ? ` · ${loc.river}` : ''} ·{' '}
                      {compactPopulation(loc.population)}
                    </span>
                    <span className="mt-1 block truncate text-[10px] text-ink-400">
                      {lang === 'hi' ? a.factors[0]?.label_hi : a.factors[0]?.label_en}
                    </span>
                  </span>
                  <span className="shrink-0 text-right">
                    <span
                      className="block font-mono text-base font-bold tabular-nums"
                      style={{ color: tierColour(a.risk.tier.key) }}
                    >
                      {a.risk.score.toFixed(0)}
                    </span>
                    <span className="block text-[9.5px] text-ink-600">
                      {mm(a.observations.rain_24h_mm)}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
