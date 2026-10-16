import { useMemo } from "react";
import { scaleLinear } from "d3-scale";
import { area, line } from "d3-shape";
import { format } from "d3-format";
import { fullCurrency as sharedFullCurrency, withCurrency } from "@/utils/format";
import {
  HoverLine,
  PointerOverlay,
  XAxisTicks,
  YAxisTicks,
  YGridLines,
  chartTickCounts,
} from "@/components/chart_frame";
import { useYearHover } from "@/utils/use_year_hover";

// --- Types ---

export interface PercentileCurve {
  label: string; // "p10", "p25", "p50", "p75", "p90"
  values: number[];
}

export interface MonteCarloFanChartProps {
  percentileCurves: PercentileCurve[];
  years: number[];
  width: number;
  height: number;
}

// --- Helpers ---

const MARGIN = { top: 20, right: 30, bottom: 40, left: 60 };

const PERCENTILE_LABELS: Record<string, string> = {
  p10: "10th",
  p25: "25th",
  p50: "50th (Median)",
  p75: "75th",
  p90: "90th",
};

const currencyFormat = (value: number): string => {
  if (Math.abs(value) >= 1_000_000) {
    return withCurrency(`${format(",.1f")(value / 1_000_000)}M`);
  }
  if (Math.abs(value) >= 1_000) {
    return withCurrency(`${format(",.0f")(value / 1_000)}k`);
  }
  return withCurrency(`${format(",.0f")(value)}`);
};

const fullCurrencyFormat = (value: number): string => sharedFullCurrency(value);

// Stable fallback so a missing percentile curve does not invalidate the memos below.
const NO_VALUES: number[] = [];

// --- Component ---

