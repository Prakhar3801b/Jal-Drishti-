import { useEffect, useState } from 'react';

/**
 * Minimal hash router.
 *
 * Every page has its own URL (#/rivers, #/hotspots/mumbai, #/location/patna), so a
 * view can be bookmarked, shared with a colleague, or reached with the browser's
 * back button. Hash routing keeps it working from `vite preview` or any static host
 * without server rewrites, and avoids a routing dependency for nine routes.
 */

export const ROUTES = [
  { name: 'home', pattern: /^\/?$/ },
  { name: 'overview', pattern: /^\/map$/ },
  { name: 'state', pattern: /^\/state\/([^/]+)$/, keys: ['state'] },
  { name: 'location', pattern: /^\/location\/([^/]+)$/, keys: ['id'] },
  { name: 'hotspots', pattern: /^\/hotspots(?:\/([^/]+))?$/, keys: ['id'] },
  { name: 'rivers', pattern: /^\/rivers(?:\/([^/]+))?$/, keys: ['river'] },
  { name: 'alerts', pattern: /^\/alerts$/ },
  { name: 'states', pattern: /^\/states$/ },
  { name: 'timemachine', pattern: /^\/time-machine$/ },
  { name: 'about', pattern: /^\/about$/ },
  { name: 'notifications', pattern: /^\/notifications$/ },
  { name: 'plan', pattern: /^\/plan$/ },
  { name: 'resources', pattern: /^\/resources$/ },
  { name: 'apikeys', pattern: /^\/api-keys$/ },
];

export function parseHash(hash) {
  const path = decodeURIComponent((hash || '').replace(/^#/, '').split('?')[0]) || '/';
  for (const r of ROUTES) {
    const m = path.match(r.pattern);
    if (m) {
      const params = {};
      (r.keys || []).forEach((k, i) => {
        if (m[i + 1]) params[k] = m[i + 1];
      });
      return { name: r.name, params, path };
    }
  }
  return { name: 'notfound', params: {}, path };
}

export function useRoute() {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      setRoute(parseHash(window.location.hash));
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}

export function go(path) {
  const target = `#${path.startsWith('/') ? path : `/${path}`}`;
  if (window.location.hash !== target) window.location.hash = target;
}

export const href = (path) => `#${path.startsWith('/') ? path : `/${path}`}`;
