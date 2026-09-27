import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { AshokaChakra, LangToggle, TricolourRule } from '../components/Chrome';

/**
 * Landing and sign-in.
 *
 * Two doors. Officials (admins) sign in as Central (all India), a State or a
 * District control room. Citizens sign in - or create an account - with an email
 * or mobile number and a home district, and get the public-safety view. Quick
 * demo enters any role without a password, so a judge can compare views in a click.
 */

const ROLE_STYLE = {
  central: { accent: '#0B2A5B', tint: 'rgba(11,42,91,0.06)' },
  state: { accent: '#E4701E', tint: 'rgba(228,112,30,0.07)' },
  district: { accent: '#0B8A3D', tint: 'rgba(11,138,61,0.07)' },
};

function RoleIcon({ role }) {
  const common = { width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' };
  if (role === 'central')
    return (
      <svg {...common} aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
      </svg>
    );
  if (role === 'state')
    return (
      <svg {...common} aria-hidden="true">
        <path d="M4 6l5-2 6 2 5-2v14l-5 2-6-2-5 2z" />
        <path d="M9 4v14M15 6v14" />
      </svg>
    );
  return (
    <svg {...common} aria-hidden="true">
      <path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z" />
      <circle cx="12" cy="9.5" r="2.5" />
    </svg>
  );
}

export default function LoginPage({ lang, onLangChange, onLogin, onDemo, onRegister }) {
  const [options, setOptions] = useState(null);
  const [audience, setAudience] = useState('official');
  const [tab, setTab] = useState('demo');
  const [citizenTab, setCitizenTab] = useState('signin');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [contact, setContact] = useState('');
  const [state, setState] = useState('');
  const [district, setDistrict] = useState('');
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const L = (en, hi) => (lang === 'hi' ? hi : en);
  const hiFont = lang === 'hi' ? 'font-devanagari' : '';

  useEffect(() => {
    api
      .authOptions()
      .then((o) => {
        setOptions(o);
        if (!o.demo) setTab('password');
        const bihar = o.states.find((s) => s.name === 'Bihar') ?? o.states[0];
        setState(bihar?.name ?? '');
        setDistrict(bihar?.districts[0] ?? '');
      })
      .catch((e) => setError(e.message));
  }, []);

  const districts = options?.states.find((s) => s.name === state)?.districts ?? [];
  const nStates = options?.states.length ?? 36;
  const nDistricts = options?.states.reduce((n, s) => n + s.districts.length, 0) ?? 111;

  const run = async (key, fn) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const select = 'w-full rounded-lg border border-ink-700 bg-white px-3 py-2.5 text-[13.5px] font-semibold text-ink-100 focus:border-chakra-500 focus:outline-none focus:ring-2 focus:ring-chakra-500/15';
  const input = 'w-full rounded-lg border border-ink-700 px-3 py-2.5 text-[14px] focus:border-chakra-500 focus:outline-none focus:ring-2 focus:ring-chakra-500/15';
  const label = 'mb-1 block text-[12.5px] font-bold text-ink-300';
  const submit = 'flex w-full items-center justify-center gap-2 rounded-xl py-3 text-[14.5px] font-bold text-white shadow-sm transition hover:brightness-110 disabled:opacity-50';
  const segmented = (items, value, onChange) => (
    <div className="inline-flex rounded-xl border border-ink-700 bg-ink-850 p-1">
      {items.map(([k, text]) => (
        <button
          key={k}
          type="button"
          onClick={() => {
            onChange(k);
            setError(null);
          }}
          aria-pressed={value === k}
          className={`whitespace-nowrap rounded-lg px-5 py-2 text-[13.5px] font-bold transition ${value === k ? 'bg-chakra-500 text-white shadow' : 'text-ink-400 hover:text-chakra-500'}`}
        >
          {text}
        </button>
      ))}
    </div>
  );

  const districtSelect = (
    <select value={district} onChange={(e) => setDistrict(e.target.value)} className={select} aria-label={L('District', 'ज़िला')}>
      {districts.map((d) => (
        <option key={d} value={d}>{d}</option>
      ))}
    </select>
  );

  const stateSelect = (
    <select
      value={state}
      onChange={(e) => {
        setState(e.target.value);
        setDistrict(options.states.find((s) => s.name === e.target.value)?.districts[0] ?? '');
      }}
      className={select}
      aria-label={L('State', 'राज्य')}
    >
      {options?.states.map((s) => (
        <option key={s.name} value={s.name}>{s.name}</option>
      ))}
    </select>
  );

  const roleCard = ({ role, title, sub, body }) => {
    const st = ROLE_STYLE[role];
    return (
      <div
        key={role}
        className="group flex flex-col rounded-2xl border border-ink-700 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg"
        style={{ borderTop: `4px solid ${st.accent}` }}
      >
        <div className="mb-3 flex items-center gap-3">
          <span className="grid h-11 w-11 place-items-center rounded-xl" style={{ background: st.tint, color: st.accent }}>
            <RoleIcon role={role} />
          </span>
          <div className={hiFont}>
            <div className="text-[16px] font-extrabold text-chakra-500">{title}</div>
            <div className="text-[11.5px] font-semibold uppercase tracking-wider text-ink-500">{sub}</div>
          </div>
        </div>
        <div className="flex-1 space-y-2">{body}</div>
        <button
          type="button"
          disabled={!!busy}
          onClick={() => run(role, () => onDemo(role, role === 'central' ? null : state, role === 'district' ? district : null))}
          className={`mt-4 flex w-full items-center justify-center gap-2 rounded-xl py-2.5 text-[14px] font-bold text-white shadow-sm transition hover:brightness-110 disabled:opacity-60 ${hiFont}`}
          style={{ background: st.accent }}
        >
          {busy === role ? L('Opening…', 'खुल रहा है…') : L('Enter dashboard', 'डैशबोर्ड खोलें')}
          <span aria-hidden="true">→</span>
        </button>
      </div>
    );
  };

  const homeDistrict = (
    <div>
      <span className={label}>{L('Home district', 'गृह ज़िला')}</span>
      <div className="grid grid-cols-2 gap-2">
        {stateSelect}
        {districtSelect}
      </div>
    </div>
  );

  const citizenPanel =
    citizenTab === 'demo' ? (
      <div className="mx-auto max-w-md space-y-4">
        {homeDistrict}
        <button type="button" disabled={!!busy} onClick={() => run('citizen', () => onDemo('citizen', state, district))} className={`${submit} bg-indiagreen-500`}>
          {busy ? L('Opening…', 'खुल रहा है…') : L('Enter as a resident', 'निवासी के रूप में प्रवेश')} <span aria-hidden="true">→</span>
        </button>
      </div>
    ) : citizenTab === 'register' ? (
      <form
        className="mx-auto max-w-md space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          run('register', () => onRegister({ name, contact, password, state, district }));
        }}
      >
        <div>
          <label className={label} htmlFor="jd-name">{L('Your name', 'आपका नाम')}</label>
          <input id="jd-name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" className={input} />
        </div>
        <div>
          <label className={label} htmlFor="jd-contact">{L('Email or mobile number', 'ईमेल या मोबाइल नंबर')}</label>
          <input id="jd-contact" value={contact} onChange={(e) => setContact(e.target.value)} autoComplete="username" className={input} placeholder="98xxxxxxxx · name@example.com" />
        </div>
        <div>
          <label className={label} htmlFor="jd-newpass">{L('Password (8+ characters)', 'पासवर्ड (8+ अक्षर)')}</label>
          <input id="jd-newpass" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" className={input} />
        </div>
        {homeDistrict}
        <button type="submit" disabled={!!busy || !name || !contact || password.length < 8} className={`${submit} bg-indiagreen-500`}>
          {busy ? L('Creating…', 'बन रहा है…') : L('Create account', 'खाता बनाएँ')}
        </button>
      </form>
    ) : (
      <form
        className="mx-auto max-w-md space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          run('signin', () => onLogin(contact, password));
        }}
      >
        <div>
          <label className={label} htmlFor="jd-cid">{L('Email or mobile number', 'ईमेल या मोबाइल नंबर')}</label>
          <input id="jd-cid" value={contact} onChange={(e) => setContact(e.target.value)} autoComplete="username" className={input} />
        </div>
        <div>
          <label className={label} htmlFor="jd-cpass">{L('Password', 'पासवर्ड')}</label>
          <input id="jd-cpass" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" className={input} />
        </div>
        <button type="submit" disabled={!!busy || !contact || !password} className={`${submit} bg-chakra-500`}>
          {busy ? L('Signing in…', 'प्रवेश हो रहा है…') : L('Sign in', 'प्रवेश करें')}
        </button>
        <p className="text-center text-[12.5px] text-ink-400">
          {L('New here?', 'नए हैं?')}{' '}
          <button type="button" className="font-bold text-chakra-500 hover:underline" onClick={() => setCitizenTab('register')}>
            {L('Create an account', 'खाता बनाएँ')}
          </button>
        </p>
      </form>
    );

  return (
    <div className={`flex min-h-full flex-col bg-ink-850 ${hiFont}`}>
      {/* ------------------------------------------------------- header */}
      <header>
        <div className="bg-chakra-500 text-white">
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-1.5">
            <span className="truncate text-[11px] text-white/90">
              {L('Flood forecasting research prototype · For official warnings see IMD / CWC', 'बाढ़ पूर्वानुमान अनुसंधान प्रोटोटाइप · आधिकारिक चेतावनी हेतु IMD / CWC देखें')}
            </span>
            <LangToggle lang={lang} onChange={onLangChange} tone="dark" />
          </div>
        </div>
        <TricolourRule />
      </header>

      <main id="main-content" className="flex-1">
        {/* --------------------------------------------------------- hero */}
        <section className="relative overflow-hidden bg-gradient-to-b from-white via-white to-ink-850">
          <svg className="pointer-events-none absolute inset-x-0 bottom-0 h-40 w-full text-chakra-500/[0.06]" viewBox="0 0 1440 160" preserveAspectRatio="none" aria-hidden="true">
            <path fill="currentColor" d="M0 96c120-32 240-32 360 0s240 32 360 0 240-32 360 0 240 32 360 0v64H0z" />
            <path fill="currentColor" d="M0 124c120-24 240-24 360 0s240 24 360 0 240-24 360 0 240 24 360 0v36H0z" />
          </svg>
          <div className="relative mx-auto flex max-w-4xl flex-col items-center px-4 pb-16 pt-12 text-center">
            <div className="grid h-24 w-24 place-items-center rounded-full border-[3px] border-saffron-500 bg-white text-chakra-500 shadow-lg">
              <AshokaChakra size={58} />
            </div>
            <div className="mt-5 flex flex-wrap items-baseline justify-center gap-x-3">
              <span className="font-devanagari text-[40px] font-bold leading-tight text-saffron-500 sm:text-[48px]">जलदृष्टि</span>
              <h1 className="text-[40px] font-extrabold leading-tight tracking-tight text-chakra-500 sm:text-[48px]">JalDrishti</h1>
            </div>
            <p className="mt-2 text-[16px] font-semibold text-ink-200 sm:text-[18px]">
              {L('Hyperlocal rainfall early warning & inundation prediction for India', 'भारत हेतु अति-स्थानीय वर्षा पूर्व चेतावनी एवं जलभराव पूर्वानुमान')}
            </p>
            <p className="mt-1 max-w-2xl text-[14px] text-ink-400">
              {L('Sign in to see what matters to your area — all of India, your state, or your district.', 'अपने क्षेत्र की जानकारी हेतु प्रवेश करें — पूरा भारत, आपका राज्य या आपका ज़िला।')}
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-2.5">
              {[
                [String(options?.places ?? nDistricts), L('places monitored', 'निगरानी स्थान')],
                [String(nStates), L('states & UTs', 'राज्य व केंद्र शासित प्रदेश')],
                ['1,000+', L('CWC river gauges', 'CWC नदी गेज')],
                ['15 min', L('river gauge checks', 'नदी गेज जाँच')],
              ].map(([v, k]) => (
                <div key={k} className="flex items-baseline gap-1.5 rounded-full border border-ink-700 bg-white px-4 py-1.5 shadow-sm">
                  <span className="font-mono text-[15px] font-extrabold text-chakra-500">{v}</span>
                  <span className="text-[12px] font-medium text-ink-400">{k}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ------------------------------------------------------ sign in */}
        <section className="relative mx-auto -mt-8 max-w-6xl px-4 pb-12">
          <div className="rounded-3xl border border-ink-700 bg-white/95 p-5 shadow-xl backdrop-blur sm:p-7">
            <div className="flex flex-col items-center gap-2 text-center">
              <h2 className="text-[20px] font-extrabold text-chakra-500">{L('Choose how to enter', 'प्रवेश का तरीका चुनें')}</h2>
              <div className="mt-1 grid w-full max-w-xl grid-cols-2 gap-3">
                {[
                  ['citizen', L('Citizen', 'नागरिक'), L('Risk, safety steps and roads to avoid in your district', 'आपके ज़िले का जोखिम, सुरक्षा उपाय व बचने वाली सड़कें')],
                  ['official', L('Official (admin)', 'अधिकारी (एडमिन)'), L('Control room for central, state and district teams', 'केंद्र, राज्य व ज़िला टीमों का नियंत्रण कक्ष')],
                ].map(([k, title, sub]) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => {
                      setAudience(k);
                      setError(null);
                    }}
                    aria-pressed={audience === k}
                    className={`rounded-xl border-2 px-4 py-3 text-left transition ${audience === k ? 'border-chakra-500 bg-chakra-500/[0.05]' : 'border-ink-700 hover:border-chakra-500/50'}`}
                  >
                    <div className="text-[15px] font-extrabold text-chakra-500">{title}</div>
                    <div className="mt-0.5 text-[12px] leading-snug text-ink-400">{sub}</div>
                  </button>
                ))}
              </div>
              <div className="mt-2">
                {audience === 'official'
                  ? segmented(
                      [...(options?.demo !== false ? [['demo', L('Quick demo', 'त्वरित डेमो')]] : []), ['password', L('Sign in with account', 'खाते से प्रवेश')]],
                      tab,
                      setTab,
                    )
                  : segmented(
                      [
                        ['signin', L('Sign in', 'प्रवेश करें')],
                        ['register', L('Create account', 'खाता बनाएँ')],
                        ...(options?.demo !== false ? [['demo', L('Quick demo', 'त्वरित डेमो')]] : []),
                      ],
                      citizenTab,
                      setCitizenTab,
                    )}
              </div>
              <p className="text-[12.5px] text-ink-500">
                {audience === 'citizen'
                  ? citizenTab === 'register'
                    ? L('Free. Pick your home district to see its flood risk.', 'निःशुल्क। अपने ज़िले का बाढ़ जोखिम देखने हेतु गृह ज़िला चुनें।')
                    : citizenTab === 'demo'
                      ? L('No password needed — pick a district to see the resident view.', 'पासवर्ड की ज़रूरत नहीं — निवासी दृश्य हेतु ज़िला चुनें।')
                      : L('Use the email or mobile number you registered with.', 'पंजीकृत ईमेल या मोबाइल नंबर का उपयोग करें।')
                  : tab === 'demo'
                    ? L('No password needed — pick a role and an area to try it.', 'पासवर्ड की ज़रूरत नहीं — कोई भूमिका व क्षेत्र चुनें।')
                    : L('Use the account issued for your control room.', 'अपने नियंत्रण कक्ष के खाते का उपयोग करें।')}
              </p>
            </div>

            {error && (
              <p className="mx-auto mt-4 max-w-xl rounded-lg border border-risk-red/40 bg-risk-red/5 px-3 py-2 text-center text-[13px] text-risk-red">{error}</p>
            )}

            <div className="mt-6">
              {!options ? (
                <p className="py-10 text-center text-[13px] text-ink-400">{L('Loading…', 'लोड हो रहा है…')}</p>
              ) : audience === 'citizen' ? (
                citizenPanel
              ) : tab === 'demo' ? (
                <div className="grid gap-4 md:grid-cols-3">
                  {roleCard({
                    role: 'central',
                    title: L('Central', 'केंद्र'),
                    sub: L('NDMA · all India', 'NDMA · पूरा भारत'),
                    body: (
                      <>
                        <p className="text-[13px] leading-snug text-ink-300">
                          {L('National control room: every state, river and alert in one view.', 'राष्ट्रीय नियंत्रण कक्ष: हर राज्य, नदी और चेतावनी एक दृश्य में।')}
                        </p>
                        <div className="rounded-lg bg-ink-850 px-3 py-2.5 text-[13px] font-semibold text-ink-200">
                          {L(`All ${nStates} states & UTs`, `सभी ${nStates} राज्य व केंद्र शासित प्रदेश`)}
                        </div>
                      </>
                    ),
                  })}
                  {roleCard({
                    role: 'state',
                    title: L('State', 'राज्य'),
                    sub: L('SDMA · one state', 'SDMA · एक राज्य'),
                    body: (
                      <>
                        <p className="text-[13px] leading-snug text-ink-300">
                          {L('State Disaster Management Authority: your districts, rivers and gauges.', 'राज्य आपदा प्रबंधन प्राधिकरण: आपके ज़िले, नदियाँ और गेज।')}
                        </p>
                        {stateSelect}
                      </>
                    ),
                  })}
                  {roleCard({
                    role: 'district',
                    title: L('District', 'ज़िला'),
                    sub: L('DEOC · one district', 'DEOC · एक ज़िला'),
                    body: (
                      <>
                        <p className="text-[13px] leading-snug text-ink-300">
                          {L('District emergency operations centre: your town down to street level.', 'ज़िला आपात संचालन केंद्र: आपका शहर, गली-स्तर तक।')}
                        </p>
                        <div className="grid grid-cols-2 gap-2">
                          {stateSelect}
                          {districtSelect}
                        </div>
                      </>
                    ),
                  })}
                </div>
              ) : (
                <form
                  className="mx-auto max-w-md"
                  onSubmit={(e) => {
                    e.preventDefault();
                    run('password', () => onLogin(username, password));
                  }}
                >
                  <label className="mb-1 block text-[12.5px] font-bold text-ink-300" htmlFor="jd-user">
                    {L('Username', 'उपयोगकर्ता नाम')}
                  </label>
                  <input
                    id="jd-user"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    autoComplete="username"
                    className="mb-4 w-full rounded-lg border border-ink-700 px-3 py-2.5 text-[14px] focus:border-chakra-500 focus:outline-none focus:ring-2 focus:ring-chakra-500/15"
                    placeholder="central · bihar · bihar.patna"
                  />
                  <label className="mb-1 block text-[12.5px] font-bold text-ink-300" htmlFor="jd-pass">
                    {L('Password', 'पासवर्ड')}
                  </label>
                  <input
                    id="jd-pass"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="current-password"
                    className="mb-5 w-full rounded-lg border border-ink-700 px-3 py-2.5 text-[14px] focus:border-chakra-500 focus:outline-none focus:ring-2 focus:ring-chakra-500/15"
                  />
                  <button
                    type="submit"
                    disabled={!!busy || !username || !password}
                    className="flex w-full items-center justify-center gap-2 rounded-xl bg-chakra-500 py-3 text-[14.5px] font-bold text-white shadow-sm transition hover:brightness-110 disabled:opacity-50"
                  >
                    {busy ? L('Signing in…', 'प्रवेश हो रहा है…') : L('Sign in', 'प्रवेश करें')}
                  </button>
                  <div className="mt-4 rounded-lg bg-ink-850 px-3 py-2.5 text-[12px] leading-relaxed text-ink-400">
                    <b className="text-ink-200">{L('Usernames', 'उपयोगकर्ता नाम')}:</b>{' '}
                    {L(
                      'central for all India · the state name for a state (bihar, uttar-pradesh) · state.district for a district (bihar.patna).',
                      'पूरे भारत हेतु central · राज्य हेतु राज्य का नाम (bihar, uttar-pradesh) · ज़िले हेतु राज्य.ज़िला (bihar.patna)।',
                    )}
                  </div>
                </form>
              )}
            </div>
          </div>
        </section>

      </main>

      {/* ------------------------------------------------------- footer */}
      <footer className="border-t-4 border-saffron-500 bg-chakra-500 text-white">
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-8 md:grid-cols-3">
          <div>
            <div className="flex items-center gap-2.5">
              <span className="grid h-10 w-10 place-items-center rounded-full bg-white text-chakra-500">
                <AshokaChakra size={26} />
              </span>
              <span className="font-devanagari text-[18px] font-bold text-saffron-300">जलदृष्टि</span>
              <span className="text-[18px] font-extrabold">JalDrishti</span>
            </div>
            <p className="mt-3 text-[12.5px] leading-relaxed text-white/75">
              {L(
                'An AI/ML flood early-warning prototype that integrates weather observations, rainfall forecasts, river-flow models, terrain and official gauges.',
                'मौसम प्रेक्षण, वर्षा पूर्वानुमान, नदी-प्रवाह मॉडल, भूभाग व सरकारी गेज को जोड़ने वाला एआई/एमएल बाढ़ पूर्व चेतावनी प्रोटोटाइप।',
              )}
            </p>
          </div>
          <div>
            <h3 className="text-[12px] font-bold uppercase tracking-wider text-saffron-300">{L('Data sources', 'आँकड़ा स्रोत')}</h3>
            <ul className="mt-3 space-y-1.5 text-[12.5px] text-white/80">
              <li>{L('Central Water Commission — river gauges', 'केंद्रीय जल आयोग — नदी गेज')}</li>
              <li>{L('NDMA SACHET — IMD, CWC & SDMA alerts (CAP)', 'NDMA SACHET — IMD, CWC व SDMA चेतावनियाँ (CAP)')}</li>
              <li>{L('Open-Meteo — rainfall observations & forecasts', 'Open-Meteo — वर्षा प्रेक्षण व पूर्वानुमान')}</li>
              <li>{L('GloFAS v4 — river discharge & 30-year climatology', 'GloFAS v4 — नदी प्रवाह व 30 वर्ष जलवायु')}</li>
              <li>{L('Copernicus DEM & OpenStreetMap — terrain, drains, roads', 'Copernicus DEM व OpenStreetMap — भूभाग, नालियाँ, सड़कें')}</li>
            </ul>
          </div>
          <div>
            <h3 className="text-[12px] font-bold uppercase tracking-wider text-saffron-300">{L('In an emergency', 'आपातकाल में')}</h3>
            <ul className="mt-3 space-y-2 text-[13px]">
              {[
                ['112', L('National emergency number', 'राष्ट्रीय आपात नंबर')],
                ['1078', L('NDMA disaster helpline', 'NDMA आपदा हेल्पलाइन')],
                ['1070 / 1077', L('State / District emergency operations centre', 'राज्य / ज़िला आपात संचालन केंद्र')],
              ].map(([n, k]) => (
                <li key={n} className="flex items-baseline gap-3">
                  <span className="w-28 shrink-0 whitespace-nowrap font-mono text-[15px] font-extrabold text-white">{n}</span>
                  <span className="text-white/75">{k}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <div className="border-t border-white/15">
          <p className="mx-auto max-w-6xl px-4 py-3 text-[11.5px] leading-relaxed text-white/65">
            {L(
              'Research prototype for demonstration — not an official Government of India service and not a public flood warning. For operational warnings follow IMD, CWC and your State Disaster Management Authority.',
              'प्रदर्शन हेतु शोध प्रोटोटाइप — भारत सरकार की आधिकारिक सेवा या सार्वजनिक बाढ़ चेतावनी नहीं। आधिकारिक चेतावनी हेतु IMD, CWC व राज्य आपदा प्रबंधन प्राधिकरण का पालन करें।',
            )}
          </p>
        </div>
      </footer>
    </div>
  );
}
