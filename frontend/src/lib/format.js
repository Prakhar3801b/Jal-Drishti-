/**
 * Formatting helpers.
 *
 * Numbers are formatted for an Indian audience: lakh/crore rather than
 * millions/billions, and en-IN digit grouping (12,44,237 not 1,244,237). Getting
 * this wrong is the fastest way to make a government-facing dashboard feel
 * foreign.
 */

export const RISK_COLOURS = {
  green: '#0B8A3D',
  yellow: '#C99700',
  orange: '#E4701E',
  red: '#C1121F',
};

export const TIER_ORDER = ['red', 'orange', 'yellow', 'green'];

export const TIER_LABELS = {
  red: { en: 'Red', hi: 'लाल', action_en: 'Take action', action_hi: 'कार्रवाई करें' },
  orange: { en: 'Orange', hi: 'नारंगी', action_en: 'Be prepared', action_hi: 'तैयार रहें' },
  yellow: { en: 'Yellow', hi: 'पीला', action_en: 'Be aware', action_hi: 'सतर्क रहें' },
  green: { en: 'Green', hi: 'हरा', action_en: 'No warning', action_hi: 'कोई चेतावनी नहीं' },
};

export function tierColour(tier) {
  return RISK_COLOURS[tier] ?? RISK_COLOURS.green;
}

/** Indian numbering: 1,20,00,000 -> "1.2 crore". */
export function compactPopulation(pop) {
  if (!pop || pop <= 0) return '—';
  if (pop >= 1e7) return `${(pop / 1e7).toFixed(pop >= 1e8 ? 0 : 2)} crore`;
  if (pop >= 1e5) return `${(pop / 1e5).toFixed(1)} lakh`;
  if (pop >= 1000) return `${Math.round(pop / 1000)}k`;
  return String(pop);
}

