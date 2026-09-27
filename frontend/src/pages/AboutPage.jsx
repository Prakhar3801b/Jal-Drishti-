import { href } from '../lib/router';

/**
 * About JalDrishti: each capability, how it works, and where to see it, followed
 * by the data sources and the known limits.
 */

const hi = (lang) => (lang === 'hi' ? 'font-devanagari' : '');

const ROWS = [
  {
    req: ['Early warning with lead time', 'पूर्व चेतावनी एवं अग्रिम समय'],
    how: [
      'Every place carries an IMD-aligned warning level (Green, Yellow, Orange, Red) with the NDMA action for that level, a stated confidence, and how long the warning holds: a 72 h town trajectory, a 48 h street-ponding timeline, and hours-to-danger for each river gauge',
      'हर स्थान पर IMD अनुरूप चेतावनी स्तर (हरा, पीला, नारंगी, लाल), NDMA कार्रवाई, विश्वसनीयता तथा अग्रिम समय: 72 घंटे का प्रक्षेपवक्र, 48 घंटे की जलभराव समयरेखा व खतरे तक शेष घंटे',
    ],
    link: ['/map', 'Live warning levels'],
  },
  {
    req: ['Multi-source data integration', 'बहु-स्रोत आँकड़ा एकीकरण'],
    how: [
      'Observational weather (hourly rainfall and soil moisture), numerical weather prediction rainfall forecasts, satellite-derived terrain (Copernicus DEM) and satellite-informed hydrological reanalysis and forecast (GloFAS v4), fused with official CWC gauge observations and NDMA/IMD alerts in one score',
      'प्रेक्षित मौसम, संख्यात्मक मौसम पूर्वानुमान वर्षा, उपग्रह-आधारित भूभाग (Copernicus DEM) एवं जल-विज्ञान पुनर्विश्लेषण (GloFAS v4), CWC गेज प्रेक्षण व NDMA/IMD चेतावनियों के साथ एक स्कोर में',
    ],
    link: ['/location/patna', 'See the inputs'],
  },
  {
    req: ['Street-level waterlogging detection', 'गली-स्तरीय जलभराव पहचान'],
    how: [
      '800 m grid per city: DEM low ground, sink depth and D8 flow accumulation; OpenStreetMap drains, roads and built-up land; hourly rain on a 3×3 lattice; an hour-by-hour ponding model',
      'प्रति शहर 800 मी ग्रिड: DEM से निचली भूमि, गड्ढे व जल-प्रवाह संचय; OSM से नालियाँ, सड़कें व निर्मित क्षेत्र; प्रति घंटा वर्षा पर जलभराव मॉडल',
    ],
    link: ['/hotspots/mumbai', 'Street-level hotspots'],
  },
  {
    req: ['Flood propagation between connected places', 'जुड़े स्थानों के बीच बाढ़ का फैलाव'],
    how: [
      'City grid as a flow graph: each hour cells pass water they cannot hold to lower neighbours (slope-weighted), so flooding spreads cell to cell; a no-inflow counterfactual separates cells flooded by their own rain from cells flooded by water from upslope; a 20-run ensemble (rain amount and timing, drain capacity, ±1.5 m terrain) gives flood probability, arrival-time range and an evidence rating; a "likely affected next" list with the path water takes. Between towns, river flood waves are traced from upstream CWC gauges with arrival ranges from wave speed',
      'शहर ग्रिड एक प्रवाह नेटवर्क: हर घंटे कोशिकाएँ अतिरिक्त पानी ढलान से निचली पड़ोसी कोशिकाओं में भेजती हैं, जिससे बाढ़ फैलती है; बिना-अंतर्वाह तुलना से पता चलता है कि बाढ़ अपनी वर्षा से है या ऊपर से आए पानी से; 20 रन का समूह बाढ़ संभावना, पहुँच समय सीमा व साक्ष्य स्तर देता है; "आगे प्रभावित" सूची पानी के रास्ते सहित। शहरों के बीच, ऊपरी CWC गेज से नदी बाढ़ लहर व पहुँच समय',
    ],
    link: ['/hotspots/mumbai', 'Spread & arrival'],
  },
  {
    req: ['Drivers of flood risk and scenarios', 'बाढ़ जोखिम के कारक व परिदृश्य'],
    how: [
      'Ten named factors with weights and point contributions; what-if simulator re-scores real inputs; design-storm and drain-capacity controls on the hotspot map',
      'भार व योगदान सहित दस नामित कारक; क्या-यदि सिम्युलेटर; हॉटस्पॉट नक्शे पर डिज़ाइन तूफ़ान व नाली क्षमता नियंत्रण',
    ],
    link: ['/location/mumbai', 'Location assessment'],
  },
  {
    req: ['Nationwide risk monitoring', 'राष्ट्रव्यापी जोखिम निगरानी'],
    how: [
      '112 towns in all 36 states/UTs scored against IMD colour tiers; live CWC gauges above danger and NDMA/IMD alerts raise scores; anomaly detection flags unusual combinations',
      'सभी 36 राज्यों/केंद्र शासित प्रदेशों में 112 शहर IMD रंग स्तरों पर; CWC गेज व आधिकारिक चेतावनियाँ स्कोर बढ़ाती हैं; असामान्यता पहचान',
    ],
    link: ['/map', 'Overview'],
  },
  {
    req: ['Forecasts: how risk evolves', 'पूर्वानुमान: जोखिम कैसे बदलेगा'],
    how: [
      '72 h town trajectory with ensemble band; 48 h hotspot timeline with play-through; Chronos-Bolt (Hugging Face) forecasts each river gauge 48 h ahead, including time to cross the danger mark',
      'एन्सेम्बल पट्टी सहित 72 घंटे का प्रक्षेपवक्र; 48 घंटे हॉटस्पॉट समयरेखा; Chronos-Bolt से नदी गेज का 48 घंटे पूर्वानुमान',
    ],
    link: ['/rivers', 'Rivers'],
  },
  {
    req: ['Response prioritisation by impact', 'प्रभाव अनुसार प्रतिक्रिया प्राथमिकता'],
    how: [
      'Hotspot priority list = water risk × exposure (urban density, hospitals, schools, road underpasses) with specific actions; state monitor ranks states by gauges above danger and people at risk',
      'हॉटस्पॉट प्राथमिकता = जलभराव जोखिम × प्रभाव (घनत्व, अस्पताल, स्कूल, अंडरपास) व विशिष्ट कार्रवाई; राज्य निगरानी',
    ],
    link: ['/states', 'State monitor'],
  },
  {
    req: ['Confidence and uncertainty', 'विश्वसनीयता व अनिश्चितता'],
    how: [
      'Confidence badge with written reasons (ensemble spread, baseline, gauge availability, model agreement); uncertainty bands on every forecast; hotspot 20-run ensemble with per-cell flood probability, 10–90 % ponding and arrival ranges, and weak-evidence cells drawn dashed',
      'लिखित कारणों सहित विश्वसनीयता; हर पूर्वानुमान पर अनिश्चितता पट्टी; हॉटस्पॉट पर 20 रन का समूह — हर कोशिका की बाढ़ संभावना, 10–90% सीमा, और कमज़ोर साक्ष्य धराशायी',
    ],
    link: ['/location/patna', 'Confidence detail'],
  },
  {
    req: ['Explainable assessments', 'व्याख्या योग्य आकलन'],
    how: [
      'Plain-language narrative in English and Hindi generated from the actual contributions; model attribution (log-odds); similar past floods found by k-NN over 2,699 real days',
      'वास्तविक योगदान से हिंदी व अंग्रेज़ी व्याख्या; मॉडल गुणारोपण; 2,699 वास्तविक दिनों पर k-NN से मिलती-जुलती पिछली बाढ़',
    ],
    link: ['/location/patna', 'Explanation'],
  },
  {
    req: ['Continuous live updates', 'निरंतर लाइव अद्यतन'],
    how: [
      'Weather re-ingested every 90 min and on demand with a change report; all 1,036 CWC gauges re-read every 15 min, re-scoring towns when a nearby river crosses a mark; Time Machine runs the same engine on any past date',
      'हर 90 मिनट व माँग पर मौसम पुनः गणना; सभी 1,036 CWC गेज हर 15 मिनट; टाइम मशीन',
    ],
    link: ['/time-machine', 'Time Machine'],
  },
  {
    req: ['Preparedness and decision support', 'तैयारी व निर्णय-सहायता'],
    how: [
      'NDMA-aligned actions per tier; bilingual public advisory + SMS draft; grounded AI copilot for questions in English or Hindi',
      'NDMA अनुरूप कार्रवाई; द्विभाषी जन-सलाह व SMS; हिंदी/अंग्रेज़ी में प्रश्नों हेतु एआई सहायक',
    ],
    link: ['/alerts', 'Official alerts'],
  },
];

