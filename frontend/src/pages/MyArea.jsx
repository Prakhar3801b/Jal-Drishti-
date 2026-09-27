import { useState } from 'react';
import { href } from '../lib/router';
import { roleName } from '../lib/auth';
import { canonicalState, directionGlyph, stateName, tierColour, TIER_LABELS, weatherInfo } from '../lib/format';

/**
 * "My area": the one screen an officer needs, in plain language.
 *
 * Everything here is computed automatically for the signed-in user's area on
 * every update - status, alerts with ready-to-send advisories, what is coming,
 * what changed - so nothing has to be looked for. The detailed tools stay under
 * "Advanced tools".
 */

const KIND = {
  place: { en: 'Place at risk', hi: 'जोखिम में स्थान', icon: 'warn' },
  gauge: { en: 'River above danger', hi: 'नदी खतरे से ऊपर', icon: 'river' },
  wave: { en: 'Flood wave coming', hi: 'बाढ़ लहर आ रही', icon: 'wave' },
  official: { en: 'Official alert', hi: 'आधिकारिक चेतावनी', icon: 'shield' },
};
const ACTION = {
  red: { en: 'Take action now', hi: 'अभी कार्रवाई करें' },
  orange: { en: 'Be prepared', hi: 'तैयार रहें' },
  yellow: { en: 'Be aware', hi: 'सतर्क रहें' },
  green: { en: 'All normal', hi: 'सब सामान्य' },
};

// Readable text on white for each tier (yellow itself is too light for text).
const INK = { red: '#A50F1A', orange: '#B4530F', yellow: '#7A5E00', green: '#0A6E31' };
const ink = (tier) => INK[tier] ?? '#0B2A5B';

function Icon({ name, size = 18 }) {
  const p = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true };
  const d = {
    warn: 'M12 3l9.5 17h-19L12 3zM12 10v4M12 17.5h.01',
    river: 'M3 8c3-2 6 2 9 0s6-2 9 0M3 13c3-2 6 2 9 0s6-2 9 0M3 18c3-2 6 2 9 0s6-2 9 0',
    wave: 'M3 12h13M12 6l6 6-6 6',
    shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z',
    bell: 'M6 16V11a6 6 0 1 1 12 0v5l2 2H4l2-2zM10 20a2 2 0 0 0 4 0',
    people: 'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21v-1a6 6 0 0 1 12 0v1M16 3.5a4 4 0 0 1 0 7.5M22 21v-1a6 6 0 0 0-4-5.6',
    trend: 'M3 17l6-6 4 4 8-8M15 7h6v6',
    check: 'M5 12l5 5L20 7',
    map: 'M4 6l5-2 6 2 5-2v14l-5 2-6-2-5 2zM9 4v14M15 6v14',
    grid: 'M4 4h16v16H4zM4 9.3h16M4 14.6h16M9.3 4v16M14.6 4v16',
    note: 'M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7',
    clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',
    swap: 'M7 7h13l-3-3M17 17H4l3 3',
    pin: 'M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21zM12 12a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z',
  };
  return (
    <svg {...p}>
      <path d={d[name]} />
    </svg>
  );
}

function Sparkle({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9L12 3zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15z" fill="currentColor" />
    </svg>
  );
}

