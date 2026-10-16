import { useRef, type KeyboardEvent } from "react";
import { scaleBand, scaleLinear } from "d3-scale";
import { line } from "d3-shape";

import { ChartLegend } from "@/components/chart_chrome";
import { compactCurrency, signedCompactCurrency } from "@/utils/format";

/** One candidate in display units: its ages, the plotted delta, and whether it is the best run. */
export interface ClaimingCell {
  key: string;
  ages: number[];
  value: number;
  best: boolean;
}

const POSITIVE = "var(--viz-1)";
const NEGATIVE = "var(--viz-2)";
const HEATMAP_MARGIN = { top: 28, right: 8, bottom: 8, left: 40 };
const COLUMNS_HEIGHT = 220;
const heatmapSize = (width: number) => Math.max(200, Math.min(width, 460));

/**
 * Drawn height of the claiming chart for one or two people in a container of
 * `width`, after `maxWidth: 100%` scaling, so a loading state can reserve it.
 */
export function claimingChartHeight(people: 1 | 2, width: number): number {
  const m = HEATMAP_MARGIN;
  const [svgWidth, svgHeight] =
    people === 2
      ? [heatmapSize(width), heatmapSize(width) + m.top + m.bottom - m.left - m.right]
      : [Math.max(280, width), COLUMNS_HEIGHT];
  return svgHeight * Math.min(1, width / svgWidth);
}

/** Diverging fill with a neutral midpoint at zero: blue above, orange below, card surface at 0. */
export function divergingFill(value: number, extent: number): string {
  if (!(extent > 0) || value === 0) return "var(--surface-card)";
  const share = Math.round(Math.min(1, Math.abs(value) / extent) * 85 + 10);
  return `color-mix(in srgb, ${value > 0 ? POSITIVE : NEGATIVE} ${share}%, var(--surface-card))`;
}

/** Arrow keys move the selection through `cells` laid out in rows of `columns`. */
function useRovingSelection(
  cells: ClaimingCell[],
  columns: number,
  onSelect: (key: string) => void,
) {
  const container = useRef<SVGSVGElement>(null);
  const move = (event: KeyboardEvent, index: number) => {
    const rows = Math.ceil(cells.length / columns);
    const row = Math.floor(index / columns);
    const column = index % columns;
    const target = {
      ArrowRight: column < columns - 1 ? index + 1 : index,
      ArrowLeft: column > 0 ? index - 1 : index,
      ArrowDown: row < rows - 1 ? index + columns : index,
      ArrowUp: row > 0 ? index - columns : index,
      Home: row * columns,
      End: Math.min(cells.length - 1, row * columns + columns - 1),
    }[event.key];
    if (target === undefined) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onSelect(cells[index].key);
      }
      return;
    }
    event.preventDefault();
    const next = cells[Math.min(cells.length - 1, target)];
    onSelect(next.key);
    container.current?.querySelector<SVGElement>(`[data-cell="${next.key}"]`)?.focus();
  };
  return { container, move };
}

function cellLabel(cell: ClaimingCell, names: string[], metric: string) {
  const ages = cell.ages.map((age, i) => `${names[i]} ${age}`).join(", ");
  return `${ages}: ${metric} ${signedCompactCurrency(cell.value)}${cell.best ? ", highest" : ""}`;
}

/**
 * Primary person's age (rows) by partner's age (columns), colored by the selected metric's
 * change from the current plan. The current ages are a dashed ring, which sits
 * between cells when a planned claim is not a whole age.
 */
