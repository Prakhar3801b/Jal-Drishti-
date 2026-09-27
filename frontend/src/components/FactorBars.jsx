import { useState } from 'react';
import { tierColour } from '../lib/format';
import { t } from '../lib/i18n';

/**
 * The factor breakdown — the answer to "why is this number what it is".
 *
 * Two quantities are plotted per row and they mean different things, so the bar
 * shows both rather than picking one:
 *
 *   the tinted bar     = the feature's own 0-100 level ("the soil is at 100 of
 *                        100"), coloured by what that level alone would imply on
 *                        the IMD scale
 *   the pale segment   = that feature's share of the total score
 *
 * The share is deliberately *not* normalised against the largest contributor. An
 * earlier version scaled it that way, which made the top factor's bar full-width
 * on every location — so a Green location displayed a maxed-out red bar and read
 * as an emergency. Scaling by share of the score instead means a saturated
 * feature that only accounts for a third of the score looks like a third.
 *
 * Hovering a row reveals the exact arithmetic.
 */

export default function FactorBars({ factors = [], lang, ruleScore, limit = null }) {
  const [expanded, setExpanded] = useState(false);
  const rows = limit && !expanded ? factors.slice(0, limit) : factors;

  return (
    <div className="px-3 pb-3 pt-2">
      <ul className="space-y-1.5">
        {rows.map((f) => {
          const label = lang === 'hi' ? f.label_hi : f.label_en;
          // Colour the bar by what the feature's own level would imply on the IMD
          // scale, so a row that is individually at Red reads as Red.
          const colour = tierColour(
            f.value >= 75 ? 'red' : f.value >= 50 ? 'orange' : f.value >= 25 ? 'yellow' : 'green',
          );
          const shareWidth = Math.max(0, Math.min(100, f.share_of_score ?? 0));

          return (
            <li key={f.key} className="group">
              <div className="mb-1 flex items-baseline justify-between gap-3">
                <span
                  className={`flex min-w-0 items-center gap-1.5 text-[11.5px] ${
                    f.is_top ? 'font-semibold text-ink-100' : 'text-ink-300'
                  } ${lang === 'hi' ? 'font-devanagari' : ''}`}
                >
                  <span className="w-3 shrink-0 font-mono text-[9.5px] text-ink-600">
                    {f.rank}
                  </span>
                  <span className="truncate">{label}</span>
                </span>
                <span className="shrink-0 font-mono text-[11px] tabular-nums text-ink-200">
                  {f.value.toFixed(0)}
                  <span className="ml-1 text-[9.5px] text-ink-600">
                    ·{f.contribution.toFixed(1)}pt
                  </span>
                </span>
              </div>

              <div className="relative h-[7px] overflow-hidden rounded-full bg-ink-800">
                {/* the feature's own level, tinted by what that level implies */}
                <div
                  className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-700 ease-out"
                  style={{ width: `${f.value}%`, background: colour, opacity: 0.34 }}
                />
                {/* its share of the score, as a pale overlay */}
                <div
                  className="absolute inset-y-0 left-0 rounded-full bg-ink-100/80 transition-[width] duration-700 ease-out"
                  style={{ width: `${shareWidth}%` }}
                />
              </div>

              <div className="mt-1 hidden text-[10px] text-ink-500 group-hover:block">
                {f.value.toFixed(0)} × weight {f.weight.toFixed(2)} ={' '}
                <span className="text-ink-300">{f.contribution.toFixed(2)} points</span>
                {ruleScore > 0 && (
                  <span className="text-ink-600">
                    {' '}
                    · {f.share_of_score.toFixed(0)}% of the {ruleScore.toFixed(1)} rule score
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {limit && factors.length > limit && (
        <button
          type="button"
          className="btn btn-ghost mt-2.5 w-full py-1.5 text-[10.5px]"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded
            ? lang === 'hi'
              ? 'कम दिखाएँ'
              : 'Show fewer'
            : lang === 'hi'
              ? `सभी ${factors.length} कारक दिखाएँ`
              : `Show all ${factors.length} factors`}
        </button>
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-ink-800 pt-2 text-[9.5px] text-ink-600">
        <span className="flex items-center gap-1.5">
          <span
            className="h-[6px] w-4 rounded-full"
            style={{ background: tierColour('orange'), opacity: 0.34 }}
          />
          {lang === 'hi' ? 'कारक का स्तर' : 'feature level'}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-[6px] w-4 rounded-full bg-ink-100/80" />
          {lang === 'hi' ? 'स्कोर में हिस्सा' : 'share of score'}
        </span>
      </div>
    </div>
  );
}
