import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { go } from '../lib/router';

/**
 * Guided tutorial: every page and feature, one step at a time.
 *
 * Each step names a route and a `data-tour` marker in the page. The tour
 * navigates there, waits for the element to render (pages load their own data),
 * scrolls it into view and spotlights it with a card beside it. A step whose
 * element is not on screen (hidden on a phone, absent in replay mode) falls back
 * to a centred card, so the tour never stalls.
 *
 * The spotlight does not block the page: people can try a control while its
 * step explains it.
 */

export const TOUR_SEEN_KEY = 'jd.tour.v1';

const CHAPTERS = {
  welcome: { en: 'Welcome', hi: 'स्वागत' },
  myarea: { en: 'My area', hi: 'मेरा क्षेत्र' },
  basics: { en: 'Getting around', hi: 'उपयोग की मूल बातें' },
  overview: { en: 'Risk map', hi: 'जोखिम नक्शा' },
  location: { en: 'City assessment', hi: 'शहर आकलन' },
  hotspots: { en: 'Street-level hotspots', hi: 'गली-स्तरीय हॉटस्पॉट' },
  rivers: { en: 'Rivers', hi: 'नदियाँ' },
  alerts: { en: 'Official alerts', hi: 'आधिकारिक चेतावनियाँ' },
  states: { en: 'State monitor', hi: 'राज्य निगरानी' },
  timemachine: { en: 'Time machine', hi: 'टाइम मशीन' },
  about: { en: 'About & finish', hi: 'परिचय व समापन' },
};

