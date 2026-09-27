import { href } from '../lib/router';
import { SectionHead } from './Primitives';

/**
 * River flood waves travelling downstream between places.
 *
 *   UpstreamCard   on a town's page: gauges upstream on its river that are above
 *                  warning or rising, and when their water could arrive here
 *   TownsInPath    on the Rivers page: every monitored town with a wave coming,
 *                  soonest first - the network-level "affected next" list
 *
 * Arrival is a range from typical flood-wave speeds (2.5-7 km/h), never a single
 * time, and each entry carries an evidence rating with its reasons.
 */

const hi = (lang) => (lang === 'hi' ? 'font-devanagari' : '');

const STATUS = {
  DANGER: { colour: '#C1121F', en: 'above danger', hi: 'खतरे से ऊपर' },
  WARNING: { colour: '#E4701E', en: 'above warning', hi: 'चेतावनी से ऊपर' },
  NORMAL: { colour: '#C99700', en: 'rising near danger', hi: 'खतरे के पास बढ़ रहा' },
};
const EVIDENCE = {
  strong: { colour: '#0B8A3D', en: 'strong evidence', hi: 'मज़बूत साक्ष्य' },
  moderate: { colour: '#C99700', en: 'moderate evidence', hi: 'मध्यम साक्ष्य' },
  weak: { colour: '#C1121F', en: 'weak evidence', hi: 'कमज़ोर साक्ष्य' },
};
const TREND = { RISING: { en: 'rising', hi: 'बढ़ रहा' }, FALLING: { en: 'falling', hi: 'घट रहा' }, STEADY: { en: 'steady', hi: 'स्थिर' } };

function eta(e, lang) {
  return lang === 'hi' ? `~${e.p50} घं (${e.p10}–${e.p90} घं)` : `~${e.p50} h (${e.p10}–${e.p90} h)`;
}

function ThreatRow({ t, lang, onOpenStation }) {
  const st = STATUS[t.status] ?? STATUS.WARNING;
  const ev = EVIDENCE[t.evidence];
  return (
    <div className={`text-[11.5px] ${hi(lang)}`}>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <button type="button" onClick={() => onOpenStation?.(t.code)} className="font-bold text-chakra-500 hover:underline">
          {t.name}
        </button>
        <span className="text-ink-500">
          {lang === 'hi' ? t.river_hi || t.river : t.river} · {t.distance_km} km {lang === 'hi' ? 'ऊपर' : 'upstream'}
        </span>
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10.5px]">
        <span className="font-semibold" style={{ color: st.colour }}>
          {lang === 'hi' ? st.hi : st.en}
          {t.above_danger_m != null &&
            (t.above_danger_m > 0
              ? lang === 'hi' ? ` (खतरे से ${t.above_danger_m} मी ऊपर)` : ` (${t.above_danger_m} m over danger)`
              : lang === 'hi' ? ` (खतरे से ${Math.abs(t.above_danger_m)} मी नीचे)` : ` (${Math.abs(t.above_danger_m)} m below danger)`)}
        </span>
        {t.trend && <span className="text-ink-400">{lang === 'hi' ? TREND[t.trend]?.hi : TREND[t.trend]?.en ?? t.trend.toLowerCase()}</span>}
        <span className="font-mono font-semibold text-risk-red">
          {lang === 'hi' ? 'पहुँच' : 'arrives'} {eta(t.eta_h, lang)}
        </span>
        <span className="font-semibold" style={{ color: ev.colour }}>● {lang === 'hi' ? ev.hi : ev.en}</span>
      </div>
      {t.evidence_reasons.length > 0 && <div className="mt-0.5 text-[10px] text-ink-500">{t.evidence_reasons.join('; ')}</div>}
    </div>
  );
}

export function UpstreamCard({ lang, threats, onOpenStation }) {
  return (
    <section className="panel" data-tour="loc-upstream">
      <SectionHead title={lang === 'hi' ? 'ऊपर से आती बाढ़ लहर' : 'Flood wave coming downstream'} lang={lang} />
      <div className="space-y-3 p-4">
        {threats.length === 0 ? (
          <p className={`text-[12px] text-ink-400 ${hi(lang)}`}>
            {lang === 'hi'
              ? 'इस नदी पर ऊपर की ओर कोई गेज चेतावनी स्तर से ऊपर या खतरे के पास बढ़ता नहीं दिख रहा।'
              : 'No gauge upstream on this river is above warning or rising towards danger right now.'}
          </p>
        ) : (
          threats.map((t) => <ThreatRow key={t.code} t={t} lang={lang} onOpenStation={onOpenStation} />)
        )}
        <p className={`border-t border-ink-800 pt-2 text-[10px] text-ink-500 ${hi(lang)}`}>
          {lang === 'hi'
            ? 'पहुँच समय नदी दूरी व सामान्य बाढ़-लहर गति (2.5–7 किमी/घं) से; बाँध, तटबंध टूटना व सहायक नदियाँ इसे बदल सकती हैं।'
            : 'Arrival from river distance and typical flood-wave speed (2.5–7 km/h); dams, embankment breaches and tributaries can change it.'}
        </p>
      </div>
    </section>
  );
}

export function TownsInPath({ lang, rows, onOpenStation }) {
  return (
    <section className="panel" data-tour="rv-path">
      <SectionHead
        title={lang === 'hi' ? 'बाढ़ लहर के रास्ते में शहर' : 'Towns in the path of a flood wave'}
        lang={lang}
        right={<span className="text-[10px] text-ink-500">{rows.length}</span>}
      />
      {rows.length === 0 ? (
        <p className={`px-4 py-4 text-[12px] text-ink-400 ${hi(lang)}`}>
          {lang === 'hi'
            ? 'किसी निगरानी शहर के ऊपर की ओर अभी कोई गेज चेतावनी से ऊपर नहीं है।'
            : 'No monitored town has a gauge above warning upstream on its river right now.'}
        </p>
      ) : (
        <ol className="max-h-[520px] divide-y divide-ink-800 overflow-y-auto scrollbar-thin">
          {rows.map((r) => (
            <li key={r.id} className="px-4 py-3">
              <a href={href(`/location/${r.id}`)} className={`text-[13px] font-bold text-ink-100 hover:text-chakra-500 hover:underline ${hi(lang)}`}>
                {lang === 'hi' && r.name_hi ? r.name_hi : r.name}
              </a>
              <span className="ml-2 text-[10.5px] text-ink-500">{r.state}</span>
              <div className="mt-1.5 space-y-2">
                {r.threats.map((t) => (
                  <ThreatRow key={t.code} t={t} lang={lang} onOpenStation={onOpenStation} />
                ))}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
