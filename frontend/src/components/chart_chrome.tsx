import { useState, type CSSProperties, type ReactNode } from "react";

// ---------------------------------------------------------------------------
// Shared chart chrome: header, legend, tooltip, table view.
// Every dashboard chart composes these so the charts read as one system.
// ---------------------------------------------------------------------------

export function ChartHeader({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="chart-header">
      <div style={{ minWidth: 0 }}>
        <h3 className="chart-title">{title}</h3>
        {subtitle && <div className="chart-subtitle">{subtitle}</div>}
      </div>
      {children}
    </div>
  );
}

export type LegendKind = "line" | "dashed" | "swatch" | "dot";

export interface LegendEntry {
  label: string;
  color: string;
  kind?: LegendKind;
}

export function ChartLegend({ entries, style }: { entries: LegendEntry[]; style?: CSSProperties }) {
  if (entries.length === 0) return null;
  return (
    <div className="chart-legend" style={style}>
      {entries.map((entry) => (
        <span key={entry.label} className="legend-item">
          <LegendKey kind={entry.kind ?? "line"} color={entry.color} />
          {entry.label}
        </span>
      ))}
    </div>
  );
}

export function LegendKey({ kind, color }: { kind: LegendKind; color: string }) {
  switch (kind) {
    case "dashed":
      return <span className="legend-line dashed" style={{ borderTopColor: color }} />;
    case "swatch":
      return <span className="legend-swatch" style={{ background: color }} />;
    case "dot":
      return <span className="legend-dot" style={{ background: color }} />;
    default:
      return <span className="legend-line" style={{ background: color }} />;
  }
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

export interface TooltipPlacement {
  left: number;
  top: number;
}

/**
 * Place a tooltip beside an anchor inside a container, flipping to the left of
 * the anchor when it would overflow the right edge and clamping vertically.
 */
export function placeTooltip(opts: {
  anchorX: number;
  anchorY: number;
  width: number;
  height: number;
  containerWidth: number;
  containerHeight: number;
  gap?: number;
}): TooltipPlacement {
  const { anchorX, anchorY, width, height, containerWidth, containerHeight } = opts;
  const gap = opts.gap ?? 14;
  let left = anchorX + gap;
  if (left + width > containerWidth - 8) left = anchorX - gap - width;
  if (left < 8) left = Math.max(8, Math.min(anchorX + gap, containerWidth - width - 8));
  const maxTop = Math.max(8, containerHeight - height - 8);
  const top = Math.max(8, Math.min(anchorY - 24, maxTop));
  return { left, top };
}

export function VizTooltip({
  placement,
  width,
  maxHeight,
  title,
  meta,
  children,
}: {
  placement: TooltipPlacement;
  width: number;
  maxHeight?: number;
  title: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      className="viz-tooltip"
      role="status"
      style={{
        left: placement.left,
        top: placement.top,
        width,
        maxHeight,
        overflowY: maxHeight ? "auto" : undefined,
      }}
    >
      <div className="viz-tooltip-title">
        <strong>{title}</strong>
        {meta && <span>{meta}</span>}
      </div>
      <div className="viz-tooltip-rows">{children}</div>
    </div>
  );
}

export function TooltipRow({
  label,
  value,
  color,
  emphasis,
  muted,
  sub,
}: {
  label: ReactNode;
  value: ReactNode;
  color?: string;
  emphasis?: boolean;
  muted?: boolean;
  sub?: boolean;
}) {
  return (
    <>
      <span className={`viz-tooltip-label${sub ? " viz-tooltip-sub" : ""}`}>
        {color && <span className="viz-tooltip-key" style={{ background: color }} />}
        {label}
      </span>
      <span
        className={`viz-tooltip-value${muted || sub ? " muted" : ""}`}
        style={emphasis ? { fontSize: 13 } : undefined}
      >
        {value}
      </span>
    </>
  );
}

export function TooltipDivider() {
  return <div className="viz-tooltip-divider" />;
}

// ---------------------------------------------------------------------------
// Table view — the WCAG-clean twin of every chart
// ---------------------------------------------------------------------------

export interface TableColumn {
  key: string;
  label: string;
  numeric?: boolean;
}

export function ChartTable({
  columns,
  rows,
  caption,
  note,
  maxHeight = 280,
}: {
  columns: TableColumn[];
  rows: Array<Record<string, ReactNode>>;
  caption: string;
  note?: ReactNode;
  maxHeight?: number;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <div className="chart-footer">
        <span className="chart-note">{note}</span>
        <button
          type="button"
          className="chart-table-toggle"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "Hide data table" : "Show data table"}
        </button>
      </div>
      {open && (
        <div className="chart-table-wrap" style={{ maxHeight, overflowY: "auto" }}>
          <table className="chart-table">
            <caption
              style={{
                position: "absolute",
                width: 1,
                height: 1,
                overflow: "hidden",
                clip: "rect(0 0 0 0)",
              }}
            >
              {caption}
            </caption>
            <thead>
              <tr>
                {columns.map((col) => (
                  <th key={col.key} className={col.numeric ? "num" : undefined} scope="col">
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  {columns.map((col) => (
                    <td key={col.key} className={col.numeric ? "num" : undefined}>
                      {row[col.key]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Segmented control (currency mode, etc.)
// ---------------------------------------------------------------------------

export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
}: {
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (value: T) => void;
  ariaLabel: string;
}) {
  return (
    <div className="seg-control" role="group" aria-label={ariaLabel}>
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`seg-option${opt.value === value ? " active" : ""}`}
          aria-pressed={opt.value === value}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
