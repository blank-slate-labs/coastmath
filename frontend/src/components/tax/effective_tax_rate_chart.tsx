import { useMemo, useRef } from "react";
import { scaleLinear } from "d3-scale";
import { line } from "d3-shape";
import { format } from "d3-format";
import {
  HoverLine,
  PointerOverlay,
  XAxisTicks,
  YAxisTicks,
  YGridLines,
  chartTickCounts,
} from "@/components/chart_frame";
import { useObservedSize } from "@/utils/use_chart_size";
import { useYearHover } from "@/utils/use_year_hover";

import type { YearSnapshot } from "@/types/plan";

const MARGIN = { top: 20, right: 30, bottom: 40, left: 50 };

const pctFormat = (value: number): string => format(".0%")(value);
const pctFormatDetail = (value: number): string => format(".1%")(value);

interface EffectiveTaxRateChartProps {
  snapshots: YearSnapshot[];
}

export const EffectiveTaxRateChart = ({ snapshots }: EffectiveTaxRateChartProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const size = useObservedSize(containerRef);

  const data = snapshots;

  const innerWidth = size.width - MARGIN.left - MARGIN.right;
  const innerHeight = size.height - MARGIN.top - MARGIN.bottom;

  // D3 scales
  const xScale = useMemo(() => {
    if (data.length === 0) return scaleLinear().domain([0, 1]).range([0, innerWidth]);
    const years = data.map((d) => d.year);
    return scaleLinear()
      .domain([Math.min(...years), Math.max(...years)])
      .range([0, innerWidth]);
  }, [data, innerWidth]);

  const yScale = useMemo(() => {
    if (data.length === 0) return scaleLinear().domain([0, 0.5]).range([innerHeight, 0]);
    const allRates = data.flatMap((d) => [d.effective_rate, d.marginal_rate]);
    const max = Math.max(...allRates, 0.1);
    const padding = max * 0.15;
    return scaleLinear()
      .domain([0, max + padding])
      .range([innerHeight, 0])
      .nice();
  }, [data, innerHeight]);

  // D3 line generators
  const effectivePath = useMemo(() => {
    const gen = line<YearSnapshot>()
      .x((d) => xScale(d.year))
      .y((d) => yScale(d.effective_rate));
    return gen(data) ?? "";
  }, [data, xScale, yScale]);

  const marginalPath = useMemo(() => {
    const gen = line<YearSnapshot>()
      .x((d) => xScale(d.year))
      .y((d) => yScale(d.marginal_rate));
    return gen(data) ?? "";
  }, [data, xScale, yScale]);

  // Axis ticks
  const tickCounts = chartTickCounts(innerWidth, innerHeight);
  const xTicks = useMemo(() => xScale.ticks(tickCounts.x), [xScale, tickCounts.x]);
  const yTicks = useMemo(() => yScale.ticks(tickCounts.y), [yScale, tickCounts.y]);

  // Hover handler
  const { hoverIndex, handleMouseMove, handleMouseLeave } = useYearHover(data, xScale);

  const hoverPoint = hoverIndex !== null ? data[hoverIndex] : null;

  if (data.length === 0) {
    return (
      <div
        ref={containerRef}
        style={{
          padding: 16,
          border: "1px solid #e0e0e0",
          borderRadius: 6,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#888",
          fontSize: 14,
          minHeight: 300,
        }}
      >
        No simulation data
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      style={{
        border: "1px solid #e0e0e0",
        borderRadius: 6,
        padding: 16,
        position: "relative",
        minHeight: 340,
      }}
    >
      <h3 style={{ margin: "0 0 4px" }}>Effective Tax Rate</h3>

      {/* Legend */}
      <div style={{ display: "flex", gap: 16, fontSize: 12, color: "#666", marginBottom: 8 }}>
        <span>
          <svg width={20} height={10} style={{ verticalAlign: "middle" }}>
            <line x1={0} y1={5} x2={20} y2={5} stroke="#4a90d9" strokeWidth={2} />
          </svg>{" "}
          Effective
        </span>
        <span>
          <svg width={20} height={10} style={{ verticalAlign: "middle" }}>
            <line
              x1={0}
              y1={5}
              x2={20}
              y2={5}
              stroke="#e8913a"
              strokeWidth={2}
              strokeDasharray="4 2"
            />
          </svg>{" "}
          Marginal
        </span>
      </div>

      {size.width > 0 && size.height > 0 && (
        <>
          <svg width={size.width - 32} height={size.height - 80}>
            <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
              <YGridLines ticks={yTicks} yScale={yScale} width={innerWidth} />

              {/* Effective rate line (solid) */}
              <path
                d={effectivePath}
                fill="none"
                stroke="#4a90d9"
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />

              {/* Marginal rate line (dashed) */}
              <path
                d={marginalPath}
                fill="none"
                stroke="#e8913a"
                strokeWidth={2}
                strokeDasharray="6 3"
                strokeLinejoin="round"
                strokeLinecap="round"
              />

              <XAxisTicks ticks={xTicks} xScale={xScale} y={innerHeight} />
              <YAxisTicks ticks={yTicks} yScale={yScale} format={pctFormat} />

              {/* Hover indicator */}
              {hoverPoint && (
                <>
                  <HoverLine x={xScale(hoverPoint.year)} height={innerHeight} />
                  <circle
                    cx={xScale(hoverPoint.year)}
                    cy={yScale(hoverPoint.effective_rate)}
                    r={4}
                    fill="#4a90d9"
                    stroke="#fff"
                    strokeWidth={2}
                    pointerEvents="none"
                  />
                  <circle
                    cx={xScale(hoverPoint.year)}
                    cy={yScale(hoverPoint.marginal_rate)}
                    r={4}
                    fill="#e8913a"
                    stroke="#fff"
                    strokeWidth={2}
                    pointerEvents="none"
                  />
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
          {hoverPoint && (
            <div
              style={{
                position: "absolute",
                left: xScale(hoverPoint.year) + MARGIN.left + 28,
                top: MARGIN.top + 20,
                background: "rgba(0,0,0,0.85)",
                color: "#fff",
                padding: "6px 10px",
                borderRadius: 4,
                fontSize: 12,
                lineHeight: 1.4,
                pointerEvents: "none",
                whiteSpace: "nowrap",
              }}
            >
              <div>
                <strong>{hoverPoint.year}</strong> (age {hoverPoint.age})
              </div>
              <div>
                Effective:{" "}
                <span style={{ color: "#7ab8ff" }}>
                  {pctFormatDetail(hoverPoint.effective_rate)}
                </span>
              </div>
              <div>
                Marginal:{" "}
                <span style={{ color: "#f5b77a" }}>
                  {pctFormatDetail(hoverPoint.marginal_rate)}
                </span>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};
