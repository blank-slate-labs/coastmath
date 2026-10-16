import {
  Fragment,
  useCallback,
  useMemo,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import { yearBisector } from "@/utils/year_bisector";
import { scaleLinear } from "d3-scale";
import {
  area,
  curveMonotoneX,
  line,
  stack,
  stackOffsetDiverging,
  type SeriesPoint,
} from "d3-shape";

import { ChartTable } from "@/components/chart_chrome";
import { LedgerRow } from "@/components/year_ledger";
import type { YearSnapshot } from "@/types/plan";
import { compactCurrency, fullCurrency } from "@/utils/format";
import { useChartSize } from "@/utils/use_chart_size";
import { useScrubScrollLock } from "@/utils/use_scrub_scroll_lock";

// ---------------------------------------------------------------------------
// Where the net worth sits: the year-end balance of every account, stacked,
// from the snapshots the dashboard already shows (so the dollar mode applies).
// The selected year is the dashboard's; hovering previews a year in the
// readout, clicking or the arrow keys pin it for every panel.
// ---------------------------------------------------------------------------

/** The validated categorical slots (theme.css), in their fixed order. */
const SLOTS = [
  "var(--viz-1)",
  "var(--viz-2)",
  "var(--viz-3)",
  "var(--viz-4)",
  "var(--viz-5)",
  "var(--viz-6)",
  "var(--viz-7)",
  "var(--viz-8)",
];
const OTHER_KEY = "other";
const OTHER_COLOR = "var(--viz-context)";
/** Balances under half a dollar round to $0 and are not drawn. */
const VISIBLE = 0.5;

const CHART_HEIGHT = 260;
const MARGIN_DESKTOP = { top: 16, right: 16, bottom: 30, left: 58 };
const MARGIN_MOBILE = { top: 14, right: 12, bottom: 28, left: 46 };

export interface AccountLabel {
  id: string;
  name: string;
}

export interface CompositionSeries {
  key: string;
  name: string;
  color: string;
  /** Account IDs summed into this band; one, except for "Other accounts". */
  members: string[];
}

const accountLabel = (id: string, names: Map<string, string>): string =>
  names.get(id) || `Account ${id.slice(0, 8)}`;

/**
 * One band per account with a balance in any year, stacked from the baseline up
 * in the plan's account order (unknown IDs last). Colour follows that order, so
 * an account keeps its colour from year to year and between dollar modes. Past
 * eight accounts the remainder folds into one neutral "Other accounts" band.
 */
export function compositionSeries(
  snapshots: YearSnapshot[],
  accounts: AccountLabel[],
): CompositionSeries[] {
  const present = new Set<string>();
  for (const point of snapshots) {
    for (const [id, balance] of Object.entries(point.accounts ?? {}))
      if (Math.abs(balance) >= VISIBLE) present.add(id);
  }
  const names = new Map(accounts.map((account) => [account.id, account.name]));
  const ordered = [
    ...accounts.map((account) => account.id).filter((id) => present.has(id)),
    ...[...present].filter((id) => !names.has(id)).sort(),
  ];
  const own = ordered.length > SLOTS.length ? ordered.slice(0, SLOTS.length - 1) : ordered;
  const series: CompositionSeries[] = own.map((id, index) => ({
    key: id,
    name: accountLabel(id, names),
    color: SLOTS[index],
    members: [id],
  }));
  const rest = ordered.slice(own.length);
  if (rest.length > 0)
    series.push({ key: OTHER_KEY, name: "Other accounts", color: OTHER_COLOR, members: rest });
  return series;
}

const bandValue = (point: YearSnapshot, band: CompositionSeries): number =>
  band.members.reduce((sum, id) => sum + (point.accounts?.[id] ?? 0), 0);

export default function AccountCompositionChart({
  data,
  accounts,
  selectedYear,
  onSelectYear,
  dollarLabel,
}: {
  /** Snapshots in the dashboard's dollar mode. */
  data: YearSnapshot[];
  /** The plan's accounts, in their list order. */
  accounts: AccountLabel[];
  selectedYear: number | null;
  onSelectYear: (year: number) => void;
  dollarLabel: string;
}) {
  const { ref: chartRef, width, isCompact, isTiny } = useChartSize(720, CHART_HEIGHT);
  const [hoverYear, setHoverYear] = useState<number | null>(null);
  const hitRef = useScrubScrollLock<SVGRectElement>();

  const series = useMemo(() => compositionSeries(data, accounts), [data, accounts]);
  const names = useMemo(
    () => new Map(accounts.map((account) => [account.id, account.name])),
    [accounts],
  );
  const chartHeight = isTiny ? 200 : CHART_HEIGHT;
  const MARGIN = isCompact ? MARGIN_MOBILE : MARGIN_DESKTOP;
  const innerWidth = Math.max(width - MARGIN.left - MARGIN.right, 0);
  const innerHeight = Math.max(chartHeight - MARGIN.top - MARGIN.bottom, 0);

  const geometry = useMemo(() => {
    if (data.length === 0 || series.length === 0) return null;
    const first = data[0].year;
    const last = data[data.length - 1].year;
    const x = scaleLinear()
      .domain(first === last ? [first - 0.5, last + 0.5] : [first, last])
      .range([0, innerWidth]);
    const byKey = new Map(series.map((band) => [band.key, band]));
    const layers = stack<YearSnapshot, string>()
      .keys(series.map((band) => band.key))
      .value((point, key) => bandValue(point, byKey.get(key)!))
      .offset(stackOffsetDiverging)(data);
    const low = Math.min(0, ...layers.flatMap((layer) => layer.map((segment) => segment[0])));
    const high = Math.max(0, ...layers.flatMap((layer) => layer.map((segment) => segment[1])));
    const y = scaleLinear()
      .domain([low, high > low ? high : low + 1])
      .range([innerHeight, 0])
      .nice();
    const fill = area<SeriesPoint<YearSnapshot>>()
      .x((segment) => x(segment.data.year))
      .y0((segment) => y(segment[0]))
      .y1((segment) => y(segment[1]))
      .curve(curveMonotoneX);
    const edge = line<SeriesPoint<YearSnapshot>>()
      .x((segment) => x(segment.data.year))
      .y((segment) => y(segment[1]))
      .curve(curveMonotoneX);
    const bands = layers.map((layer, index) => ({
      band: series[index],
      fill: fill(layer) ?? "",
      edge: edge(layer) ?? "",
    }));
    const xTicks = x
      .ticks(Math.max(2, Math.floor(innerWidth / (isCompact ? 110 : 80))))
      .filter(Number.isInteger);
    const yTicks = y.ticks(isTiny ? 3 : 4);
    return { x, y, bands, xTicks, yTicks };
  }, [data, series, innerWidth, innerHeight, isCompact, isTiny]);

  const yearIndex = useMemo(() => new Map(data.map((point, index) => [point.year, index])), [data]);
  const pinnedIndex = selectedYear !== null ? (yearIndex.get(selectedYear) ?? null) : null;
  const activeIndex =
    (hoverYear !== null ? yearIndex.get(hoverYear) : undefined) ?? pinnedIndex ?? data.length - 1;
  const point = data[activeIndex] ?? null;
  const preview = hoverYear !== null && hoverYear !== selectedYear;

  const yearAt = useCallback(
    (event: MouseEvent<SVGRectElement>) => {
      if (!geometry) return null;
      const rect = event.currentTarget.getBoundingClientRect();
      return data[yearBisector(data, geometry.x.invert(event.clientX - rect.left))]?.year ?? null;
    },
    [data, geometry],
  );

  const onKeyDown = (event: KeyboardEvent<SVGRectElement>) => {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (step) {
      event.preventDefault();
      const current = pinnedIndex ?? (step > 0 ? -1 : data.length);
      onSelectYear(data[Math.max(0, Math.min(data.length - 1, current + step))].year);
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      onSelectYear(data[event.key === "Home" ? 0 : data.length - 1].year);
    } else if (event.key === "Escape") {
      setHoverYear(null);
    }
  };

  if (!geometry || !point) return <p className="ledger-empty">No account balances.</p>;

  const { x, y, bands, xTicks, yTicks } = geometry;
  const total = Object.values(point.accounts ?? {}).reduce((sum, balance) => sum + balance, 0);
  const totalAt = (snapshot: YearSnapshot) =>
    Object.values(snapshot.accounts ?? {}).reduce((sum, balance) => sum + balance, 0);
  const firstPoint = data[0];
  const lastPoint = data[data.length - 1];
  // The readout lists the top band first, as the bands stack.
  const readout = [...series].reverse();

  return (
    <div className="dash-split composition">
      <div className="dash-main" style={{ display: "grid", gap: 12 }}>
        <div className="viz-plot" ref={chartRef} style={{ width: "100%", height: chartHeight }}>
          <svg
            width={width}
            height={chartHeight}
            style={{ maxWidth: "100%", display: "block", overflow: "visible" }}
            role="img"
            aria-label={`Year-end balance of each account, stacked: ${compactCurrency(totalAt(firstPoint))} in ${firstPoint.year} to ${compactCurrency(totalAt(lastPoint))} in ${lastPoint.year}, ${dollarLabel.toLowerCase()}`}
          >
            <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
              {yTicks.map((tick) => (
                <line
                  key={`grid-${tick}`}
                  x1={0}
                  x2={innerWidth}
                  y1={y(tick)}
                  y2={y(tick)}
                  style={{ stroke: tick === 0 ? "var(--viz-axis)" : "var(--viz-grid)" }}
                  strokeWidth={1}
                  shapeRendering="crispEdges"
                />
              ))}

              {bands.map(({ band, fill }) => (
                <path key={band.key} d={fill} data-band={band.key} style={{ fill: band.color }} />
              ))}
              {/* A surface-coloured seam between neighbouring bands. */}
              {bands.slice(0, -1).map(({ band, edge }) => (
                <path
                  key={`edge-${band.key}`}
                  d={edge}
                  fill="none"
                  style={{ stroke: "var(--surface-card)" }}
                  strokeWidth={2}
                />
              ))}

              <line
                x1={x(point.year)}
                x2={x(point.year)}
                y1={0}
                y2={innerHeight}
                style={{ stroke: preview ? "var(--viz-axis)" : "var(--text-secondary)" }}
                strokeWidth={1}
                shapeRendering="crispEdges"
              />

              {xTicks.map((tick) => (
                <text
                  key={`x-${tick}`}
                  x={x(tick)}
                  y={innerHeight + 20}
                  textAnchor="middle"
                  fontSize={11}
                  style={{ fill: "var(--text-tertiary)" }}
                >
                  {tick}
                </text>
              ))}
              {yTicks.map((tick) => (
                <text
                  key={`y-${tick}`}
                  x={-12}
                  y={y(tick)}
                  dy="0.32em"
                  textAnchor="end"
                  fontSize={11}
                  style={{ fill: "var(--text-tertiary)" }}
                >
                  {compactCurrency(tick)}
                </text>
              ))}

              <rect
                width={innerWidth}
                height={innerHeight}
                fill="transparent"
                ref={hitRef}
                data-hover-target
                tabIndex={0}
                aria-label="Choose a year with arrow keys or by clicking the chart"
                style={{ touchAction: "pan-y", cursor: "pointer" }}
                onPointerMove={(event) => setHoverYear(yearAt(event))}
                onPointerLeave={() => setHoverYear(null)}
                onPointerCancel={() => setHoverYear(null)}
                onClick={(event) => {
                  const year = yearAt(event);
                  if (year !== null) onSelectYear(year);
                }}
                onKeyDown={onKeyDown}
              />
            </g>
          </svg>
        </div>

        <ChartTable
          caption="Account balances by year"
          columns={[
            { key: "year", label: "Year" },
            { key: "age", label: "Age" },
            ...series.map((band) => ({ key: band.key, label: band.name, numeric: true })),
            { key: "total", label: "Total", numeric: true },
          ]}
          rows={data.map((snapshot) => ({
            year: snapshot.year,
            age: snapshot.age,
            ...Object.fromEntries(
              series.map((band) => [band.key, fullCurrency(bandValue(snapshot, band))]),
            ),
            total: fullCurrency(totalAt(snapshot)),
          }))}
        />
      </div>

      <aside
        className={`ledger ledger-section composition-readout${preview ? " is-preview" : ""}`}
        aria-live="polite"
        aria-label={`Account balances, ${point.year}`}
      >
        <div className="ledger-section-head">
          <h3>{point.year}</h3>
          <span className="ledger-meta">age {point.age}</span>
        </div>
        <div className="ledger-rows">
          <h4 className="ledger-group-title">
            Year-end balances <span>{dollarLabel}</span>
          </h4>
          <LedgerRow label="Cash & investments" value={fullCurrency(total)} />
          {readout.map((band) => (
            <Fragment key={band.key}>
              <LedgerRow
                label={band.name}
                value={fullCurrency(bandValue(point, band))}
                keyColor={band.color}
              />
              {band.members.length > 1 &&
                band.members.map((id) => (
                  <LedgerRow
                    key={id}
                    label={accountLabel(id, names)}
                    value={fullCurrency(point.accounts?.[id] ?? 0)}
                    sub
                  />
                ))}
            </Fragment>
          ))}
        </div>
      </aside>
    </div>
  );
}