const SOURCES = [
  {
    kind: ['Observational weather', 'प्रेक्षित मौसम'],
    items: ['Open-Meteo — hourly rainfall and soil moisture on a ~5 km analysis grid'],
  },
  {
    kind: ['Numerical weather prediction', 'संख्यात्मक मौसम पूर्वानुमान'],
    items: ['Open-Meteo forecast API — ICON / GFS rainfall out to 7 days, used as the forward-looking input'],
  },
  {
    kind: ['Satellite-derived and reanalysis', 'उपग्रह-आधारित एवं पुनर्विश्लेषण'],
    items: [
      'GloFAS v4 (Copernicus Emergency Management Service) — river discharge with a 30-member ensemble and 1994–2024 climatology',
      'Copernicus DEM GLO-90 (TanDEM-X) — elevation, slope, sinks and flow accumulation',
    ],
  },
  {
    kind: ['Official observations and warnings', 'आधिकारिक प्रेक्षण एवं चेतावनियाँ'],
    items: [
      'Central Water Commission — 1,036 river gauges, hourly levels, warning and danger marks',
      'NDMA SACHET — live CAP alerts issued by IMD, CWC and State DMAs',
    ],
  },
  {
    kind: ['Terrain, drainage and models', 'भूभाग, जल-निकासी एवं मॉडल'],
    items: [
      'OpenStreetMap — drains, roads, land use, hospitals, schools, underpasses',
      'Hugging Face amazon/chronos-bolt-small — 48 h river-level forecasting',
      'Natural Earth — river network geometry',
    ],
  },
];