function buildSteps({ sampleLocation, sampleCity, mapPath = '/map', role = 'central' }) {
  const loc = sampleLocation ? `/location/${sampleLocation}` : '/';
  const city = sampleCity ? `/hotspots/${sampleCity}` : '/hotspots';
  const steps = [
    // ------------------------------------------------------------ welcome
    {
      chapter: 'welcome',
      route: '/',
      target: null,
      title: { en: 'Welcome to JalDrishti', hi: 'जलदृष्टि में आपका स्वागत है' },
      body: {
        en: [
          'JalDrishti is an early-warning system for heavy rain and flooding across India. It combines weather observations, rainfall forecasts, river-flow models, terrain and official government gauges into one warning level per place — and shows you only your own area: all of India for Central, your state or your district.',
          'This tour walks through every screen and feature in {N} short steps. Use Next / Back, the arrow keys, or Contents to jump to a section. You can leave at any time and replay it from the Tutorial button.',
        ],
        hi: [
          'जलदृष्टि पूरे भारत के लिए भारी वर्षा और बाढ़ की पूर्व चेतावनी प्रणाली है। यह मौसम प्रेक्षण, वर्षा पूर्वानुमान, नदी-प्रवाह मॉडल, भूभाग और सरकारी गेज आँकड़ों को मिलाकर हर स्थान के लिए एक चेतावनी स्तर देती है — और आपको केवल आपका क्षेत्र दिखाती है: केंद्र हेतु पूरा भारत, या आपका राज्य या ज़िला।',
          'यह ट्यूटोरियल {N} छोटे चरणों में हर स्क्रीन और सुविधा दिखाता है। आगे / पीछे, तीर कुंजियाँ या "विषय-सूची" से किसी भी भाग पर जाएँ। आप कभी भी बाहर निकल सकते हैं और "ट्यूटोरियल" बटन से दोबारा देख सकते हैं।',
        ],
      },
    },

    // ------------------------------------------------------------ my area
    {
      chapter: 'myarea',
      route: '/',
      target: 'my-status',
      title: { en: 'Your area at a glance', hi: 'आपका क्षेत्र एक नज़र में' },
      body: {
        en: ['The big circle is the most serious warning anywhere in your area, in the IMD colours: Green (normal), Yellow (be aware), Orange (be prepared), Red (take action). Beside it, how many places are at each colour. It updates on its own.'],
        hi: ['बड़ा वृत्त आपके क्षेत्र की सबसे गंभीर चेतावनी है, IMD रंगों में: हरा (सामान्य), पीला (सतर्क रहें), नारंगी (तैयार रहें), लाल (कार्रवाई करें)। बगल में, कितने स्थान किस रंग पर हैं। यह अपने-आप अद्यतन होता है।'],
      },
    },
    {
      chapter: 'myarea',
      route: '/',
      target: 'my-alerts',
      title: { en: 'Alerts — act on these', hi: 'चेतावनियाँ — इन पर कार्रवाई करें' },
      body: {
        en: [
          'Created automatically: places at Orange or Red, places that just got worse, rivers above danger, flood waves heading your way, and official IMD/CWC/SDMA alerts. Each says what to do.',
          '"Ready-made advisory & SMS" opens a drafted public advisory and SMS for that place — review, then copy with one click. New alerts also pop up in the corner on any screen.',
        ],
        hi: [
          'अपने-आप बनती हैं: नारंगी या लाल स्थान, अभी बिगड़े स्थान, खतरे से ऊपर नदियाँ, आपकी ओर आती बाढ़ लहरें, और आधिकारिक IMD/CWC/SDMA चेतावनियाँ। हर एक बताती है कि क्या करना है।',
          '"तैयार सलाह व SMS" उस स्थान के लिए तैयार जन-सलाह और SMS खोलता है — जाँचें, फिर एक क्लिक में कॉपी करें। नई चेतावनियाँ किसी भी स्क्रीन पर कोने में अपने-आप दिखती हैं।',
        ],
      },
    },
    {
      chapter: 'myarea',
      route: '/',
      target: 'my-brief',
      title: { en: "Today's brief", hi: 'आज का सारांश' },
      body: {
        en: ['A few plain sentences written automatically for your area: how things stand, the highest risk, what is expected next, rivers and official alerts, and what changed since you last looked.'],
        hi: ['आपके क्षेत्र के लिए अपने-आप लिखे कुछ सरल वाक्य: स्थिति, सबसे अधिक जोखिम, आगे क्या अपेक्षित है, नदियाँ व आधिकारिक चेतावनियाँ, और पिछली बार से क्या बदला।'],
      },
    },
    {
      chapter: 'myarea',
      route: '/',
      target: 'my-next',
      title: { en: 'Coming next', hi: 'आगे क्या' },
      body: {
        en: ['Places expected to get worse in the next 3 days and when, and river flood waves on their way with an arrival time range.'],
        hi: ['अगले 3 दिनों में कौन-से स्थान बिगड़ सकते हैं और कब, और रास्ते में आती नदी बाढ़ लहरें पहुँच समय सीमा सहित।'],
      },
    },
    {
      chapter: 'myarea',
      route: '/',
      target: 'my-changes',
      title: { en: 'Since you last looked', hi: 'पिछली बार से बदलाव' },
      body: {
        en: ['Which places got worse (▲) or better (▼) since your previous visit, so you never have to compare by memory.'],
        hi: ['आपकी पिछली यात्रा के बाद कौन-से स्थान बिगड़े (▲) या सुधरे (▼) — याद से तुलना करने की ज़रूरत नहीं।'],
      },
    },
    {
      chapter: 'myarea',
      route: '/',
      target: 'my-places',
      title: { en: 'Places in your area', hi: 'आपके क्षेत्र के स्थान' },
      body: {
        en: ['Every monitored place in your area, worst first, with its score, trend and current weather. Click one for its full assessment.'],
        hi: ['आपके क्षेत्र का हर निगरानी स्थान, सबसे गंभीर पहले — स्कोर, रुझान और वर्तमान मौसम सहित। पूरे आकलन के लिए क्लिक करें।'],
      },
    },

    // ------------------------------------------------------------- basics
    {
      chapter: 'basics',
      route: '/',
      target: 'nav-notify',
      title: { en: 'Alerts on your phone and email', hi: 'फ़ोन व ईमेल पर चेतावनियाँ' },
      body: {
        en: ['Add your email, WhatsApp or phone number and alerts for your area reach you automatically — a message as soon as a place gets worse, a phone call for Red, an all-clear, and the daily brief. On WhatsApp you can reply ACK, "status", or ask a question.'],
        hi: ['अपना ईमेल, व्हाट्सऐप या फ़ोन नंबर जोड़ें और आपके क्षेत्र की चेतावनियाँ अपने-आप आप तक पहुँचेंगी — स्थिति बिगड़ते ही संदेश, लाल पर फ़ोन कॉल, सब-सामान्य संदेश और दैनिक सारांश। व्हाट्सऐप पर ACK, "status" या प्रश्न भेज सकते हैं।'],
      },
    },
    {
      chapter: 'basics',
      route: '/',
      target: 'nav-advanced',
      title: { en: 'Advanced tools', hi: 'उन्नत उपकरण' },
      body: {
        en: [
          'My area is all most people need. The detailed screens live under Advanced tools — risk map, street-level hotspots, rivers, official alerts, time machine and about — already filtered to your area. The rest of this tour visits each one.',
        ],
        hi: [
          'अधिकतर लोगों के लिए "मेरा क्षेत्र" पर्याप्त है। विस्तृत स्क्रीन "उन्नत उपकरण" में हैं — जोखिम नक्शा, गली-स्तरीय हॉटस्पॉट, नदियाँ, आधिकारिक चेतावनियाँ, टाइम मशीन और परिचय — पहले से आपके क्षेत्र तक सीमित। यह ट्यूटोरियल आगे हर एक दिखाता है।',
        ],
      },
    },
    {
      chapter: 'basics',
      route: '/',
      target: 'account',
      title: { en: 'Your account', hi: 'आपका खाता' },
      body: {
        en: ['Shows which area you are signed in for. Sign out to switch — Central sees all India, a State official one state, a District official one district.'],
        hi: ['दिखाता है कि आप किस क्षेत्र के लिए प्रवेश किए हैं। बदलने के लिए बाहर निकलें — केंद्र पूरा भारत, राज्य अधिकारी एक राज्य, ज़िला अधिकारी एक ज़िला देखते हैं।'],
      },
    },
    {
      chapter: 'basics',
      route: '/',
      target: 'search',
      title: { en: 'Search any place', hi: 'कोई भी स्थान खोजें' },
      body: {
        en: ['Type a city, district or river (English or Hindi) to jump straight to its full assessment. Press / from anywhere to focus the search box.'],
        hi: ['किसी शहर, ज़िले या नदी का नाम (अंग्रेज़ी या हिंदी) लिखें और सीधे उसके पूरे आकलन पर जाएँ। कहीं से भी / दबाकर खोज पर पहुँचें।'],
      },
    },
    {
      chapter: 'basics',
      route: '/',
      target: 'live',
      title: { en: 'Always up to date — automatically', hi: 'हमेशा अद्यतन — अपने-आप' },
      body: {
        en: ['Nothing to refresh. The system re-reads weather, rivers and forecasts every 90 minutes and river gauges every 15 minutes, and the screen checks for new results every minute. This shows how old the data is and when the next update is due.'],
        hi: ['कुछ भी ताज़ा करने की ज़रूरत नहीं। प्रणाली हर 90 मिनट में मौसम, नदियाँ व पूर्वानुमान और हर 15 मिनट में नदी गेज दोबारा पढ़ती है, और स्क्रीन हर मिनट नए परिणाम देखती है। यह दिखाता है कि आँकड़े कितने पुराने हैं और अगला अद्यतन कब है।'],
      },
    },
    {
      chapter: 'basics',
      route: '/',
      target: 'copilot',
      title: { en: 'AI Copilot', hi: 'एआई सहायक' },
      body: {
        en: ['Ask questions in plain language — "Which towns in Assam are rising?" or "Why is Patna orange?". Answers are grounded in the current risk table; each reply says which AI (or the offline rule-based answerer) produced it.'],
        hi: ['सरल भाषा में पूछें — "असम में किन शहरों का जोखिम बढ़ रहा है?" या "पटना नारंगी क्यों है?"। उत्तर वर्तमान जोखिम तालिका पर आधारित होते हैं; हर उत्तर बताता है कि किस एआई (या ऑफ़लाइन नियम-आधारित प्रणाली) ने दिया।'],
      },
    },
    {
      chapter: 'basics',
      route: '/',
      target: 'system',
      title: { en: 'How it is calculated', hi: 'गणना कैसे होती है' },
      body: {
        en: ['Opens the model card: the scoring formula and weights, the IMD four-colour alert scale, every data source with its licence and live health, and the log of recent runs.'],
        hi: ['मॉडल कार्ड खोलता है: स्कोर का सूत्र व भार, IMD का चार-रंग चेतावनी पैमाना, हर आँकड़ा स्रोत उसके लाइसेंस व स्थिति सहित, और हाल के रन का लॉग।'],
      },
    },
    {
      chapter: 'basics',
      route: '/',
      target: 'access',
      title: { en: 'Language and text size', hi: 'भाषा और अक्षर आकार' },
      body: {
        en: ['Switch the whole interface between English and हिंदी, and make text smaller or larger (A- / A / A+). Both choices are remembered.'],
        hi: ['पूरा इंटरफ़ेस अंग्रेज़ी और हिंदी के बीच बदलें, और अक्षर छोटे या बड़े करें (A- / A / A+)। दोनों विकल्प याद रखे जाते हैं।'],
      },
    },
    {
      chapter: 'basics',
      route: '/',
      target: 'footer',
      title: { en: 'Status bar', hi: 'स्थिति पट्टी' },
      body: {
        en: ['The disclaimer, plus run number, places scored, how long the run took, the climatology baseline in use and the version. This is a research prototype — for official warnings follow IMD, CWC and your State Disaster Management Authority.'],
        hi: ['अस्वीकरण, साथ में रन संख्या, आँके गए स्थान, रन का समय, प्रयुक्त जलवायु आधार-रेखा और संस्करण। यह शोध प्रोटोटाइप है — आधिकारिक चेतावनी हेतु IMD, CWC व राज्य आपदा प्रबंधन प्राधिकरण देखें।'],
      },
    },

    // ----------------------------------------------------------- overview
    {
      chapter: 'overview',
      route: mapPath,
      target: 'ov-map',
      title: { en: 'The India risk map', hi: 'भारत जोखिम नक्शा' },
      body: {
        en: [
          'Each state is coloured by its highest-risk town, and each dot is a monitored place sized by population. Click a state to drill down to its districts and towns; click a dot to see that place.',
        ],
        hi: ['हर राज्य का रंग उसके सबसे अधिक जोखिम वाले शहर के अनुसार है, और हर बिंदु एक निगरानी स्थान है (आकार = जनसंख्या)। किसी राज्य पर क्लिक करके उसके ज़िले और शहर देखें; बिंदु पर क्लिक करके वह स्थान।'],
      },
    },
    {
      chapter: 'overview',
      route: mapPath,
      target: 'ov-layers',
      title: { en: 'Basemap and layers', hi: 'आधार नक्शा और परतें' },
      body: {
        en: ['Switch between a light map, streets and satellite imagery. Toggle layers: town risk scores, CWC river gauges above warning or danger (click one for its hydrograph), and official alert areas.'],
        hi: ['सरल नक्शा, सड़कें या उपग्रह चित्र चुनें। परतें चालू/बंद करें: शहर जोखिम स्कोर, चेतावनी/खतरे से ऊपर CWC नदी गेज (क्लिक करने पर जल-स्तर ग्राफ़), और आधिकारिक चेतावनी क्षेत्र।'],
      },
    },
    {
      chapter: 'overview',
      route: mapPath,
      target: 'ov-legend',
      title: { en: 'The IMD four-colour scale', hi: 'IMD चार-रंग पैमाना' },
      body: {
        en: ['• Green (0–24): no warning\n• Yellow (25–49): be aware\n• Orange (50–74): be prepared\n• Red (75–100): take action\nThe counts show how many places sit in each band right now.'],
        hi: ['• हरा (0–24): कोई चेतावनी नहीं\n• पीला (25–49): सतर्क रहें\n• नारंगी (50–74): तैयार रहें\n• लाल (75–100): कार्रवाई करें\nसंख्याएँ बताती हैं कि अभी कितने स्थान किस स्तर पर हैं।'],
      },
    },
    {
      chapter: 'overview',
      route: mapPath,
      target: 'ov-left',
      nonCentral: true,
      title: { en: 'Your state in detail', hi: 'आपका राज्य विस्तार से' },
      body: {
        en: ['Your state with its districts drawn on the map, how many places are at each level, people in Orange and Red areas, and every monitored place ranked by score. Click one to preview it on the right.'],
        hi: ['आपका राज्य, नक्शे पर ज़िलों सहित — कितने स्थान किस स्तर पर, नारंगी व लाल क्षेत्रों में लोग, और हर निगरानी स्थान स्कोर के क्रम में। दाईं ओर पूर्वावलोकन के लिए किसी पर क्लिक करें।'],
      },
    },
    {
      chapter: 'overview',
      route: mapPath,
      target: 'ov-national',
      centralOnly: true,
      title: { en: 'National situation', hi: 'राष्ट्रीय स्थिति' },
      body: {
        en: ['How many places are at each level, how many people live in Orange and Red areas, and a one-line national summary.'],
        hi: ['कितने स्थान किस स्तर पर हैं, नारंगी व लाल क्षेत्रों में कितने लोग रहते हैं, और एक पंक्ति का राष्ट्रीय सारांश।'],
      },
    },
    {
      chapter: 'overview',
      route: mapPath,
      target: 'ov-watchlist',
      centralOnly: true,
      title: { en: 'Highest-risk watchlist', hi: 'सर्वाधिक जोखिम सूची' },
      body: {
        en: ['The places to look at first, ranked by score, with whether each is rising or easing. Click one to preview it on the right.'],
        hi: ['पहले देखे जाने वाले स्थान, स्कोर के क्रम में, साथ में जोखिम बढ़ रहा है या घट रहा है। दाईं ओर पूर्वावलोकन के लिए किसी पर क्लिक करें।'],
      },
    },
    {
      chapter: 'overview',
      route: mapPath,
      target: 'ov-rollup',
      centralOnly: true,
      title: { en: 'By state and by river basin', hi: 'राज्य व नदी बेसिन अनुसार' },
      body: {
        en: ['Roll-ups in the two ways flood response is organised: by state (NDMA/SDMA) and by CWC river basin, so a basin-wide flood is visible even when it crosses state lines.'],
        hi: ['बाढ़ प्रबंधन के दोनों तरीकों से सारांश: राज्य अनुसार (NDMA/SDMA) और CWC नदी बेसिन अनुसार, ताकि राज्य-सीमा पार करने वाली बाढ़ भी दिखे।'],
      },
    },
    {
      chapter: 'overview',
      route: mapPath,
      target: 'ov-right',
      title: { en: 'Place preview', hi: 'स्थान पूर्वावलोकन' },
      body: {
        en: ['A quick read of the selected place — score, colour, confidence, the main reasons and the 72-hour outlook — with a link to its full assessment. Next, we open one.'],
        hi: ['चुने गए स्थान का त्वरित विवरण — स्कोर, रंग, विश्वसनीयता, मुख्य कारण और 72 घंटे का रुझान — पूरे आकलन के लिंक सहित। आगे हम एक स्थान खोलते हैं।'],
      },
    },

    // ----------------------------------------------------------- location
    {
      chapter: 'location',
      route: loc,
      target: 'loc-risk',
      title: { en: 'Risk score', hi: 'जोखिम स्कोर' },
      body: {
        en: [
          'The 0–100 score and its IMD colour, how confident the system is, and whether risk is rising or easing. Underneath: the model score, the trained machine-learning probability and the rule score, so you can see where the number comes from.',
        ],
        hi: ['0–100 स्कोर और उसका IMD रंग, प्रणाली की विश्वसनीयता, और जोखिम बढ़ रहा है या घट रहा है। नीचे: मॉडल स्कोर, प्रशिक्षित मशीन-लर्निंग संभावना और नियम स्कोर — ताकि पता चले संख्या कहाँ से आई।'],
      },
    },
    {
      chapter: 'location',
      route: loc,
      target: 'loc-official',
      title: { en: 'Official government data', hi: 'आधिकारिक सरकारी आँकड़े' },
      body: {
        en: ['The nearest Central Water Commission gauge — its level against warning and danger marks — and any IMD/CWC/SDMA alert covering this place. When official data shows more danger than the model, it raises the score and says so.'],
        hi: ['निकटतम केंद्रीय जल आयोग गेज — चेतावनी व खतरे के निशान के सापेक्ष स्तर — और इस स्थान पर लागू कोई IMD/CWC/SDMA चेतावनी। जब आधिकारिक आँकड़े मॉडल से अधिक खतरा दिखाते हैं, तो स्कोर बढ़ता है और इसका कारण लिखा जाता है।'],
      },
    },
    {
      chapter: 'location',
      route: loc,
      target: 'loc-upstream',
      title: { en: 'Flood wave coming downstream', hi: 'ऊपर से आती बाढ़ लहर' },
      body: {
        en: ['Flooding travels between places along rivers. This lists CWC gauges upstream on the same river that are above warning or rising towards danger, how far away they are, and when that water could arrive here — as a range from typical flood-wave speeds, with an evidence rating (weaker when the gauge is falling or the reach is long).'],
        hi: ['बाढ़ नदियों के साथ एक स्थान से दूसरे तक जाती है। यहाँ उसी नदी पर ऊपर की ओर के CWC गेज हैं जो चेतावनी से ऊपर हैं या खतरे की ओर बढ़ रहे हैं — कितनी दूर, और वह पानी यहाँ कब पहुँच सकता है — सामान्य बाढ़-लहर गति से एक सीमा के रूप में, साक्ष्य स्तर सहित (गेज घट रहा हो या दूरी लंबी हो तो कमज़ोर)।'],
      },
    },
    {
      chapter: 'location',
      route: loc,
      target: 'loc-why',
      title: { en: 'Why this score', hi: 'यह स्कोर क्यों' },
      body: {
        en: ['A plain-language explanation of what is driving the risk — rainfall, river flow against its seasonal normal, soil saturation, terrain — in English or Hindi.'],
        hi: ['जोखिम किस कारण है, इसकी सरल भाषा में व्याख्या — वर्षा, मौसमी सामान्य के सापेक्ष नदी प्रवाह, मिट्टी की नमी, भूभाग — हिंदी या अंग्रेज़ी में।'],
      },
    },
    {
      chapter: 'location',
      route: loc,
      target: 'loc-actions',
      title: { en: 'Response actions and CAP 1.2', hi: 'प्रतिक्रिया कार्य और CAP 1.2' },
      body: {
        en: ['What the IMD colour means and the matching NDMA response actions. For Yellow, Orange and Red places, the link opens the same warning as an OASIS CAP 1.2 alert — the XML format NDMA SACHET, IMD and CWC exchange (marked Exercise, never official).'],
        hi: ['IMD रंग का अर्थ और उससे जुड़े NDMA प्रतिक्रिया कार्य। पीले, नारंगी और लाल स्थानों के लिए लिंक वही चेतावनी OASIS CAP 1.2 प्रारूप में खोलता है — वह XML प्रारूप जो NDMA SACHET, IMD और CWC उपयोग करते हैं (अभ्यास के रूप में चिह्नित, आधिकारिक नहीं)।'],
      },
    },
    {
      chapter: 'location',
      route: loc,
      target: 'loc-trajectory',
      title: { en: '72-hour trajectory', hi: '72 घंटे का रुझान' },
      body: {
        en: ['How the risk is expected to evolve over the next 24, 48 and 72 hours, re-scored against forecast rain and river flow. The shaded band is the ensemble uncertainty — the wider it is, the less certain the forecast.'],
        hi: ['अगले 24, 48 और 72 घंटों में जोखिम कैसे बदलेगा, पूर्वानुमानित वर्षा व नदी प्रवाह के आधार पर। छायांकित पट्टी अनिश्चितता है — जितनी चौड़ी, पूर्वानुमान उतना कम निश्चित।'],
      },
    },
    {
      chapter: 'location',
      route: loc,
      target: 'loc-river',
      title: { en: 'River against its seasonal normal', hi: 'मौसमी सामान्य के सापेक्ष नदी' },
      body: {
        en: ['River discharge from GloFAS compared with 30 years (1994–2024) of the same time of year. "97th percentile" means higher than on 97% of comparable days.'],
        hi: ['GloFAS नदी प्रवाह की तुलना पिछले 30 वर्षों (1994–2024) में साल के इसी समय से। "97वाँ प्रतिशतक" यानी तुलनीय दिनों के 97% से अधिक।'],
      },
    },
    {
      chapter: 'location',
      route: loc,
      target: 'loc-factors',
      title: { en: 'Contributing factors', hi: 'योगदान देने वाले कारक' },
      body: {
        en: ['Each input\'s share of the score — recent rain, forecast rain, river flow, soil moisture, terrain, flood history — so the biggest driver is obvious.'],
        hi: ['स्कोर में हर इनपुट का हिस्सा — हाल की वर्षा, पूर्वानुमानित वर्षा, नदी प्रवाह, मिट्टी की नमी, भूभाग, बाढ़ इतिहास — ताकि मुख्य कारण स्पष्ट हो।'],
      },
    },
    {
      chapter: 'location',
      route: loc,
      target: 'loc-raw',
      title: { en: 'Observed data', hi: 'प्रेक्षित आँकड़े' },
      body: {
        en: ['The raw numbers behind the score, each with its source, so any value can be checked.'],
        hi: ['स्कोर के पीछे के मूल आँकड़े, हर एक का स्रोत सहित, ताकि किसी भी मान की जाँच हो सके।'],
      },
    },
    {
      chapter: 'location',
      route: loc,
      target: 'loc-history',
      title: { en: 'Score history', hi: 'स्कोर इतिहास' },
      body: {
        en: ['How this place\'s score has moved over recent refreshes.'],
        hi: ['हाल के रिफ़्रेश में इस स्थान का स्कोर कैसे बदला।'],
      },
    },
    {
      chapter: 'location',
      route: loc,
      target: 'loc-ai',
      title: { en: 'AI / ML assessment', hi: 'एआई / एमएल आकलन' },
      body: {
        en: ['Independent machine-learning reads of the same data: a trained logistic model, the most similar real past days (k-nearest analogs), an anomaly detector, and a second rainfall forecast to check model agreement.'],
        hi: ['उन्हीं आँकड़ों पर स्वतंत्र मशीन-लर्निंग आकलन: प्रशिक्षित लॉजिस्टिक मॉडल, सबसे मिलते-जुलते वास्तविक पुराने दिन (k-निकटतम), असामान्यता पहचान, और मॉडल सहमति जाँचने हेतु दूसरा वर्षा पूर्वानुमान।'],
      },
    },
    {
      chapter: 'location',
      route: loc,
      target: 'loc-whatif',
      title: { en: 'What-if simulator', hi: 'क्या-हो-अगर सिम्युलेटर' },
      body: {
        en: ['Add extra rain in the past or next 24 hours, or scale the river flow, and re-score through the real engine: "what if another 100 mm falls tonight?"'],
        hi: ['पिछले या अगले 24 घंटों में अतिरिक्त वर्षा जोड़ें, या नदी प्रवाह बढ़ाएँ, और असली इंजन से पुनर्मूल्यांकन करें: "अगर आज रात 100 मिमी और बरसे तो?"'],
      },
    },
    {
      chapter: 'location',
      route: loc,
      target: 'loc-advisory',
      title: { en: 'Public advisory generator', hi: 'जन-सलाह जनरेटर' },
      body: {
        en: ['Drafts a bilingual public advisory and a short SMS from the current assessment, ready for an officer to review. It says whether an AI model or the offline template wrote it.'],
        hi: ['वर्तमान आकलन से द्विभाषी जन-सलाह और छोटा SMS तैयार करता है, अधिकारी की समीक्षा हेतु। बताता है कि इसे एआई मॉडल ने लिखा या ऑफ़लाइन टेम्पलेट ने।'],
      },
    },
    {
      chapter: 'location',
      route: loc,
      target: 'loc-replay',
      title: { en: 'Event replay (back-test)', hi: 'घटना पुनरावृत्ति (बैक-टेस्ट)' },
      body: {
        en: ['Pick a past flood and the system re-runs the exact same scoring on archived data for that day, then shows whether it would have warned: hit, miss or false alarm — all reported honestly.'],
        hi: ['कोई पुरानी बाढ़ चुनें — प्रणाली उस दिन के संग्रहीत आँकड़ों पर वही गणना दोबारा चलाती है और बताती है कि क्या चेतावनी दी जाती: सही, चूक या झूठा अलार्म — सब ईमानदारी से।'],
      },
    },
    {
      chapter: 'location',
      route: loc,
      target: 'loc-events',
      optional: true, // absent for a place with no recorded floods
      title: { en: 'Past flood events', hi: 'पुरानी बाढ़ घटनाएँ' },
      body: {
        en: ['Documented floods at this place from the historical register. Flood history also feeds the score.'],
        hi: ['ऐतिहासिक रजिस्टर से इस स्थान की दर्ज बाढ़ें। बाढ़ इतिहास भी स्कोर में शामिल होता है।'],
      },
    },

    // ----------------------------------------------------------- hotspots
    {
      chapter: 'hotspots',
      route: city,
      target: 'hs-city',
      title: { en: 'Street-level waterlogging', hi: 'गली-स्तरीय जलभराव' },
      body: {
        en: ['City weather cannot say which streets flood. This screen splits a city into an 800 m grid and estimates, hour by hour, where water collects. Pick any monitored city here.'],
        hi: ['शहर का मौसम यह नहीं बताता कि कौन-सी गलियाँ डूबेंगी। यह स्क्रीन शहर को 800 मीटर ग्रिड में बाँटकर घंटा-दर-घंटा अनुमान लगाती है कि पानी कहाँ जमा होगा। यहाँ कोई भी शहर चुनें।'],
      },
    },
    {
      chapter: 'hotspots',
      route: city,
      target: 'hs-map',
      title: { en: 'The water-accumulation grid', hi: 'जलभराव ग्रिड' },
      body: {
        en: [
          'The city is a connected flow network. Every hour each cell gains rain runoff plus water flowing in from higher neighbours, loses what its drains carry away, and passes what it cannot hold to its lower neighbours — so flooding spreads from cell to cell over time.',
          'Terrain comes from a 90 m elevation model, drains and roads from OpenStreetMap, rain hour by hour. Numbered pins are response priorities; click any cell for its details.',
        ],
        hi: [
          'शहर एक जुड़ा हुआ प्रवाह नेटवर्क है। हर घंटे हर कोशिका को वर्षा का बहाव और ऊँची पड़ोसी कोशिकाओं से आया पानी मिलता है, नालियाँ जितना ले जाएँ वह निकलता है, और जो वह नहीं रख पाती वह निचली कोशिकाओं में जाता है — इस तरह बाढ़ समय के साथ फैलती है।',
          'भूभाग 90 मीटर ऊँचाई मॉडल से, नालियाँ व सड़कें OpenStreetMap से, वर्षा घंटा-दर-घंटा। क्रमांकित पिन प्राथमिकता क्रम हैं; विवरण के लिए किसी कोशिका पर क्लिक करें।',
        ],
      },
    },
    {
      chapter: 'hotspots',
      route: city,
      target: 'hs-mode',
      title: { en: 'Four views', hi: 'चार दृश्य' },
      body: {
        en: ['• Water at selected hour — ponding at the hour on the time slider\n• Peak in next 24 h — the worst each cell gets\n• Spread & arrival — when water reaches each cell (red = soon), faded by how likely it is; dashed outline = weak evidence\n• Terrain susceptibility — where water would collect first, rain or not (useful for pre-monsoon planning)'],
        hi: ['• चुने घंटे पर जलभराव — समय स्लाइडर वाले घंटे पर\n• अगले 24 घंटे का शिखर — हर कोशिका की सबसे बुरी स्थिति\n• फैलाव व पहुँच समय — पानी हर कोशिका तक कब पहुँचेगा (लाल = जल्दी), संभावना के अनुसार हल्का-गहरा; धराशायी किनारा = कमज़ोर साक्ष्य\n• भूभाग संवेदनशीलता — बारिश हो या न हो, पानी पहले कहाँ जमेगा (मानसून-पूर्व योजना हेतु)'],
      },
    },
    {
      chapter: 'hotspots',
      route: city,
      target: 'hs-flow',
      title: { en: 'Water flow arrows', hi: 'जल प्रवाह तीर' },
      body: {
        en: ['Blue arrows show water moving from each cell to the lower neighbour it drains into, thicker where more water flows. In "Water at selected hour" they show that hour\'s flow, so playing the timeline shows the flood travelling across the city.'],
        hi: ['नीले तीर दिखाते हैं कि पानी हर कोशिका से किस निचली पड़ोसी कोशिका में जाता है — जहाँ ज़्यादा पानी, वहाँ मोटा तीर। "चुने घंटे पर जलभराव" में वे उस घंटे का प्रवाह दिखाते हैं, तो समय चलाने पर बाढ़ शहर में आगे बढ़ती दिखती है।'],
      },
    },
    {
      chapter: 'hotspots',
      route: city,
      target: 'hs-storm',
      title: { en: 'Design-storm scenarios', hi: 'वर्षा परिदृश्य' },
      body: {
        en: ['Live forecast uses real rain. The 20, 50 and 90 mm/h buttons run a 3-hour storm instead, answering the planner\'s question "what happens in a cloudburst?" even on a dry day — and switch to the Spread view so you can watch the water move.'],
        hi: ['लाइव पूर्वानुमान असली वर्षा उपयोग करता है। 20, 50 और 90 मिमी/घंटा बटन 3 घंटे का तूफ़ान चलाते हैं — सूखे दिन भी योजनाकार का प्रश्न "बादल फटे तो क्या होगा?" हल करते हैं।'],
      },
    },
    {
      chapter: 'hotspots',
      route: city,
      target: 'hs-drain',
      title: { en: 'Drain capacity', hi: 'नाली क्षमता' },
      body: {
        en: ['Slide below 1.0× to model blocked or silted drains, above to model cleaned or upgraded ones, and watch the hotspots change.'],
        hi: ['जाम या गाद भरी नालियों के लिए 1.0× से कम, साफ़ या बेहतर नालियों के लिए अधिक करें, और हॉटस्पॉट बदलते देखें।'],
      },
    },
    {
      chapter: 'hotspots',
      route: city,
      target: 'hs-time',
      title: { en: 'Play 48 hours', hi: '48 घंटे चलाएँ' },
      body: {
        en: ['Scrub or play through 24 hours back and 24 hours ahead to watch water build up and drain away.'],
        hi: ['24 घंटे पीछे से 24 घंटे आगे तक चलाएँ और पानी जमते व उतरते देखें।'],
      },
    },
    {
      chapter: 'hotspots',
      route: city,
      target: 'hs-summary',
      title: { en: 'City summary', hi: 'शहर सारांश' },
      body: {
        en: ['How many cells reach high or elevated risk at the peak, and the deepest ponding expected. Zeros on a dry day are correct — no rain, no ponding.'],
        hi: ['शिखर पर कितनी कोशिकाएँ उच्च या बढ़े जोखिम पर हैं, और सबसे गहरा अपेक्षित जलभराव। सूखे दिन शून्य सही है — बारिश नहीं तो जलभराव नहीं।'],
      },
    },
    {
      chapter: 'hotspots',
      route: city,
      target: 'hs-next',
      title: { en: 'Likely affected next', hi: 'आगे प्रभावित होने की संभावना' },
      body: {
        en: [
          'Places that are dry now but expected to flood, soonest first. Each shows how likely it is (share of 20 simulation runs that flood it), when water arrives with a range, whether it floods from its own rain or from water flowing in from upslope, and the path the water takes to get there.',
          'Evidence is rated strong, moderate or weak: weak when the runs disagree, the arrival time is uncertain, or the ground is so flat the direction of flow is within terrain error.',
        ],
        hi: [
          'जो स्थान अभी सूखे हैं पर बाढ़ की आशंका है, सबसे जल्दी वाले पहले। हर एक के साथ संभावना (20 सिमुलेशन रन में से कितनों में बाढ़), पहुँचने का समय सीमा सहित, बाढ़ अपनी वर्षा से है या ऊपर से बहकर आए पानी से, और पानी किस रास्ते से पहुँचता है।',
          'साक्ष्य मज़बूत, मध्यम या कमज़ोर आँका जाता है: कमज़ोर तब जब रन असहमत हों, पहुँच समय अनिश्चित हो, या ज़मीन इतनी समतल हो कि प्रवाह की दिशा भूभाग त्रुटि के भीतर हो।',
        ],
      },
    },
    {
      chapter: 'hotspots',
      route: city,
      target: 'hs-priority',
      title: { en: 'Response priority list', hi: 'प्रतिक्रिया प्राथमिकता सूची' },
      body: {
        en: ['Cells ranked by risk × impact — hospitals, schools and underpasses count more — each with why it floods and what to do: pre-position pumps, close an underpass, warn residents.'],
        hi: ['जोखिम × प्रभाव के क्रम में कोशिकाएँ — अस्पताल, स्कूल और अंडरपास अधिक महत्व रखते हैं — हर एक के साथ कारण और कार्य: पंप तैनात करें, अंडरपास बंद करें, निवासियों को सचेत करें।'],
      },
    },
    {
      chapter: 'hotspots',
      route: city,
      target: 'hs-confidence',
      title: { en: 'Confidence and limits', hi: 'विश्वसनीयता और सीमाएँ' },
      body: {
        en: ['States plainly what the grid can and cannot see: a 90 m terrain model misses a 2 m underpass dip; drains are only as good as OpenStreetMap; and it tells you when live rain was unavailable and a fallback was used.'],
        hi: ['स्पष्ट बताता है कि ग्रिड क्या देख सकता है और क्या नहीं: 90 मीटर भूभाग मॉडल 2 मीटर के अंडरपास गड्ढे नहीं देखता; नालियाँ उतनी ही सही जितना OpenStreetMap; और लाइव वर्षा न मिलने पर कौन-सा विकल्प उपयोग हुआ।'],
      },
    },

    // ------------------------------------------------------------- rivers
    {
      chapter: 'rivers',
      route: '/rivers',
      target: 'rv-map',
      title: { en: 'India\'s river network', hi: 'भारत का नदी तंत्र' },
      body: {
        en: ['Rivers coloured by the status of the CWC gauges along them — red where a reach is above its danger mark, orange above warning.'],
        hi: ['नदियाँ उन पर लगे CWC गेज की स्थिति के अनुसार रंगी हैं — जहाँ पानी खतरे के निशान से ऊपर वहाँ लाल, चेतावनी से ऊपर नारंगी।'],
      },
    },
    {
      chapter: 'rivers',
      route: '/rivers',
      target: 'rv-list',
      title: { en: 'Pick a river', hi: 'नदी चुनें' },
      body: {
        en: ['Every mapped river with its current gauge status. Choose one to focus the map on it and see its profile.'],
        hi: ['हर नदी उसके गेज की वर्तमान स्थिति सहित। नक्शे पर देखने और प्रोफ़ाइल के लिए एक चुनें।'],
      },
    },
    {
      chapter: 'rivers',
      route: '/rivers',
      target: 'rv-profile',
      title: { en: 'Upstream → downstream profile', hi: 'ऊपर से नीचे तक प्रोफ़ाइल' },
      body: {
        en: ['Every gauge on the chosen river from source to mouth, showing where along it the water is above warning or danger — and whether a flood wave is travelling downstream.'],
        hi: ['चुनी गई नदी के स्रोत से मुहाने तक हर गेज — कहाँ पानी चेतावनी या खतरे से ऊपर है, और क्या बाढ़ की लहर नीचे की ओर बढ़ रही है।'],
      },
    },

    {
      chapter: 'rivers',
      route: '/rivers',
      target: 'rv-path',
      title: { en: 'Towns in the path of a flood wave', hi: 'बाढ़ लहर के रास्ते में शहर' },
      body: {
        en: ['Every monitored town with a gauge above warning (or rising towards danger) upstream on its river, soonest first — which towns are likely to be affected next as the water travels downstream, with arrival ranges and evidence.'],
        hi: ['हर वह निगरानी शहर जिसकी नदी पर ऊपर की ओर कोई गेज चेतावनी से ऊपर (या खतरे की ओर बढ़ रहा) है, सबसे जल्दी वाले पहले — पानी के नीचे की ओर बहने पर आगे कौन-से शहर प्रभावित होंगे, पहुँच सीमा व साक्ष्य सहित।'],
      },
    },

    // ------------------------------------------------------------- alerts
    {
      chapter: 'alerts',
      route: '/alerts',
      target: 'al-stats',
      title: { en: 'Straight from government sources', hi: 'सीधे सरकारी स्रोतों से' },
      body: {
        en: ['Live counts from the Central Water Commission (hourly river levels at gauges with published danger marks) and NDMA SACHET (alerts issued by IMD, CWC and State Disaster Management Authorities).'],
        hi: ['केंद्रीय जल आयोग (प्रकाशित खतरे के निशान वाले गेज पर प्रति घंटा नदी स्तर) और NDMA SACHET (IMD, CWC व राज्य आपदा प्राधिकरणों की चेतावनियाँ) से लाइव गिनती।'],
      },
    },
    {
      chapter: 'alerts',
      route: '/alerts',
      target: 'al-tabs',
      title: { en: 'Gauges and alerts', hi: 'गेज और चेतावनियाँ' },
      body: {
        en: ['Switch between river gauges above warning and the active alerts. Search by station, state or area; filter alerts by colour or to flood and rain only.'],
        hi: ['चेतावनी से ऊपर नदी गेज और सक्रिय चेतावनियों के बीच बदलें। स्टेशन, राज्य या क्षेत्र से खोजें; चेतावनियों को रंग या केवल बाढ़/वर्षा से छाँटें।'],
      },
    },
    {
      chapter: 'alerts',
      route: '/alerts',
      target: 'al-graph',
      title: { en: 'Gauge graph + AI forecast', hi: 'गेज ग्राफ़ + एआई पूर्वानुमान' },
      body: {
        en: ['Opens a gauge\'s real hourly water level against its warning, danger and highest-ever marks, CWC\'s own forecast where issued, and an AI (Chronos) forecast band with hours until danger.'],
        hi: ['गेज का वास्तविक प्रति घंटा जल-स्तर, चेतावनी, खतरे और अब तक के उच्चतम निशान के सापेक्ष; जहाँ जारी हो CWC का पूर्वानुमान; और खतरे तक बचे घंटों सहित एआई (Chronos) पूर्वानुमान।'],
      },
    },
    {
      chapter: 'alerts',
      route: '/alerts',
      target: 'al-cap',
      title: { en: 'Our CAP 1.2 feed', hi: 'हमारा CAP 1.2 फ़ीड' },
      body: {
        en: ['JalDrishti\'s own warnings as a standard CAP 1.2 feed that any alerting system can subscribe to. Each warning is an Alert, then Updates, then an All Clear when the place returns to Green. All messages validate against the official OASIS schema.'],
        hi: ['जलदृष्टि की अपनी चेतावनियाँ मानक CAP 1.2 फ़ीड के रूप में, जिसे कोई भी चेतावनी प्रणाली ले सकती है। हर चेतावनी पहले Alert, फिर Update, और स्थान के हरे होने पर All Clear। सभी संदेश आधिकारिक OASIS स्कीमा पर मान्य हैं।'],
      },
    },

    // ------------------------------------------------------------- states
    {
      chapter: 'states',
      route: '/states',
      target: 'sm-map',
      title: { en: 'Every state at a glance', hi: 'हर राज्य एक नज़र में' },
      body: {
        en: ['Every town as a risk circle and every CWC gauge above warning, with case counts per state. Click a state to narrow the cards below to it.'],
        hi: ['हर शहर जोखिम वृत्त के रूप में और चेतावनी से ऊपर हर CWC गेज, राज्यवार गिनती सहित। नीचे के कार्ड उस राज्य तक सीमित करने के लिए राज्य पर क्लिक करें।'],
      },
    },
    {
      chapter: 'states',
      route: '/states',
      target: 'sm-filters',
      title: { en: 'Find, filter and sort', hi: 'खोजें, छाँटें, क्रमबद्ध करें' },
      body: {
        en: ['Find a state, filter by colour, and sort by risk, gauges above danger, people at risk, where it is raining now, or name.'],
        hi: ['राज्य खोजें, रंग से छाँटें, और जोखिम, खतरे से ऊपर गेज, जोखिम में लोग, अभी बारिश, या नाम से क्रमबद्ध करें।'],
      },
    },
    {
      chapter: 'states',
      route: '/states',
      target: 'sm-cards',
      title: { en: 'State cards', hi: 'राज्य कार्ड' },
      body: {
        en: ['Each card: the state\'s highest score and trend, the mix of colours across its towns, CWC gauges at danger and warning, people at risk, and any gauge above its danger mark. Click to open the state.'],
        hi: ['हर कार्ड: राज्य का सर्वोच्च स्कोर व रुझान, शहरों में रंगों का मिश्रण, खतरे व चेतावनी पर CWC गेज, जोखिम में लोग, और खतरे के निशान से ऊपर कोई गेज। राज्य खोलने के लिए क्लिक करें।'],
      },
    },
    {
      chapter: 'states',
      route: '/states',
      target: 'sm-weather',
      title: { en: 'Current weather', hi: 'वर्तमान मौसम' },
      body: {
        en: ['Conditions right now at the state\'s largest monitored town: sky, temperature and feels-like, humidity and wind, the temperature range across the state, and where it is raining at this moment.'],
        hi: ['राज्य के सबसे बड़े निगरानी शहर में अभी का मौसम: आकाश, तापमान व महसूस तापमान, आर्द्रता व हवा, पूरे राज्य में तापमान सीमा, और इस समय कहाँ बारिश हो रही है।'],
      },
    },

    // -------------------------------------------------------- time machine
    {
      chapter: 'timemachine',
      route: '/time-machine',
      target: 'tm-date',
      title: { en: 'Replay any date since 1994', hi: '1994 से कोई भी तारीख़' },
      body: {
        en: ['Choose a past date and the whole dashboard is re-scored as the system would have seen it that day, using archived weather and river data. A blue bar shows you are in replay; "Back to live" returns.'],
        hi: ['कोई पुरानी तारीख़ चुनें — पूरा डैशबोर्ड संग्रहीत मौसम व नदी आँकड़ों से वैसे ही आँका जाता है जैसे उस दिन दिखता। नीली पट्टी बताती है कि आप पुनरावृत्ति में हैं; "लाइव पर लौटें" से वापस।'],
      },
    },
    {
      chapter: 'timemachine',
      route: '/time-machine',
      target: 'tm-presets',
      optional: true, // empty for an area with no major recorded flood
      title: { en: 'Major recorded floods', hi: 'प्रमुख दर्ज बाढ़ें' },
      body: {
        en: ['One click to well-documented flood days — Mumbai 2005, Chennai 2015, Kochi 2018, Wayanad 2024 and 34 more — to see whether the system would have raised the alarm.'],
        hi: ['एक क्लिक में प्रसिद्ध बाढ़ के दिन — मुंबई 2005, चेन्नई 2015, कोच्चि 2018, वायनाड 2024 और 34 अन्य — देखें कि क्या प्रणाली चेतावनी देती।'],
      },
    },

    // ------------------------------------------------------------- about
    {
      chapter: 'about',
      route: '/about',
      target: 'ab-table',
      title: { en: 'Capabilities, methods and limits', hi: 'क्षमताएँ, कार्यप्रणाली और सीमाएँ' },
      body: {
        en: ['Each requirement of the problem statement, how JalDrishti meets it, the data behind it, and its known limits.'],
        hi: ['समस्या कथन की हर आवश्यकता, जलदृष्टि उसे कैसे पूरा करती है, पीछे के आँकड़े, और ज्ञात सीमाएँ।'],
      },
    },
    {
      chapter: 'about',
      route: '/',
      target: 'tutorial',
      title: { en: 'You\'re all set', hi: 'आप तैयार हैं' },
      body: {
        en: [
          'That\'s every feature. Replay this tutorial any time from this button.',
          'Remember: JalDrishti is a research prototype, not an official warning service. For operational warnings follow IMD, CWC and your State Disaster Management Authority.',
        ],
        hi: [
          'ये सभी सुविधाएँ थीं। यह ट्यूटोरियल कभी भी इस बटन से दोबारा देखें।',
          'ध्यान दें: जलदृष्टि शोध प्रोटोटाइप है, आधिकारिक चेतावनी सेवा नहीं। आधिकारिक चेतावनी हेतु IMD, CWC व अपने राज्य आपदा प्रबंधन प्राधिकरण का पालन करें।',
        ],
      },
    },
  ];
  // State monitor compares states; only Central has it in the menu.
  return role === 'central'
    ? steps.filter((st) => !st.nonCentral)
    : steps.filter((st) => st.chapter !== 'states' && !st.centralOnly);
}

