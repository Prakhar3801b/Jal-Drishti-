import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { href } from '../lib/router';
import { stateName } from '../lib/format';

/**
 * Resources (officials only): every depot the user can see, its stock per type,
 * what is deployed and what is available. Officials overwrite demo counts with real
 * ones (e.g. from IDRN) for the depots they manage; each change re-optimises the plan.
 */

const KIND_ORDER = ['ndrf', 'sdrf', 'district'];

function StockCell({ depot, rtype, lang, onSave }) {
  const s = depot.stock[rtype];
  const [value, setValue] = useState(String(s?.total ?? 0));
  const [state, setState] = useState(null);
  useEffect(() => setValue(String(s?.total ?? 0)), [s?.total]);
  if (!s) return <td className="px-2 py-2 text-center text-ink-600">—</td>;
  const dirty = Number(value) !== s.total;
  return (
    <td className="px-2 py-2 align-top">
      <div className="flex items-center gap-1.5">
        {depot.can_edit ? (
          <input
            type="number"
            min="0"
            max="10000"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="w-16 rounded-md border border-ink-700 px-1.5 py-1 text-right font-mono text-[12.5px]"
            aria-label={`${depot.name} ${rtype}`}
          />
        ) : (
          <span className="w-16 text-right font-mono text-[12.5px] font-bold">{s.total}</span>
        )}
        {dirty && (
          <button
            type="button"
            className="btn px-2 py-0.5 text-[11px]"
            onClick={async () => {
              setState('saving');
              try {
                await onSave(depot.id, rtype, Number(value));
                setState(null);
              } catch (e) {
                setState(e.message);
              }
            }}
          >
            {state === 'saving' ? '…' : lang === 'hi' ? 'सहेजें' : 'Save'}
          </button>
        )}
      </div>
      <div className="mt-0.5 text-[10.5px] text-ink-500">
        {s.available} {lang === 'hi' ? 'उपलब्ध' : 'free'}
        {s.deployed ? ` · ${s.deployed} ${lang === 'hi' ? 'तैनात' : 'out'}` : ''}
        {s.demo && <span className="ml-1 rounded bg-saffron-50 px-1 font-bold text-saffron-300">demo</span>}
      </div>
      {state && state !== 'saving' && <div className="text-[10.5px] text-risk-red">{state}</div>}
    </td>
  );
}

export default function ResourcesPage({ lang }) {
  const L = (en, hi) => (lang === 'hi' ? hi : en);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('');

  const load = useCallback(async () => {
    try {
      setData(await api.resources());
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const groups = useMemo(() => {
    if (!data) return [];
    const q = filter.trim().toLowerCase();
    const rows = data.depots.filter((d) => !q || d.name.toLowerCase().includes(q) || d.state.toLowerCase().includes(q));
    return KIND_ORDER.map((k) => ({ kind: k, rows: rows.filter((d) => d.kind === k) })).filter((g) => g.rows.length);
  }, [data, filter]);

  if (error && !data) return <p className="m-6 rounded-xl border border-risk-red/40 bg-white p-4 text-[13px] text-risk-red">{error}</p>;
  if (!data) return <div className="p-10 text-center text-[13px] text-ink-400">{L('Loading resources…', 'संसाधन लोड हो रहे हैं…')}</div>;

  const tname = (r) => (lang === 'hi' ? data.types[r].hi : data.types[r].en);
  const save = async (depotId, rtype, total) => {
    await api.setStock(depotId, rtype, total);
    await load();
  };

  return (
    <div id="main-content" className={`mx-auto w-full max-w-[1200px] space-y-5 px-4 py-5 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
      <section className="rounded-3xl border border-ink-700 bg-white px-6 py-5 shadow-sm">
        <div className="flex flex-wrap items-start gap-4">
          <div className="min-w-[260px] flex-1">
            <div className="text-[12px] font-bold uppercase tracking-wider text-ink-500">{L('Resources', 'संसाधन')}</div>
            <h1 className="mt-1 text-[26px] font-extrabold leading-tight text-chakra-500">{L('Stock at every depot', 'हर डिपो का भंडार')}</h1>
            <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-ink-400">
              {L(
                `NDRF: ${data.ndrf.battalions} battalions, ${data.ndrf.teams_per_battalion} teams each of ~${data.ndrf.team_size} personnel (public figures). Everything marked demo is illustrative — India’s resource inventory (IDRN) is open to officials only. Enter real counts for the depots you manage; the plan re-optimises at once.`,
                `NDRF: ${data.ndrf.battalions} बटालियन, प्रत्येक में ${data.ndrf.teams_per_battalion} दल (सार्वजनिक आँकड़े)। "demo" चिह्नित आँकड़े उदाहरण हैं। अपने डिपो के वास्तविक आँकड़े दर्ज करें; योजना तुरंत पुनः अनुकूलित होगी।`,
              )}
            </p>
          </div>
          <div className="flex gap-2">
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={L('Filter by depot or state', 'डिपो या राज्य खोजें')}
              className="rounded-lg border border-ink-700 px-3 py-2 text-[13px]"
            />
            <a href={href('/plan')} className="btn">{L('← Response plan', '← प्रतिक्रिया योजना')}</a>
          </div>
        </div>
      </section>

      {groups.map((g) => {
        const rtypes = data.holds[g.kind];
        const label = { ndrf: L('NDRF battalions (central)', 'एनडीआरएफ बटालियन (केंद्र)'), sdrf: L('State Disaster Response Force', 'राज्य आपदा प्रतिक्रिया बल'), district: L('District stores', 'ज़िला भंडार') }[g.kind];
        return (
          <section key={g.kind} className="overflow-hidden rounded-2xl border border-ink-700 bg-white shadow-sm">
            <div className="flex items-center gap-2 border-b border-ink-800 px-4 py-3">
              <h2 className="text-[14px] font-extrabold text-chakra-500">{label}</h2>
              <span className="rounded-full bg-ink-850 px-2 py-0.5 font-mono text-[11px] font-bold text-ink-300">{g.rows.length}</span>
              <span className="ml-auto text-[11.5px] text-ink-500">{L(`mobilises in ~${data.mobilise_h[g.kind]} h`, `~${data.mobilise_h[g.kind]} घंटे में तैयार`)}</span>
            </div>
            <div className="max-h-[520px] overflow-auto">
              <table className="w-full text-[12.5px]">
                <thead className="sticky top-0 bg-white">
                  <tr className="text-left text-[11px] uppercase tracking-wide text-ink-500">
                    <th className="px-4 py-2 font-bold">{L('Depot', 'डिपो')}</th>
                    <th className="px-2 py-2 font-bold">{L('State', 'राज्य')}</th>
                    {rtypes.map((r) => (
                      <th key={r} className="px-2 py-2 font-bold">{tname(r)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-800">
                  {g.rows.map((d) => (
                    <tr key={d.id}>
                      <td className="px-4 py-2 align-top font-semibold text-ink-100">
                        {d.name}
                        {!d.can_edit && <span className="ml-1.5 text-[10.5px] font-normal text-ink-500">{L('(view only)', '(केवल देखें)')}</span>}
                      </td>
                      <td className="px-2 py-2 align-top text-ink-400">{stateName(d.state, lang)}</td>
                      {rtypes.map((r) => (
                        <StockCell key={r} depot={d} rtype={r} lang={lang} onSave={save} />
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}
    </div>
  );
}
