import { useEffect, useMemo, useRef, useState } from 'react';
import { compactPopulation, stateName, tierColour } from '../lib/format';
import { t } from '../lib/i18n';

/**
 * Search across monitored locations by name (Latin or Devanagari), state, district
 * or river.
 *
 * River search matters more than it looks: an operations question is often "who
 * is on the Brahmaputra right now", not "show me Dibrugarh". Matching the river
 * field turns one keystroke into a basin-wide answer.
 *
 * Keyboard: "/" focuses, arrows move, Enter selects, Escape dismisses.
 */

export default function SearchBox({ lang, locations = [], onSelect }) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef(null);
  const boxRef = useRef(null);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const scored = [];
    for (const loc of locations) {
      const haystacks = [
        [loc.name, 3],
        [loc.name_hi, 3],
        [loc.river, 2],
        [loc.district, 2],
        [loc.state, 1],
        [loc.basin, 1],
      ];
      let best = 0;
      let matchedOn = null;
      for (const [text, boost] of haystacks) {
        if (!text) continue;
        const lower = String(text).toLowerCase();
        if (lower.startsWith(q)) {
          if (boost * 2 > best) {
            best = boost * 2;
            matchedOn = text;
          }
        } else if (lower.includes(q)) {
          if (boost > best) {
            best = boost;
            matchedOn = text;
          }
        }
      }
      if (best > 0) scored.push({ loc, score: best, matchedOn });
    }
    // Rank by match quality first, then by current risk — a matching Red location
    // should not sit below a matching Green one.
    scored.sort((a, b) => b.score - a.score || b.loc.score - a.loc.score);
    return scored.slice(0, 8);
  }, [query, locations]);

  useEffect(() => setCursor(0), [query]);

  // "/" as a global focus shortcut, the way operations tools usually bind it.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === '/' && document.activeElement !== inputRef.current) {
        const tag = document.activeElement?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  useEffect(() => {
    const onClick = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    };
    window.addEventListener('mousedown', onClick);
    return () => window.removeEventListener('mousedown', onClick);
  }, []);

  function choose(loc) {
    onSelect(loc.id);
    setQuery('');
    setOpen(false);
    inputRef.current?.blur();
  }

  function onKeyDown(e) {
    if (e.key === 'Escape') {
      setOpen(false);
      inputRef.current?.blur();
      return;
    }
    if (!results.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setCursor((c) => (c + 1) % results.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setCursor((c) => (c - 1 + results.length) % results.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      choose(results[cursor].loc);
    }
  }

  return (
    <div ref={boxRef} className="relative mx-auto w-full max-w-md">
      <div className="relative">
        <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-500">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2.2" />
            <path d="M16.5 16.5L21 21" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
          </svg>
        </span>
        <input
          ref={inputRef}
          type="search"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={t(lang, 'search')}
          aria-label={t(lang, 'search')}
          role="combobox"
          aria-expanded={open && results.length > 0}
          aria-controls="search-results"
          className={`w-full rounded-lg border border-ink-700/70 bg-ink-850/80 py-1.5 pl-8 pr-9 text-[11.5px] text-ink-100 placeholder:text-ink-600 focus:border-saffron-500/60 ${
            lang === 'hi' ? 'font-devanagari' : ''
          }`}
        />
        {!query && (
          <kbd className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-ink-700 bg-ink-800 px-1.5 py-0.5 font-mono text-[9.5px] text-ink-500">
            /
          </kbd>
        )}
      </div>

      {open && query.trim() && (
        <ul
          id="search-results"
          role="listbox"
          className="panel absolute left-0 right-0 top-full z-30 mt-1.5 max-h-72 overflow-y-auto py-1 scrollbar-thin"
        >
          {results.length === 0 && (
            <li className={`px-3 py-3 text-center text-[11px] text-ink-500 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
              {t(lang, 'noResults')}
            </li>
          )}
          {results.map(({ loc, matchedOn }, i) => (
            <li key={loc.id} role="option" aria-selected={i === cursor}>
              <button
                type="button"
                onClick={() => choose(loc)}
                onMouseEnter={() => setCursor(i)}
                className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition ${
                  i === cursor ? 'bg-saffron-500/10' : ''
                }`}
              >
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ background: tierColour(loc.tier) }}
                />
                <span className="min-w-0 flex-1">
                  <span className={`block truncate text-[12px] font-semibold text-ink-100 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
                    {lang === 'hi' && loc.name_hi ? loc.name_hi : loc.name}
                  </span>
                  <span className="block truncate text-[10px] text-ink-500">
                    {loc.district ? `${loc.district} · ` : ''}
                    {stateName(loc.state, lang)}
                    {matchedOn && matchedOn !== loc.name && matchedOn !== loc.name_hi && (
                      <span className="text-saffron-400"> · {matchedOn}</span>
                    )}
                  </span>
                </span>
                <span className="shrink-0 text-right">
                  <span
                    className="block font-mono text-[12px] font-bold tabular-nums"
                    style={{ color: tierColour(loc.tier) }}
                  >
                    {loc.score.toFixed(0)}
                  </span>
                  <span className="block text-[9px] text-ink-600">
                    {compactPopulation(loc.population)}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
