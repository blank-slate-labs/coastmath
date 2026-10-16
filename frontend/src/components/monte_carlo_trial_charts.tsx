import type { KeyboardEvent } from "react";
import { useMemo } from "react";
import { max } from "d3-array";
import { scaleLinear } from "d3-scale";
import { line } from "d3-shape";

import { compactCurrency } from "@/utils/format";
import type { HistogramBin } from "@/utils/monte_carlo_trials";

// D3 computes scales and paths only; React renders every SVG element.

function extent(values: number[]): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!Number.isFinite(lo)) return [0, 1];
  return lo === hi ? [lo - 1, hi + 1] : [lo, hi];
}

/** One trial's net worth shape. A dashed line marks zero when the path crosses it. */
export function TrialSparkline({
  values,
  failed,
  width = 120,
  height = 28,
}: {
  values: number[];
  failed: boolean;
  width?: number;
  height?: number;
}) {
  const [lo, hi] = extent(values);
  const x = scaleLinear()
    .domain([0, Math.max(values.length - 1, 1)])
    .range([1, width - 1]);
  const y = scaleLinear()
    .domain([lo, hi])
    .range([height - 2, 2]);
  const path =
    line<number>()
      .x((_, i) => x(i))
      .y((v) => y(v))(values) ?? "";
  return (
    <svg width={width} height={height} aria-hidden="true" className="mc-trial-sparkline">
      {lo < 0 && hi > 0 && (
        <line
          x1={0}
          x2={width}
          y1={y(0)}
          y2={y(0)}
          stroke="var(--text-tertiary)"
          strokeDasharray="2 2"
          strokeWidth={0.75}
        />
      )}
      <path
        d={path}
        fill="none"
        stroke={failed ? "var(--chart-red)" : "var(--chart-blue)"}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function binLabel(bin: HistogramBin): string {
  if (bin.openLow && !bin.openHigh) return `Below ${compactCurrency(bin.x1)}`;
  if (bin.openHigh && !bin.openLow) return `${compactCurrency(bin.x0)} or more`;
  if (bin.openHigh && bin.openLow) return "All trials";
  return `${compactCurrency(bin.x0)} to ${compactCurrency(bin.x1)}`;
}

/** Ending net worth histogram; failed trials stack at the bottom of each bar. */
export function EndingHistogram({
  bins,
  selected,
  onSelect,
  width,
  height = 150,
}: {
  bins: HistogramBin[];
  selected: number | null;
  onSelect: (index: number) => void;
  width: number;
  height?: number;
}) {
  const margin = { top: 6, right: 4, bottom: 22, left: 4 };
  const innerWidth = Math.max(width - margin.left - margin.right, 0);
  const innerHeight = height - margin.top - margin.bottom;
  const tallest = max(bins, (b) => b.trials.length) ?? 1;
  const y = scaleLinear()
    .domain([0, Math.max(tallest, 1)])
    .range([innerHeight, 0]);
  const slot = bins.length ? innerWidth / bins.length : 0;
  const gap = Math.min(2, slot * 0.2);
  // Distinct bins only: one or two bins would otherwise label (and key) the same bin twice.
  const labelled = bins.length
    ? [...new Set([0, Math.floor(bins.length / 2), bins.length - 1])]
    : [];

  const onKey = (event: KeyboardEvent, index: number) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(index);
    }
  };

  return (
    <svg width={width} height={height} role="group" aria-label="Ending net worth by trial">
      <g transform={`translate(${margin.left},${margin.top})`}>
        {bins.map((bin, i) => {
          const total = bin.trials.length;
          const x0 = i * slot + gap / 2;
          const barWidth = Math.max(slot - gap, 1);
          const dim = selected !== null && selected !== i;
          return (
            <g
              key={i}
              role="button"
              tabIndex={0}
              aria-pressed={selected === i}
              aria-label={`${binLabel(bin)}: ${total.toLocaleString()} ${total === 1 ? "trial" : "trials"}, ${bin.failed.toLocaleString()} failed`}
              onClick={() => onSelect(i)}
              onKeyDown={(e) => onKey(e, i)}
              style={{ cursor: "pointer", outline: "none" }}
              className="mc-histogram-bar"
              opacity={dim ? 0.35 : 1}
            >
              <rect x={x0} y={0} width={barWidth} height={innerHeight} fill="transparent" />
              <rect
                x={x0}
                y={y(total)}
                width={barWidth}
                height={innerHeight - y(total - bin.failed)}
                fill="var(--chart-blue)"
                rx={1}
              />
              <rect
                x={x0}
                y={y(bin.failed)}
                width={barWidth}
                height={innerHeight - y(bin.failed)}
                fill="var(--chart-red)"
                rx={1}
              />
            </g>
          );
        })}
        <line
          x1={0}
          x2={innerWidth}
          y1={innerHeight}
          y2={innerHeight}
          stroke="var(--text-tertiary)"
          strokeWidth={0.5}
        />
        {labelled.map((i, n) => (
          <text
            key={i}
            x={i * slot + (n === 0 ? 0 : n === labelled.length - 1 ? slot : slot / 2)}
            y={innerHeight + 15}
            textAnchor={n === 0 ? "start" : n === labelled.length - 1 ? "end" : "middle"}
            fontSize={11}
            fill="var(--text-tertiary)"
          >
            {n === 0
              ? compactCurrency(bins[i].x0)
              : n === labelled.length - 1
                ? compactCurrency(bins[i].x1)
                : compactCurrency((bins[i].x0 + bins[i].x1) / 2)}
          </text>
        ))}
      </g>
    </svg>
  );
}

