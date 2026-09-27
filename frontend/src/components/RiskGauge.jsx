import { useEffect, useRef, useState } from 'react';
import { RISK_COLOURS, tierColour, TIER_ORDER } from '../lib/format';

/**
 * The headline risk dial.
 *
 * Built as a 240-degree arc rather than a full ring so the four IMD alert bands
 * can be laid out as readable segments around the outside — the gauge teaches the
 * scale at the same time as it reports a value. The needle animates from the
 * previous score, which makes a change after a refresh legible rather than a
 * silent number swap.
 */

// Degrees clockwise from 12 o'clock: -120 is the lower-left, so a 240-degree
// sweep ends at the lower-right and the dial opens at the bottom.
const START = -120;
const SWEEP = 240;

const BANDS = [
  { tier: 'green', from: 0, to: 25 },
  { tier: 'yellow', from: 25, to: 50 },
  { tier: 'orange', from: 50, to: 75 },
  { tier: 'red', from: 75, to: 100 },
];

function polar(cx, cy, r, deg) {
  const rad = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

function arcPath(cx, cy, r, fromDeg, toDeg) {
  const [x1, y1] = polar(cx, cy, r, fromDeg);
  const [x2, y2] = polar(cx, cy, r, toDeg);
  const large = Math.abs(toDeg - fromDeg) > 180 ? 1 : 0;
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

const scoreToDeg = (score) => START + (Math.max(0, Math.min(100, score)) / 100) * SWEEP;

/** Ease the needle toward a new score instead of snapping to it. */
function useAnimatedNumber(target, duration = 780) {
  const [value, setValue] = useState(target);
  const fromRef = useRef(target);
  const rafRef = useRef(0);

  useEffect(() => {
    const from = fromRef.current;
    if (from === target) return;
    const t0 = performance.now();
    const tick = (now) => {
      const p = Math.min((now - t0) / duration, 1);
      // easeOutCubic: fast settle, no overshoot
      const eased = 1 - (1 - p) ** 3;
      setValue(from + (target - from) * eased);
      if (p < 1) rafRef.current = requestAnimationFrame(tick);
      else fromRef.current = target;
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [target, duration]);

  useEffect(() => {
    fromRef.current = value;
  }, [value]);

  return value;
}

export default function RiskGauge({ score = 0, tier = 'green', size = 200, label, lang }) {
  const animated = useAnimatedNumber(score);
  const cx = 100;
  const cy = 100;
  const r = 76;
  const colour = tierColour(tier);
  const deg = scoreToDeg(animated);

  // The indicator is a short spoke sitting across the band ring plus a cap
  // outside it, rather than a needle pivoting at the centre. A centre-pivoted
  // needle sweeps straight through the number, which is the one thing on this
  // component that has to stay readable.
  const [inX, inY] = polar(cx, cy, r - 12, deg);
  const [outX, outY] = polar(cx, cy, r + 12, deg);
  const [capX, capY] = polar(cx, cy, r + 12, deg);

  return (
    <div className="relative select-none" style={{ width: size, height: size * 0.78 }}>
      <svg
        viewBox="0 0 200 156"
        width={size}
        height={size * 0.78}
        role="img"
        aria-label={`Risk score ${score.toFixed(0)} of 100`}
      >
        <defs>
          <filter id="gauge-glow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="3.4" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* unfilled track */}
        <path
          d={arcPath(cx, cy, r, START, START + SWEEP)}
          fill="none"
          stroke="#E5EAF0"
          strokeWidth="14"
          strokeLinecap="round"
        />

        {/* the four IMD bands; a band the score has not reached stays dim, so the
            ring doubles as a legend for the scale */}
        {BANDS.map((band) => {
          const reached = animated >= band.from;
          return (
            <path
              key={band.tier}
              d={arcPath(cx, cy, r, scoreToDeg(band.from), scoreToDeg(band.to))}
              fill="none"
              stroke={RISK_COLOURS[band.tier]}
              strokeWidth="14"
              strokeLinecap="butt"
              opacity={reached ? 0.95 : 0.22}
              style={{ transition: 'opacity 0.45s ease' }}
            />
          );
        })}

        {/* band boundaries */}
        {[25, 50, 75].map((v) => {
          const [x1, y1] = polar(cx, cy, r - 8, scoreToDeg(v));
          const [x2, y2] = polar(cx, cy, r + 8, scoreToDeg(v));
          return <line key={v} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#FFFFFF" strokeWidth="2.6" />;
        })}

        {/* indicator */}
        <g style={{ filter: 'url(#gauge-glow)' }}>
          <line
            x1={inX}
            y1={inY}
            x2={outX}
            y2={outY}
            stroke="#0B2A5B"
            strokeWidth="3"
            strokeLinecap="round"
          />
          <circle cx={capX} cy={capY} r="4.2" fill={colour} stroke="#FFFFFF" strokeWidth="2" />
        </g>

        {/* scale ends */}
        <text x="16" y="143" fill="#4A5E7D" fontSize="9" fontFamily="ui-monospace, monospace">
          0
        </text>
        <text x="171" y="143" fill="#4A5E7D" fontSize="9" fontFamily="ui-monospace, monospace">
          100
        </text>
      </svg>

      {/* The readout sits in the open bottom of the arc, clear of the ring. */}
      <div
        className="pointer-events-none absolute inset-x-0 flex flex-col items-center"
        style={{ top: '38%' }}
      >
        <div
          className="font-mono text-[42px] font-extrabold leading-[0.95] tabular-nums"
          style={{ color: colour }}
        >
          {animated.toFixed(0)}
        </div>
        <div className="font-mono text-[10px] leading-none text-ink-600">/ 100</div>
        {label && (
          <div
            className={`mt-1.5 text-[9.5px] font-semibold uppercase tracking-[0.12em] text-ink-500 ${
              lang === 'hi' ? 'font-devanagari' : ''
            }`}
          >
            {label}
          </div>
        )}
      </div>
    </div>
  );
}
