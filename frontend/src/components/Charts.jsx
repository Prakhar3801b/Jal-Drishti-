import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { cumecs, dateIST, mm, RISK_COLOURS, tierColour } from '../lib/format';
import { t } from '../lib/i18n';

/**
 * Charts for the hyperlocal panel.
 *
 * Both charts share one rule: the uncertainty is drawn, never dropped. The
 * trajectory chart's band is the GloFAS p25-p75 ensemble re-scored, and the river
 * chart's band is the same ensemble in cumecs. A single confident-looking line
 * would misrepresent a 7-day river forecast.
 *
 * Colours come from the IMD risk scale so a line that climbs into the orange zone
 * is visibly in the orange zone.
 */

const AXIS = { stroke: '#6E7C8D', fontSize: 10, fontFamily: 'ui-monospace, monospace' };
const GRID = '#E5EAF0';

function ChartTooltip({ active, payload, label, lang, kind }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;

  return (
    <div className="rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-2 shadow-xl backdrop-blur">
      <div className="mb-1 font-mono text-[10px] text-ink-400">{label}</div>
      {kind === 'risk' ? (
        <>
          <div className="flex items-baseline gap-2">
            <span
              className="font-mono text-base font-bold tabular-nums"
              style={{ color: tierColour(row.tier) }}
            >
              {row.score?.toFixed(0)}
            </span>
            <span className="text-[10px] text-ink-500">/ 100</span>
          </div>
          {row.low !== undefined && row.high !== row.low && (
            <div className="mt-0.5 font-mono text-[10px] text-ink-400">
              {lang === 'hi' ? 'परिसर' : 'range'} {row.low?.toFixed(0)}–{row.high?.toFixed(0)}
            </div>
          )}
          {row.rain_24h_mm !== null && row.rain_24h_mm !== undefined && (
            <div className="mt-1 text-[10px] text-ink-400">
              {t(lang, 'rain24')}: <span className="text-ink-200">{mm(row.rain_24h_mm)}</span>
            </div>
          )}
          {row.discharge_cumecs !== null && row.discharge_cumecs !== undefined && (
            <div className="text-[10px] text-ink-400">
              {t(lang, 'currentDischarge')}:{' '}
              <span className="text-ink-200">{cumecs(row.discharge_cumecs)}</span>
            </div>
          )}
        </>
      ) : (
        <>
          <div className="font-mono text-sm font-bold text-saffron-300">
            {cumecs(row.value ?? row.median)}
          </div>
          {row.p25 !== undefined && row.p25 !== null && (
            <div className="mt-0.5 font-mono text-[10px] text-ink-400">
              p25–p75 {cumecs(row.p25)} – {cumecs(row.p75)}
            </div>
          )}
          <div className="mt-1 text-[10px] text-ink-500">
            {row.kind === 'forecast' ? t(lang, 'forecastWord') : t(lang, 'observedWord')}
          </div>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------- 72-hour trajectory */

export function TrajectoryChart({ trajectory = [], lang, height = 168 }) {
  if (trajectory.length < 2) return null;

  // Recharts stacks areas, so the band is drawn as [baseline=low, delta=high-low]
  // rather than as two overlapping areas.
  const data = trajectory.map((p) => ({
    ...p,
    name: p.hours === 0 ? (lang === 'hi' ? 'अभी' : 'Now') : `+${p.hours}h`,
    bandBase: p.low,
    bandSpan: Math.max(p.high - p.low, 0),
  }));

  const peak = Math.max(...data.map((d) => d.high));
  const yMax = Math.min(100, Math.max(40, Math.ceil((peak + 12) / 10) * 10));

  return (
    <div style={{ height }} className="px-1 pb-1">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 10, right: 12, bottom: 2, left: -18 }}>
          {/* the IMD bands as background zones, so the line's height has meaning */}
          <ReferenceArea y1={75} y2={yMax} fill={RISK_COLOURS.red} fillOpacity={0.07} />
          <ReferenceArea y1={50} y2={75} fill={RISK_COLOURS.orange} fillOpacity={0.07} />
          <ReferenceArea y1={25} y2={50} fill={RISK_COLOURS.yellow} fillOpacity={0.06} />
          <ReferenceArea y1={0} y2={25} fill={RISK_COLOURS.green} fillOpacity={0.05} />

          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="name" tick={AXIS} axisLine={{ stroke: GRID }} tickLine={false} />
          <YAxis
            domain={[0, yMax]}
            tick={AXIS}
            axisLine={false}
            tickLine={false}
            width={42}
            ticks={[0, 25, 50, 75, 100].filter((v) => v <= yMax)}
          />

          {[25, 50, 75]
            .filter((v) => v <= yMax)
            .map((v) => (
              <ReferenceLine
                key={v}
                y={v}
                stroke={
                  v === 75 ? RISK_COLOURS.red : v === 50 ? RISK_COLOURS.orange : RISK_COLOURS.yellow
                }
                strokeDasharray="3 4"
                strokeOpacity={0.45}
              />
            ))}

          <Tooltip
            content={<ChartTooltip lang={lang} kind="risk" />}
            cursor={{ stroke: '#6B809F', strokeDasharray: '3 3' }}
          />

          <Area
            dataKey="bandBase"
            stackId="band"
            stroke="none"
            fill="transparent"
            isAnimationActive={false}
          />
          <Area
            dataKey="bandSpan"
            stackId="band"
            stroke="none"
            fill="#F26A1B"
            fillOpacity={0.18}
            isAnimationActive={false}
          />

          <Line
            dataKey="score"
            stroke="#F26A1B"
            strokeWidth={2.4}
            dot={{ r: 3.2, fill: '#FFFFFF', stroke: '#F26A1B', strokeWidth: 2 }}
            activeDot={{ r: 5, fill: '#F26A1B', stroke: '#FFFFFF', strokeWidth: 2 }}
            isAnimationActive
            animationDuration={650}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ------------------------------------------------------- river discharge */

export function RiverChart({ river, lang, height = 168 }) {
  const observed = river?.observed ?? [];
  const forecast = river?.forecast ?? [];
  if (!observed.length && !forecast.length) return null;

  const data = [
    ...observed.map((o) => ({
      date: o.date,
      name: dateIST(o.date),
      value: o.discharge,
      kind: 'observed',
    })),
    ...forecast.map((f) => ({
      date: f.date,
      name: dateIST(f.date),
      value: f.median ?? f.discharge,
      median: f.median,
      p25: f.p25,
      p75: f.p75,
      bandBase: f.p25,
      bandSpan:
        f.p25 !== null && f.p75 !== null && f.p75 !== undefined
          ? Math.max(f.p75 - f.p25, 0)
          : undefined,
      kind: 'forecast',
    })),
  ];

  const bands = river?.seasonal_bands;
  const boundary = observed.length ? data[observed.length - 1]?.name : null;

  return (
    <div style={{ height }} className="px-1 pb-1">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 10, right: 12, bottom: 2, left: -8 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis
            dataKey="name"
            tick={AXIS}
            axisLine={{ stroke: GRID }}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={18}
          />
          <YAxis
            tick={AXIS}
            axisLine={false}
            tickLine={false}
            width={54}
            domain={['dataMin - 5%', 'dataMax + 5%']}
            tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toFixed(0))}
          />

          {/* the seasonal normal and the 90th percentile for this day-of-year:
              the reference lines that turn cumecs into meaning */}
          {bands?.p50 !== undefined && (
            <ReferenceLine
              y={bands.p50}
              stroke="#0B8A3D"
              strokeDasharray="4 4"
              strokeOpacity={0.8}
              label={{
                value: lang === 'hi' ? 'मौसमी सामान्य' : 'seasonal normal',
                position: 'insideTopLeft',
                fill: '#0B8A3D',
                fontSize: 9,
              }}
            />
          )}
          {bands?.p90 !== undefined && (
            <ReferenceLine
              y={bands.p90}
              stroke={RISK_COLOURS.orange}
              strokeDasharray="4 4"
              strokeOpacity={0.75}
              label={{
                value: 'p90',
                position: 'insideTopRight',
                fill: RISK_COLOURS.orange,
                fontSize: 9,
              }}
            />
          )}

          {boundary && (
            <ReferenceLine
              x={boundary}
              stroke="#6B809F"
              strokeDasharray="2 4"
              label={{
                value: lang === 'hi' ? 'पूर्वानुमान →' : 'forecast →',
                position: 'insideTopRight',
                fill: '#526071',
                fontSize: 9,
              }}
            />
          )}

          <Tooltip
            content={<ChartTooltip lang={lang} kind="river" />}
            cursor={{ stroke: '#6B809F', strokeDasharray: '3 3' }}
          />

          <Area
            dataKey="bandBase"
            stackId="q"
            stroke="none"
            fill="transparent"
            isAnimationActive={false}
            connectNulls
          />
          <Area
            dataKey="bandSpan"
            stackId="q"
            stroke="none"
            fill="#1E3A8A"
            fillOpacity={0.22}
            isAnimationActive={false}
            connectNulls
          />

          <Line
            dataKey="value"
            stroke="#0B2A5B"
            strokeWidth={2.2}
            dot={false}
            activeDot={{ r: 4, fill: '#F26A1B', stroke: '#FFFFFF', strokeWidth: 2 }}
            isAnimationActive
            animationDuration={650}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/* --------------------------------------------- score history across runs */

export function ScoreHistoryChart({ history = [], lang, height = 92 }) {
  if (history.length < 2) return null;
  const data = history.map((h, i) => ({
    name: `#${i + 1}`,
    score: h.score,
    at: h.computed_at,
    tier: h.tier,
  }));

  return (
    <div style={{ height }} className="px-1 pb-1">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 10, bottom: 0, left: -26 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="name" tick={AXIS} axisLine={false} tickLine={false} hide />
          <YAxis domain={[0, 100]} tick={AXIS} axisLine={false} tickLine={false} width={40}
                 ticks={[0, 50, 100]} />
          <Tooltip
            content={({ active, payload }) =>
              active && payload?.length ? (
                <div className="rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1.5 text-[10px]">
                  <div className="font-mono font-bold text-saffron-300">
                    {payload[0].payload.score.toFixed(1)}
                  </div>
                  <div className="text-ink-500">
                    {new Date(payload[0].payload.at).toLocaleString('en-IN', {
                      timeZone: 'Asia/Kolkata',
                      day: '2-digit',
                      month: 'short',
                      hour: '2-digit',
                      minute: '2-digit',
                      hour12: false,
                    })}
                  </div>
                </div>
              ) : null
            }
          />
          <Line
            dataKey="score"
            stroke="#F26A1B"
            strokeWidth={2}
            dot={{ r: 2.2, fill: '#F26A1B', stroke: 'none' }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
