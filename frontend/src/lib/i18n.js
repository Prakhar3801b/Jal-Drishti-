/**
 * Bilingual UI strings.
 *
 * The backend already returns every *content* string in both languages (risk
 * narratives, factor labels, NDMA actions), so this file only holds UI chrome.
 * `t(lang, key)` is intentionally dumb — no interpolation library, no lazy
 * loading — because there are two languages and one bundle.
 *
 * Hindi here is written, not machine-translated, and uses the vocabulary the
 * IMD/CWC bulletins use (चेतावनी, प्रवाह, पूर्वानुमान) so it reads as official
 * rather than as a literal gloss of the English.
 */

const STRINGS = {
  // masthead
  appName: { en: 'JalDrishti', hi: 'जलदृष्टि' },
  appNameAlt: { en: 'जलदृष्टि', hi: 'JalDrishti' },
  tagline: {
    en: 'Hyperlocal Rainfall Early Warning & Inundation Prediction',
    hi: 'अति-स्थानीय वर्षा पूर्व चेतावनी एवं जलभराव पूर्वानुमान',
  },
  prototype: { en: 'Prototype', hi: 'प्रोटोटाइप' },
  live: { en: 'Live', hi: 'लाइव' },
  updated: { en: 'Updated', hi: 'अद्यतन' },
  refresh: { en: 'Refresh now', hi: 'अभी अद्यतन करें' },
  refreshing: { en: 'Refreshing…', hi: 'अद्यतन हो रहा है…' },
  nextRefresh: { en: 'Next auto-refresh', hi: 'अगला स्वतः अद्यतन' },

  // navigation
  india: { en: 'India', hi: 'भारत' },
  backToIndia: { en: 'All India', hi: 'सम्पूर्ण भारत' },
  countryView: { en: 'National overview', hi: 'राष्ट्रीय अवलोकन' },
  stateView: { en: 'State view', hi: 'राज्य दृश्य' },
  search: { en: 'Search a city, district or river…', hi: 'शहर, ज़िला या नदी खोजें…' },
  noResults: { en: 'No monitored location matches that.', hi: 'कोई मेल खाता स्थान नहीं मिला।' },

  // national panel
  nationalSituation: { en: 'National situation', hi: 'राष्ट्रीय स्थिति' },
  monitored: { en: 'Monitored locations', hi: 'निगरानी स्थान' },
  peopleExposed: { en: 'People in Orange/Red areas', hi: 'नारंगी/लाल क्षेत्रों में जनसंख्या' },
  highestRisk: { en: 'Highest risk now', hi: 'वर्तमान सर्वाधिक जोखिम' },
  byBasin: { en: 'By river basin', hi: 'नदी बेसिन अनुसार' },
  byState: { en: 'By state', hi: 'राज्य अनुसार' },
  alertLevels: { en: 'Alert levels', hi: 'चेतावनी स्तर' },
  locationsWord: { en: 'locations', hi: 'स्थान' },

  // detail panel
  riskScore: { en: 'Risk score', hi: 'जोखिम स्कोर' },
  outOf100: { en: 'out of 100', hi: '100 में से' },
  whyThisScore: { en: 'Why this score', hi: 'यह स्कोर क्यों' },
  contributingFactors: { en: 'Contributing factors', hi: 'योगदान देने वाले कारक' },
  trajectory: { en: '72-hour risk trajectory', hi: '72-घंटे जोखिम प्रक्षेपवक्र' },
  riverState: { en: 'River discharge', hi: 'नदी प्रवाह' },
  rawData: { en: 'Observed data', hi: 'प्रेक्षित आँकड़े' },
  responseActions: { en: 'Recommended response', hi: 'अनुशंसित प्रतिक्रिया' },
  pastEvents: { en: 'Past flood events here', hi: 'यहाँ की पिछली बाढ़ घटनाएँ' },
  replay: { en: 'Event replay', hi: 'घटना पुनरावृत्ति' },
  replayHelp: {
    en: 'Re-run the model on a past date to see whether it would have flagged a real flood.',
    hi: 'किसी पुरानी तिथि पर मॉडल चलाकर देखें कि वह वास्तविक बाढ़ को चिह्नित करता या नहीं।',
  },
  runReplay: { en: 'Run replay', hi: 'पुनरावृत्ति चलाएँ' },
  selectPrompt: {
    en: 'Select a location on the map to see its hyperlocal assessment.',
    hi: 'अति-स्थानीय आकलन देखने के लिए नक्शे पर कोई स्थान चुनें।',
  },
  confidence: { en: 'Confidence', hi: 'विश्वसनीयता' },
  uncertaintyBand: { en: 'Ensemble uncertainty band', hi: 'एन्सेम्बल अनिश्चितता पट्टी' },
  seasonalNormal: { en: 'Seasonal normal', hi: 'मौसमी सामान्य' },
  forecastWord: { en: 'Forecast', hi: 'पूर्वानुमान' },
  observedWord: { en: 'Observed', hi: 'प्रेक्षित' },
  scoreHistory: { en: 'Score across recent runs', hi: 'हाल के रनों में स्कोर' },

  // observed data rows
  rain24: { en: 'Rainfall, last 24 h', hi: 'पिछले 24 घंटे की वर्षा' },
  rain72: { en: 'Rainfall, last 72 h', hi: 'पिछले 72 घंटे की वर्षा' },
  rain7d: { en: 'Rainfall, last 7 days', hi: 'पिछले 7 दिन की वर्षा' },
  rainNext24: { en: 'Forecast, next 24 h', hi: 'अगले 24 घंटे का पूर्वानुमान' },
  rainNext72: { en: 'Forecast, next 72 h', hi: 'अगले 72 घंटे का पूर्वानुमान' },
  peakHour: { en: 'Wettest hour, last 24 h', hi: 'पिछले 24 घंटे का सर्वाधिक वर्षा घंटा' },
  soilMoisture: { en: 'Soil moisture, top 27 cm', hi: 'ऊपरी 27 सेमी मिट्टी नमी' },
  imdClass: { en: 'IMD rainfall class', hi: 'IMD वर्षा श्रेणी' },
  currentDischarge: { en: 'Current discharge', hi: 'वर्तमान प्रवाह' },
  seasonalMedian: { en: 'Seasonal median', hi: 'मौसमी माध्यिका' },
  percentileSeason: { en: 'Percentile for this season', hi: 'इस मौसम के लिए प्रतिशतक' },
  trend: { en: 'Trend', hi: 'प्रवृत्ति' },
  elevation: { en: 'Elevation', hi: 'ऊँचाई' },
  population: { en: 'Population', hi: 'जनसंख्या' },
  river: { en: 'River', hi: 'नदी' },
  basin: { en: 'Basin', hi: 'बेसिन' },
  district: { en: 'District', hi: 'ज़िला' },
  gaugeCell: { en: 'GloFAS cell used', hi: 'प्रयुक्त ग्लोफास कोशिका' },

  // map
  mapLegend: { en: 'IMD alert scale', hi: 'IMD चेतावनी पैमाना' },
  basemap: { en: 'Base map', hi: 'आधार नक्शा' },
  basemapDark: { en: 'Dark', hi: 'गहरा' },
  basemapSatellite: { en: 'Satellite', hi: 'उपग्रह' },
  basemapNone: { en: 'Boundaries only', hi: 'केवल सीमाएँ' },
  showDistricts: { en: 'District boundaries', hi: 'ज़िला सीमाएँ' },
  clickState: { en: 'Click a state to drill down', hi: 'विस्तार के लिए राज्य पर क्लिक करें' },
  noMonitored: { en: 'No monitored location', hi: 'कोई निगरानी स्थान नहीं' },

  // model / sources
  howItWorks: { en: 'How this is calculated', hi: 'यह कैसे गणना होती है' },
  dataSources: { en: 'Data sources', hi: 'आँकड़ा स्रोत' },
  modelCard: { en: 'Model', hi: 'मॉडल' },
  featureWeights: { en: 'Feature weights', hi: 'कारक भार' },
  sourceHealth: { en: 'Source health', hi: 'स्रोत स्थिति' },
  runLog: { en: 'Recent runs', hi: 'हाल के रन' },
  close: { en: 'Close', hi: 'बंद करें' },

  // states
  loading: { en: 'Loading live data…', hi: 'लाइव आँकड़े लोड हो रहे हैं…' },
  warming: {
    en: 'First ingestion run is in flight. The dashboard will populate in a few seconds.',
    hi: 'पहला आँकड़ा संग्रहण चल रहा है। डैशबोर्ड कुछ ही क्षणों में भर जाएगा।',
  },
  errorTitle: { en: 'Could not load live data', hi: 'लाइव आँकड़े लोड नहीं हो सके' },
  retry: { en: 'Try again', hi: 'पुनः प्रयास करें' },
  changedSinceLast: { en: 'Changed in this refresh', hi: 'इस अद्यतन में परिवर्तित' },
  noChanges: { en: 'No score changed by more than 0.5 points.', hi: 'किसी स्कोर में 0.5 से अधिक परिवर्तन नहीं।' },
};

export function t(lang, key) {
  const row = STRINGS[key];
  if (!row) return key;
  return row[lang] ?? row.en;
}

/** Pick the right half of a bilingual pair returned by the API. */
export function pick(lang, obj, base) {
  if (!obj) return '';
  return lang === 'hi' ? (obj[`${base}_hi`] ?? obj[`${base}_en`]) : obj[`${base}_en`];
}

/** For `{en, hi}` shaped payloads. */
export function pickPlain(lang, obj) {
  if (!obj) return '';
  return lang === 'hi' ? (obj.hi ?? obj.en) : obj.en;
}
