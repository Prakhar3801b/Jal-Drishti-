import { href } from '../lib/router';
import { stateName, tierColour, TIER_LABELS } from '../lib/format';

/**
 * "My locality": the home screen for a citizen account.
 *
 * Built from the same live briefing as the officials' "My area", scoped by the
 * server to the resident's home district, but written for residents: how serious
 * it is, what to do, which roads to avoid, what is coming, and who to call. The
 * control-room tools (advisory drafts, planning, notifications) are not here and
 * the server refuses them for citizen accounts.
 */

const RESIDENT_ACTION = {
  red: { en: 'Danger — follow official instructions now', hi: 'खतरा — अभी आधिकारिक निर्देशों का पालन करें' },
  orange: { en: 'Be prepared to act', hi: 'कार्रवाई के लिए तैयार रहें' },
  yellow: { en: 'Stay alert', hi: 'सतर्क रहें' },
  green: { en: 'No flood risk right now', hi: 'अभी बाढ़ का ख़तरा नहीं' },
};
const INK = { red: '#A50F1A', orange: '#B4530F', yellow: '#7A5E00', green: '#0A6E31' };
const KIND = {
  place: { en: 'Flood risk', hi: 'बाढ़ जोखिम' },
  gauge: { en: 'River above danger', hi: 'नदी खतरे से ऊपर' },
  wave: { en: 'Flood wave coming', hi: 'बाढ़ लहर आ रही' },
  official: { en: 'Official warning', hi: 'आधिकारिक चेतावनी' },
};
const HELPLINES = [
  ['112', 'National emergency', 'राष्ट्रीय आपात नंबर'],
  ['1078', 'NDMA disaster helpline', 'NDMA आपदा हेल्पलाइन'],
  ['1070', 'State emergency operations centre', 'राज्य आपात संचालन केंद्र'],
  ['1077', 'District emergency operations centre', 'ज़िला आपात संचालन केंद्र'],
];

function Card({ title, children }) {
  return (
    <section className="overflow-hidden rounded-2xl border border-ink-700 bg-white shadow-sm">
      <h2 className="border-b border-ink-800 px-4 py-3 text-[14px] font-extrabold text-chakra-500">{title}</h2>
      <div className="p-4">{children}</div>
    </section>
  );
}