const PAD = 8;
const GAP = 14;
// A city's street grid can take ~10 s the first time it is built.
const WAIT_MS = 12000;
const OPTIONAL_WAIT_MS = 1500;

function currentPath() {
  return decodeURIComponent((window.location.hash || '').replace(/^#/, '').split('?')[0]) || '/';
}

function findTarget(key) {
  if (!key) return null;
  const el = document.querySelector(`[data-tour="${key}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 ? el : null;
}

function Body({ text, total }) {
  return text.map((raw, i) => {
    const para = raw.replace('{N}', String(total));
    const lines = para.split('\n');
    if (lines.some((l) => l.startsWith('• '))) {
      return (
        <ul key={i} className="space-y-0.5">
          {lines.map((l) =>
            l.startsWith('• ') ? (
              <li key={l} className="flex gap-1.5">
                <span className="text-saffron-500">•</span>
                <span>{l.slice(2)}</span>
              </li>
            ) : (
              <li key={l} className="pt-1">{l}</li>
            ),
          )}
        </ul>
      );
    }
    return <p key={i}>{para}</p>;
  });
}

export default function Tour({ lang, open, onClose, sampleLocation, sampleCity, mapPath, role }) {
  const steps = useMemo(
    () => buildSteps({ sampleLocation, sampleCity, mapPath, role }),
    [sampleLocation, sampleCity, mapPath, role],
  );
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState(null);
  const [searching, setSearching] = useState(false);
  const [showContents, setShowContents] = useState(false);
  const [cardPos, setCardPos] = useState(null);
  const cardRef = useRef(null);
  const targetRef = useRef(null);

  const step = steps[Math.min(index, steps.length - 1)];
  const L = (o) => (lang === 'hi' ? o.hi : o.en);
  const hiFont = lang === 'hi' ? 'font-devanagari' : '';

  useEffect(() => {
    if (open) {
      setIndex(0);
      setShowContents(false);
    }
  }, [open]);

  // Navigate to the step's page, wait for its element, bring it into view.
  useEffect(() => {
    if (!open || !step) return undefined;
    let cancelled = false;
    targetRef.current = null;
    setRect(null);
    if (step.route && currentPath() !== step.route) go(step.route);
    if (!step.target) {
      setSearching(false);
      return undefined;
    }
    setSearching(true);
    const started = Date.now();
    // Wait for the page's data to render; only sections that may legitimately
    // be absent (past floods for a place without any) get a short wait.
    const waitMs = step.optional ? OPTIONAL_WAIT_MS : WAIT_MS;
    const poll = () => {
      if (cancelled) return;
      const el = findTarget(step.target);
      if (el) {
        targetRef.current = el;
        el.scrollIntoView({ block: el.getBoundingClientRect().height > window.innerHeight * 0.7 ? 'start' : 'center', behavior: 'smooth' });
        setSearching(false);
        setRect(el.getBoundingClientRect());
      } else if (Date.now() - started < waitMs) {
        setTimeout(poll, 150);
      } else {
        setSearching(false);
      }
    };
    poll();
    return () => {
      cancelled = true;
    };
  }, [open, step, index, steps]);

  // Follow the element as the page scrolls, resizes or re-renders.
  useEffect(() => {
    if (!open) return undefined;
    const update = () => {
      const el = targetRef.current;
      if (!el || !el.isConnected) return;
      const r = el.getBoundingClientRect();
      setRect((prev) =>
        prev && Math.abs(prev.top - r.top) < 0.5 && Math.abs(prev.left - r.left) < 0.5 && Math.abs(prev.width - r.width) < 0.5 && Math.abs(prev.height - r.height) < 0.5
          ? prev
          : r,
      );
    };
    const id = setInterval(update, 200);
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    return () => {
      clearInterval(id);
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
  }, [open]);

  // Place the card beside the element: below, above, right, left, else a corner.
  useLayoutEffect(() => {
    if (!open) return;
    const card = cardRef.current;
    if (!card) return;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const w = card.offsetWidth;
    const h = card.offsetHeight;
    if (vw < 640 || !rect) {
      setCardPos(null);
      return;
    }
    const clampX = (x) => Math.max(12, Math.min(x, vw - w - 12));
    const clampY = (y) => Math.max(12, Math.min(y, vh - h - 12));
    const top = rect.top - PAD;
    const bottom = rect.bottom + PAD;
    const left = rect.left - PAD;
    const right = rect.right + PAD;
    if (bottom + GAP + h < vh) setCardPos({ top: bottom + GAP, left: clampX(rect.left) });
    else if (top - GAP - h > 0) setCardPos({ top: top - GAP - h, left: clampX(rect.left) });
    else if (right + GAP + w < vw) setCardPos({ top: clampY(rect.top), left: right + GAP });
    else if (left - GAP - w > 0) setCardPos({ top: clampY(rect.top), left: left - GAP - w });
    else setCardPos({ top: vh - h - 16, left: vw - w - 16 });
  }, [open, rect, index, lang, showContents]);

  const next = useCallback(() => {
    if (index >= steps.length - 1) onClose();
    else setIndex((i) => i + 1);
  }, [index, steps.length, onClose]);
  const back = useCallback(() => setIndex((i) => Math.max(0, i - 1)), []);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowRight' || e.key === 'Enter') {
        e.preventDefault();
        next();
      } else if (e.key === 'ArrowLeft') back();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, next, back, onClose]);

  if (!open || !step) return null;

  const chapters = Object.keys(CHAPTERS).filter((c) => steps.some((s) => s.chapter === c));
  const chapterIdx = chapters.indexOf(step.chapter);
  const firstOf = (c) => steps.findIndex((s) => s.chapter === c);
  const spot = rect && !searching;
  const last = index === steps.length - 1;

  return createPortal(
    <div className="pointer-events-none fixed inset-0 z-[3000]" aria-live="polite">
      {spot ? (
        <div
          className="absolute rounded-xl ring-4 ring-saffron-500 transition-all duration-200"
          style={{
            top: rect.top - PAD,
            left: rect.left - PAD,
            width: rect.width + 2 * PAD,
            height: rect.height + 2 * PAD,
            boxShadow: '0 0 0 9999px rgba(11, 42, 91, 0.55)',
          }}
        />
      ) : (
        <div className="absolute inset-0 bg-[rgba(11,42,91,0.55)]" />
      )}

      <div
        ref={cardRef}
        role="dialog"
        aria-labelledby="jd-tour-title"
        className={`pointer-events-auto absolute w-[min(380px,calc(100vw-24px))] rounded-xl border-t-4 border-saffron-500 bg-white shadow-2xl ${
          cardPos ? '' : spot ? 'bottom-3 left-1/2 -translate-x-1/2' : 'left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2'
        }`}
        style={cardPos ?? undefined}
      >
        <div className="flex items-center justify-between gap-2 px-4 pt-3">
          <span className={`text-[10px] font-bold uppercase tracking-wider text-saffron-500 ${hiFont}`}>
            {L(CHAPTERS[step.chapter])} · {chapterIdx + 1}/{chapters.length}
          </span>
          <button
            type="button"
            onClick={onClose}
            className="rounded px-1.5 text-[16px] leading-none text-ink-500 hover:text-chakra-500"
            aria-label={lang === 'hi' ? 'ट्यूटोरियल बंद करें' : 'Close tutorial'}
          >
            ✕
          </button>
        </div>
        <div className="mx-4 mt-2 h-1 overflow-hidden rounded-full bg-ink-800">
          <div className="h-full bg-saffron-500 transition-all" style={{ width: `${((index + 1) / steps.length) * 100}%` }} />
        </div>

        {showContents ? (
          <ol className="max-h-[50vh] overflow-y-auto px-4 py-3 scrollbar-thin">
            {chapters.map((c, i) => (
              <li key={c}>
                <button
                  type="button"
                  onClick={() => {
                    setIndex(firstOf(c));
                    setShowContents(false);
                  }}
                  className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px] ${
                    c === step.chapter ? 'bg-saffron-50 font-bold text-chakra-500' : 'text-ink-300 hover:bg-ink-850'
                  } ${hiFont}`}
                >
                  <span className="w-4 font-mono text-[11px] text-ink-500">{i + 1}</span>
                  {L(CHAPTERS[c])}
                </button>
              </li>
            ))}
          </ol>
        ) : (
          <div className="px-4 py-3">
            <h2 id="jd-tour-title" className={`text-[15px] font-extrabold text-chakra-500 ${hiFont}`}>
              {L(step.title)}
            </h2>
            <div className={`mt-1.5 space-y-2 text-[12.5px] leading-relaxed text-ink-200 ${hiFont}`}>
              <Body text={L(step.body)} total={steps.length} />
            </div>
            {searching && (
              <p className="mt-2 text-[11px] text-ink-500">{lang === 'hi' ? 'पेज लोड हो रहा है…' : 'Loading this screen…'}</p>
            )}
          </div>
        )}

        <div className="flex items-center gap-2 border-t border-ink-800 px-4 py-2.5">
          <button
            type="button"
            onClick={() => setShowContents((v) => !v)}
            className={`text-[11.5px] font-semibold text-chakra-500 hover:underline ${hiFont}`}
          >
            {showContents ? (lang === 'hi' ? '← वापस' : '← Back to step') : lang === 'hi' ? 'विषय-सूची' : 'Contents'}
          </button>
          <span className="ml-auto font-mono text-[10.5px] text-ink-500">
            {index + 1} / {steps.length}
          </span>
          {index > 0 && (
            <button type="button" onClick={back} className={`btn px-2.5 py-1 text-[12px] ${hiFont}`}>
              {lang === 'hi' ? 'पीछे' : 'Back'}
            </button>
          )}
          <button type="button" onClick={next} className={`btn btn-primary px-3 py-1 text-[12px] ${hiFont}`}>
            {index === 0 ? (lang === 'hi' ? 'शुरू करें' : 'Start tour') : last ? (lang === 'hi' ? 'समाप्त' : 'Finish') : lang === 'hi' ? 'आगे' : 'Next'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