export function ClaimingHeatmap({
  rowAges,
  columnAges,
  cells,
  current,
  selected,
  onSelect,
  names,
  metric,
  width,
}: {
  rowAges: number[];
  columnAges: number[];
  cells: ClaimingCell[];
  current: [number, number];
  selected: string;
  onSelect: (key: string) => void;
  names: [string, string];
  metric: string;
  width: number;
}) {
  const margin = HEATMAP_MARGIN;
  const size = heatmapSize(width);
  const x = scaleBand<number>()
    .domain(columnAges)
    .range([margin.left, size - margin.right])
    .padding(0.06);
  const y = scaleBand<number>()
    .domain(rowAges)
    .range([margin.top, margin.top + (size - margin.left - margin.right)])
    .padding(0.06);
  const height = (y.range()[1] ?? 0) + margin.bottom;
  const extent = Math.max(0, ...cells.map((c) => Math.abs(c.value)));
  const { container, move } = useRovingSelection(cells, columnAges.length, onSelect);
  // Linear position across band centers, so a fractional age lands between cells.
  const along = (ages: number[], band: typeof x, age: number) =>
    scaleLinear()
      .domain([ages[0], ages[ages.length - 1]])
      .range([
        (band(ages[0]) ?? 0) + band.bandwidth() / 2,
        (band(ages[ages.length - 1]) ?? 0) + band.bandwidth() / 2,
      ])(age);
  return (
    <svg
      ref={container}
      viewBox={`0 0 ${size} ${height}`}
      width={size}
      height={height}
      role="group"
      aria-label={`Claiming ages: ${names[0]} by ${names[1]}, ${metric} change from the current plan`}
      style={{ maxWidth: "100%", height: "auto", display: "block" }}
    >
      {/* Each axis names its person: rows run down, columns run across. */}
      <text
        x={margin.left - 6}
        y={margin.top - 14}
        textAnchor="end"
        fontSize={11}
        fill="var(--text-tertiary)"
      >
        {names[0]} ↓
      </text>
      <text
        x={(margin.left + size - margin.right) / 2}
        y={margin.top - 14}
        textAnchor="middle"
        fontSize={11}
        fill="var(--text-tertiary)"
      >
        {names[1]} →
      </text>
      {columnAges.map((age) => (
        <text
          key={`c${age}`}
          x={(x(age) ?? 0) + x.bandwidth() / 2}
          y={margin.top - 3}
          textAnchor="middle"
          fontSize={11}
          fill="var(--text-secondary)"
        >
          {age}
        </text>
      ))}
      {rowAges.map((age) => (
        <text
          key={`r${age}`}
          x={margin.left - 6}
          y={(y(age) ?? 0) + y.bandwidth() / 2}
          dy="0.32em"
          textAnchor="end"
          fontSize={11}
          fill="var(--text-secondary)"
        >
          {age}
        </text>
      ))}
      {cells.map((cell, index) => {
        const [row, column] = cell.ages;
        const isSelected = cell.key === selected;
        const cx = (x(column) ?? 0) + x.bandwidth() / 2;
        const cy = (y(row) ?? 0) + y.bandwidth() / 2;
        return (
          <g
            key={cell.key}
            data-cell={cell.key}
            role="button"
            tabIndex={isSelected ? 0 : -1}
            aria-pressed={isSelected}
            aria-label={cellLabel(cell, names, metric)}
            onClick={() => onSelect(cell.key)}
            onKeyDown={(e) => move(e, index)}
            style={{ cursor: "pointer", outline: "none" }}
          >
            <rect
              x={x(column)}
              y={y(row)}
              width={x.bandwidth()}
              height={y.bandwidth()}
              rx={3}
              fill={divergingFill(cell.value, extent)}
              stroke={isSelected ? "var(--text-primary)" : "var(--surface-border)"}
              strokeWidth={isSelected ? 2 : 1}
            />
            {cell.best && (
              <circle
                cx={cx}
                cy={cy}
                r={Math.min(4, x.bandwidth() / 6)}
                fill="var(--text-primary)"
              />
            )}
          </g>
        );
      })}
      <circle
        data-testid="current-marker"
        cx={along(columnAges, x, current[1])}
        cy={along(rowAges, y, current[0])}
        r={Math.max(5, x.bandwidth() / 3)}
        fill="none"
        stroke="var(--text-primary)"
        strokeWidth={1.5}
        strokeDasharray="3 2"
        pointerEvents="none"
      />
    </svg>
  );
}

