import type { MouseEventHandler } from "react";

/**
 * Shared SVG pieces for the hand-drawn D3 line and bar charts. D3 supplies the scales and
 * ticks; these render the frame around the data inside the chart's margin-translated `<g>`.
 * Defaults match the light grey frame most charts use; themed charts pass their colours in.
 */

type Scale = (value: number) => number;

/** Tick counts that keep roughly 80px between x labels and 50px between y labels. */
export function chartTickCounts(innerWidth: number, innerHeight: number): { x: number; y: number } {
  return {
    x: Math.max(2, Math.floor(innerWidth / 80)),
    y: Math.max(2, Math.floor(innerHeight / 50)),
  };
}

interface YGridLinesProps {
  ticks: number[];
  yScale: Scale;
  width: number;
  stroke?: string;
  /** `null` draws solid lines. */
  strokeDasharray?: string | null;
  strokeWidth?: number;
}

/** One horizontal grid line per y tick, spanning the plot width. */
export function YGridLines({
  ticks,
  yScale,
  width,
  stroke = "#e0e0e0",
  strokeDasharray = "4 2",
  strokeWidth,
}: YGridLinesProps) {
  return (
    <>
      {ticks.map((tick) => (
        <line
          key={`yg-${tick}`}
          x1={0}
          x2={width}
          y1={yScale(tick)}
          y2={yScale(tick)}
          stroke={stroke}
          strokeDasharray={strokeDasharray ?? undefined}
          strokeWidth={strokeWidth}
        />
      ))}
    </>
  );
}

interface AxisTicksProps {
  ticks: number[];
  /** Draw a 6px tick mark in the label colour beside each label. */
  tickLine?: boolean;
  fill?: string;
  fontFamily?: string;
}

interface XAxisTicksProps extends AxisTicksProps {
  xScale: Scale;
  /** The plot's inner height: labels sit below it. */
  y: number;
}

/** Year-style labels centred under each x tick. */
export function XAxisTicks({
  ticks,
  xScale,
  y,
  tickLine = true,
  fill = "#666",
  fontFamily,
}: XAxisTicksProps) {
  return (
    <>
      {ticks.map((tick) => (
        <g key={`x-${tick}`} transform={`translate(${xScale(tick)},${y})`}>
          {tickLine && <line y2={6} stroke={fill} />}
          <text y={20} textAnchor="middle" fontSize={11} fill={fill} fontFamily={fontFamily}>
            {tick}
          </text>
        </g>
      ))}
    </>
  );
}

interface YAxisTicksProps extends AxisTicksProps {
  yScale: Scale;
  format: (value: number) => string;
}

/** Right-aligned value labels left of each y tick. */
export function YAxisTicks({
  ticks,
  yScale,
  format,
  tickLine = true,
  fill = "#666",
  fontFamily,
}: YAxisTicksProps) {
  return (
    <>
      {ticks.map((tick) => (
        <g key={`y-${tick}`} transform={`translate(0,${yScale(tick)})`}>
          {tickLine && <line x2={-6} stroke={fill} />}
          <text
            x={-10}
            dy="0.32em"
            textAnchor="end"
            fontSize={11}
            fill={fill}
            fontFamily={fontFamily}
          >
            {format(tick)}
          </text>
        </g>
      ))}
    </>
  );
}

/** Dashed vertical line through the hovered x position. */
export function HoverLine({
  x,
  height,
  stroke = "#999",
}: {
  x: number;
  height: number;
  stroke?: string;
}) {
  return (
    <line
      x1={x}
      x2={x}
      y1={0}
      y2={height}
      stroke={stroke}
      strokeDasharray="4 2"
      pointerEvents="none"
    />
  );
}

interface PointerOverlayProps {
  width: number;
  height: number;
  onMouseMove: MouseEventHandler<SVGRectElement>;
  onMouseLeave: MouseEventHandler<SVGRectElement>;
}

/** Transparent rect over the plot area that receives the hover events. Render it last. */
export function PointerOverlay({ width, height, onMouseMove, onMouseLeave }: PointerOverlayProps) {
  return (
    <rect
      width={width}
      height={height}
      fill="transparent"
      onMouseMove={onMouseMove}
      onMouseLeave={onMouseLeave}
    />
  );
}