export interface PathPoint {
  year: number;
  value: number;
}

/** A replayed trial's yearly net worth against the run's median, with a failure marker. */
export function TrialPathChart({
  path,
  median,
  failureYear,
  width,
  height = 240,
}: {
  path: PathPoint[];
  median: PathPoint[];
  failureYear: number | null;
  width: number;
  height?: number;
}) {
  const margin = { top: 10, right: 12, bottom: 24, left: 56 };
  const innerWidth = Math.max(width - margin.left - margin.right, 0);
  const innerHeight = height - margin.top - margin.bottom;
  const scales = useMemo(() => {
    const years = [...path, ...median].map((p) => p.year);
    const [y0, y1] = extent(years);
    const [v0, v1] = extent([...path, ...median].map((p) => p.value).concat(0));
    const x = scaleLinear().domain([y0, y1]).range([0, innerWidth]);
    const y = scaleLinear().domain([v0, v1]).nice(5).range([innerHeight, 0]);
    return { x, y };
  }, [path, median, innerWidth, innerHeight]);
  const { x, y } = scales;
  const toPath = (points: PathPoint[]) =>
    line<PathPoint>()
      .x((p) => x(p.year))
      .y((p) => y(p.value))(points) ?? "";
  const yTicks = y.ticks(5);
  const xTicks = x.ticks(Math.max(2, Math.floor(innerWidth / 90))).filter(Number.isInteger);

  return (
    <svg
      width={width}
      height={height}
      role="img"
      aria-label={`Net worth by year for this trial${failureYear !== null ? `, failing in ${failureYear}` : ""}, against the median of all trials`}
    >
      <g transform={`translate(${margin.left},${margin.top})`}>
        {yTicks.map((t) => (
          <g key={t}>
            <line
              x1={0}
              x2={innerWidth}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--text-tertiary)"
              strokeOpacity={t === 0 ? 0.6 : 0.15}
            />
            <text
              x={-8}
              y={y(t)}
              dy="0.32em"
              textAnchor="end"
              fontSize={11}
              fill="var(--text-tertiary)"
            >
              {compactCurrency(t)}
            </text>
          </g>
        ))}
        {xTicks.map((t) => (
          <text
            key={t}
            x={x(t)}
            y={innerHeight + 16}
            textAnchor="middle"
            fontSize={11}
            fill="var(--text-tertiary)"
          >
            {t}
          </text>
        ))}
        {failureYear !== null && (
          <line
            x1={x(failureYear)}
            x2={x(failureYear)}
            y1={0}
            y2={innerHeight}
            stroke="var(--chart-red)"
            strokeDasharray="4 3"
          />
        )}
        <path
          d={toPath(median)}
          fill="none"
          stroke="var(--text-tertiary)"
          strokeDasharray="5 4"
          strokeWidth={1.25}
        />
        <path
          d={toPath(path)}
          fill="none"
          stroke={failureYear !== null ? "var(--chart-red)" : "var(--chart-blue)"}
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </g>
    </svg>
  );
}