/** One person: the selected metric's change from the current plan at each claim age. */
export function ClaimingColumns({
  cells,
  current,
  selected,
  onSelect,
  name,
  metric,
  width,
}: {
  cells: ClaimingCell[];
  current: number;
  selected: string;
  onSelect: (key: string) => void;
  name: string;
  metric: string;
  width: number;
}) {
  const height = COLUMNS_HEIGHT;
  const margin = { top: 12, right: 8, bottom: 26, left: 52 };
  const ages = cells.map((c) => c.ages[0]);
  const x = scaleBand<number>()
    .domain(ages)
    .range([margin.left, width - margin.right])
    .padding(0.2);
  const values = cells.map((c) => c.value);
  const y = scaleLinear()
    .domain([Math.min(0, ...values), Math.max(0, ...values)])
    .nice()
    .range([height - margin.bottom, margin.top]);
  if (y.domain()[0] === y.domain()[1]) y.domain([-1, 1]);
  const { container, move } = useRovingSelection(cells, cells.length, onSelect);
  const currentX =
    ages.length > 1
      ? scaleLinear()
          .domain([ages[0], ages[ages.length - 1]])
          .range([
            (x(ages[0]) ?? 0) + x.bandwidth() / 2,
            (x(ages[ages.length - 1]) ?? 0) + x.bandwidth() / 2,
          ])(current)
      : (x(ages[0]) ?? 0) + x.bandwidth() / 2;
  return (
    <svg
      ref={container}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="group"
      aria-label={`${metric} change from the current plan by ${name}'s claim age`}
      style={{ maxWidth: "100%", height: "auto", display: "block" }}
    >
      {y.ticks(4).map((t) => (
        <g key={t}>
          <line
            x1={margin.left}
            x2={width - margin.right}
            y1={y(t)}
            y2={y(t)}
            stroke={t === 0 ? "var(--viz-axis)" : "var(--viz-grid)"}
          />
          <text
            x={margin.left - 6}
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
      {cells.map((cell, index) => {
        const isSelected = cell.key === selected;
        const top = y(Math.max(0, cell.value));
        const barHeight = Math.max(1, Math.abs(y(cell.value) - y(0)));
        return (
          <g
            key={cell.key}
            data-cell={cell.key}
            role="button"
            tabIndex={isSelected ? 0 : -1}
            aria-pressed={isSelected}
            aria-label={cellLabel(cell, [name], metric)}
            onClick={() => onSelect(cell.key)}
            onKeyDown={(e) => move(e, index)}
            style={{ cursor: "pointer", outline: "none" }}
          >
            <rect
              x={x(cell.ages[0])}
              y={margin.top}
              width={x.bandwidth()}
              height={height - margin.top - margin.bottom}
              fill="transparent"
            />
            <rect
              x={x(cell.ages[0])}
              y={top}
              width={x.bandwidth()}
              height={barHeight}
              rx={2}
              fill={cell.value >= 0 ? POSITIVE : NEGATIVE}
              fillOpacity={cell.best || isSelected ? 1 : 0.45}
              stroke={isSelected ? "var(--text-primary)" : "none"}
              strokeWidth={2}
            />
            {cell.best && (
              <circle
                cx={(x(cell.ages[0]) ?? 0) + x.bandwidth() / 2}
                cy={top - 6}
                r={3}
                fill="var(--text-primary)"
              />
            )}
            <text
              x={(x(cell.ages[0]) ?? 0) + x.bandwidth() / 2}
              y={height - 8}
              textAnchor="middle"
              fontSize={11}
              fill={isSelected ? "var(--text-primary)" : "var(--text-secondary)"}
            >
              {cell.ages[0]}
            </text>
          </g>
        );
      })}
      <line
        data-testid="current-marker"
        x1={currentX}
        x2={currentX}
        y1={margin.top}
        y2={height - margin.bottom}
        stroke="var(--text-primary)"
        strokeWidth={1.5}
        strokeDasharray="3 2"
        pointerEvents="none"
      />
    </svg>
  );
}

export interface CumulativeSeries {
  id: string;
  label: string;
  color: string;
  dashed?: boolean;
  values: number[];
}

/** Household Social Security received to date, by year: where the lines cross is break-even. */
export function CumulativeBenefitsChart({
  years,
  series,
  width,
  label,
}: {
  years: number[];
  series: CumulativeSeries[];
  width: number;
  label: string;
}) {
  const height = 200;
  const margin = { top: 10, right: 12, bottom: 24, left: 56 };
  if (years.length === 0) return null;
  const x = scaleLinear()
    .domain([years[0], years[years.length - 1]])
    .range([margin.left, width - margin.right]);
  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const y = scaleLinear()
    .domain([0, max])
    .nice()
    .range([height - margin.bottom, margin.top]);
  const path = line<number>()
    .x((_, i) => x(years[i]))
    .y((v) => y(v));
  return (
    <div>
      <ChartLegend
        entries={series.map((s) => ({
          label: s.label,
          color: s.color,
          kind: s.dashed ? "dashed" : "line",
        }))}
      />
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        role="img"
        aria-label={label}
        style={{ maxWidth: "100%", height: "auto", display: "block" }}
      >
        {y.ticks(4).map((t) => (
          <g key={t}>
            <line
              x1={margin.left}
              x2={width - margin.right}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--viz-grid)"
            />
            <text
              x={margin.left - 6}
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
        {x.ticks(Math.min(6, years.length)).map((t) => (
          <text
            key={t}
            x={x(t)}
            y={height - 6}
            textAnchor="middle"
            fontSize={11}
            fill="var(--text-tertiary)"
          >
            {Math.round(t)}
          </text>
        ))}
        {series.map((s) => (
          <path
            key={s.id}
            d={path(s.values) ?? undefined}
            fill="none"
            stroke={s.color}
            strokeWidth={2}
            strokeDasharray={s.dashed ? "4 4" : undefined}
          />
        ))}
      </svg>
    </div>
  );
}
