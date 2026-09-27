import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from './lib/api';
import { inScope, isAdmin, lastSeen, markSeen, roleName, scopeName, useSession } from './lib/auth';
import { canonicalState, tierColour } from './lib/format';
import { t } from './lib/i18n';
import { go, href, useRoute } from './lib/router';
import { AshokaChakra, Footer, Masthead } from './components/Chrome';
import Copilot from './components/Copilot';
import { StationModal } from './components/Official';
import SearchBox from './components/SearchBox';
import SystemDialog from './components/SystemDialog';
import Tour, { TOUR_SEEN_KEY } from './components/Tour';
import AboutPage from './pages/AboutPage';
import CitizenHome from './pages/CitizenHome';
import HotspotsPage from './pages/HotspotsPage';
import LocationPage from './pages/LocationPage';
import LoginPage from './pages/LoginPage';
import MyArea from './pages/MyArea';
import NotificationsPage from './pages/NotificationsPage';
import Overview from './pages/Overview';
import PlanPage from './pages/PlanPage';
import { OfficialPage, StateMonitor, TimeMachine } from './pages/Pages';
import ResourcesPage from './pages/ResourcesPage';
import RiversPage from './pages/RiversPage';
import ApiKeysPage from './pages/ApiKeysPage';

/**
 * Application shell: sign-in, shared data, chrome and routing.
 *
 * Officials (admins) sign in as Central, a State or a District and land on "My
 * area" - one plain-language screen for their area, built by the server and
 * refreshed automatically. The detailed tools live under "Advanced tools",
 * filtered to the user's area. New alerts pop up on their own wherever the user is.
 *
 * Citizens sign in for their home district and get a public-safety view: "My
 * locality", the street map, rivers and official alerts. Control-room pages are
 * not in their navigation, show an "officials only" notice if opened by URL, and
 * are refused by the server anyway.
 */

const POLL_MS = 60_000;

// Pages for officials only; the server refuses their endpoints for citizens.
const ADMIN_ROUTES = ['overview', 'state', 'states', 'timemachine', 'notifications', 'plan', 'resources', 'apikeys'];

const CITIZEN_NAV = [
  { route: 'hotspots', to: '/hotspots', en: 'Street map', hi: 'गली नक्शा' },
  { route: 'rivers', to: '/rivers', en: 'Rivers', hi: 'नदियाँ' },
  { route: 'alerts', to: '/alerts', en: 'Official alerts', hi: 'आधिकारिक चेतावनियाँ' },
  { route: 'about', to: '/about', en: 'About', hi: 'परिचय' },
];

const ADVANCED = [
  { route: 'overview', en: 'Risk map', hi: 'जोखिम नक्शा', icon: '◉', match: ['overview', 'state'] },
  { route: 'hotspots', to: '/hotspots', en: 'Street-level hotspots', hi: 'गली-स्तरीय हॉटस्पॉट', icon: '▦', match: ['hotspots'] },
  { route: 'rivers', to: '/rivers', en: 'Rivers', hi: 'नदियाँ', icon: '≋', match: ['rivers'] },
  { route: 'alerts', to: '/alerts', en: 'Official alerts', hi: 'आधिकारिक चेतावनियाँ', icon: '⛨', match: ['alerts'] },
  { route: 'states', to: '/states', en: 'State monitor', hi: 'राज्य निगरानी', icon: '▤', match: ['states'], central: true },
  { route: 'timemachine', to: '/time-machine', en: 'Time machine', hi: 'टाइम मशीन', icon: '⟲', match: ['timemachine'] },
  { route: 'about', to: '/about', en: 'About JalDrishti', hi: 'जलदृष्टि परिचय', icon: 'ⓘ', match: ['about'] },
];

function useStickyLang() {
  const [lang, setLang] = useState(() => {
    try {
      const saved = localStorage.getItem('jd.lang');
      if (saved === 'en' || saved === 'hi') return saved;
    } catch {
      /* storage blocked */
    }
    return 'en';
  });
  useEffect(() => {
    try {
      localStorage.setItem('jd.lang', lang);
    } catch {
      /* non-fatal */
    }
    document.documentElement.lang = lang;
  }, [lang]);
  return [lang, setLang];
}

function readSeen(user) {
  try {
    return new Set(JSON.parse(localStorage.getItem(`jd.seenAlerts.${user.username}`) || '[]'));
  } catch {
    return new Set();
  }
}
function writeSeen(user, ids) {
  try {
    localStorage.setItem(`jd.seenAlerts.${user.username}`, JSON.stringify([...ids].slice(-500)));
  } catch {
    /* non-fatal */
  }
}