const LIMITS = [
  [
    'Live Doppler radar is not ingested: IMD and ISRO publish no open radar API. The prototype validates the same pipeline on open satellite-informed data (GloFAS reanalysis and forecast) and NWP rainfall; radar nowcasting is the production upgrade once data sharing is arranged.',
    'लाइव डॉपलर रडार सम्मिलित नहीं: IMD/ISRO का कोई खुला रडार API नहीं है। प्रोटोटाइप वही पाइपलाइन खुले उपग्रह-आधारित आँकड़ों (GloFAS) व NWP वर्षा पर सिद्ध करता है; डेटा साझेदारी के बाद रडार नाउकास्टिंग अगला चरण है।',
  ],
  ['The DEM is 90 m: individual underpasses and kerb-level dips are below its resolution.', 'DEM 90 मी है: अलग-अलग अंडरपास इसकी सूक्ष्मता से छोटे हैं।'],
  ['No open storm-sewer network data exists for Indian cities, so drainage capacity is estimated from mapped drains and land use.', 'भारतीय शहरों के सीवर नेटवर्क के खुले आँकड़े नहीं हैं; नाली क्षमता अनुमानित है।'],
  ['CWC data comes from the endpoints behind its flood-forecast portal, not a documented public API, and may change.', 'CWC आँकड़े उसके पोर्टल के आंतरिक एंडपॉइंट से हैं, प्रलेखित API से नहीं।'],
  ['IMD APIs require IP whitelisting; IMD warnings are read through NDMA SACHET instead.', 'IMD API हेतु IP अनुमति आवश्यक; IMD चेतावनियाँ SACHET से पढ़ी जाती हैं।'],
  ['Historical replays are model-only: past gauge readings and alerts are not archived.', 'ऐतिहासिक पुनरावृत्ति केवल मॉडल आधारित है।'],
];

