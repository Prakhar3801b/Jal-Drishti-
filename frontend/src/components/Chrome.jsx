import { useEffect, useMemo, useState } from 'react';
import { relativeAge, stateName, tierColour, TIER_LABELS, TIER_ORDER } from '../lib/format';
import { pickPlain, t } from '../lib/i18n';

/**
 * Application chrome: the tricolour rule, masthead, alert ticker and footer.
 *
 * On the government aesthetic, and its limits: the visual language here quotes
 * Indian public-service dashboards deliberately — the tricolour rule, the Ashoka
 * Chakra, the Devanagari/Latin bilingual pairing, IMD's four-colour alert scale.
 * What it does *not* do is borrow anyone's identity. There is no State Emblem
 * (its use is restricted by the State Emblem of India Act, 2005), no ministry
 * name, no departmental logo, and a "Prototype" badge sits in the masthead with a
 * standing disclaimer in the footer. The look should say "built for Indian
 * emergency response", never "issued by the Government of India".
 */

/** The 24-spoke Ashoka Chakra. Spins while data is in flight. */
export function AshokaChakra({ size = 26, spinning = false, className = '' }) {
  const spokes = useMemo(
    () => Array.from({ length: 24 }, (_, i) => (i * 360) / 24),
    [],
  );
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={`${spinning ? 'animate-chakra-spin' : ''} ${className}`}
      role="img"
      aria-label="Ashoka Chakra"
    >
      <circle cx="50" cy="50" r="46" fill="none" stroke="currentColor" strokeWidth="4" />
      <circle cx="50" cy="50" r="7" fill="currentColor" />
      {spokes.map((deg) => (
        <line
          key={deg}
          x1="50"
          y1="50"
          x2="50"
          y2="6"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          transform={`rotate(${deg} 50 50)`}
        />
      ))}
    </svg>
  );
}

export function TricolourRule() {
  return <div className="tricolour-rule h-[3px] w-full shrink-0" aria-hidden="true" />;
}

function LiveDot({ refreshing }) {
  return (
    <span className="relative flex h-2 w-2" aria-hidden="true">
      <span
        className={`absolute inline-flex h-full w-full rounded-full ${
          refreshing ? 'bg-saffron-400' : 'bg-indiagreen-300'
        } opacity-70 ${refreshing ? 'animate-ping' : ''}`}
      />
      <span
        className={`relative inline-flex h-2 w-2 rounded-full ${
          refreshing ? 'bg-saffron-500' : 'bg-indiagreen-400'
        }`}
      />
    </span>
  );
}

