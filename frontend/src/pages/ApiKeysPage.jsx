import { useCallback, useEffect, useState } from 'react';
import { gateway } from '../lib/api';

/**
 * API Keys management page — admin only.
 *
 * Lets officials create, view, and revoke API keys for external platform
 * access to JalDrishti data. Matches the visual style of the existing
 * Notifications and Resources pages.
 */

const SCOPE_LABELS = {
  score_read: { en: 'Risk scores', hi: 'जोखिम स्कोर' },
  forecast_read: { en: 'Forecasts', hi: 'पूर्वानुमान' },
  maps_read: { en: 'Maps & layers', hi: 'नक्शे और परतें' },
  simulate_write: { en: 'Simulations', hi: 'सिमुलेशन' },
  alert_subscribe: { en: 'Alerts & gauges', hi: 'चेतावनियाँ व गेज' },
};

const ALL_SCOPES = Object.keys(SCOPE_LABELS);

export default function ApiKeysPage({ lang }) {
  const hi = lang === 'hi' ? 'font-devanagari' : '';
  const L = (en, hiText) => (lang === 'hi' ? hiText : en);

  const [keys, setKeys] = useState([]);
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showRevoked, setShowRevoked] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState(null);
  const [usageKey, setUsageKey] = useState(null);
  const [usage, setUsage] = useState(null);

  // Form state
  const [formName, setFormName] = useState('');
  const [formEnv, setFormEnv] = useState('test');
  const [formTier, setFormTier] = useState('standard');
  const [formScopes, setFormScopes] = useState(['score_read']);
  const [formExpiry, setFormExpiry] = useState('');
  const [formError, setFormError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [keysRes, overviewRes] = await Promise.all([
        gateway.listKeys(showRevoked),
        gateway.overview(),
      ]);
      setKeys(keysRes.keys);
      setOverview(overviewRes);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [showRevoked]);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async (e) => {
    e.preventDefault();
    setFormError(null);
    if (!formName.trim()) { setFormError(L('Name is required', 'नाम आवश्यक है')); return; }
    if (formScopes.length === 0) { setFormError(L('Select at least one scope', 'कम से कम एक अनुमति चुनें')); return; }
    setSubmitting(true);
    try {
      const result = await gateway.createKey({
        name: formName.trim(),
        environment: formEnv,
        tier: formTier,
        scopes: formScopes,
        expires_at: formExpiry || null,
      });
      setNewKey(result);
      setCreating(false);
      setFormName('');
      setFormEnv('test');
      setFormTier('standard');
      setFormScopes(['score_read']);
      setFormExpiry('');
      await load();
    } catch (e) {
      setFormError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevoke = async (id) => {
    if (!confirm(L('Revoke this API key? External platforms using it will lose access immediately.', 'इस API कुंजी को रद्द करें? इसे उपयोग करने वाले बाहरी प्लेटफ़ॉर्म तुरंत पहुँच खो देंगे।')))
      return;
    try {
      await gateway.revokeKey(id);
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  const viewUsage = async (key) => {
    setUsageKey(key);
    try {
      const u = await gateway.keyUsage(key.id);
      setUsage(u);
    } catch (e) {
      setUsage(null);
    }
  };

  const toggleScope = (scope) => {
    setFormScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    );
  };

  const copyToClipboard = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Fallback
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
  };

  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-4 p-4">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-3 border-b-2 border-saffron-500 pb-3">
        <div>
          <h2 className={`text-xl font-extrabold tracking-tight text-chakra-500 ${hi}`}>
            {L('API Gateway', 'एपीआई गेटवे')}
          </h2>
          <p className={`mt-0.5 text-[12px] text-ink-400 ${hi}`}>
            {L(
              'Manage API keys for external platforms to access JalDrishti data',
              'बाहरी प्लेटफ़ॉर्मों को JalDrishti डेटा तक पहुँच के लिए API कुंजियाँ प्रबंधित करें',
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-[12px] text-ink-400">
            <input
              type="checkbox"
              checked={showRevoked}
              onChange={(e) => setShowRevoked(e.target.checked)}
              className="accent-saffron-500"
            />
            {L('Show revoked', 'रद्द दिखाएँ')}
          </label>
          <button
            type="button"
            className="btn border-chakra-500 bg-chakra-500 text-white hover:bg-[#123A78]"
            onClick={() => { setCreating(true); setNewKey(null); }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true">
              <path d="M12 5v14M5 12h14" />
            </svg>
            <span className={hi}>{L('New API key', 'नई API कुंजी')}</span>
          </button>
        </div>
      </div>

      {error && <div className="rounded-lg border border-risk-red/30 bg-risk-red/10 px-4 py-2 text-[13px] text-risk-red">{error}</div>}

      {/* Stats row */}
      {overview && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="panel px-4 py-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500">{L('Active keys', 'सक्रिय कुंजियाँ')}</div>
            <div className="font-mono text-3xl font-extrabold text-chakra-500">{overview.keys.active}</div>
          </div>
          <div className="panel px-4 py-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500">{L('Revoked', 'रद्द')}</div>
            <div className="font-mono text-3xl font-extrabold text-ink-400">{overview.keys.revoked}</div>
          </div>
          <div className="panel px-4 py-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500">{L('Requests today', 'आज के अनुरोध')}</div>
            <div className="font-mono text-3xl font-extrabold text-indiagreen-300">{overview.requests.today}</div>
          </div>
          <div className="panel px-4 py-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500">{L('Last hour', 'पिछला घंटा')}</div>
            <div className="font-mono text-3xl font-extrabold text-saffron-400">{overview.requests.last_hour}</div>
          </div>
        </div>
      )}

      {/* New key revealed */}
      {newKey && newKey.key && (
        <div className="rounded-xl border-2 border-indiagreen-500 bg-indiagreen-500/[0.06] p-4">
          <div className="flex items-center gap-2 text-[13px] font-bold text-indiagreen-300">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M9 12l2 2 4-4" />
              <circle cx="12" cy="12" r="10" />
            </svg>
            {L('Key created! Copy it now — it won\'t be shown again.', 'कुंजी बन गई! इसे अभी कॉपी करें — यह फिर नहीं दिखेगी।')}
          </div>
          <div className="mt-2 flex items-center gap-2">
            <code className="flex-1 rounded-lg bg-ink-850 px-3 py-2 font-mono text-[13px] text-indiagreen-300 select-all break-all">
              {newKey.key}
            </code>
            <button
              type="button"
              className="btn border-indiagreen-500 text-indiagreen-300 hover:bg-indiagreen-500/10"
              onClick={() => copyToClipboard(newKey.key)}
            >
              {L('Copy', 'कॉपी')}
            </button>
          </div>
          <p className="mt-1 text-[11px] text-ink-400">{L('Name', 'नाम')}: {newKey.name} · {L('Tier', 'स्तर')}: {newKey.tier} · {L('Scopes', 'अनुमतियाँ')}: {newKey.scopes.join(', ')}</p>
          <button type="button" onClick={() => setNewKey(null)} className="mt-2 text-[12px] text-ink-500 hover:text-ink-200">
            {L('Dismiss', 'बंद करें')}
          </button>
        </div>
      )}

      {/* Create form */}
      {creating && (
        <div className="panel p-4">
          <h3 className={`text-[14px] font-bold text-chakra-500 ${hi}`}>{L('Create new API key', 'नई API कुंजी बनाएँ')}</h3>
          <form onSubmit={handleCreate} className="mt-3 space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-[11px] font-bold uppercase tracking-wider text-ink-500">{L('Name', 'नाम')}</label>
                <input
                  type="text"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  placeholder={L('e.g. NDMA Dashboard', 'उदा. NDMA डैशबोर्ड')}
                  className="w-full rounded-lg border border-ink-700 bg-white px-3 py-2 text-[13px] text-ink-100 placeholder:text-ink-600 focus:border-saffron-500 focus:outline-none"
                  maxLength={120}
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-bold uppercase tracking-wider text-ink-500">{L('Environment', 'वातावरण')}</label>
                <select
                  value={formEnv}
                  onChange={(e) => setFormEnv(e.target.value)}
                  className="w-full rounded-lg border border-ink-700 bg-white px-3 py-2 text-[13px] text-ink-100 focus:border-saffron-500 focus:outline-none"
                >
                  <option value="test">{L('Test (sk_test_)', 'टेस्ट (sk_test_)')}</option>
                  <option value="live">{L('Live (sk_live_)', 'लाइव (sk_live_)')}</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-bold uppercase tracking-wider text-ink-500">{L('Tier', 'स्तर')}</label>
                <select
                  value={formTier}
                  onChange={(e) => setFormTier(e.target.value)}
                  className="w-full rounded-lg border border-ink-700 bg-white px-3 py-2 text-[13px] text-ink-100 focus:border-saffron-500 focus:outline-none"
                >
                  <option value="standard">{L('Standard (100 req/hr)', 'मानक (100 अनु/घंटा)')}</option>
                  <option value="enterprise">{L('Enterprise (1,000 req/hr)', 'एंटरप्राइज़ (1,000 अनु/घंटा)')}</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-bold uppercase tracking-wider text-ink-500">{L('Expires (optional)', 'समाप्ति (वैकल्पिक)')}</label>
                <input
                  type="datetime-local"
                  value={formExpiry}
                  onChange={(e) => setFormExpiry(e.target.value)}
                  className="w-full rounded-lg border border-ink-700 bg-white px-3 py-2 text-[13px] text-ink-100 focus:border-saffron-500 focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label className="mb-1 block text-[11px] font-bold uppercase tracking-wider text-ink-500">{L('Scopes', 'अनुमतियाँ')}</label>
              <div className="flex flex-wrap gap-2">
                {ALL_SCOPES.map((scope) => (
                  <button
                    key={scope}
                    type="button"
                    onClick={() => toggleScope(scope)}
                    className={`rounded-lg border px-3 py-1.5 text-[12px] font-semibold transition ${
                      formScopes.includes(scope)
                        ? 'border-saffron-500 bg-saffron-50 text-chakra-500'
                        : 'border-ink-700 text-ink-400 hover:border-ink-500'
                    }`}
                  >
                    {lang === 'hi' ? SCOPE_LABELS[scope].hi : SCOPE_LABELS[scope].en}
                  </button>
                ))}
              </div>
            </div>

            {formError && <p className="text-[12px] text-risk-red">{formError}</p>}

            <div className="flex gap-2">
              <button
                type="submit"
                disabled={submitting}
                className="btn border-chakra-500 bg-chakra-500 text-white hover:bg-[#123A78] disabled:opacity-50"
              >
                {submitting ? L('Creating…', 'बना रहे हैं…') : L('Create key', 'कुंजी बनाएँ')}
              </button>
              <button type="button" className="btn" onClick={() => setCreating(false)}>
                {L('Cancel', 'रद्द करें')}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Keys table */}
      {loading ? (
        <div className="py-10 text-center text-[13px] text-ink-400">{L('Loading…', 'लोड हो रहा…')}</div>
      ) : keys.length === 0 ? (
        <div className="panel py-10 text-center">
          <p className={`text-[14px] font-bold text-ink-300 ${hi}`}>{L('No API keys yet', 'अभी कोई API कुंजी नहीं')}</p>
          <p className={`mt-1 text-[12px] text-ink-500 ${hi}`}>
            {L('Create one to let external platforms access JalDrishti data.', 'बाहरी प्लेटफ़ॉर्मों को डेटा एक्सेस देने के लिए एक बनाएँ।')}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-ink-700">
          <table className="w-full text-left text-[12.5px]">
            <thead>
              <tr className="border-b border-ink-700 bg-ink-850">
                <th className="px-3 py-2 font-bold text-ink-400">{L('Name', 'नाम')}</th>
                <th className="px-3 py-2 font-bold text-ink-400">{L('Key prefix', 'कुंजी उपसर्ग')}</th>
                <th className="px-3 py-2 font-bold text-ink-400">{L('Env', 'वातावरण')}</th>
                <th className="px-3 py-2 font-bold text-ink-400">{L('Tier', 'स्तर')}</th>
                <th className="px-3 py-2 font-bold text-ink-400">{L('Scopes', 'अनुमतियाँ')}</th>
                <th className="px-3 py-2 font-bold text-ink-400">{L('Status', 'स्थिति')}</th>
                <th className="px-3 py-2 font-bold text-ink-400">{L('Created', 'बनाया')}</th>
                <th className="px-3 py-2 font-bold text-ink-400">{L('Actions', 'कार्य')}</th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id} className={`border-b border-ink-800 ${!k.is_active ? 'opacity-50' : 'hover:bg-ink-850/50'}`}>
                  <td className="px-3 py-2 font-semibold text-ink-100">{k.name}</td>
                  <td className="px-3 py-2 font-mono text-[11px] text-ink-300">{k.key_prefix}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                      k.environment === 'live' ? 'bg-indiagreen-500/15 text-indiagreen-300' : 'bg-ink-700 text-ink-400'
                    }`}>
                      {k.environment}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-ink-300">{k.tier}</td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1">
                      {k.scopes.map((s) => (
                        <span key={s} className="rounded bg-saffron-50 px-1.5 py-0.5 text-[10px] font-semibold text-saffron-300">
                          {lang === 'hi' ? SCOPE_LABELS[s]?.hi ?? s : SCOPE_LABELS[s]?.en ?? s}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    {k.is_active ? (
                      <span className="flex items-center gap-1 text-indiagreen-300">
                        <span className="h-1.5 w-1.5 rounded-full bg-indiagreen-400" />
                        {L('Active', 'सक्रिय')}
                      </span>
                    ) : (
                      <span className="text-ink-500">{L('Revoked', 'रद्द')}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-ink-400">
                    {k.created_at ? new Date(k.created_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        className="rounded px-2 py-1 text-[11px] font-semibold text-chakra-500 hover:bg-ink-850"
                        onClick={() => viewUsage(k)}
                        title={L('Usage', 'उपयोग')}
                      >
                        {L('Usage', 'उपयोग')}
                      </button>
                      {k.is_active && (
                        <button
                          type="button"
                          className="rounded px-2 py-1 text-[11px] font-semibold text-risk-red hover:bg-risk-red/10"
                          onClick={() => handleRevoke(k.id)}
                        >
                          {L('Revoke', 'रद्द करें')}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Usage panel */}
      {usageKey && usage && (
        <div className="panel p-4">
          <div className="flex items-center justify-between">
            <h3 className={`text-[14px] font-bold text-chakra-500 ${hi}`}>
              {L('Usage — ', 'उपयोग — ')}{usageKey.name}
            </h3>
            <button type="button" onClick={() => { setUsageKey(null); setUsage(null); }} className="text-[12px] text-ink-500 hover:text-ink-200">✕</button>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg bg-ink-850 px-3 py-2">
              <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500">{L('Total (24h)', 'कुल (24 घंटे)')}</div>
              <div className="font-mono text-2xl font-extrabold text-chakra-500">{usage.total_requests}</div>
            </div>
            <div className="rounded-lg bg-ink-850 px-3 py-2">
              <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500">{L('Current window', 'वर्तमान विंडो')}</div>
              <div className="font-mono text-2xl font-extrabold text-saffron-400">{usage.current_window_count}</div>
            </div>
            <div className="rounded-lg bg-ink-850 px-3 py-2">
              <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500">{L('Window', 'विंडो')}</div>
              <div className="font-mono text-sm font-bold text-ink-300">{usage.current_window}</div>
            </div>
          </div>
          {usage.by_endpoint?.length > 0 && (
            <div className="mt-3">
              <div className="text-[11px] font-bold uppercase tracking-wider text-ink-500">{L('By endpoint', 'एंडपॉइंट के अनुसार')}</div>
              <div className="mt-1 space-y-1">
                {usage.by_endpoint.map((e, i) => (
                  <div key={i} className="flex items-center justify-between rounded bg-ink-850 px-3 py-1.5 text-[12px]">
                    <span className="font-mono text-ink-300">{e.method} {e.endpoint}</span>
                    <span className="font-mono font-bold text-ink-200">{e.count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* API docs hint */}
      <div className="panel px-4 py-3">
        <p className={`text-[12px] text-ink-400 ${hi}`}>
          <span className="font-bold text-ink-300">{L('Quick start', 'त्वरित शुरुआत')}:</span>{' '}
          {L(
            'Include your API key as',
            'अपनी API कुंजी इस प्रकार शामिल करें',
          )}{' '}
          <code className="rounded bg-ink-850 px-1.5 py-0.5 font-mono text-[11px] text-saffron-300">Authorization: Bearer sk_live_...</code>{' '}
          {L('in the request header. Endpoints:', 'अनुरोध हेडर में। एंडपॉइंट:')}{' '}
          <code className="rounded bg-ink-850 px-1.5 py-0.5 font-mono text-[11px] text-chakra-400">/api/gateway/v1/scores/summary</code>,{' '}
          <code className="rounded bg-ink-850 px-1.5 py-0.5 font-mono text-[11px] text-chakra-400">/api/gateway/v1/scores/locations</code>,{' '}
          <code className="rounded bg-ink-850 px-1.5 py-0.5 font-mono text-[11px] text-chakra-400">/api/gateway/v1/forecasts/{'{id}'}</code>,{' '}
          <code className="rounded bg-ink-850 px-1.5 py-0.5 font-mono text-[11px] text-chakra-400">/api/gateway/v1/alerts</code>
        </p>
      </div>
    </div>
  );
}