export default function MonteCarloFanChart({
  percentileCurves,
  years,
  width,
  height,
}: MonteCarloFanChartProps) {
  // Build lookup by label
  const curveMap = useMemo(() => {
    const m = new Map<string, number[]>();
    for (const c of percentileCurves) {
      m.set(c.label, c.values);
    }
    return m;
  }, [percentileCurves]);

  const p10 = curveMap.get("p10") ?? NO_VALUES;
  const p25 = curveMap.get("p25") ?? NO_VALUES;
  const p50 = curveMap.get("p50") ?? NO_VALUES;
  const p75 = curveMap.get("p75") ?? NO_VALUES;
  const p90 = curveMap.get("p90") ?? NO_VALUES;

  const innerWidth = width - MARGIN.left - MARGIN.right;
  const innerHeight = height - MARGIN.top - MARGIN.bottom;

  // D3 scales
  const xScale = useMemo(() => {
    if (years.length === 0) return scaleLinear().domain([0, 1]).range([0, innerWidth]);
    return scaleLinear()
      .domain([years[0], years[years.length - 1]])
      .range([0, innerWidth]);
  }, [years, innerWidth]);

  const yScale = useMemo(() => {
    const allValues = [...p10, ...p25, ...p50, ...p75, ...p90];
    if (allValues.length === 0) return scaleLinear().domain([0, 1]).range([innerHeight, 0]);
    const min = Math.min(...allValues, 0);
    const max = Math.max(...allValues, 0);
    const padding = (max - min) * 0.1 || 1000;
    return scaleLinear()
      .domain([min < 0 ? min - padding : 0, max + padding])
      .range([innerHeight, 0])
      .nice();
  }, [p10, p25, p50, p75, p90, innerHeight]);

  // Area generators for bands
  const outerBandD = useMemo(() => {
    if (years.length === 0 || p10.length === 0 || p90.length === 0) return "";
    const gen = area<number>()
      .x((_d, i) => xScale(years[i]))
      .y0((_d, i) => yScale(p10[i]))
      .y1((_d, i) => yScale(p90[i]));
    return gen(years) ?? "";
  }, [years, p10, p90, xScale, yScale]);

  const innerBandD = useMemo(() => {
    if (years.length === 0 || p25.length === 0 || p75.length === 0) return "";
    const gen = area<number>()
      .x((_d, i) => xScale(years[i]))
      .y0((_d, i) => yScale(p25[i]))
      .y1((_d, i) => yScale(p75[i]));
    return gen(years) ?? "";
  }, [years, p25, p75, xScale, yScale]);

  // Line generator for median
  const medianD = useMemo(() => {
    if (years.length === 0 || p50.length === 0) return "";
    const gen = line<number>()
      .x((_d, i) => xScale(years[i]))
      .y((_d, i) => yScale(p50[i]));
    return gen(years) ?? "";
  }, [years, p50, xScale, yScale]);

  // Axis ticks
  const tickCounts = chartTickCounts(innerWidth, innerHeight);
  const xTicks = useMemo(() => xScale.ticks(tickCounts.x), [xScale, tickCounts.x]);
  const yTicks = useMemo(() => yScale.ticks(tickCounts.y), [yScale, tickCounts.y]);

  // Hover
  const { hoverIndex, handleMouseMove, handleMouseLeave } = useYearHover(years, xScale);

  if (years.length === 0 || percentileCurves.length === 0) {
    return (
      <div
        style={{
          width,
          height,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#888",
          fontSize: "14px",
        }}
      >
        No Monte Carlo data
      </div>
    );
  }

  const hoverYear = hoverIndex !== null ? years[hoverIndex] : null;

  return (
    <div style={{ width, height, position: "relative" }}>
      <svg width={width} height={height}>
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          <YGridLines ticks={yTicks} yScale={yScale} width={innerWidth} />

          {/* Zero line */}
          {yScale.domain()[0] < 0 && yScale.domain()[1] > 0 && (
            <line
              x1={0}
              x2={innerWidth}
              y1={yScale(0)}
              y2={yScale(0)}
              stroke="#999"
              strokeWidth={1}
            />
          )}

          {/* Outer band: p10–p90 */}
          <path
            d={outerBandD}
            fill="rgba(74,144,217,0.15)"
            stroke="none"
            data-testid="band-outer"
          />

          {/* Inner band: p25–p75 */}
          <path
            d={innerBandD}
            fill="rgba(74,144,217,0.35)"
            stroke="none"
            data-testid="band-inner"
          />

          {/* Median line: p50 */}
          <path
            d={medianD}
            fill="none"
            stroke="#4a90d9"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            data-testid="line-median"
          />

          <XAxisTicks ticks={xTicks} xScale={xScale} y={innerHeight} />
          <YAxisTicks ticks={yTicks} yScale={yScale} format={currencyFormat} />

          {/* Hover crosshair */}
          {hoverIndex !== null && hoverYear !== null && (
            <>
              <HoverLine x={xScale(hoverYear)} height={innerHeight} />
              {/* Dots on each percentile */}
              {[
                { key: "p10", values: p10, color: "rgba(74,144,217,0.4)" },
                { key: "p25", values: p25, color: "rgba(74,144,217,0.6)" },
                { key: "p50", values: p50, color: "#4a90d9" },
                { key: "p75", values: p75, color: "rgba(74,144,217,0.6)" },
                { key: "p90", values: p90, color: "rgba(74,144,217,0.4)" },
              ].map(({ key, values, color }) =>
                values[hoverIndex] !== undefined ? (
                  <circle
                    key={key}
                    cx={xScale(hoverYear)}
                    cy={yScale(values[hoverIndex])}
                    r={4}
                    fill={color}
                    stroke="#fff"
                    strokeWidth={1.5}
                    pointerEvents="none"
                  />
                ) : null,
              )}
            </>
          )}

          <PointerOverlay
            width={innerWidth}
            height={innerHeight}
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
          />
        </g>
      </svg>

      {/* Tooltip */}
      {hoverIndex !== null && hoverYear !== null && (
        <div
          data-testid="fan-tooltip"
          style={{
            position: "absolute",
            left: xScale(hoverYear) + MARGIN.left + 12,
            top: MARGIN.top,
            background: "rgba(0,0,0,0.85)",
            color: "#fff",
            padding: "8px 12px",
            borderRadius: "4px",
            fontSize: "12px",
            lineHeight: "1.5",
            pointerEvents: "none",
            whiteSpace: "nowrap",
            zIndex: 10,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4 }}>{hoverYear}</div>
          {(["p90", "p75", "p50", "p25", "p10"] as const).map((key) => {
            const values = curveMap.get(key);
            if (!values || values[hoverIndex] === undefined) return null;
            return (
              <div
                key={key}
                style={{
                  fontWeight: key === "p50" ? 600 : 400,
                  color: key === "p50" ? "#7bb8f0" : "#ccc",
                }}
              >
                {PERCENTILE_LABELS[key] ?? key}: {fullCurrencyFormat(values[hoverIndex])}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