export default function CitizenHome({ lang, user, brief, error, onRetry, onOpenCopilot }) {
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
  if (!brief) return <div className="p-10 text-center text-[13px] text-ink-400">{L('Checking your area…', 'आपके क्षेत्र की जाँच हो रही है…')}</div>;

  const place = brief.places[0];
  const tier = place?.tier ?? 'green';
  const colour = tierColour(tier);
  const resident = brief.resident ?? { en: [], hi: [], routes: [] };
  const steps = (resident[lang] ?? resident.en).filter((x) => !x.startsWith('Avoid these roads') && !x.startsWith('इन सड़कों से बचें'));
  const coming = brief.coming_next.places.find((c) => c.id === place?.id);
  const wave = brief.coming_next.waves.find((w) => w.id === place?.id);
  const tz = { timeZone: 'Asia/Kolkata' };
  const updated = new Date(brief.computed_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', ...tz });
  const area = `${user.district}, ${stateName(user.state, lang)}`;

  return (
    <div id="main-content" className={`mx-auto w-full max-w-[1100px] space-y-5 px-4 py-5 ${hiFont}`}>
      {/* ---------------------------------------------------------- status */}
      <section
        className="relative overflow-hidden rounded-3xl border border-ink-700 bg-white shadow-sm"
        style={{ backgroundImage: `linear-gradient(110deg, ${colour}1F 0%, ${colour}08 40%, #ffffff 72%)` }}
      >
        <div className="absolute inset-y-0 left-0 w-1.5" style={{ background: colour }} aria-hidden="true" />
        <div className="flex flex-wrap items-center gap-5 px-6 py-6 sm:px-8">
          <div className="flex flex-col items-center">
            <div className="grid h-20 w-20 place-items-center rounded-full text-white shadow-md" style={{ background: colour, boxShadow: `0 0 0 6px ${colour}33` }}>
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d={tier === 'green' ? 'M5 12l5 5L20 7' : 'M12 3l9.5 17h-19L12 3zM12 10v4M12 17.5h.01'} />
              </svg>
            </div>
            <span className="mt-2 text-[12px] font-extrabold uppercase tracking-wider" style={{ color: INK[tier] }}>
              {L(TIER_LABELS[tier].en, TIER_LABELS[tier].hi)}
            </span>
          </div>
          <div className="min-w-[240px] flex-1">
            <div className="text-[12px] font-bold uppercase tracking-wider text-ink-500">
              {L('Your area', 'आपका क्षेत्र')}
              {user.name ? ` · ${user.name}` : ''}
            </div>
            <h1 className="mt-1 text-[28px] font-extrabold leading-tight tracking-tight text-chakra-500">{area}</h1>
            <p className="mt-1 text-[18px] font-bold" style={{ color: INK[tier] }}>{L(RESIDENT_ACTION[tier].en, RESIDENT_ACTION[tier].hi)}</p>
            {place && (lang === 'hi' ? place.reason_hi : place.reason_en) && tier !== 'green' && (
              <p className="mt-1 text-[13.5px] text-ink-300">
                {L('Main reason', 'मुख्य कारण')}: {lang === 'hi' ? place.reason_hi : place.reason_en}
              </p>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3 border-t border-ink-800/80 bg-white/70 px-6 py-3 sm:px-8">
          <span className="text-[12.5px] text-ink-400">{L(`Updated ${updated} IST · updates automatically`, `अद्यतन ${updated} IST · स्वतः अद्यतन`)}</span>
          <span className="ml-auto flex flex-wrap gap-2">
            {onOpenCopilot && (
              <button type="button" onClick={onOpenCopilot} className="btn border-chakra-500 bg-chakra-500 px-3.5 py-1.5 text-[12.5px] text-white hover:bg-[#123A78] hover:text-white">
                {L('Ask about my area', 'मेरे क्षेत्र के बारे में पूछें')}
              </button>
            )}
            {place && (
              <a href={href(`/hotspots/${place.id}`)} className="btn px-3 py-1.5 text-[12.5px]">{L('Street-level map', 'गली-स्तर नक्शा')}</a>
            )}
          </span>
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
        <div className="min-w-0 space-y-5">
          {/* ------------------------------------------------------ what to do */}
          <Card title={L('What you should do', 'आपको क्या करना चाहिए')}>
            {resident.routes?.length > 0 && (
              <div className="mb-3">
                <div className="mb-1.5 text-[12.5px] font-bold text-ink-200">{L('Avoid these roads', 'इन सड़कों से बचें')}</div>
                <div className="flex flex-wrap gap-1.5">
                  {resident.routes.map((r) => (
                    <span key={r} className="rounded-md border border-risk-red/30 bg-white px-2 py-0.5 text-[12.5px] font-semibold text-risk-red">⛔ {r}</span>
                  ))}
                </div>
              </div>
            )}
            <ul className="space-y-2">
              {steps.map((x) => (
                <li key={x} className="flex gap-2 text-[13.5px] leading-snug text-ink-200">
                  <span className="text-saffron-500" aria-hidden="true">•</span>
                  {x}
                </li>
              ))}
            </ul>
          </Card>

          {/* -------------------------------------------------- coming next */}
          <Card title={L('Next 3 days', 'अगले 3 दिन')}>
            <ul className="space-y-2 text-[13.5px] text-ink-200">
              <li>
                {coming
                  ? L(
                      `Risk may rise to ${TIER_LABELS[coming.to].en} in about ${coming.in_hours} hours.`,
                      `लगभग ${coming.in_hours} घंटे में जोखिम ${TIER_LABELS[coming.to].hi} तक बढ़ सकता है।`,
                    )
                  : L('No worsening is expected in the next 3 days.', 'अगले 3 दिनों में स्थिति बिगड़ने की आशंका नहीं।')}
              </li>
              {wave && (
                <li>
                  {L(
                    `High water on the ${wave.river} may reach here in about ${wave.eta_h.p50} hours (between ${wave.eta_h.p10} and ${wave.eta_h.p90} h).`,
                    `${wave.river} नदी का ऊँचा पानी लगभग ${wave.eta_h.p50} घंटे में यहाँ पहुँच सकता है (${wave.eta_h.p10}–${wave.eta_h.p90} घंटे)।`,
                  )}
                </li>
              )}
            </ul>
          </Card>

          {/* ------------------------------------------------------ warnings */}
          <Card title={L('Warnings for your area', 'आपके क्षेत्र की चेतावनियाँ')}>
            {brief.alerts.length === 0 ? (
              <p className="text-[13.5px] font-semibold text-indiagreen-300">{L('No warnings for your area right now.', 'अभी आपके क्षेत्र के लिए कोई चेतावनी नहीं।')}</p>
            ) : (
              <ul className="space-y-3">
                {brief.alerts.map((al) => (
                  <li key={al.id} className="rounded-xl border border-ink-700 p-3" style={{ borderLeft: `4px solid ${tierColour(al.level)}` }}>
                    <div className="text-[11px] font-extrabold uppercase tracking-wider text-ink-500">{L(KIND[al.kind]?.en ?? '', KIND[al.kind]?.hi ?? '')}</div>
                    <div className="mt-0.5 text-[14.5px] font-bold text-ink-100">{L(al.title_en, al.title_hi)}</div>
                    <p className="mt-0.5 text-[13px] leading-snug text-ink-300">{L(al.detail_en, al.detail_hi)}</p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        {/* ------------------------------------------------------- helplines */}
        <div className="space-y-5">
          <Card title={L('In an emergency', 'आपातकाल में')}>
            <ul className="space-y-2.5">
              {HELPLINES.map(([n, en, hi]) => (
                <li key={n}>
                  <a href={`tel:${n}`} className="flex items-baseline gap-3 rounded-lg px-1 hover:bg-ink-850">
                    <span className="w-14 shrink-0 font-mono text-[18px] font-extrabold text-chakra-500">{n}</span>
                    <span className="text-[12.5px] text-ink-300">{L(en, hi)}</span>
                  </a>
                </li>
              ))}
            </ul>
          </Card>
          <p className="rounded-xl border border-ink-700 bg-white p-3 text-[11.5px] leading-relaxed text-ink-500">
            {L(
              'JalDrishti is a research prototype, not an official warning. Always follow instructions from IMD, CWC, your State Disaster Management Authority and local officials.',
              'जलदृष्टि एक शोध प्रोटोटाइप है, आधिकारिक चेतावनी नहीं। हमेशा IMD, CWC, राज्य आपदा प्रबंधन प्राधिकरण व स्थानीय अधिकारियों के निर्देशों का पालन करें।',
            )}
          </p>
        </div>
      </div>
    </div>
  );
}