/** Pop-ups for alerts that appeared since the user last saw them. */
function AlertToasts({ lang, toasts, onDismiss }) {
  if (!toasts.length) return null;
  const L = (en, hi) => (lang === 'hi' ? hi : en);
  return (
    <div className="pointer-events-none fixed right-3 top-[150px] z-[2500] flex w-[min(360px,calc(100vw-24px))] flex-col gap-2" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.key} className="pointer-events-auto rounded-xl border border-ink-700 border-l-[6px] bg-white p-3 shadow-2xl" style={{ borderLeftColor: tierColour(toast.level) }}>
          <div className="flex items-start justify-between gap-2">
            <div className="text-[11px] font-extrabold uppercase tracking-wider text-ink-500">🔔 {L('New alert', 'नई चेतावनी')}</div>
            <button type="button" onClick={() => onDismiss(toast.key)} className="text-[14px] leading-none text-ink-500 hover:text-chakra-500" aria-label={L('Dismiss', 'बंद करें')}>
              ✕
            </button>
          </div>
          <div className="mt-1 text-[14px] font-bold text-ink-100">{toast.title}</div>
          {toast.detail && <p className="mt-0.5 line-clamp-2 text-[12.5px] text-ink-300">{toast.detail}</p>}
          <a href={href('/')} onClick={() => onDismiss(toast.key)} className="mt-1.5 inline-block text-[12.5px] font-bold text-chakra-500 hover:underline">
            {L('See in My area →', 'मेरे क्षेत्र में देखें →')}
          </a>
        </div>
      ))}
    </div>
  );
}

