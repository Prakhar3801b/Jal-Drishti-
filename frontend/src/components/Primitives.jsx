import {
  CONFIDENCE_TONE,
  directionGlyph,
  directionTone,
  tierColour,
  TIER_LABELS,
} from '../lib/format';
import { t } from '../lib/i18n';

/** Small reusable pieces shared by the national and hyperlocal panels. */

export function TierChip({ tier, lang, showAction = false, size = 'sm' }) {
  const meta = TIER_LABELS[tier] ?? TIER_LABELS.green;
  const colour = tierColour(tier);
  return (
    <span
      className={`chip ${size === 'lg' ? 'px-3 py-1.5 text-xs' : ''} ${
        lang === 'hi' ? 'font-devanagari' : ''
      }`}
      style={{
        color: colour,
        borderColor: `${colour}70`,
        background: `${colour}1f`,
      }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: colour }} />
      {lang === 'hi' ? meta.hi : meta.en}
      {showAction && (
        <span className="opacity-75">· {lang === 'hi' ? meta.action_hi : meta.action_en}</span>
      )}
    </span>
  );
}

export function ConfidenceChip({ level, label, lang, value }) {
  return (
    <span
      className={`chip ${CONFIDENCE_TONE[level] ?? CONFIDENCE_TONE.medium} ${
        lang === 'hi' ? 'font-devanagari' : ''
      }`}
      title={value !== undefined ? `${(value * 100).toFixed(0)} / 100` : undefined}
    >
      <ConfidenceBars level={level} />
      {label}
    </span>
  );
}

/** Three ascending bars — a signal-strength read on confidence. */
function ConfidenceBars({ level }) {
  const filled = level === 'high' ? 3 : level === 'medium' ? 2 : 1;
  return (
    <span className="flex items-end gap-[2px]" aria-hidden="true">
      {[3, 5, 7].map((h, i) => (
        <span
          key={h}
          className="w-[2.5px] rounded-sm"
          style={{
            height: `${h}px`,
            background: 'currentColor',
            opacity: i < filled ? 1 : 0.28,
          }}
        />
      ))}
    </span>
  );
}

export function DirectionBadge({ direction, lang }) {
  if (!direction) return null;
  return (
    <span
      className={`inline-flex items-center gap-1 text-[11px] font-semibold ${directionTone(
        direction.key,
      )} ${lang === 'hi' ? 'font-devanagari' : ''}`}
      title={`${direction.delta > 0 ? '+' : ''}${direction.delta} over 72 h`}
    >
      <span aria-hidden="true">{directionGlyph(direction.key)}</span>
      {lang === 'hi' ? direction.label_hi : direction.label_en}
    </span>
  );
}

/**
 * Compact metric tile. `label` is rendered at a size that fits the four-across
 * alert grid without ellipsis — the tier names are short by design, so the kicker
 * tracking is relaxed here rather than letting "Orange" truncate to "Oran…".
 */
export function StatTile({ label, value, sub, tone = 'default', onClick, active = false }) {
  const tones = {
    default: 'border-ink-700/70',
    red: 'border-risk-red/45 bg-risk-red/[0.07]',
    orange: 'border-risk-orange/45 bg-risk-orange/[0.07]',
    yellow: 'border-risk-yellow/40 bg-risk-yellow/[0.06]',
    green: 'border-indiagreen-500/45 bg-indiagreen-500/[0.07]',
  };
  const textTones = {
    default: 'text-ink-100',
    red: 'text-risk-red',
    orange: 'text-risk-orange',
    yellow: 'text-risk-yellow',
    green: 'text-indiagreen-300',
  };
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag
      type={onClick ? 'button' : undefined}
      onClick={onClick}
      aria-pressed={onClick ? active : undefined}
      className={`panel-tight px-2.5 py-2 text-left transition ${tones[tone]} ${
        onClick ? 'hover:border-saffron-500/50 hover:bg-ink-800/80' : ''
      } ${active ? 'ring-1 ring-saffron-500/60' : ''}`}
    >
      <div className="truncate text-[9.5px] font-semibold uppercase tracking-[0.06em] text-ink-500">
        {label}
      </div>
      <div className={`font-mono text-xl font-bold tabular-nums ${textTones[tone]}`}>{value}</div>
      {sub && <div className="truncate text-[10px] text-ink-500">{sub}</div>}
    </Tag>
  );
}

/**
 * Inline sparkline for the score-history strip.
 *
 * Hand-rolled SVG rather than a chart library: it renders 40 of these in a list,
 * and Recharts' per-instance overhead is not worth it for a 60x18 polyline.
 */
export function Sparkline({ values = [], width = 62, height = 18, colour = '#FF671F' }) {
  if (values.length < 2) {
    return <div style={{ width, height }} className="rounded bg-ink-800/60" />;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = width / (values.length - 1);
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(height - ((v - min) / span) * (height - 3) - 1.5).toFixed(1)}`);

  return (
    <svg width={width} height={height} className="overflow-visible" aria-hidden="true">
      <polyline
        points={pts.join(' ')}
        fill="none"
        stroke={colour}
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.95"
      />
      <circle
        cx={pts[pts.length - 1].split(',')[0]}
        cy={pts[pts.length - 1].split(',')[1]}
        r="2.1"
        fill={colour}
      />
    </svg>
  );
}

/** A labelled key/value row, used throughout the observed-data blocks. */
export function DataRow({ label, value, hint, lang }) {
  return (
    <div className="data-row">
      <span className={`data-label ${lang === 'hi' ? 'font-devanagari' : ''}`} title={hint}>
        {label}
      </span>
      <span className="data-value">{value}</span>
    </div>
  );
}

export function SectionHead({ title, lang, right, icon }) {
  return (
    <div className="panel-head">
      <h3 className={`panel-title flex items-center gap-2 ${lang === 'hi' ? 'font-devanagari' : ''}`}>
        {icon}
        {title}
      </h3>
      {right}
    </div>
  );
}

export function Spinner({ label, lang }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-8 text-[11px] text-ink-400">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-ink-600 border-t-saffron-500" />
      <span className={lang === 'hi' ? 'font-devanagari' : ''}>{label ?? t(lang, 'loading')}</span>
    </div>
  );
}

export function EmptyState({ children, lang }) {
  return (
    <div
      className={`grid place-items-center px-6 py-10 text-center text-[11.5px] leading-relaxed text-ink-500 ${
        lang === 'hi' ? 'font-devanagari' : ''
      }`}
    >
      {children}
    </div>
  );
}