export default function AboutPage({ lang }) {
  return (
    <div id="main-content" className="mx-auto w-full max-w-[1200px] space-y-5 p-4">
      <div className="border-b-2 border-saffron-500 pb-3">
        <h1 className={`text-2xl font-extrabold tracking-tight text-chakra-500 ${hi(lang)}`}>
          {lang === 'hi' ? 'जलदृष्टि के बारे में' : 'About JalDrishti'}
        </h1>
        <p className={`mt-1 text-[12.5px] text-ink-400 ${hi(lang)}`}>
          {lang === 'hi'
            ? 'एआई/एमएल आधारित एकीकृत भारी वर्षा पूर्व चेतावनी एवं जलभराव पूर्वानुमान प्रणाली — क्षमताएँ, कार्यप्रणाली, आँकड़ा स्रोत और सीमाएँ'
            : 'An AI/ML integrated heavy-rainfall early warning and inundation prediction system — its capabilities, how they work, the data behind them, and their limits'}
        </p>
      </div>

      <div className="panel overflow-x-auto" data-tour="ab-table">
        <table className="w-full text-left text-[12.5px]">
          <thead className="bg-chakra-500 text-[11px] uppercase tracking-wider text-white">
            <tr>
              <th className="px-4 py-3">{lang === 'hi' ? 'क्षमता' : 'Capability'}</th>
              <th className="px-4 py-3">{lang === 'hi' ? 'यह कैसे काम करता है' : 'How it works'}</th>
              <th className="px-4 py-3">{lang === 'hi' ? 'देखें' : 'Explore'}</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map((r, i) => (
              <tr key={i} className="border-t border-ink-800 align-top even:bg-ink-850">
                <td className={`w-[30%] px-4 py-3 font-semibold text-chakra-500 ${hi(lang)}`}>{lang === 'hi' ? r.req[1] : r.req[0]}</td>
                <td className={`px-4 py-3 text-ink-200 ${hi(lang)}`}>{lang === 'hi' ? r.how[1] : r.how[0]}</td>
                <td className="whitespace-nowrap px-4 py-3">
                  <a href={href(r.link[0])} className="font-bold text-saffron-300 hover:underline">{r.link[1]} →</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="panel p-4">
          <h2 className={`text-[13px] font-bold uppercase tracking-wider text-chakra-500 ${hi(lang)}`}>{lang === 'hi' ? 'आँकड़ा स्रोत' : 'Data sources'}</h2>
          <dl className="mt-2 space-y-2.5 text-[12px] text-ink-200">
            {SOURCES.map((g) => (
              <div key={g.kind[0]}>
                <dt className={`text-[10.5px] font-bold uppercase tracking-wider text-ink-500 ${hi(lang)}`}>
                  {lang === 'hi' ? g.kind[1] : g.kind[0]}
                </dt>
                {g.items.map((it) => (
                  <dd key={it} className="ml-0 mt-0.5">• {it}</dd>
                ))}
              </div>
            ))}
          </dl>
        </section>
        <section className="panel p-4">
          <h2 className={`text-[13px] font-bold uppercase tracking-wider text-chakra-500 ${hi(lang)}`}>{lang === 'hi' ? 'ज्ञात सीमाएँ' : 'Known limitations'}</h2>
          <ul className="mt-2 space-y-1.5">
            {LIMITS.map((l) => (
              <li key={l[0]} className={`text-[12px] text-ink-300 ${hi(lang)}`}>• {lang === 'hi' ? l[1] : l[0]}</li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
