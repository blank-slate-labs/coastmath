import { useCallback, useMemo, useRef } from "react";
import { scaleLinear } from "d3-scale";
import { line } from "d3-shape";

import { generateCurve } from "@/utils/spline";
import { YGridLines } from "@/components/chart_frame";
import type { ControlPoint } from "@/types/plan";
import type { ControlPoint as SplinePoint } from "@/utils/spline";
import type { CurveType, CurveMode } from "@/types/plan";

const MARGIN = { top: 16, right: 16, bottom: 32, left: 48 };
const SVG_WIDTH = 480;
const SVG_HEIGHT = 240;
const INNER_W = SVG_WIDTH - MARGIN.left - MARGIN.right;
const INNER_H = SVG_HEIGHT - MARGIN.top - MARGIN.bottom;
const POINT_RADIUS = 6;

export interface AssumptionCurveEditorProps {
  curveType: CurveType;
  mode: CurveMode;
  fixedRate: number | null;
  controlPoints: ControlPoint[];
  onChange: (update: {
    mode?: CurveMode;
    fixedRate?: number | null;
    controlPoints?: ControlPoint[];
  }) => void;
  minAge: number;
  maxAge: number;
  minValue: number;
  maxValue: number;
  label: string;
  /** Id of the message explaining why the fixed rate is invalid. */
  invalid?: string;
}

/** Convert plan ControlPoint {x,y} to spline ControlPoint {age,value}. */
function toSplinePoints(pts: ControlPoint[]): SplinePoint[] {
  return pts.map((p) => ({ age: p.x, value: p.y }));
}