function Card({ title, icon, count, right, children, tour, bodyClass = 'p-4' }) {
  return (
    <section className="overflow-hidden rounded-2xl border border-ink-700 bg-white shadow-sm" data-tour={tour}>
      <div className="flex items-center gap-2.5 border-b border-ink-800 px-4 py-3">
        {icon && (
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-navy-50 text-chakra-500">
            <Icon name={icon} size={16} />
          </span>
        )}
        <h2 className="text-[14px] font-extrabold text-chakra-500">{title}</h2>
        {count != null && <span className="rounded-full bg-ink-850 px-2 py-0.5 font-mono text-[11px] font-bold text-ink-300">{count}</span>}
        <span className="ml-auto">{right}</span>
      </div>
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

function copy(text) {
  try {
    navigator.clipboard?.writeText(text);
  } catch {
    /* clipboard blocked */
  }
}

function AlertItem({ al, lang }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(null);
  const L = (en, hi) => (lang === 'hi' ? hi : en);
  const colour = tierColour(al.level);
  const adv = al.advisory?.[lang] ?? al.advisory?.en;
  const kind = KIND[al.kind] ?? KIND.place;
  const safety = al.safety?.[lang] ?? al.safety?.en ?? [];
  const routes = al.safety?.routes ?? [];
  const doCopy = (what, text) => {
    copy(text);
    setCopied(what);
    setTimeout(() => setCopied(null), 1500);
  };
  return (
    <li className="rounded-xl border border-ink-700 bg-white p-4 transition hover:shadow-md">
      <div className="flex gap-3.5">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full" style={{ background: `${colour}1A`, color: ink(al.level) }}>
          <Icon name={kind.icon} size={19} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-md px-2 py-0.5 text-[10.5px] font-extrabold uppercase tracking-wide text-white" style={{ background: colour }}>
              {L(ACTION[al.level]?.en ?? al.level, ACTION[al.level]?.hi ?? al.level)}
            </span>
            <span className="text-[11.5px] font-semibold text-ink-500">{L(kind.en, kind.hi)}</span>
          </div>
          <div className="mt-1.5 text-[15.5px] font-bold leading-snug text-ink-100">{L(al.title_en, al.title_hi)}</div>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-300">{L(al.detail_en, al.detail_hi)}</p>
          <div className="mt-3 rounded-lg px-3 py-2.5" style={{ background: `${colour}12`, borderLeft: `3px solid ${colour}` }}>
            <div className="text-[10.5px] font-extrabold uppercase tracking-wider" style={{ color: ink(al.level) }}>{L('What to do', 'क्या करें')}</div>
            <div className="mt-0.5 text-[13.5px] font-semibold leading-snug text-ink-100">{L(al.do_en, al.do_hi)}</div>
          </div>
          {safety.length > 0 && (
            <div className="mt-2 rounded-lg border border-ink-800 bg-ink-850 px-3 py-2.5">
              <div className="text-[10.5px] font-extrabold uppercase tracking-wider text-chakra-500">{L('Stay safe — tell residents', 'सुरक्षित रहें — नागरिकों को बताएँ')}</div>
              {routes.length > 0 && (
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  <span className="text-[12px] font-semibold text-ink-300">{L('Avoid:', 'इनसे बचें:')}</span>
                  {routes.map((r) => (
                    <span key={r} className="rounded-md border border-risk-red/30 bg-white px-2 py-0.5 text-[12px] font-semibold text-risk-red">⛔ {r}</span>
                  ))}
                </div>
              )}
              <ul className="mt-1.5 space-y-1">
                {safety.filter((x) => !x.startsWith('Avoid these roads') && !x.startsWith('इन सड़कों से बचें')).slice(0, 3).map((x) => (
                  <li key={x} className="text-[12.5px] leading-snug text-ink-200">• {x}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {al.place_id && (
              <a href={href(`/location/${al.place_id}`)} className="btn px-3 py-1.5 text-[12.5px]">
                {L('Open details', 'विवरण खोलें')} →
              </a>
            )}
            {adv && (
              <button type="button" className="btn px-3 py-1.5 text-[12.5px]" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
                <Icon name="note" size={14} />
                {open ? L('Hide advisory', 'सलाह छिपाएँ') : L('Ready-made advisory & SMS', 'तैयार सलाह व SMS')}
              </button>
            )}
          </div>
          {open && adv && (
            <div className="mt-3 space-y-2.5 rounded-xl border border-ink-700 bg-ink-850 p-3.5">
              <div className="text-[13px] font-bold text-chakra-500">{adv.title}</div>
              <p className="whitespace-pre-line text-[12.5px] leading-relaxed text-ink-200">{adv.body}</p>
              <div>
                <div className="mb-1 text-[10.5px] font-bold uppercase tracking-wider text-ink-500">SMS</div>
                <div className="rounded-lg border border-ink-700 bg-white px-2.5 py-2 font-mono text-[12px] text-ink-200">{adv.sms}</div>
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" className="btn btn-primary px-3 py-1.5 text-[12.5px]" onClick={() => doCopy('adv', `${adv.title}\n\n${adv.body}`)}>
                  {copied === 'adv' ? L('Copied ✓', 'कॉपी हुआ ✓') : L('Copy advisory', 'सलाह कॉपी करें')}
                </button>
                <button type="button" className="btn px-3 py-1.5 text-[12.5px]" onClick={() => doCopy('sms', adv.sms)}>
                  {copied === 'sms' ? L('Copied ✓', 'कॉपी हुआ ✓') : L('Copy SMS', 'SMS कॉपी करें')}
                </button>
              </div>
              <p className="text-[11px] text-ink-500">{L('Drafted automatically from the current assessment — review before sending.', 'वर्तमान आकलन से स्वतः तैयार — भेजने से पहले जाँचें।')}</p>
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

export default function MyArea({ lang, user, brief, error, onRetry, onOpenCopilot }) {
  const [showAll, setShowAll] = useState(false);
  const L = (en, hi) => (lang === 'hi' ? hi : en);
  const hiFont = lang === 'hi' ? 'font-devanagari' : '';

  if (error && !brief) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <p className="rounded-xl border border-risk-red/40 bg-white p-4 text-[13px] text-risk-red">{error}</p>
        <button type="button" className="btn btn-primary mt-3" onClick={onRetry}>{L('Try again', 'पुनः प्रयास करें')}</button>
      </div>
    );
  }
  if (!brief) return <div className="p-10 text-center text-[13px] text-ink-400">{L('Preparing your area briefing…', 'आपके क्षेत्र की जानकारी तैयार हो रही है…')}</div>;

  const st = brief.status;
  // A state or the whole country has no single level: one Red district does not
  // make all of India Red. Those views lead with counts; only a district gets a level.
  const aggregate = user.role !== 'district';
  const colour = aggregate ? '#0B2A5B' : tierColour(st.tier);
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const headline = !aggregate
    ? L(ACTION[st.tier].en, ACTION[st.tier].hi)
    : st.counts.red + st.counts.orange + st.counts.yellow === 0
      ? L('All places normal', 'सभी स्थान सामान्य')
      : [
          st.counts.red && L(`${plural(st.counts.red, 'place needs', 'places need')} action now`, `${st.counts.red} स्थानों पर अभी कार्रवाई`),
          st.counts.orange && L(`${st.counts.orange} to prepare`, `${st.counts.orange} पर तैयारी`),
          st.counts.yellow && L(`${st.counts.yellow} to watch`, `${st.counts.yellow} पर नज़र`),
        ]
          .filter(Boolean)
          .join(' · ');
  const urgent = ['red', 'orange', 'yellow'].find((t) => st.counts[t]);
  const area = user.role === 'central' ? L('All India', 'संपूर्ण भारत') : user.role === 'state' ? stateName(user.state, lang) : `${user.district}, ${stateName(user.state, lang)}`;
  const alerts = showAll ? brief.alerts : brief.alerts.slice(0, 5);
  const coming = brief.coming_next;
  const tz = { timeZone: 'Asia/Kolkata' };
  const updated = new Date(brief.computed_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', ...tz });
  const today = new Date().toLocaleDateString(lang === 'hi' ? 'hi-IN' : 'en-IN', { weekday: 'long', day: 'numeric', month: 'long', ...tz });
  const districtTown = user.role === 'district' ? brief.places[0] : null;
  const mapHref = href(user.role === 'central' ? '/map' : `/state/${canonicalState(user.state)}`);
  const total = Math.max(1, st.places);
  const worseCount = brief.changes.items.filter((c) => c.worse).length;

  const kpis = [
    ['bell', brief.alerts.length, L('Active alerts', 'सक्रिय चेतावनियाँ'), brief.alerts.length ? tierColour(brief.alerts[0].level) : '#0B8A3D'],
    ['people', st.people_at_risk > 0 ? st.people_at_risk.toLocaleString('en-IN') : '0', L('People in Orange/Red areas', 'नारंगी/लाल क्षेत्रों में लोग'), st.people_at_risk > 0 ? '#E4701E' : '#0B8A3D'],
    ['trend', coming.places.length, L('May worsen in 3 days', '3 दिनों में बिगड़ सकते हैं'), coming.places.length ? '#C1121F' : '#0B8A3D'],
    ['river', coming.waves.length, L('River waves on the way', 'रास्ते में नदी लहरें'), coming.waves.length ? '#1B5FA8' : '#0B8A3D'],
  ];

  return (
    <div id="main-content" className={`mx-auto w-full max-w-[1320px] space-y-5 px-4 py-5 ${hiFont}`}>
      {/* ------------------------------------------------------------ status */}
      <section
        className="relative overflow-hidden rounded-3xl border border-ink-700 bg-white shadow-sm"
        data-tour="my-status"
        style={{ backgroundImage: `linear-gradient(110deg, ${colour}1F 0%, ${colour}08 38%, #ffffff 70%)` }}
      >
        <div className="absolute inset-y-0 left-0 w-1.5" style={{ background: colour }} aria-hidden="true" />
        <div className="flex flex-wrap items-center gap-6 px-6 py-6 sm:px-8">
          <div className="flex flex-col items-center">
            <div className="grid h-24 w-24 place-items-center rounded-full bg-white shadow-md" style={{ boxShadow: `0 0 0 6px ${colour}33, 0 8px 20px -8px ${colour}` }}>
              <div className="grid h-[76px] w-[76px] place-items-center rounded-full text-white" style={{ background: colour }}>
                {aggregate ? <Icon name={urgent ? 'map' : 'check'} size={34} /> : <Icon name={st.tier === 'green' ? 'check' : 'warn'} size={34} />}
              </div>
            </div>
            <span className="mt-2 text-[12px] font-extrabold uppercase tracking-wider" style={{ color: aggregate ? colour : ink(st.tier) }}>
              {aggregate
                ? user.role === 'central' ? L('National view', 'राष्ट्रीय दृश्य') : L('State view', 'राज्य दृश्य')
                : L(TIER_LABELS[st.tier].en, TIER_LABELS[st.tier].hi)}
            </span>
          </div>

          <div className="min-w-[240px] flex-1">
            <div className="flex flex-wrap items-center gap-x-2 text-[12px] font-bold uppercase tracking-wider text-ink-500">
              <span>{roleName(user, lang)}</span>
              <span className="text-ink-600">•</span>
              <span className="normal-case tracking-normal">{today}</span>
            </div>
            <h1 className="mt-1 text-[30px] font-extrabold leading-tight tracking-tight text-chakra-500">{area}</h1>
            <p className="mt-1 text-[18px] font-bold" style={{ color: ink(aggregate ? urgent ?? 'green' : st.tier) }}>
              {headline}
              <span className="font-semibold text-ink-400"> · {L(`${st.places} place${st.places !== 1 ? 's' : ''} monitored`, `${st.places} निगरानी स्थान`)}</span>
            </p>
            {brief.brief[lang]?.[1] && <p className="mt-1.5 max-w-2xl text-[13.5px] leading-snug text-ink-300">{brief.brief[lang][1]}</p>}
          </div>

          <div className="w-full sm:w-auto sm:min-w-[300px]">
            <div className="flex h-3 overflow-hidden rounded-full bg-ink-800" aria-hidden="true">
              {['red', 'orange', 'yellow', 'green'].map((t) =>
                st.counts[t] ? <span key={t} style={{ width: `${(100 * st.counts[t]) / total}%`, background: tierColour(t) }} /> : null,
              )}
            </div>
            <div className="mt-3 grid grid-cols-4 gap-2">
              {['red', 'orange', 'yellow', 'green'].map((t) => (
                <div key={t} className="rounded-xl border bg-white px-2 py-2 text-center" style={{ borderColor: st.counts[t] ? `${tierColour(t)}80` : '#E5EAF0' }}>
                  <div className="font-mono text-[22px] font-extrabold leading-none" style={{ color: st.counts[t] ? tierColour(t) : '#A3AEBB' }}>{st.counts[t]}</div>
                  <div className="mt-1 text-[10px] font-bold uppercase tracking-wide text-ink-500">{L(TIER_LABELS[t].en, TIER_LABELS[t].hi)}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-ink-800/80 bg-white/70 px-6 py-3 sm:px-8">
          <span className="flex items-center gap-2 text-[12.5px] text-ink-400">
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indiagreen-500 opacity-50" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-indiagreen-500" />
            </span>
            {L(`Updated ${updated} IST · updates automatically`, `अद्यतन ${updated} IST · स्वतः अद्यतन`)}
          </span>
          <span className="ml-auto flex flex-wrap gap-2">
            {onOpenCopilot && (
              <button
                type="button"
                onClick={onOpenCopilot}
                className="btn border-chakra-500 bg-chakra-500 px-3.5 py-1.5 text-[12.5px] text-white hover:bg-[#123A78] hover:text-white"
              >
                <Sparkle size={14} />
                {L('Ask AI about my area', 'मेरे क्षेत्र के बारे में एआई से पूछें')}
              </button>
            )}
            {districtTown && (
              <a href={href(`/hotspots/${districtTown.id}`)} className="btn px-3 py-1.5 text-[12.5px]">
                <Icon name="grid" size={14} /> {L('Street-level map', 'गली-स्तर नक्शा')}
              </a>
            )}
            <a href={mapHref} className="btn px-3 py-1.5 text-[12.5px]">
              <Icon name="map" size={14} /> {L('Open map', 'नक्शा खोलें')}
            </a>
          </span>
        </div>
      </section>

      {/* -------------------------------------------------------------- kpis */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {kpis.map(([icon, value, label, c]) => (
          <div key={label} className="flex items-center gap-3 rounded-2xl border border-ink-700 bg-white px-4 py-3.5 shadow-sm">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl" style={{ background: `${c}14`, color: c }}>
              <Icon name={icon} size={20} />
            </span>
            <div className="min-w-0">
              <div className="truncate font-mono text-[22px] font-extrabold leading-none text-ink-100">{value}</div>
              <div className="mt-1 text-[11.5px] font-semibold leading-tight text-ink-400">{label}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_390px]">
        <div className="min-w-0 space-y-5">
          {/* ------------------------------------------------------- alerts */}
          <Card tour="my-alerts" icon="bell" title={L('Alerts — act on these', 'चेतावनियाँ — इन पर कार्रवाई करें')} count={brief.alerts.length}>
            {brief.alerts.length === 0 ? (
              <div className="flex items-center gap-3 rounded-xl bg-indiagreen-500/[0.07] px-4 py-4 text-[14px] font-semibold text-indiagreen-300">
                <Icon name="check" size={20} /> {L('No alerts in your area right now.', 'अभी आपके क्षेत्र में कोई चेतावनी नहीं।')}
              </div>
            ) : (
              <>
                <ul className="space-y-3">
                  {alerts.map((al) => (
                    <AlertItem key={al.id} al={al} lang={lang} />
                  ))}
                </ul>
                {brief.alerts.length > 5 && (
                  <button type="button" className="mt-3 w-full rounded-xl border border-dashed border-ink-700 py-2 text-[13px] font-bold text-chakra-500 hover:bg-ink-850" onClick={() => setShowAll((v) => !v)}>
                    {showAll ? L('Show fewer', 'कम दिखाएँ') : L(`Show all ${brief.alerts.length} alerts`, `सभी ${brief.alerts.length} चेतावनियाँ दिखाएँ`)}
                  </button>
                )}
              </>
            )}
          </Card>

          {/* ------------------------------------------------------- places */}
          <Card
            tour="my-places"
            icon="pin"
            title={user.role === 'district' ? L('Your place', 'आपका स्थान') : L('Places in your area', 'आपके क्षेत्र के स्थान')}
            count={brief.places.length}
            bodyClass="p-2"
          >
            <ul className="divide-y divide-ink-800">
              {brief.places.slice(0, user.role === 'central' ? 40 : 200).map((p) => {
                const wx = p.weather ? weatherInfo(p.weather.code, p.weather.is_day) : null;
                const c = tierColour(p.tier);
                return (
                  <li key={p.id}>
                    <a href={href(`/location/${p.id}`)} className="flex items-center gap-3 rounded-xl px-3 py-3 transition hover:bg-ink-850">
                      <span className="h-10 w-1.5 shrink-0 rounded-full" style={{ background: c }} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14.5px] font-bold text-ink-100">{lang === 'hi' && p.name_hi ? p.name_hi : p.name}</span>
                        <span className="mt-0.5 block truncate text-[12px] text-ink-500">
                          {user.role === 'central' ? `${stateName(p.state, lang)} · ` : p.district ? `${p.district} · ` : ''}
                          {L(p.reason_en ?? '', p.reason_hi ?? '')}
                        </span>
                      </span>
                      {wx && (
                        <span className="hidden shrink-0 items-center gap-1 rounded-lg bg-ink-850 px-2 py-1 text-[12px] text-ink-300 sm:flex" title={L(wx.en, wx.hi)}>
                          <span aria-hidden="true">{wx.icon}</span> {Math.round(p.weather.temp_c)}°
                        </span>
                      )}
                      <span className="flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1" style={{ background: `${c}14` }}>
                        <span className="font-mono text-[15px] font-extrabold" style={{ color: ink(p.tier) }}>{p.score}</span>
                        <span className="text-[11px]" style={{ color: ink(p.tier) }}>{directionGlyph(p.direction)}</span>
                      </span>
                    </a>
                  </li>
                );
              })}
            </ul>
            {user.role === 'central' && brief.places.length > 40 && (
              <p className="px-3 pb-2 pt-1 text-[12px] text-ink-500">{L(`Showing the 40 highest of ${brief.places.length}. Open the map for all.`, `${brief.places.length} में से 40 सर्वाधिक। सभी के लिए नक्शा खोलें।`)}</p>
            )}
          </Card>
        </div>

        <div className="space-y-5">
          {/* -------------------------------------------------------- brief */}
          <section className="overflow-hidden rounded-2xl border border-ink-700 bg-white shadow-sm" data-tour="my-brief">
            <div className="bg-chakra-500 px-4 py-3 text-white">
              <div className="flex items-center gap-2">
                <Icon name="note" size={16} />
                <h2 className="text-[14px] font-extrabold">{L("Today's brief", 'आज का सारांश')}</h2>
              </div>
              <div className="mt-0.5 text-[11.5px] text-white/70">{today} · {L('written automatically', 'स्वतः लिखित')}</div>
            </div>
            <ol className="space-y-3 p-4">
              {(brief.brief[lang] ?? brief.brief.en).map((line, i) => (
                <li key={line} className="flex gap-3 text-[13.5px] leading-snug text-ink-200">
                  <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-saffron-50 font-mono text-[10.5px] font-bold text-saffron-300">{i + 1}</span>
                  <span>{line}</span>
                </li>
              ))}
            </ol>
          </section>

          {/* -------------------------------------------------- coming next */}
          <Card tour="my-next" icon="clock" title={L('Coming next', 'आगे क्या')}>
            {coming.places.length === 0 && coming.waves.length === 0 ? (
              <div className="flex items-center gap-2 text-[13px] text-ink-400">
                <Icon name="check" size={16} /> {L('Nothing is expected to get worse in the next 3 days.', 'अगले 3 दिनों में स्थिति बिगड़ने की आशंका नहीं।')}
              </div>
            ) : (
              <ol className="relative space-y-4 border-l-2 border-ink-800 pl-5">
                {coming.places.map((p) => (
                  <li key={`p-${p.id}`} className="relative text-[13px]">
                    <span className="absolute -left-[27px] top-1 h-3 w-3 rounded-full ring-4 ring-white" style={{ background: tierColour(p.to) }} />
                    <div className="font-mono text-[11px] font-bold text-ink-500">{L(`within ${p.in_hours} h`, `${p.in_hours} घंटे में`)}</div>
                    <a href={href(`/location/${p.id}`)} className="font-bold text-ink-100 hover:underline">{lang === 'hi' && p.name_hi ? p.name_hi : p.name}</a>
                    <span className="text-ink-400"> {L('may reach', 'पहुँच सकता है')} </span>
                    <b style={{ color: ink(p.to) }}>{L(TIER_LABELS[p.to].en, TIER_LABELS[p.to].hi)}</b>
                  </li>
                ))}
                {coming.waves.map((w) => (
                  <li key={`w-${w.id}`} className="relative text-[13px]">
                    <span className="absolute -left-[27px] top-1 h-3 w-3 rounded-full bg-[#1B5FA8] ring-4 ring-white" />
                    <div className="font-mono text-[11px] font-bold text-ink-500">
                      ~{w.eta_h.p50} h ({w.eta_h.p10}–{w.eta_h.p90} h)
                    </div>
                    {L(`${w.river} flood wave reaches`, `${w.river} बाढ़ लहर पहुँचेगी`)}{' '}
                    <a href={href(`/location/${w.id}`)} className="font-bold text-ink-100 hover:underline">{lang === 'hi' && w.name_hi ? w.name_hi : w.name}</a>
                  </li>
                ))}
              </ol>
            )}
          </Card>

          {/* ------------------------------------------------------ changes */}
          <Card
            tour="my-changes"
            icon="swap"
            title={brief.changes.since ? L('Since you last looked', 'पिछली बार से बदलाव') : L('Since the last update', 'पिछले अद्यतन से बदलाव')}
            right={worseCount > 0 && <span className="rounded-full bg-risk-red/10 px-2 py-0.5 text-[11px] font-bold text-risk-red">▲ {worseCount}</span>}
          >
            {brief.changes.compared_run == null ? (
              <p className="text-[13px] text-ink-400">{L('Welcome — changes will show here after the next update.', 'स्वागत है — अगले अद्यतन के बाद यहाँ बदलाव दिखेंगे।')}</p>
            ) : brief.changes.items.length === 0 ? (
              <div className="flex items-center gap-2 text-[13px] text-ink-400">
                <Icon name="check" size={16} /> {L('Nothing has changed.', 'कोई बदलाव नहीं।')}
              </div>
            ) : (
              <ul className="space-y-2">
                {brief.changes.items.map((c) => (
                  <li key={c.id} className="flex items-center gap-2.5 rounded-lg bg-ink-850 px-3 py-2 text-[13px]">
                    <span className={`font-bold ${c.worse ? 'text-risk-red' : 'text-indiagreen-300'}`}>{c.worse ? '▲' : '▼'}</span>
                    <a href={href(`/location/${c.id}`)} className="min-w-0 flex-1 truncate font-bold text-ink-100 hover:underline">{lang === 'hi' && c.name_hi ? c.name_hi : c.name}</a>
                    <span className="shrink-0 text-[12px]">
                      <span style={{ color: ink(c.from) }}>{L(TIER_LABELS[c.from].en, TIER_LABELS[c.from].hi)}</span>
                      <span className="text-ink-500"> → </span>
                      <b style={{ color: ink(c.to) }}>{L(TIER_LABELS[c.to].en, TIER_LABELS[c.to].hi)}</b>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
