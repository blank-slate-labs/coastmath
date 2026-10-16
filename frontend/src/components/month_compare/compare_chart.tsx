import { useMemo } from "react";
import { scaleLinear } from "d3-scale";
import { line } from "d3-shape";
import {
  ChartHeader,
  ChartLegend,
  SegmentedControl,
  type LegendEntry,
} from "@/components/chart_chrome";
import type { SpendingOutcome } from "@/api/spending_models";
import type { CurrencyMode } from "@/utils/currency";
import { compactCurrency, dollarsOr } from "@/utils/format";
import { PLAN_COLOR, SERIES_COLORS, shownNetWorth } from "./month_format";

const WIDTH = 720;
const HEIGHT = 300;
const MARGIN = { top: 16, right: 16, bottom: 28, left: 56 };
/** Variant lines within this many pixels of each other at every year draw as one line. */
const SAME_LINE_PX = 1;

type Point = { x: number; y: number };

function sameLine(a: Point[], b: Point[]): boolean {
  return (
    a.length === b.length &&
    a.every(
      (p, i) => Math.abs(p.x - b[i].x) <= SAME_LINE_PX && Math.abs(p.y - b[i].y) <= SAME_LINE_PX,
    )
  );
}

/**
 * Net worth for the plan (dashed) and each spending variant, in future or today's dollars.
 * Variants that would draw on top of each other share one line and one legend entry, so
 * every selected variant stays findable; the plan draws last so its dashes show over a match.
 */
export default function CompareChart({
  plan,
  variants,
  mode,
  onModeChange,
}: {
  plan: SpendingOutcome;
  variants: SpendingOutcome[];
  mode: CurrencyMode;
  onModeChange: (mode: CurrencyMode) => void;
}) {
  const geometry = useMemo(() => {
    const series = [plan, ...variants].map((outcome) =>
      outcome.net_worth_path.map((point) => ({
        year: point.year,
        value: shownNetWorth(point, mode),
      })),
    );
    const points = series.flat();
    const years = points.map((p) => p.year);
    const values = points.map((p) => p.value);
    const x = scaleLinear()
      .domain([Math.min(...years), Math.max(...years)])
      .range([MARGIN.left, WIDTH - MARGIN.right]);
    const y = scaleLinear()
      .domain([Math.min(0, ...values), Math.max(1, ...values)])
      .nice()
      .range([HEIGHT - MARGIN.bottom, MARGIN.top]);
    const path = line<Point>()
      .x((p) => p.x)
      .y((p) => p.y);
    const [planPixels, ...variantPixels] = series.map((s) =>
      s.map((p) => ({ x: x(p.year), y: y(p.value) })),
    );
    const groups: { members: number[]; pixels: Point[] }[] = [];
    variantPixels.forEach((pixels, index) => {
      const match = groups.find((group) => sameLine(group.pixels, pixels));
      if (match) match.members.push(index);
      else groups.push({ members: [index], pixels });
    });
    return {
      x,
      y,
      planPath: path(planPixels) ?? "",
      groups: groups.map((group) => ({ members: group.members, d: path(group.pixels) ?? "" })),
    };
  }, [plan, variants, mode]);

  if (plan.net_worth_path.length === 0) return null;
  const { x, y, planPath, groups } = geometry;
  const legend: LegendEntry[] = [
    { label: plan.label, color: PLAN_COLOR, kind: "dashed" },
    ...groups.map((group, index) => ({
      label:
        group.members.map((member) => variants[member].label).join(", ") +
        (group.members.length > 1 ? " (same line)" : ""),
      color: SERIES_COLORS[index % SERIES_COLORS.length],
    })),
  ];

  return (
    <div className="card" style={{ display: "grid", gap: 8 }}>
      <ChartHeader title="Net worth">
        <div className="chart-header-tools">
          <SegmentedControl<CurrencyMode>
            ariaLabel="Currency mode"
            value={mode}
            onChange={onModeChange}
            options={[
              { value: "nominal", label: dollarsOr("Future dollars", "Future (nominal)") },
              { value: "inflation_adjusted", label: dollarsOr("Today's $", "Today's money") },
            ]}
          />
        </div>
      </ChartHeader>
      <ChartLegend entries={legend} />
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        style={{ width: "100%", height: "auto" }}
        aria-label={`Net worth by year for ${legend.map((entry) => entry.label).join(", ")}`}
      >
        {y.ticks(5).map((tick) => (
          <g key={`y-${tick}`}>
            <line
              x1={MARGIN.left}
              x2={WIDTH - MARGIN.right}
              y1={y(tick)}
              y2={y(tick)}
              shapeRendering="crispEdges"
              style={{ stroke: tick === 0 ? "var(--viz-axis)" : "var(--viz-grid)" }}
            />
            <text
              x={MARGIN.left - 8}
              y={y(tick)}
              dy="0.32em"
              textAnchor="end"
              fontSize={11}
              style={{ fill: "var(--text-tertiary)" }}
            >
              {compactCurrency(tick)}
            </text>
          </g>
        ))}
        {x
          .ticks(6)
          .filter(Number.isInteger)
          .map((tick) => (
            <text
              key={`x-${tick}`}
              x={x(tick)}
              y={HEIGHT - 8}
              textAnchor="middle"
              fontSize={11}
              style={{ fill: "var(--text-tertiary)" }}
            >
              {tick}
            </text>
          ))}
        {groups.map((group, index) => (
          <path
            key={group.members.join("-")}
            data-series={`variant-${index}`}
            d={group.d}
            fill="none"
            style={{ stroke: SERIES_COLORS[index % SERIES_COLORS.length] }}
            strokeWidth={2.25}
            strokeLinejoin="round"
          />
        ))}
        <path
          data-series="plan"
          d={planPath}
          fill="none"
          style={{ stroke: PLAN_COLOR }}
          strokeWidth={1.75}
          strokeDasharray="5 4"
        />
      </svg>
    </div>
  );
}