export default function AssumptionCurveEditor({
  curveType,
  mode,
  fixedRate,
  controlPoints,
  onChange,
  minAge,
  maxAge,
  minValue,
  maxValue,
  label,
  invalid,
}: AssumptionCurveEditorProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const draggingIdx = useRef<number | null>(null);

  // D3 scales
  const xScale = useMemo(
    () => scaleLinear().domain([minAge, maxAge]).range([0, INNER_W]),
    [minAge, maxAge],
  );

  const yScale = useMemo(
    () => scaleLinear().domain([minValue, maxValue]).range([INNER_H, 0]),
    [minValue, maxValue],
  );

  // Generate the dense curve path from control points
  const curvePath = useMemo(() => {
    if (controlPoints.length < 2) return "";
    const splinePts = toSplinePoints(controlPoints);
    const dense = generateCurve(splinePts, minAge, maxAge, 0.5);
    const gen = line<SplinePoint>()
      .x((d) => xScale(d.age))
      .y((d) => yScale(d.value));
    return gen(dense) ?? "";
  }, [controlPoints, minAge, maxAge, xScale, yScale]);

  // Axis ticks
  const xTicks = useMemo(() => xScale.ticks(Math.max(2, Math.floor(INNER_W / 80))), [xScale]);
  const yTicks = useMemo(() => yScale.ticks(Math.max(2, Math.floor(INNER_H / 40))), [yScale]);

  // Convert pixel coords (relative to inner area) to data coords, clamped
  const pixelToData = useCallback(
    (clientX: number, clientY: number): { x: number; y: number } => {
      const svg = svgRef.current;
      if (!svg) return { x: minAge, y: minValue };
      const rect = svg.getBoundingClientRect();
      const px = ((clientX - rect.left) * SVG_WIDTH) / (rect.width || SVG_WIDTH) - MARGIN.left;
      const py = ((clientY - rect.top) * SVG_HEIGHT) / (rect.height || SVG_HEIGHT) - MARGIN.top;
      const x = Math.round(Math.max(minAge, Math.min(maxAge, xScale.invert(px))));
      const y = Math.max(minValue, Math.min(maxValue, parseFloat(yScale.invert(py).toFixed(4))));
      return { x, y };
    },
    [minAge, maxAge, minValue, maxValue, xScale, yScale],
  );

  // --- Drag handlers via pointer events on window ---

  const handlePointerDown = useCallback(
    (idx: number) => (e: React.PointerEvent<SVGCircleElement>) => {
      e.preventDefault();
      e.stopPropagation();
      (e.target as SVGCircleElement).setPointerCapture(e.pointerId);
      draggingIdx.current = idx;

      const onMove = (me: PointerEvent) => {
        if (draggingIdx.current === null) return;
        const { x, y } = pixelToData(me.clientX, me.clientY);
        const next = [...controlPoints];
        next[draggingIdx.current] = { x, y };
        onChange({ controlPoints: next });
      };

      const onUp = () => {
        draggingIdx.current = null;
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      };

      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    },
    [controlPoints, onChange, pixelToData],
  );

  // Click on background to add a point
  const handleCanvasClick = useCallback(
    (e: React.MouseEvent<SVGRectElement>) => {
      const { x, y } = pixelToData(e.clientX, e.clientY);
      const next = [...controlPoints, { x, y }].sort((a, b) => a.x - b.x);
      onChange({ controlPoints: next });
    },
    [controlPoints, onChange, pixelToData],
  );

  // Double-click or right-click to remove a point (min 2)
  const handleRemovePoint = useCallback(
    (idx: number) => (e: React.MouseEvent<SVGCircleElement>) => {
      e.preventDefault();
      e.stopPropagation();
      if (controlPoints.length <= 2) return;
      const next = controlPoints.filter((_, i) => i !== idx);
      onChange({ controlPoints: next });
    },
    [controlPoints, onChange],
  );

  // Format value for display
  const formatValue = (v: number): string => {
    return `${(v * 100).toFixed(1)}%`;
  };

  return (
    <div data-testid="assumption-curve-editor" data-curve-type={curveType}>
      <div
        style={{
          fontSize: 13,
          fontWeight: 600,
          marginBottom: 6,
          color: "var(--text-primary)",
        }}
      >
        {label}
      </div>

      {/* Mode toggle */}
      <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
        <button
          data-testid="mode-fixed"
          onClick={() => onChange({ mode: "fixed" })}
          style={{
            padding: "4px 10px",
            fontSize: 12,
            border: "1px solid var(--surface-border-strong)",
            borderRadius: 4,
            cursor: "pointer",
            background: mode === "fixed" ? "var(--brand-primary)" : "var(--surface-card)",
            color: mode === "fixed" ? "var(--text-inverse)" : "var(--text-primary)",
          }}
        >
          Fixed Rate
        </button>
        <button
          data-testid="mode-curve"
          onClick={() => onChange({ mode: "curve" })}
          style={{
            padding: "4px 10px",
            fontSize: 12,
            border: "1px solid var(--surface-border-strong)",
            borderRadius: 4,
            cursor: "pointer",
            background: mode === "curve" ? "var(--brand-primary)" : "var(--surface-card)",
            color: mode === "curve" ? "var(--text-inverse)" : "var(--text-primary)",
          }}
        >
          Custom Curve
        </button>
      </div>

      {/* Fixed rate input */}
      {mode === "fixed" && (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input
            data-testid="fixed-rate-input"
            data-field="rate"
            aria-invalid={invalid ? true : undefined}
            aria-describedby={invalid}
            type="number"
            aria-label={`${label} percent`}
            step="0.1"
            value={fixedRate === null ? "" : Number((fixedRate * 100).toFixed(4))}
            onChange={(e) =>
              onChange({
                fixedRate: e.target.value === "" ? null : parseFloat(e.target.value) / 100,
              })
            }
            style={{
              width: 100,
              padding: "4px 8px",
              fontSize: 13,
              border: `1px solid ${invalid ? "var(--color-danger)" : "var(--surface-border-strong)"}`,
              borderRadius: 4,
            }}
          />
          <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
            {fixedRate !== null ? `${(fixedRate * 100).toFixed(1)}%` : "Not set"}
          </span>
        </div>
      )}

      {/* SVG curve editor */}
      {mode === "curve" && (
        <svg
          ref={svgRef}
          viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
          width="100%"
          role="img"
          aria-label={`${label} by age`}
          style={{ border: "1px solid var(--surface-border)", borderRadius: 4 }}
          data-testid="curve-svg"
        >
          <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
            <YGridLines
              ticks={yTicks}
              yScale={yScale}
              width={INNER_W}
              stroke="var(--surface-border)"
            />

            {/* X-axis ticks */}
            {xTicks.map((tick) => (
              <g key={`x-${tick}`} transform={`translate(${xScale(tick)},${INNER_H})`}>
                <line y2={4} stroke="var(--text-tertiary)" />
                <text y={16} textAnchor="middle" fontSize={10} fill="var(--text-secondary)">
                  {tick}
                </text>
              </g>
            ))}

            {/* Y-axis ticks */}
            {yTicks.map((tick) => (
              <g key={`y-${tick}`} transform={`translate(0,${yScale(tick)})`}>
                <line x2={-4} stroke="var(--text-tertiary)" />
                <text
                  x={-8}
                  dy="0.32em"
                  textAnchor="end"
                  fontSize={10}
                  fill="var(--text-secondary)"
                >
                  {formatValue(tick)}
                </text>
              </g>
            ))}

            {/* Catmull-Rom curve path */}
            {curvePath && (
              <path
                d={curvePath}
                fill="none"
                stroke="var(--brand-primary)"
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
                pointerEvents="none"
              />
            )}

            {/* Invisible click target to add points */}
            <rect
              width={INNER_W}
              height={INNER_H}
              fill="transparent"
              onClick={handleCanvasClick}
              data-testid="curve-canvas"
              data-sample-edit
            />

            {/* Draggable control points */}
            {controlPoints.map((pt, idx) => (
              <circle
                key={`cp-${idx}`}
                cx={xScale(pt.x)}
                cy={yScale(pt.y)}
                r={POINT_RADIUS}
                fill="var(--brand-primary)"
                stroke="var(--surface-card)"
                strokeWidth={2}
                style={{ cursor: "grab", touchAction: "none" }}
                onPointerDown={handlePointerDown(idx)}
                onDoubleClick={handleRemovePoint(idx)}
                onContextMenu={handleRemovePoint(idx)}
                data-testid={`control-point-${idx}`}
                data-sample-edit
              />
            ))}
          </g>
        </svg>
      )}
    </div>
  );
}