export function inNumber(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toLocaleString('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function mm(value, digits) {
  if (value === null || value === undefined) return '—';
  const d = digits ?? (value >= 10 ? 0 : 1);
  return `${value.toFixed(d)} mm`;
}

export function cumecs(value) {
  if (value === null || value === undefined) return '—';
  if (value >= 10000) return `${inNumber(Math.round(value))} m³/s`;
  if (value >= 100) return `${value.toFixed(0)} m³/s`;
  return `${value.toFixed(1)} m³/s`;
}

export function pct(value, digits = 0) {
  if (value === null || value === undefined) return '—';
  return `${value.toFixed(digits)}%`;
}

/** 97 -> "97th". Used for "the 97th percentile for mid-September". */
export function ordinal(n) {
  if (n === null || n === undefined) return '—';
  const v = Math.round(n);
  const mod100 = v % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${v}th`;
  return `${v}${['th', 'st', 'nd', 'rd'][v % 10] ?? 'th'}`;
}

/** "3 min ago" / "just now" — the data-freshness label, in either language. */
export function relativeAge(seconds, lang = 'en') {
  if (seconds === null || seconds === undefined) return '—';
  const hi = lang === 'hi';
  if (seconds < 45) return hi ? 'अभी' : 'just now';
  if (seconds < 90) return hi ? '1 मिनट पूर्व' : '1 min ago';
  if (seconds < 3600) {
    const m = Math.round(seconds / 60);
    return hi ? `${m} मिनट पूर्व` : `${m} min ago`;
  }
  const hours = seconds / 3600;
  if (hours < 24) {
    const h = hours.toFixed(hours < 10 ? 1 : 0);
    return hi ? `${h} घंटे पूर्व` : `${h} h ago`;
  }
  const d = Math.round(hours / 24);
  return hi ? `${d} दिन पूर्व` : `${d} d ago`;
}

/**
 * Hindi names for states and union territories.
 *
 * Keyed on the 2011 Census `st_nm` spellings the GeoJSON and the API both use, so
 * a lookup miss falls back to the English name rather than breaking. Covers all
 * 36 states and UTs, not just the ones currently monitored, so extending the
 * location set does not leave gaps in the Hindi UI.
 */
const STATE_HI = {
  'Andaman and Nicobar Islands': 'अंडमान एवं निकोबार द्वीपसमूह',
  'Andhra Pradesh': 'आंध्र प्रदेश',
  'Arunachal Pradesh': 'अरुणाचल प्रदेश',
  Assam: 'असम',
  Bihar: 'बिहार',
  Chandigarh: 'चंडीगढ़',
  Chhattisgarh: 'छत्तीसगढ़',
  'Dadra and Nagar Haveli and Daman and Diu': 'दादरा एवं नगर हवेली और दमन एवं दीव',
  Delhi: 'दिल्ली',
  Goa: 'गोवा',
  Gujarat: 'गुजरात',
  Haryana: 'हरियाणा',
  'Himachal Pradesh': 'हिमाचल प्रदेश',
  'Jammu and Kashmir': 'जम्मू एवं कश्मीर',
  Jharkhand: 'झारखंड',
  Karnataka: 'कर्नाटक',
  Kerala: 'केरल',
  Ladakh: 'लद्दाख',
  Lakshadweep: 'लक्षद्वीप',
  'Madhya Pradesh': 'मध्य प्रदेश',
  Maharashtra: 'महाराष्ट्र',
  Manipur: 'मणिपुर',
  Meghalaya: 'मेघालय',
  Mizoram: 'मिज़ोरम',
  Nagaland: 'नागालैंड',
  Odisha: 'ओडिशा',
  Puducherry: 'पुदुचेरी',
  Punjab: 'पंजाब',
  Rajasthan: 'राजस्थान',
  Sikkim: 'सिक्किम',
  'Tamil Nadu': 'तमिल नाडु',
  Telangana: 'तेलंगाना',
  Tripura: 'त्रिपुरा',
  'Uttar Pradesh': 'उत्तर प्रदेश',
  Uttarakhand: 'उत्तराखंड',
  'West Bengal': 'पश्चिम बंगाल',
};

export function stateName(name, lang) {
  if (!name) return name;
  return lang === 'hi' ? (STATE_HI[name] ?? name) : name;
}

export function clockIST(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Kolkata',
    hour12: false,
  });
}

export function dateIST(iso, opts = {}) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    timeZone: 'Asia/Kolkata',
    ...opts,
  });
}

export function longDateIST(iso) {
  return dateIST(iso, { year: 'numeric', weekday: 'short' });
}

/**
 * Map a state name from the API onto the spelling used in the GeoJSON.
 *
 * The boundary file follows the 2011 Census `st_nm` spellings; a couple of
 * locations use the everyday name instead. Only genuine mismatches belong here.
 */
const STATE_ALIASES = {
  Delhi: 'Delhi',
  'NCT of Delhi': 'Delhi',
  Odisha: 'Odisha',
  Uttarakhand: 'Uttarakhand',
  'Jammu and Kashmir': 'Jammu and Kashmir',
  'Jammu & Kashmir': 'Jammu and Kashmir',
  Puducherry: 'Puducherry',
};

export function canonicalState(name) {
  if (!name) return name;
  return STATE_ALIASES[name] ?? name;
}

/** Direction arrow for the trajectory badge. */
export function directionGlyph(key) {
  return key === 'worsening' ? '▲' : key === 'easing' ? '▼' : '▬';
}

export function directionTone(key) {
  if (key === 'worsening') return 'text-risk-red';
  if (key === 'easing') return 'text-indiagreen-300';
  return 'text-ink-400';
}

export const CONFIDENCE_TONE = {
  high: 'text-indiagreen-300 border-indiagreen-500/45 bg-indiagreen-500/10',
  medium: 'text-risk-yellow border-risk-yellow/40 bg-risk-yellow/10',
  low: 'text-risk-orange border-risk-orange/45 bg-risk-orange/10',
};

/**
 * WMO weather codes (as Open-Meteo reports them) to an icon and a short label.
 * Codes are grouped the way the WMO table groups them; night swaps the sun for a moon.
 */
const WMO = [
  [[0], '☀️', '🌙', 'Clear', 'साफ़'],
  [[1, 2], '🌤️', '☁️', 'Partly cloudy', 'आंशिक बादल'],
  [[3], '☁️', '☁️', 'Overcast', 'घने बादल'],
  [[45, 48], '🌫️', '🌫️', 'Fog', 'कोहरा'],
  [[51, 53, 55, 56, 57], '🌦️', '🌧️', 'Drizzle', 'बूंदाबांदी'],
  [[61, 66, 80], '🌦️', '🌧️', 'Light rain', 'हल्की बारिश'],
  [[63, 81], '🌧️', '🌧️', 'Rain', 'बारिश'],
  [[65, 67, 82], '🌧️', '🌧️', 'Heavy rain', 'भारी बारिश'],
  [[71, 73, 75, 77, 85, 86], '🌨️', '🌨️', 'Snow', 'बर्फ़बारी'],
  [[95], '⛈️', '⛈️', 'Thunderstorm', 'आंधी-तूफ़ान'],
  [[96, 99], '⛈️', '⛈️', 'Thunderstorm, hail', 'तूफ़ान, ओले'],
];

export function weatherInfo(code, isDay = true) {
  const row = WMO.find(([codes]) => codes.includes(code));
  if (!row) return { icon: '🌡️', en: 'Weather', hi: 'मौसम' };
  const [, day, night, en, hi] = row;
  return { icon: isDay ? day : night, en, hi };
}

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
export function compass(deg) {
  if (deg === null || deg === undefined) return '';
  return COMPASS[Math.round(deg / 45) % 8];
}
