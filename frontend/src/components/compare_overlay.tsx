import { useMemo, useId } from "react";
import { line, area } from "d3-shape";
import type { ScaleLinear } from "d3-scale";
import type { YearSnapshot, YearDelta } from "@/types/plan";

interface CompareOverlayProps {
  baselineTimeline: YearSnapshot[];
  delta: YearDelta[];
  innerWidth: number;
  innerHeight: number;
  xScale: ScaleLinear<number, number>;
  yScale: ScaleLinear<number, number>;
  hoverYear: number | null;
}

/**
 * Baseline comparison layer for the net worth chart: a dashed baseline plus a
 * wash between the two series, tinted by polarity (ahead = success, behind =
 * danger). The legend lives in the parent chart's legend row.
 */
export default function CompareOverlay({
  baselineTimeline,
  delta,
  innerHeight,
  xScale,
  yScale,
  hoverYear,
}: CompareOverlayProps) {
  const clipId = useId();
  const clipAboveId = `clip-above-${clipId}`;
  const clipBelowId = `clip-below-${clipId}`;

  const baselinePath = useMemo(() => {
    const gen = line<YearSnapshot>()
      .x((d) => xScale(d.year))
      .y((d) => yScale(d.net_worth));
    return gen(baselineTimeline) ?? "";
  }, [baselineTimeline, xScale, yScale]);

  const deltaAreaPath = useMemo(() => {
    const gen = area<YearDelta>()
      .x((d) => xScale(d.year))
      .y0((d) => yScale(d.baselineNetWorth))
      .y1((d) => yScale(d.currentNetWorth));
    return gen(delta) ?? "";
  }, [delta, xScale, yScale]);

  const clipAbovePath = useMemo(() => {
    const gen = area<YearDelta>()
      .x((d) => xScale(d.year))
      .y0(0)
      .y1((d) => yScale(d.baselineNetWorth));
    return gen(delta) ?? "";
  }, [delta, xScale, yScale]);

  const clipBelowPath = useMemo(() => {
    const gen = area<YearDelta>()
      .x((d) => xScale(d.year))
      .y0((d) => yScale(d.baselineNetWorth))
      .y1(innerHeight);
    return gen(delta) ?? "";
  }, [delta, xScale, yScale, innerHeight]);

  const hoveredDelta = useMemo(() => {
    if (hoverYear === null) return null;
    return delta.find((d) => d.year === hoverYear) ?? null;
  }, [delta, hoverYear]);

  if (delta.length === 0) return null;

  return (
    <g className="compare-overlay">
      <defs>
        <clipPath id={clipAboveId}>
          <path d={clipAbovePath} />
        </clipPath>
        <clipPath id={clipBelowId}>
          <path d={clipBelowPath} />
        </clipPath>
      </defs>

      {/* Ahead of baseline */}
      <path
        d={deltaAreaPath}
        clipPath={`url(#${clipAboveId})`}
        style={{ fill: "var(--color-success)" }}
        fillOpacity={0.16}
        stroke="none"
      />

      {/* Behind baseline */}
      <path
        d={deltaAreaPath}
        clipPath={`url(#${clipBelowId})`}
        style={{ fill: "var(--color-danger)" }}
        fillOpacity={0.16}
        stroke="none"
      />

      <path
        d={baselinePath}
        fill="none"
        style={{ stroke: "var(--viz-context)" }}
        strokeWidth={1.5}
        strokeDasharray="5 4"
        strokeLinejoin="round"
        strokeLinecap="round"
      />

      {hoveredDelta && (
        <circle
          cx={xScale(hoveredDelta.year)}
          cy={yScale(hoveredDelta.baselineNetWorth)}
          r={4}
          style={{ fill: "var(--viz-context)", stroke: "var(--surface-card)" }}
          strokeWidth={2}
          pointerEvents="none"
        />
      )}
    </g>
  );
}
