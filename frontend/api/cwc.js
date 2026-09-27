/**
 * CWC relay (Vercel Function, pinned to Mumbai in vercel.json).
 *
 * The Central Water Commission flood portal does not answer requests from
 * outside India, and the JalDrishti API runs on Render in Singapore. This
 * function forwards the API's CWC reads from an Indian region. It is not an
 * open proxy:
 *   - it requires the shared token (CWC_RELAY_TOKEN, the same value as the API's
 *     JALDRISHTI_CWC_RELAY_TOKEN)
 *   - it only reaches ffs.india-water.gov.in, and only its /iam/api/ and
 *     /ffm/api/ data paths, with GET
 *
 * It also forwards Open-Meteo forecast/flood/archive reads, used only when the
 * API's shared Render IP is rate limited (HTTP 429) by Open-Meteo.
 *
 * GET  with header x-cwc-target: "/iam/api/...?query" or a full allowed URL -> the response
 * POST {"items": [{path, params, className}, ...]}       -> {"results": [{status, data}]}
 *      (up to 120 reads per call, so a full gauge sweep is ~11 invocations)
 */

import { timingSafeEqual } from 'node:crypto';

const CWC = 'https://ffs.india-water.gov.in';
// Allowed upstreams and, for each, the paths that may be requested.
const ALLOWED = {
  [CWC]: /^\/(iam|ffm)\/api\/[A-Za-z0-9/_-]+\/?$/,
  'https://api.open-meteo.com': /^\/v1\/(forecast|elevation)$/,
  'https://flood-api.open-meteo.com': /^\/v1\/flood$/,
  'https://archive-api.open-meteo.com': /^\/v1\/archive$/,
};
const MAX_ITEMS = 120;
const CONCURRENCY = 12;
const UPSTREAM_TIMEOUT_MS = 45_000;
const UA = 'Mozilla/5.0 (JalDrishti flood-risk research prototype)';

function authorised(req) {
  const expected = process.env.CWC_RELAY_TOKEN || '';
  const given = String(req.headers['x-relay-token'] || '');
  if (expected.length < 16 || given.length !== expected.length) return false;
  return timingSafeEqual(Buffer.from(given), Buffer.from(expected));
}

function targetUrl(pathWithQuery) {
  // Relative paths resolve against CWC; absolute URLs must be an allowed origin and path.
  let url;
  try {
    url = new URL(pathWithQuery, CWC);
  } catch {
    return null;
  }
  const pathRule = Object.hasOwn(ALLOWED, url.origin) ? ALLOWED[url.origin] : null;
  if (!pathRule || url.username || url.password || !pathRule.test(url.pathname)) return null;
  return url;
}

async function upstream(url, className) {
  const headers = { 'User-Agent': UA, Accept: 'application/json' };
  if (className) headers['class-name'] = String(className).slice(0, 80);
  return fetch(url, { headers, signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS) });
}

async function readBody(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (!authorised(req)) return res.status(401).json({ error: 'unauthorised' });

  if (req.method === 'GET') {
    const url = targetUrl(String(req.headers['x-cwc-target'] || ''));
    if (!url) return res.status(400).json({ error: 'target not allowed' });
    try {
      const r = await upstream(url, req.headers['class-name']);
      const text = await r.text();
      res.setHeader('Content-Type', r.headers.get('content-type') || 'application/json');
      return res.status(r.status).send(text);
    } catch (err) {
      return res.status(504).json({ error: `upstream: ${err.name}` });
    }
  }

  if (req.method === 'POST') {
    let body;
    try {
      body = await readBody(req);
    } catch {
      return res.status(400).json({ error: 'invalid JSON' });
    }
    const items = Array.isArray(body?.items) ? body.items.slice(0, MAX_ITEMS) : [];
    const results = new Array(items.length);
    let next = 0;

    async function worker() {
      while (next < items.length) {
        const i = next++;
        const item = items[i] || {};
        const url = targetUrl(String(item.path || ''));
        if (!url) {
          results[i] = { status: 400, data: null };
          continue;
        }
        for (const [k, v] of Object.entries(item.params || {})) url.searchParams.set(k, String(v));
        try {
          const r = await upstream(url, item.className);
          results[i] = { status: r.status, data: r.ok ? await r.json() : null };
        } catch (err) {
          results[i] = { status: 504, data: null, error: err.name };
        }
      }
    }

    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, items.length) }, worker));
    return res.status(200).json({ results });
  }

  res.setHeader('Allow', 'GET, POST');
  return res.status(405).json({ error: 'method not allowed' });
}
