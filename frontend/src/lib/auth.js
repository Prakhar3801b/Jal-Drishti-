import { useCallback, useEffect, useState } from 'react';
import { api, setAuthToken } from './api';

/**
 * Signed-in session: token + user (role, state, district), kept in localStorage
 * so a reload stays signed in until the token expires.
 *
 * Scope helpers filter what the Advanced tools show to the user's area. The
 * server enforces scope on the area briefing; the national data behind the
 * advanced pages is public, so there the filter keeps the view focused rather
 * than hiding anything secret.
 */

const KEY = 'jd.session';

function load() {
  try {
    const s = JSON.parse(localStorage.getItem(KEY) || 'null');
    if (s?.token && s?.user) return s;
  } catch {
    /* storage blocked or corrupt */
  }
  return null;
}

export function useSession() {
  const [session, setSession] = useState(() => {
    const s = load();
    setAuthToken(s?.token ?? null);
    return s;
  });

  const save = useCallback((s) => {
    setAuthToken(s?.token ?? null);
    setSession(s);
    try {
      if (s) localStorage.setItem(KEY, JSON.stringify(s));
      else localStorage.removeItem(KEY);
    } catch {
      /* non-fatal */
    }
  }, []);

  // Confirm a restored session is still valid; drop it if the server says no.
  useEffect(() => {
    if (!session) return;
    api.me().catch((e) => {
      if (e.status === 401) save(null);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(async (username, password) => save(await api.login(username, password)), [save]);
  const demo = useCallback(async (role, state, district) => save(await api.demoLogin(role, state, district)), [save]);
  const register = useCallback(async (details) => save(await api.register(details)), [save]);
  const logout = useCallback(() => save(null), [save]);

  return { user: session?.user ?? null, login, demo, register, logout };
}

/** Central, state and district officials; citizens get the public-safety view only. */
export function isAdmin(user) {
  return ['central', 'state', 'district'].includes(user?.role);
}

export function inScope(user, loc) {
  if (!user || user.role === 'central') return true;
  if (loc.state !== user.state) return false;
  return user.role === 'state' || loc.district === user.district;
}

export function scopeName(user, lang) {
  if (!user || user.role === 'central') return lang === 'hi' ? 'संपूर्ण भारत' : 'All India';
  return user.role === 'state' ? user.state : `${user.district}, ${user.state}`;
}

export function roleName(user, lang) {
  const names = {
    central: ['Central control room', 'केंद्रीय नियंत्रण कक्ष'],
    state: ['State control room', 'राज्य नियंत्रण कक्ष'],
    district: ['District control room', 'ज़िला नियंत्रण कक्ष'],
    citizen: ['Resident', 'निवासी'],
  };
  const n = names[user?.role] ?? names.central;
  return lang === 'hi' ? n[1] : n[0];
}

/** Last time this user looked, for "what changed since". Read once per sign-in. */
export function lastSeen(user) {
  try {
    return localStorage.getItem(`jd.lastSeen.${user.username}`);
  } catch {
    return null;
  }
}
export function markSeen(user) {
  try {
    localStorage.setItem(`jd.lastSeen.${user.username}`, new Date().toISOString());
  } catch {
    /* non-fatal */
  }
}