export default function App() {
  const [lang, setLang] = useStickyLang();
  const route = useRoute();
  const session = useSession();
  const user = session.user;
  const admin = isAdmin(user);

  const [system, setSystem] = useState(null);
  const [country, setCountry] = useState(null);
  const [locations, setLocations] = useState([]);
  const [gauges, setGauges] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [status, setStatus] = useState('loading');
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [replayDate, setReplayDate] = useState(null);
  const [stationCode, setStationCode] = useState(null);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [systemOpen, setSystemOpen] = useState(false);
  const [tourOpen, setTourOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [brief, setBrief] = useState(null);
  const [briefError, setBriefError] = useState(null);
  const [toasts, setToasts] = useState([]);
  const pollRef = useRef(null);
  const sinceRef = useRef(null);
  const firstBriefRef = useRef(true);

  const loadCore = useCallback(
    async ({ quiet = false } = {}) => {
      if (!quiet) setStatus((s) => (s === 'ready' ? s : 'loading'));
      try {
        const [summary, locs] = await Promise.all([api.countrySummary(replayDate), api.locations(replayDate)]);
        setCountry(summary);
        setLocations(locs.locations);
        setStatus('ready');
        setError(null);
      } catch (err) {
        if (err instanceof ApiError && err.warming) setStatus('warming');
        else {
          setStatus('error');
          setError(err.message);
        }
      }
    },
    [replayDate],
  );

  useEffect(() => {
    if (!user) return;
    loadCore();
    api.system().then(setSystem).catch(() => {});
  }, [loadCore, user]);

  useEffect(() => {
    clearInterval(pollRef.current);
    if (replayDate || !user) return undefined;
    pollRef.current = setInterval(() => loadCore({ quiet: true }), status === 'warming' ? 5000 : POLL_MS);
    return () => clearInterval(pollRef.current);
  }, [loadCore, status, replayDate, user]);

  useEffect(() => {
    if (replayDate || !user) return;
    api.officialStations(false).then((d) => setGauges(d.stations)).catch(() => {});
    api.officialAlerts(true).then((d) => setAlerts(d.alerts)).catch(() => {});
  }, [replayDate, country?.meta?.run_id, user]);

  // ------------------------------------------------------------ area briefing
  // "Since you last looked" compares with the previous visit, captured once at
  // sign-in so it stays put for the whole session.
  useEffect(() => {
    if (!user) return;
    sinceRef.current = lastSeen(user);
    firstBriefRef.current = true;
    setBrief(null);
    setToasts([]);
  }, [user]);

  const loadBrief = useCallback(async () => {
    if (!user) return;
    try {
      const b = await api.brief(sinceRef.current);
      setBrief(b);
      setBriefError(null);
      markSeen(user);

      // Automatic alerts: pop up anything not seen before. On the first load of
      // a session, one summary pop-up rather than a burst.
      const seen = readSeen(user);
      const fresh = b.alerts.filter((al) => !seen.has(al.id));
      if (fresh.length) {
        const L = (en, hi) => (lang === 'hi' ? hi : en);
        const add =
          firstBriefRef.current && fresh.length > 1
            ? [
                {
                  key: `sum-${Date.now()}`,
                  level: fresh[0].level,
                  title: L(`${fresh.length} alerts need attention in ${scopeName(user, 'en')}`, `${scopeName(user, 'hi')} में ${fresh.length} चेतावनियों पर ध्यान दें`),
                  detail: L(fresh[0].title_en, fresh[0].title_hi),
                },
              ]
            : fresh.slice(0, 3).map((al) => ({ key: `${al.id}-${Date.now()}`, level: al.level, title: L(al.title_en, al.title_hi), detail: L(al.detail_en, al.detail_hi) }));
        setToasts((prev) => [...add, ...prev].slice(0, 4));
        fresh.forEach((al) => seen.add(al.id));
        writeSeen(user, seen);
      }
      firstBriefRef.current = false;
    } catch (err) {
      if (err.status === 401) session.logout();
      else setBriefError(err.message);
    }
  }, [user, lang, session.logout]);

  useEffect(() => {
    if (!user || status !== 'ready') return undefined;
    loadBrief();
    const id = setInterval(loadBrief, POLL_MS);
    return () => clearInterval(id);
    // Re-brief when a new scoring run lands, not on every language switch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, status, country?.meta?.run_id]);

  useEffect(() => {
    if (!toasts.length) return undefined;
    const id = setTimeout(() => setToasts((prev) => prev.slice(0, -1)), 15000);
    return () => clearTimeout(id);
  }, [toasts]);

  useEffect(() => setAdvancedOpen(false), [route.path]);

  // --------------------------------------------------------- scope filtering
  const scoped = useMemo(() => {
    if (!user || user.role === 'central') return { locations, country, alerts, gauges };
    const st = canonicalState(user.state);
    return {
      locations: locations.filter((l) => inScope(user, l)),
      country: country && { ...country, states: (country.states ?? []).filter((s) => canonicalState(s.state) === st) },
      alerts: alerts.filter((a) => (a.area || '').toLowerCase().includes(user.state.toLowerCase())),
      gauges: gauges.filter((g) => canonicalState(g.state) === st),
    };
  }, [user, locations, country, alerts, gauges]);
  const scopedById = useMemo(() => Object.fromEntries(scoped.locations.map((l) => [l.id, l])), [scoped.locations]);

  const onRefresh = useCallback(async () => {
    if (replayDate) {
      setReplayDate(null);
      return;
    }
    setRefreshing(true);
    try {
      await api.refresh();
      await loadCore({ quiet: true });
      await loadBrief();
    } catch (err) {
      setError(err.message);
    } finally {
      setRefreshing(false);
    }
  }, [loadCore, loadBrief, replayDate]);

  const mapPath = !user || user.role === 'central' ? '/map' : `/state/${canonicalState(user.state)}`;
  const startReplay = useCallback(
    async (date) => {
      await api.countrySummary(date);
      setReplayDate(date);
      go(mapPath);
    },
    [mapPath],
  );

  const openLocation = useCallback((id) => go(`/location/${id}`), []);

  // Offer the tutorial once, on the first signed-in visit that has data to show.
  // The tutorial walks through the control-room tools, so it is for officials.
  useEffect(() => {
    if (status !== 'ready' || !user || !admin) return;
    try {
      if (!localStorage.getItem(TOUR_SEEN_KEY)) setTourOpen(true);
    } catch {
      /* storage blocked: never auto-open */
    }
  }, [status, user, admin]);

  const closeTour = useCallback(() => {
    setTourOpen(false);
    try {
      localStorage.setItem(TOUR_SEEN_KEY, '1');
    } catch {
      /* non-fatal */
    }
  }, []);
  const hi = lang === 'hi' ? 'font-devanagari' : '';
  const L = (en, hiText) => (lang === 'hi' ? hiText : en);

  if (!user) {
    return (
      <LoginPage
        lang={lang}
        onLangChange={setLang}
        onLogin={async (username, password) => {
          await session.login(username, password);
          go('/');
        }}
        onDemo={async (role, state, district) => {
          await session.demo(role, state, district);
          go('/');
        }}
        onRegister={async (details) => {
          await session.register(details);
          go('/');
        }}
      />
    );
  }

  const chromeProps = {
    lang,
    onLangChange: setLang,
    refreshing: refreshing || country?.meta?.refreshing,
    onRefresh,
    onOpenSystem: () => setSystemOpen(true),
    onOpenCopilot: () => setCopilotOpen(true),
    onOpenTour: admin ? () => setTourOpen(true) : undefined,
    user: { ...user, area: scopeName(user, lang), roleLabel: roleName(user, lang) },
    onLogout: session.logout,
  };

  if (status === 'error' || status === 'loading' || status === 'warming') {
    return (
      <div className="flex h-full flex-col">
        <Masthead {...chromeProps} meta={null} refreshing={status !== 'error'} onRefresh={() => loadCore()} />
        <main className="grid flex-1 place-items-center p-6">
          {status === 'error' ? (
            <div className="panel max-w-md p-5 text-center">
              <h2 className={`mb-2 text-sm font-bold text-risk-orange ${hi}`}>{t(lang, 'errorTitle')}</h2>
              <p className="mb-4 text-[12px] text-ink-300">{error}</p>
              <code className="block rounded bg-ink-850 p-3 text-left font-mono text-[11px] text-chakra-500">
                cd backend
                <br />
                python -m uvicorn app.main:app --port 8000
              </code>
              <button type="button" className="btn btn-primary mt-4 w-full" onClick={() => loadCore()}>
                {t(lang, 'retry')}
              </button>
            </div>
          ) : (
            <div className="max-w-sm text-center">
              <span className="mx-auto mb-4 block w-fit text-chakra-500">
                <AshokaChakra size={52} spinning />
              </span>
              <p className={`text-[13px] text-ink-300 ${hi}`}>{status === 'warming' ? t(lang, 'warming') : t(lang, 'loading')}</p>
            </div>
          )}
        </main>
      </div>
    );
  }

  const worstId = brief?.status?.worst?.id ?? scoped.country?.worst?.find((w) => scopedById[w.id])?.id ?? scoped.locations[0]?.id;
  const cityId = user.role === 'district' || user.role === 'citizen' ? scoped.locations[0]?.id : scopedById.mumbai ? 'mumbai' : worstId;

  let page;
  switch (!admin && ADMIN_ROUTES.includes(route.name) ? 'officials-only' : route.name) {
    case 'officials-only':
      page = (
        <div className="grid flex-1 place-items-center p-10 text-center">
          <div>
            <p className="text-lg font-bold text-chakra-500">{L('This page is for officials', 'यह पृष्ठ अधिकारियों के लिए है')}</p>
            <p className="mt-1 text-[13px] text-ink-400">{L('Sign in with a control-room account to use it.', 'इसके लिए नियंत्रण कक्ष खाते से प्रवेश करें।')}</p>
            <a href={href('/')} className="mt-2 inline-block text-saffron-300 hover:underline">← {L('My locality', 'मेरा इलाका')}</a>
          </div>
        </div>
      );
      break;
    case 'home':
      page = !admin ? (
        <CitizenHome lang={lang} user={user} brief={brief} error={briefError} onRetry={loadBrief} onOpenCopilot={() => setCopilotOpen(true)} />
      ) : (
        <MyArea
          lang={lang}
          user={user}
          brief={brief}
          error={briefError}
          onRetry={loadBrief}
          onOpenCopilot={() => setCopilotOpen(true)}
        />
      );
      break;
    case 'overview':
    case 'state':
      page = (
        <Overview
          lang={lang}
          country={scoped.country}
          locations={scoped.locations}
          selectedState={route.params.state ?? (user.role === 'central' ? null : canonicalState(user.state))}
          replayDate={replayDate}
          gauges={scoped.gauges}
          alerts={scoped.alerts}
          onOpenStation={setStationCode}
        />
      );
      break;
    case 'location':
      page = <LocationPage lang={lang} id={route.params.id} replayDate={replayDate} onOpenStation={setStationCode} locationsById={scopedById} admin={admin} />;
      break;
    case 'hotspots':
      page = <HotspotsPage lang={lang} id={route.params.id ?? cityId} locations={scoped.locations} />;
      break;
    case 'rivers':
      page = <RiversPage lang={lang} river={route.params.river} onOpenStation={setStationCode} />;
      break;
    case 'alerts':
      page = <OfficialPage lang={lang} onOpenStation={setStationCode} />;
      break;
    case 'states':
      page = (
        <StateMonitor
          lang={lang}
          country={scoped.country}
          locations={scoped.locations}
          alerts={scoped.alerts}
          replayDate={replayDate}
          onViewState={(name) => go(`/state/${name}`)}
          onOpenLocation={openLocation}
          onOpenStation={setStationCode}
        />
      );
      break;
    case 'timemachine':
      page = <TimeMachine lang={lang} replayDate={replayDate} onReplay={startReplay} onExit={() => setReplayDate(null)} />;
      break;
    case 'about':
      page = <AboutPage lang={lang} />;
      break;
    case 'notifications':
      page = <NotificationsPage lang={lang} user={user} />;
      break;
    case 'plan':
      page = <PlanPage lang={lang} />;
      break;
    case 'resources':
      page = <ResourcesPage lang={lang} />;
      break;
    case 'apikeys':
      page = <ApiKeysPage lang={lang} />;
      break;
    default:
      page = (
        <div className="grid flex-1 place-items-center p-10 text-center">
          <div>
            <p className="text-lg font-bold text-chakra-500">Page not found</p>
            <a href={href('/')} className="text-saffron-300 hover:underline">← {L('My area', 'मेरा क्षेत्र')}</a>
          </div>
        </div>
      );
  }

  // The map dashboard is fixed-height; every other page scrolls as a document.
  const scrollingPage = !['overview', 'state'].includes(route.name);
  const advanced = ADVANCED.filter((n) => !n.central || user.role === 'central');
  const activeAdvanced = advanced.find((n) => n.match.includes(route.name));

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <Masthead {...chromeProps} meta={country?.meta}>
        <SearchBox lang={lang} locations={scoped.locations} onSelect={openLocation} />
      </Masthead>

      <nav className="relative z-30 shrink-0 border-b border-ink-700 bg-white" aria-label="Main" data-tour="nav">
        <div className="flex items-stretch gap-1 px-3">
          <a
            href={href('/')}
            aria-current={route.name === 'home' ? 'page' : undefined}
            data-tour="nav-home"
            className={`flex shrink-0 items-center gap-1.5 border-b-[3px] px-3 py-2.5 text-[13px] font-extrabold ${
              route.name === 'home' ? 'border-saffron-500 text-chakra-500' : 'border-transparent text-ink-400 hover:text-chakra-500'
            } ${hi}`}
          >
            <span aria-hidden="true" className="text-saffron-500">⌂</span>
            {admin ? L('My area', 'मेरा क्षेत्र') : L('My locality', 'मेरा इलाका')}
            {brief?.alerts?.length > 0 && (
              <span className="rounded-full px-1.5 text-[10.5px] font-extrabold text-white" style={{ background: tierColour(brief.alerts[0].level) }}>
                {brief.alerts.length}
              </span>
            )}
          </a>

          {!admin &&
            CITIZEN_NAV.map((n) => (
              <a
                key={n.route}
                href={href(n.to)}
                aria-current={route.name === n.route ? 'page' : undefined}
                className={`flex shrink-0 items-center border-b-[3px] px-3 py-2.5 text-[13px] font-bold ${
                  route.name === n.route ? 'border-saffron-500 text-chakra-500' : 'border-transparent text-ink-400 hover:text-chakra-500'
                } ${hi}`}
              >
                {L(n.en, n.hi)}
              </a>
            ))}

          {admin && (
            <a
              href={href('/notifications')}
              aria-current={route.name === 'notifications' ? 'page' : undefined}
              data-tour="nav-notify"
              className={`flex shrink-0 items-center gap-1.5 border-b-[3px] px-3 py-2.5 text-[13px] font-bold ${
                route.name === 'notifications' ? 'border-saffron-500 text-chakra-500' : 'border-transparent text-ink-400 hover:text-chakra-500'
              } ${hi}`}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4l2-2zM10 20a2 2 0 0 0 4 0" />
              </svg>
              {L('Notifications', 'सूचनाएँ')}
            </a>
          )}

          {admin && (
            <a
              href={href('/plan')}
              aria-current={route.name === 'plan' || route.name === 'resources' ? 'page' : undefined}
              className={`flex shrink-0 items-center gap-1.5 border-b-[3px] px-3 py-2.5 text-[13px] font-bold ${
                route.name === 'plan' || route.name === 'resources' ? 'border-saffron-500 text-chakra-500' : 'border-transparent text-ink-400 hover:text-chakra-500'
              } ${hi}`}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M4 6l5-2 6 2 5-2v14l-5 2-6-2-5 2zM9 4v14M15 6v14" />
              </svg>
              {L('Response plan', 'प्रतिक्रिया योजना')}
            </a>
          )}

          {admin && (
            <a
              href={href('/api-keys')}
              aria-current={route.name === 'apikeys' ? 'page' : undefined}
              className={`flex shrink-0 items-center gap-1.5 border-b-[3px] px-3 py-2.5 text-[13px] font-bold ${
                route.name === 'apikeys' ? 'border-saffron-500 text-chakra-500' : 'border-transparent text-ink-400 hover:text-chakra-500'
              } ${hi}`}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
              </svg>
              {L('API Keys', 'API कुंजियाँ')}
            </a>
          )}

          {admin && (
            <div className="relative" data-tour="nav-advanced">
              <button
                type="button"
                onClick={() => setAdvancedOpen((v) => !v)}
                aria-expanded={advancedOpen}
                className={`flex h-full items-center gap-1.5 border-b-[3px] px-3 py-2.5 text-[13px] font-bold ${
                  activeAdvanced ? 'border-saffron-500 text-chakra-500' : 'border-transparent text-ink-400 hover:text-chakra-500'
                } ${hi}`}
              >
                <span aria-hidden="true" className="text-saffron-500">⚙</span>
                {L('Advanced tools', 'उन्नत उपकरण')}
                {activeAdvanced && <span className="text-ink-500">· {L(activeAdvanced.en, activeAdvanced.hi)}</span>}
                <span aria-hidden="true" className="text-[10px]">▾</span>
              </button>
              {advancedOpen && (
                <div className="absolute left-0 top-full z-40 mt-1 w-64 rounded-xl border border-ink-700 bg-white p-1.5 shadow-2xl">
                  {advanced.map((n) => (
                    <a
                      key={n.route}
                      href={href(n.to ?? mapPath)}
                      className={`flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] font-semibold ${
                        n.match.includes(route.name) ? 'bg-saffron-50 text-chakra-500' : 'text-ink-200 hover:bg-ink-850'
                      } ${hi}`}
                    >
                      <span aria-hidden="true" className="w-4 text-saffron-500">{n.icon}</span>
                      {L(n.en, n.hi)}
                    </a>
                  ))}
                </div>
              )}
            </div>
          )}

          {route.name !== 'home' && (
            <a href={href('/')} className={`ml-auto hidden items-center text-[12px] font-bold text-chakra-500 hover:underline sm:flex ${hi}`}>
              ← {admin ? L('Back to My area', 'मेरे क्षेत्र पर लौटें') : L('Back to My locality', 'मेरे इलाके पर लौटें')}
            </a>
          )}
        </div>
      </nav>

      {replayDate && (
        <div className="relative z-10 flex shrink-0 flex-wrap items-center gap-3 bg-chakra-500 px-4 py-2 text-white">
          <span className="rounded bg-saffron-500 px-2 py-0.5 text-[10.5px] font-extrabold uppercase tracking-wider">
            {L('Historical replay', 'ऐतिहासिक पुनरावृत्ति')}
          </span>
          <span className="font-mono text-[13px] font-bold">
            {new Date(replayDate).toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'long', year: 'numeric' })}
          </span>
          <button type="button" onClick={() => setReplayDate(null)} className="ml-auto rounded-md bg-white px-3 py-1 text-[12px] font-bold text-chakra-500">
            {L('Back to live', 'लाइव पर लौटें')}
          </button>
        </div>
      )}

      <div className="shrink-0 border-b border-ink-700 bg-white px-3 py-2 md:hidden">
        <SearchBox lang={lang} locations={scoped.locations} onSelect={openLocation} />
      </div>

      {scrollingPage ? <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">{page}</div> : page}

      <Footer lang={lang} system={system} meta={country?.meta} />

      <AlertToasts lang={lang} toasts={toasts} onDismiss={(key) => setToasts((prev) => prev.filter((x) => x.key !== key))} />
      <StationModal lang={lang} code={stationCode} onClose={() => setStationCode(null)} />
      <Copilot lang={lang} open={copilotOpen} onClose={() => setCopilotOpen(false)} onSelectLocation={openLocation} locations={scoped.locations} />
      <SystemDialog lang={lang} system={system} open={systemOpen} onClose={() => setSystemOpen(false)} />
      <Tour lang={lang} open={tourOpen} onClose={closeTour} sampleLocation={worstId} sampleCity={cityId} mapPath={mapPath} role={user.role} />
    </div>
  );
}
