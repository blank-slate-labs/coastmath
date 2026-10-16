import { useMemo, useRef } from "react";
import { scaleBand, scaleLinear } from "d3-scale";
import { format } from "d3-format";
import { YAxisTicks, YGridLines, chartTickCounts } from "@/components/chart_frame";
import { useObservedSize } from "@/utils/use_chart_size";

import type { YearSnapshot } from "@/types/plan";

const MARGIN = { top: 20, right: 20, bottom: 40, left: 60 };
const STANDARD_COLOR = "#4a90d9";
const ITEMIZED_COLOR = "#10b981";

const currencyFormat = (value: number): string => {
  if (Math.abs(value) >= 1_000_000) {
    return `$${format(",.1f")(value / 1_000_000)}M`;
  }
  if (Math.abs(value) >= 1_000) {
    return `$${format(",.0f")(value / 1_000)}k`;
  }
  return `$${format(",.0f")(value)}`;
};

interface DeductionComparisonProps {
  snapshots: YearSnapshot[];
}

export const DeductionComparison = ({ snapshots }: DeductionComparisonProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  // The container only mounts once there are snapshots.
  const size = useObservedSize(containerRef, snapshots.length > 0);

  const itemizedCount = useMemo(
    () => snapshots.filter((s) => s.deduction_used === "itemized").length,
    [snapshots],
  );

  const innerWidth = size.width - MARGIN.left - MARGIN.right;
  const innerHeight = size.height - MARGIN.top - MARGIN.bottom;

  const xScale = useMemo(() => {
    const years = snapshots.map((s) => String(s.year));
    return scaleBand<string>().domain(years).range([0, innerWidth]).padding(0.3);
  }, [snapshots, innerWidth]);

  const yMax = useMemo(() => {
    let max = 0;
    for (const s of snapshots) {
      const std = s.standard_deduction ?? 0;
      const amt = s.deduction_amount ?? 0;
      if (std > max) max = std;
      if (amt > max) max = amt;
    }
    return max || 1000;
  }, [snapshots]);

  const yScale = useMemo(
    () =>
      scaleLinear()
        .domain([0, yMax * 1.1])
        .range([innerHeight, 0])
        .nice(),
    [yMax, innerHeight],
  );

  const yTickCount = chartTickCounts(innerWidth, innerHeight).y;
  const yTicks = useMemo(() => yScale.ticks(yTickCount), [yScale, yTickCount]);

  const barWidth = useMemo(() => {
    const bw = xScale.bandwidth();
    return Math.max(1, (bw - 2) / 2);
  }, [xScale]);

  // Decide which years to label (skip labels when bars are narrow)
  const xLabels = useMemo(() => {
    const years = snapshots.map((s) => String(s.year));
    if (years.length <= 15) return years;
    const step = Math.ceil(years.length / 15);
    return years.filter((_, i) => i % step === 0);
  }, [snapshots]);

  if (snapshots.length === 0) {
    return (
      <div style={{ padding: 16, border: "1px solid #e0e0e0", borderRadius: 6 }}>
        <h3 style={{ margin: "0 0 8px" }}>Deduction Comparison</h3>
        <p style={{ color: "#888" }}>No simulation data</p>
      </div>
    );
  }

  return (
    <div style={{ border: "1px solid #e0e0e0", borderRadius: 6, padding: 16 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 4,
        }}
      >
        <h3 style={{ margin: 0 }}>Deduction Comparison</h3>
        <span style={{ fontSize: 12, color: "#666" }}>
          You itemize in {itemizedCount} of {snapshots.length} years
        </span>
      </div>

      {/* Legend */}
      <div style={{ display: "flex", gap: 16, fontSize: 12, color: "#555", marginBottom: 4 }}>
        <span>
          <span
            style={{
              display: "inline-block",
              width: 10,
              height: 10,
              background: STANDARD_COLOR,
              borderRadius: 2,
              marginRight: 4,
              verticalAlign: "middle",
            }}
          />
          Standard
        </span>
        <span>
          <span
            style={{
              display: "inline-block",
              width: 10,
              height: 10,
              background: ITEMIZED_COLOR,
              borderRadius: 2,
              marginRight: 4,
              verticalAlign: "middle",
            }}
          />
          Itemized
        </span>
      </div>

      <div ref={containerRef} style={{ width: "100%", height: 260 }}>
        {size.width > 0 && size.height > 0 && (
          <svg width={size.width} height={size.height}>
            <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
              <YGridLines ticks={yTicks} yScale={yScale} width={innerWidth} />

              {/* Bars */}
              {snapshots.map((s) => {
                const x = xScale(String(s.year)) ?? 0;
                const isItemized = s.deduction_used === "itemized";
                const stdVal = s.standard_deduction ?? 0;
                const itemVal = isItemized ? s.deduction_amount : 0;

                return (
                  <g key={s.year}>
                    {/* Standard deduction bar */}
                    <rect
                      x={x}
                      y={yScale(stdVal)}
                      width={barWidth}
                      height={Math.max(0, innerHeight - yScale(stdVal))}
                      fill={STANDARD_COLOR}
                      opacity={isItemized ? 0.3 : 1}
                      rx={1}
                    />
                    {/* Itemized deduction bar */}
                    {itemVal > 0 && (
                      <rect
                        x={x + barWidth + 2}
                        y={yScale(itemVal)}
                        width={barWidth}
                        height={Math.max(0, innerHeight - yScale(itemVal))}
                        fill={ITEMIZED_COLOR}
                        opacity={isItemized ? 1 : 0.3}
                        rx={1}
                      />
                    )}
                  </g>
                );
              })}

              {/* X-axis labels */}
              {xLabels.map((yearStr) => {
                const x = xScale(yearStr);
                if (x == null) return null;
                return (
                  <text
                    key={`xl-${yearStr}`}
                    x={x + xScale.bandwidth() / 2}
                    y={innerHeight + 20}
                    textAnchor="middle"
                    fontSize={11}
                    fill="#666"
                  >
                    {yearStr}
                  </text>
                );
              })}

              <YAxisTicks ticks={yTicks} yScale={yScale} format={currencyFormat} />

              {/* X-axis baseline */}
              <line x1={0} x2={innerWidth} y1={innerHeight} y2={innerHeight} stroke="#ccc" />
            </g>
          </svg>
        )}
      </div>
    </div>
  );
};