export function LangToggle({ lang, onChange, tone = 'light' }) {
  const onDark = tone === 'dark';
  return (
    <div
      className={`flex items-center rounded-md p-0.5 ${
        onDark ? 'bg-white/15' : 'border border-ink-700 bg-ink-850'
      }`}
      role="group"
      aria-label="Language"
    >
      {[
        ['en', 'English'],
        ['hi', 'हिंदी'],
      ].map(([key, label]) => (
        <button
          key={key}
          type="button"
          onClick={() => onChange(key)}
          aria-pressed={lang === key}
          className={`rounded px-2 py-0.5 text-[11px] font-semibold transition ${
            lang === key
              ? onDark
                ? 'bg-white text-chakra-500'
                : 'bg-saffron-500 text-white shadow-sm'
              : onDark
                ? 'text-white/80 hover:text-white'
                : 'text-ink-400 hover:text-ink-100'
          } ${key === 'hi' ? 'font-devanagari' : ''}`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/**
 * Text-size control, the A- / A / A+ pattern Indian government portals carry
 * under the GIGW accessibility guidelines. Applied as page zoom, because the
 * dashboard's dense type is set in fixed pixel sizes that a root font-size
 * change would not reach.
 */
function TextSizeControl({ lang }) {
  const [zoom, setZoom] = useState(() => {
    try {
      return Number(localStorage.getItem('jd.zoom')) || 1;
    } catch {
      return 1;
    }
  });
  useEffect(() => {
    document.documentElement.style.zoom = String(zoom);
    try {
      localStorage.setItem('jd.zoom', String(zoom));
    } catch {
      /* non-fatal */
    }
  }, [zoom]);

  const steps = [
    [0.9, 'A-', lang === 'hi' ? 'छोटा पाठ' : 'Smaller text'],
    [1, 'A', lang === 'hi' ? 'सामान्य पाठ' : 'Normal text'],
    [1.1, 'A+', lang === 'hi' ? 'बड़ा पाठ' : 'Larger text'],
  ];
  return (
    <div className="flex items-center gap-0.5" role="group" aria-label="Text size">
      {steps.map(([value, label, title]) => (
        <button
          key={label}
          type="button"
          title={title}
          aria-label={title}
          aria-pressed={zoom === value}
          onClick={() => setZoom(value)}
          className={`min-w-[22px] rounded px-1 py-0.5 text-[10.5px] font-bold transition ${
            zoom === value ? 'bg-white text-chakra-500' : 'text-white/80 hover:bg-white/15 hover:text-white'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export function Masthead({
  lang,
  onLangChange,
  meta,
  refreshing,
  onRefresh,
  onOpenSystem,
  onOpenCopilot,
  onOpenTour,
  user,
  onLogout,
  children,
}) {
  // A local ticking clock, so "updated 3 min ago" ages visibly between refreshes
  // instead of freezing at whatever the last API response said.
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 15000);
    return () => clearInterval(id);
  }, []);

  const ageSeconds = meta ? meta.age_seconds + tick * 15 : null;

  return (
    <header className="relative z-20 shrink-0">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-1.5 focus:text-xs focus:font-semibold focus:text-chakra-500 focus:shadow"
      >
        {lang === 'hi' ? 'मुख्य सामग्री पर जाएँ' : 'Skip to main content'}
      </a>

      {/* utility strip — navy, the portal convention */}
      <div className="bg-chakra-500 text-white">
        <div className="flex items-center gap-3 px-4 py-1 lg:px-5">
          <span className={`truncate text-[10.5px] font-medium text-white/90 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
            {lang === 'hi'
              ? 'बाढ़ पूर्वानुमान अनुसंधान प्रोटोटाइप · आधिकारिक चेतावनी हेतु IMD / CWC देखें'
              : 'Flood forecasting research prototype · For official warnings see IMD / CWC'}
          </span>
          <div className="ml-auto flex shrink-0 items-center gap-3" data-tour="access">
            <span className="hidden sm:block">
              <TextSizeControl lang={lang} />
            </span>
            <span className="hidden h-3.5 w-px bg-white/25 sm:block" aria-hidden="true" />
            <LangToggle lang={lang} onChange={onLangChange} tone="dark" />
          </div>
        </div>
      </div>

      <TricolourRule />

      {/* identity row — white */}
      <div className="border-b border-ink-700 bg-white">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5 lg:px-5">
          <div className="flex min-w-0 items-center gap-3">
            <div className="grid h-12 w-12 shrink-0 place-items-center rounded-full border-2 border-saffron-500 bg-white text-chakra-500 shadow-sm">
              <AshokaChakra size={30} spinning={refreshing} />
            </div>
            <div className="min-w-0 leading-tight">
              <div className="flex items-baseline gap-2">
                <span className="font-devanagari truncate text-[20px] font-bold text-saffron-500">
                  जलदृष्टि
                </span>
                <h1 className="truncate text-[20px] font-extrabold tracking-tight text-chakra-500">
                  JalDrishti
                </h1>
                <span className="chip border-saffron-500/50 bg-saffron-50 px-2 py-0.5 text-[10px] text-saffron-300">
                  {t(lang, 'prototype')}
                </span>
              </div>
              <p className={`truncate text-[11.5px] font-medium text-ink-400 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
                {t(lang, 'tagline')}
                <span className="text-ink-600"> · </span>
                <span className="text-indiagreen-300">{lang === 'hi' ? 'एआई/एमएल सक्षम' : 'AI/ML enabled'}</span>
              </p>
            </div>
          </div>

          <div className="mx-auto hidden min-w-0 flex-1 md:block" data-tour="search">{children}</div>

          <div className="ml-auto flex items-center gap-2">
            {meta && meta.weather_mode && meta.weather_mode !== 'live' ? (
              // Weather source unavailable (e.g. over its daily quota): say so, and
              // that gauges and official alerts are still updating.
              <div
                className="hidden items-center gap-2 rounded-lg border border-risk-orange/40 bg-risk-orange/[0.07] px-2.5 py-1.5 sm:flex"
                data-tour="live"
                title={
                  lang === 'hi'
                    ? 'मौसम स्रोत अभी उपलब्ध नहीं; नदी गेज व आधिकारिक चेतावनियाँ लाइव हैं'
                    : `Weather source unavailable${meta.weather_pause_kind ? ` (${meta.weather_pause_kind} limit reached)` : ''}. River gauges and official alerts are still live; scores update when they change.`
                }
              >
                <LiveDot refreshing={refreshing} />
                <div className="leading-tight">
                  <div className="text-[9.5px] font-bold uppercase tracking-wider text-risk-orange">
                    {lang === 'hi' ? 'गेज लाइव · मौसम रुका' : 'Gauges live · weather paused'}
                  </div>
                  <div className="font-mono text-[11px] text-ink-300">
                    {lang === 'hi' ? 'मौसम ' : 'weather '}
                    {relativeAge(meta.weather_age_seconds + tick * 15, lang)}
                    {meta.weather_paused_until &&
                      ` · ${lang === 'hi' ? 'फिर' : 'resumes'} ${new Date(meta.weather_paused_until).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' })}`}
                  </div>
                </div>
              </div>
            ) : (
              <div
                className="hidden items-center gap-2 rounded-lg border border-indiagreen-500/30 bg-indiagreen-500/[0.06] px-2.5 py-1.5 sm:flex"
                data-tour="live"
                title={lang === 'hi' ? 'आँकड़े अपने-आप अद्यतन होते हैं' : 'Data updates automatically — no need to refresh'}
              >
                <LiveDot refreshing={refreshing} />
                <div className="leading-tight">
                  <div className="text-[9.5px] font-bold uppercase tracking-wider text-indiagreen-300">
                    {refreshing ? t(lang, 'refreshing') : lang === 'hi' ? 'लाइव · स्वतः अद्यतन' : 'Live · auto-updates'}
                  </div>
                  <div className="font-mono text-[11px] text-ink-300">
                    {meta ? relativeAge(ageSeconds, lang) : '—'}
                  </div>
                </div>
              </div>
            )}

            <button
              type="button"
              className="btn border-chakra-500 bg-chakra-500 text-white hover:bg-[#123A78] hover:text-white"
              onClick={onOpenCopilot}
              data-tour="copilot"
              title={lang === 'hi' ? 'एआई सहायक से पूछें' : 'Ask the AI Copilot'}
              aria-label={lang === 'hi' ? 'एआई सहायक' : 'AI Copilot'}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="text-white">
                <path
                  d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9L12 3zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15z"
                  fill="currentColor"
                />
              </svg>
              <span className={`hidden sm:inline ${lang === 'hi' ? 'font-devanagari' : ''}`}>
                {lang === 'hi' ? 'एआई सहायक' : 'AI Copilot'}
              </span>
            </button>

            {onOpenTour && (
              <button
                type="button"
                className="btn"
                onClick={onOpenTour}
                data-tour="tutorial"
                title={lang === 'hi' ? 'ट्यूटोरियल: हर सुविधा चरण-दर-चरण' : 'Tutorial: every feature, step by step'}
                aria-label={lang === 'hi' ? 'ट्यूटोरियल' : 'Tutorial'}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5v-13zM13 4h5.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H13V4z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
                </svg>
                <span className={`hidden xl:inline ${lang === 'hi' ? 'font-devanagari' : ''}`}>{lang === 'hi' ? 'ट्यूटोरियल' : 'Tutorial'}</span>
              </button>
            )}

            <button
              type="button"
              className="btn"
              data-tour="system"
              onClick={onOpenSystem}
              title={t(lang, 'howItWorks')}
              aria-label={t(lang, 'howItWorks')}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="12" cy="12" r="9.2" stroke="currentColor" strokeWidth="2" />
                <path d="M12 10.6v6M12 7.6h.01" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
              </svg>
            </button>

            {user && (
              <div className="flex items-center gap-2 border-l border-ink-700 pl-2" data-tour="account">
                <div className={`hidden text-right leading-tight lg:block ${lang === 'hi' ? 'font-devanagari' : ''}`}>
                  <div className="max-w-[180px] truncate text-[12.5px] font-bold text-chakra-500">{user.area}</div>
                  <div className="text-[10.5px] text-ink-500">
                    {user.roleLabel}
                    {user.demo ? (lang === 'hi' ? ' · डेमो' : ' · demo') : ''}
                  </div>
                </div>
                <button type="button" className="btn px-2.5 text-[12px]" onClick={onLogout} title={lang === 'hi' ? 'बाहर निकलें' : 'Sign out'}>
                  {lang === 'hi' ? 'बाहर निकलें' : 'Sign out'}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}

/**
 * Scrolling advisory ticker.
 *
 * The list is duplicated and the track translated -50%, which is what makes the
 * loop seamless; `aria-hidden` on the clone keeps screen readers from reading
 * every alert twice.
 */
export function AlertTicker({ lang, worst = [], summary }) {
  const items = useMemo(() => {
    const rows = worst.map((w) => ({
      key: w.id,
      tier: w.tier,
      text: `${lang === 'hi' && w.name_hi ? w.name_hi : w.name}, ${stateName(
        w.state,
        lang,
      )} — ${w.score.toFixed(0)}/100 ${
        lang === 'hi' ? TIER_LABELS[w.tier]?.hi ?? '' : TIER_LABELS[w.tier]?.en ?? ''
      }${w.river ? ` · ${w.river}` : ''}`,
    }));
    return rows.length ? rows : [{ key: 'none', tier: 'green', text: pickPlain(lang, summary) }];
  }, [worst, lang, summary]);

  const Row = ({ ariaHidden }) => (
    <div
      className="flex shrink-0 items-center gap-7 pr-7"
      aria-hidden={ariaHidden ? 'true' : undefined}
    >
      {items.map((it) => (
        <span key={it.key} className="flex shrink-0 items-center gap-2 text-[11.5px] font-medium">
          <span
            className="h-2 w-2 shrink-0 rounded-full ring-2 ring-white/80"
            style={{ background: tierColour(it.tier) }}
          />
          <span className={lang === 'hi' ? 'font-devanagari' : ''}>{it.text}</span>
        </span>
      ))}
    </div>
  );

  return (
    <div data-tour="ticker" className="relative z-10 flex shrink-0 items-stretch bg-gradient-to-r from-saffron-500 to-saffron-400 text-white shadow-sm">
      <div className="flex shrink-0 items-center gap-2 bg-chakra-500 px-3 py-1.5">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-saffron-400" />
        <span className={`text-[10px] font-bold uppercase tracking-[0.14em] text-white ${lang === 'hi' ? 'font-devanagari' : ''}`}>
          {lang === 'hi' ? 'ताज़ा सलाह' : 'Latest advisory'}
        </span>
      </div>
      <div className="group relative flex-1 overflow-hidden py-1.5 text-white">
        <div className="flex w-max animate-ticker group-hover:[animation-play-state:paused]">
          <Row />
          <Row ariaHidden />
        </div>
        {/* Fade the ends so text does not collide with the chrome. */}
        <div className="pointer-events-none absolute inset-y-0 left-0 w-8 bg-gradient-to-r from-saffron-500 to-transparent" />
        <div className="pointer-events-none absolute inset-y-0 right-0 w-8 bg-gradient-to-l from-saffron-400 to-transparent" />
      </div>
    </div>
  );
}

export function TierLegend({ lang, counts, compact = false }) {
  return (
    <div className={`flex ${compact ? 'gap-2' : 'gap-3'} flex-wrap items-center`}>
      {TIER_ORDER.map((tier) => (
        <div key={tier} className="flex items-center gap-1.5">
          <span
            className="h-2.5 w-2.5 rounded-sm"
            style={{ background: tierColour(tier) }}
            aria-hidden="true"
          />
          <span className={`text-[10.5px] text-ink-300 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
            {lang === 'hi' ? TIER_LABELS[tier].hi : TIER_LABELS[tier].en}
          </span>
          {counts && (
            <span className="font-mono text-[10.5px] font-semibold text-ink-100">
              {counts[tier] ?? 0}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

export function Footer({ lang, system, meta }) {
  const disclaimer = system?.app
    ? lang === 'hi'
      ? system.app.disclaimer_hi
      : system.app.disclaimer_en
    : '';

  return (
    <footer data-tour="footer" className="relative z-10 shrink-0 border-t-4 border-saffron-500 bg-chakra-500 px-4 py-2 text-white lg:px-5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        {/* basis-full below lg: sharing a row with the shrink-0 run stats
            squeezed this paragraph to one word per line on a phone */}
        <p
          className={`basis-full text-[10.5px] leading-snug text-white/80 lg:min-w-0 lg:flex-1 lg:basis-auto ${
            lang === 'hi' ? 'font-devanagari' : ''
          }`}
        >
          {disclaimer}
        </p>
        <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] text-white/70">
          {meta && (
            <>
              <span>run #{meta.run_id}</span>
              <span className="text-white/30">·</span>
              <span>{meta.locations} loc</span>
              <span className="text-white/30">·</span>
              <span>{(meta.duration_ms / 1000).toFixed(1)}s</span>
              <span className="text-white/30">·</span>
              <span>GloFAS {meta.climatology_years}</span>
            </>
          )}
          {system?.app && (
            <>
              <span className="text-white/30">·</span>
              <span>v{system.app.version}</span>
            </>
          )}
        </div>
      </div>
    </footer>
  );
}
