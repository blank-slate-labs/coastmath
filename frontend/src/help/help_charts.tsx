/* Chart primitives for help figures. D3 computes scales and geometry; React renders the SVG.
   Marks follow one spec: 2px lines, bars ≤ 24px with a 4px rounded data end, 2px surface gaps,
   solid hairline grids, text in ink tokens (never the series color), a legend for 2+ series.
   Hue meaning is fixed across the help center: blue income, orange tax, cyan saving,
   magenta spending, gray a neutral reference. */
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import {
  area as d3Area,
  curveMonotoneX,
  curveStepAfter,
  line as d3Line,
  scaleBand,
  scaleLinear,
} from "d3";
import { formatTick, formatValue, type ValueFormat } from "./help_format";

export type SeriesColor = "blue" | "orange" | "cyan" | "magenta" | "gray";

const FALLBACK_WIDTH = 680;
const MARGIN = { top: 16, right: 16, bottom: 34, left: 56 };

/** Measured width after hydration; the prerendered SVG uses the fallback and scales with CSS. */
function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(FALLBACK_WIDTH);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () => {
      const measured = Math.round(element.getBoundingClientRect().width);
      if (measured > 0) setWidth(Math.max(280, measured));
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function Legend({
  items,
}: {
  items: { label: string; color: SeriesColor; shape?: "line" | "block" }[];
}) {
  if (items.length < 2) return null;
  return (
    <ul className="help-chart-legend">
      {items.map((item) => (
        <li key={item.label}>
          <span
            className={`help-key is-${item.color} is-${item.shape ?? "block"}`}
            aria-hidden="true"
          />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

function Tooltip({
  x,
  y,
  width,
  children,
}: {
  x: number;
  y: number;
  width: number;
  children: ReactNode;
}) {
  const flip = x > width * 0.6;
  return (
    <div
      className="help-chart-tooltip"
      aria-hidden="true"
      style={{
        left: flip ? undefined : x + 12,
        right: flip ? width - x + 12 : undefined,
        top: Math.max(0, y),
      }}
    >
      {children}
    </div>
  );
}

function niceDomain(values: number[], min?: number, max?: number): [number, number] {
  const low = min ?? Math.min(0, ...values);
  const high = max ?? Math.max(0, ...values);
  const scale = scaleLinear()
    .domain([low, high === low ? low + 1 : high])
    .nice(5);
  return scale.domain() as [number, number];
}

/** Category labels angle down when the widest one wouldn't fit its slot. */
const LABEL_CHAR_WIDTH = 6.6;
function categoryLayout(labels: string[], slot: number) {
  const widest = Math.max(0, ...labels.map((label) => label.length * LABEL_CHAR_WIDTH));
  const angled = widest > slot - 4;
  return { angled, extra: angled ? Math.min(90, Math.round(widest * 0.64)) : 0 };
}

function CategoryLabel({
  x,
  y,
  text,
  angled,
}: {
  x: number;
  y: number;
  text: string;
  angled: boolean;
}) {
  return angled ? (
    <text
      className="help-chart-xtick"
      x={x}
      y={y - 8}
      textAnchor="end"
      transform={`rotate(-40 ${x} ${y - 8})`}
    >
      {text}
    </text>
  ) : (
    <text className="help-chart-xtick" x={x} y={y} textAnchor="middle">
      {text}
    </text>
  );
}

type XFormat = "year" | "age" | "num" | "usd" | "pct";
const xText = (value: number, format: XFormat) =>
  format === "age"
    ? `${Math.round(value)}`
    : format === "usd" || format === "pct"
      ? formatTick(value, format)
      : formatValue(value, format);
const xTitle = (value: number, format: XFormat) =>
  format === "age"
    ? `Age ${Math.round(value)}`
    : format === "usd" || format === "pct"
      ? formatValue(value, format)
      : xText(value, format);

/* ------------------------------------------------------------------ line */

export interface LineSeries {
  id: string;
  label: string;
  color: SeriesColor;
  points: [number, number][];
  area?: boolean;
}

/**
 * Values over years or ages. `markers` draw a labeled vertical rule (an event); `bands` shade an
 * x-range (a period). `step` holds each value until the next point, for annual amounts that
 * change only at year boundaries.
 */
export function LineChart({
  series,
  xFormat = "year",
  yFormat = "usd",
  yMin,
  yMax,
  markers = [],
  bands = [],
  step = false,
  height = 280,
  label,
}: {
  series: LineSeries[];
  xFormat?: XFormat;
  yFormat?: ValueFormat;
  yMin?: number;
  yMax?: number;
  markers?: { x: number; label: string }[];
  bands?: { from: number; to: number; label: string }[];
  step?: boolean;
  height?: number;
  label: string;
}) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState<number | null>(null);
  const xs = useMemo(
    () => [...new Set(series.flatMap((s) => s.points.map((p) => p[0])))].sort((a, b) => a - b),
    [series],
  );
  const inner = { w: width - MARGIN.left - MARGIN.right, h: height - MARGIN.top - MARGIN.bottom };
  const x = scaleLinear()
    .domain([xs[0], xs[xs.length - 1]])
    .range([0, inner.w]);
  const y = scaleLinear()
    .domain(
      niceDomain(
        series.flatMap((s) => s.points.map((p) => p[1])),
        yMin,
        yMax,
      ),
    )
    .range([inner.h, 0]);
  const curve = step ? curveStepAfter : curveMonotoneX;
  const path = d3Line<[number, number]>()
    .x((p) => x(p[0]))
    .y((p) => y(p[1]))
    .curve(curve);
  const fill = d3Area<[number, number]>()
    .x((p) => x(p[0]))
    .y0(y(Math.max(0, y.domain()[0])))
    .y1((p) => y(p[1]))
    .curve(curve);
  const xTicks = x
    .ticks(Math.max(2, Math.min(8, Math.floor(inner.w / 80))))
    .filter((t) => (xFormat !== "year" && xFormat !== "age") || Number.isInteger(t));

  const pick = (clientX: number, rect: DOMRect) => {
    const value = x.invert(clientX - rect.left - MARGIN.left);
    let best = 0;
    xs.forEach((candidate, index) => {
      if (Math.abs(candidate - value) < Math.abs(xs[best] - value)) best = index;
    });
    setActive(best);
  };
  const onKey = (event: KeyboardEvent) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    setActive((current) =>
      Math.min(
        xs.length - 1,
        Math.max(
          0,
          (current ?? (event.key === "ArrowLeft" ? xs.length : -1)) +
            (event.key === "ArrowLeft" ? -1 : 1),
        ),
      ),
    );
  };
  const activeX = active == null ? null : xs[active];

  return (
    <div className="help-chart" ref={ref}>
      <Legend items={series.map((s) => ({ label: s.label, color: s.color, shape: "line" }))} />
      <div className="help-chart-stage">
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={label}
          tabIndex={0}
          onKeyDown={onKey}
          onBlur={() => setActive(null)}
          onPointerMove={(event: PointerEvent<SVGSVGElement>) =>
            pick(event.clientX, event.currentTarget.getBoundingClientRect())
          }
          onPointerLeave={() => setActive(null)}
        >
          <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
            {bands.map((band) => (
              <g key={band.label} className="help-chart-band">
                <rect
                  x={x(band.from)}
                  y={0}
                  width={Math.max(0, x(band.to) - x(band.from))}
                  height={inner.h}
                />
                <text x={x(band.from) + 6} y={12}>
                  {band.label}
                </text>
              </g>
            ))}
            {y.ticks(5).map((t) => (
              <g key={t} className="help-chart-grid">
                <line x1={0} x2={inner.w} y1={y(t)} y2={y(t)} />
                <text x={-10} y={y(t)} dy="0.32em" textAnchor="end">
                  {formatTick(t, yFormat)}
                </text>
              </g>
            ))}
            {xTicks.map((t) => (
              <text
                key={t}
                className="help-chart-xtick"
                x={x(t)}
                y={inner.h + 22}
                textAnchor="middle"
              >
                {xText(t, xFormat)}
              </text>
            ))}
            {series
              .filter((s) => s.area)
              .map((s) => (
                <path
                  key={`${s.id}-area`}
                  className={`help-area is-${s.color}`}
                  d={fill(s.points) ?? undefined}
                />
              ))}
            {series.map((s) => (
              <path
                key={s.id}
                className={`help-line is-${s.color}`}
                d={path(s.points) ?? undefined}
              />
            ))}
            {markers.map((marker, index) => (
              <g key={marker.label} className="help-chart-marker">
                <line x1={x(marker.x)} x2={x(marker.x)} y1={index % 2 ? 18 : 4} y2={inner.h} />
                <text
                  x={x(marker.x) + (x(marker.x) > inner.w * 0.75 ? -6 : 6)}
                  y={index % 2 ? 26 : 12}
                  textAnchor={x(marker.x) > inner.w * 0.75 ? "end" : "start"}
                >
                  {marker.label}
                </text>
              </g>
            ))}
            {activeX != null && (
              <line
                className="help-chart-crosshair"
                x1={x(activeX)}
                x2={x(activeX)}
                y1={0}
                y2={inner.h}
              />
            )}
            {activeX != null &&
              series.map((s) => {
                const point = s.points.find((p) => p[0] === activeX);
                return point ? (
                  <circle
                    key={s.id}
                    className={`help-dot is-${s.color}`}
                    cx={x(point[0])}
                    cy={y(point[1])}
                    r={4}
                  />
                ) : null;
              })}
          </g>
        </svg>
        {activeX != null && (
          <Tooltip x={MARGIN.left + x(activeX)} y={MARGIN.top} width={width}>
            <p className="help-chart-tooltip-title">{xTitle(activeX, xFormat)}</p>
            {series.map((s) => {
              const point = s.points.find((p) => p[0] === activeX);
              return point ? (
                <p key={s.id}>
                  <span className={`help-key is-${s.color} is-line`} />
                  {s.label}
                  <b>{formatValue(point[1], yFormat)}</b>
                </p>
              ) : null;
            })}
          </Tooltip>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ bars */

export interface BarSeries {
  id: string;
  label: string;
  color: SeriesColor;
  values: number[];
}

/**
 * Columns per category (years, ages or named cases). Stacked by default; positive values stack
 * up from zero and negative values stack down, so inflows and outflows share one baseline.
 */
export function BarChart({
  categories,
  series,
  stacked = true,
  yFormat = "usd",
  yMin,
  yMax,
  highlight,
  height = 280,
  label,
}: {
  categories: (string | number)[];
  series: BarSeries[];
  stacked?: boolean;
  yFormat?: ValueFormat;
  yMin?: number;
  yMax?: number;
  highlight?: number;
  height?: number;
  label: string;
}) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState<number | null>(null);
  const labels = categories.map(String);
  const numeric = categories.every((c) => typeof c === "number");
  const probe = scaleBand<number>()
    .domain(categories.map((_, i) => i))
    .range([0, width - MARGIN.left - MARGIN.right])
    .paddingOuter(0.1);
  const { angled, extra } = numeric
    ? { angled: false, extra: 0 }
    : categoryLayout(labels, probe.step());
  const chartHeight = height + extra;
  const inner = { w: width - MARGIN.left - MARGIN.right, h: height - MARGIN.top - MARGIN.bottom };
  const x = scaleBand<number>()
    .domain(categories.map((_, i) => i))
    .range([0, inner.w])
    .paddingInner(stacked ? 0.35 : 0.2)
    .paddingOuter(0.1);
  const groupWidth = x.bandwidth();
  const barWidth = stacked
    ? Math.min(24, groupWidth)
    : Math.min(24, (groupWidth - 2 * (series.length - 1)) / series.length);

  const stacks = categories.map((_, i) => {
    let up = 0,
      down = 0;
    return series.map((s) => {
      const v = s.values[i] ?? 0;
      if (!stacked) return { s, from: 0, to: v };
      if (v >= 0) {
        const from = up;
        up += v;
        return { s, from, to: up };
      }
      const from = down;
      down += v;
      return { s, from, to: down };
    });
  });
  const extent = stacks.flatMap((stack) => stack.flatMap((item) => [item.from, item.to]));
  const y = scaleLinear()
    .domain(niceDomain(extent, yMin, yMax))
    .range([inner.h, 0]);
  const everyNth = numeric
    ? Math.max(1, Math.ceil(categories.length / Math.max(2, Math.floor(inner.w / 56))))
    : 1;

  const onKey = (event: KeyboardEvent) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    setActive((current) =>
      Math.min(
        categories.length - 1,
        Math.max(
          0,
          (current ?? (event.key === "ArrowLeft" ? categories.length : -1)) +
            (event.key === "ArrowLeft" ? -1 : 1),
        ),
      ),
    );
  };

  const barPath = (x0: number, w: number, from: number, to: number) => {
    // Square at the baseline side, 4px rounded at the data end; a 2px surface gap between stacked segments.
    const gap = stacked && from !== 0 ? 1 : 0;
    const top = y(Math.max(from, to)) + (to >= from ? 0 : gap);
    const bottom = y(Math.min(from, to)) - (to >= from ? gap : 0);
    const h = Math.max(0, bottom - top);
    const r = Math.min(4, h / 2, w / 2);
    const outer = to >= 0;
    return outer
      ? `M${x0},${bottom}V${top + r}Q${x0},${top} ${x0 + r},${top}H${x0 + w - r}Q${x0 + w},${top} ${x0 + w},${top + r}V${bottom}Z`
      : `M${x0},${top}V${bottom - r}Q${x0},${bottom} ${x0 + r},${bottom}H${x0 + w - r}Q${x0 + w},${bottom} ${x0 + w},${bottom - r}V${top}Z`;
  };

  return (
    <div className="help-chart" ref={ref}>
      <Legend items={series.map((s) => ({ label: s.label, color: s.color }))} />
      <div className="help-chart-stage">
        <svg
          width={width}
          height={chartHeight}
          viewBox={`0 0 ${width} ${chartHeight}`}
          role="img"
          aria-label={label}
          tabIndex={0}
          onKeyDown={onKey}
          onBlur={() => setActive(null)}
          onPointerLeave={() => setActive(null)}
        >
          <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
            {y.ticks(5).map((t) => (
              <g key={t} className={`help-chart-grid${t === 0 ? " is-zero" : ""}`}>
                <line x1={0} x2={inner.w} y1={y(t)} y2={y(t)} />
                <text x={-10} y={y(t)} dy="0.32em" textAnchor="end">
                  {formatTick(t, yFormat)}
                </text>
              </g>
            ))}
            {categories.map((category, i) => {
              const x0 = x(i) ?? 0;
              const dim =
                (highlight != null && highlight !== i) || (active != null && active !== i);
              return (
                <g
                  key={i}
                  className={dim ? "is-dim" : undefined}
                  onPointerEnter={() => setActive(i)}
                >
                  <rect
                    className="help-chart-hit"
                    x={x0 - (x.step() - groupWidth) / 2}
                    y={0}
                    width={x.step()}
                    height={inner.h}
                  />
                  {stacks[i].map((item, j) => {
                    if (item.to === item.from) return null;
                    const bx = stacked
                      ? x0 + (groupWidth - barWidth) / 2
                      : x0 +
                        (groupWidth - (barWidth * series.length + 2 * (series.length - 1))) / 2 +
                        j * (barWidth + 2);
                    return (
                      <path
                        key={item.s.id}
                        className={`help-bar is-${item.s.color}`}
                        d={barPath(bx, barWidth, item.from, item.to)}
                      />
                    );
                  })}
                  {i % everyNth === 0 && (
                    <CategoryLabel
                      x={x0 + groupWidth / 2}
                      y={inner.h + 22}
                      text={String(category)}
                      angled={angled}
                    />
                  )}
                </g>
              );
            })}
          </g>
        </svg>
        {active != null && (
          <Tooltip x={MARGIN.left + (x(active) ?? 0) + groupWidth / 2} y={MARGIN.top} width={width}>
            <p className="help-chart-tooltip-title">{categories[active]}</p>
            {series.map((s) =>
              s.values[active] ? (
                <p key={s.id}>
                  <span className={`help-key is-${s.color}`} />
                  {s.label}
                  <b>{formatValue(s.values[active], yFormat)}</b>
                </p>
              ) : null,
            )}
          </Tooltip>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ brackets */

export interface Bracket {
  rate: number;
  upTo: number | null;
}
export interface BracketSegment {
  label: string;
  amount: number;
  color: SeriesColor;
}

/**
 * Income stacked left to right across rate brackets: where each layer lands and at what rate.
 * `start` offsets the first segment (e.g. ordinary income already below a gains layer).
 * `thresholds` add labeled rules that are not bracket edges (a surcharge tier, a deduction).
 */
export function BracketBar({
  brackets,
  segments,
  start = 0,
  thresholds = [],
  max,
  label,
}: {
  brackets: Bracket[];
  segments: BracketSegment[];
  start?: number;
  thresholds?: { at: number; label: string }[];
  max?: number;
  label: string;
}) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState<number | null>(null);
  const total = start + segments.reduce((sum, s) => sum + s.amount, 0);
  const finiteEdges = brackets.map((b) => b.upTo).filter((v): v is number => v != null);
  const domainMax =
    max ?? Math.max(total * 1.12, ...finiteEdges.filter((edge) => edge <= total * 1.6));
  const margin = { left: 16, right: 16 };
  const inner = width - margin.left - margin.right;
  const x = scaleLinear().domain([0, domainMax]).range([0, inner]).clamp(true);
  const height = 150;
  const barY = 64,
    barH = 24;
  let cursor = start;
  const placed = segments.map((s) => {
    const from = cursor;
    cursor += s.amount;
    return { ...s, from, to: cursor };
  });
  const zones = brackets
    .map((b, i) => ({
      ...b,
      from: i === 0 ? 0 : (brackets[i - 1].upTo ?? 0),
      to: b.upTo ?? domainMax,
    }))
    .filter((z) => z.from < domainMax);
  const ratesAcross = (from: number, to: number) =>
    zones
      .filter((z) => z.to > from && z.from < to)
      .map((z) => formatValue(z.rate, "pct", (z.rate * 100) % 1 ? 1 : 0));

  return (
    <div className="help-chart" ref={ref}>
      <Legend items={segments.map((s) => ({ label: s.label, color: s.color }))} />
      <div className="help-chart-stage">
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={label}
          tabIndex={0}
          onBlur={() => setActive(null)}
          onPointerLeave={() => setActive(null)}
          onKeyDown={(event) => {
            if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
              event.preventDefault();
              setActive((current) =>
                Math.min(
                  placed.length - 1,
                  Math.max(0, (current ?? -1) + (event.key === "ArrowRight" ? 1 : -1)),
                ),
              );
            }
          }}
        >
          <g transform={`translate(${margin.left},0)`}>
            {zones.map((zone, i) => (
              <g key={i} className={`help-bracket-zone${i % 2 ? " is-alt" : ""}`}>
                <rect
                  x={x(zone.from)}
                  y={34}
                  width={Math.max(0, x(zone.to) - x(zone.from))}
                  height={barH + 60}
                />
                {x(zone.to) - x(zone.from) > 34 && (
                  <text x={(x(zone.from) + x(zone.to)) / 2} y={50} textAnchor="middle">
                    {formatValue(zone.rate, "pct", (zone.rate * 100) % 1 ? 1 : 0)}
                  </text>
                )}
                {i > 0 && (
                  <line x1={x(zone.from)} x2={x(zone.from)} y1={34} y2={barY + barH + 26} />
                )}
              </g>
            ))}
            {placed.map(
              (s, i) =>
                s.amount > 0 && (
                  <rect
                    key={s.label}
                    className={`help-bar is-${s.color}${active != null && active !== i ? " is-dim" : ""}`}
                    x={x(s.from) + (i > 0 || start > 0 ? 1 : 0)}
                    y={barY}
                    width={Math.max(
                      0,
                      x(s.to) -
                        x(s.from) -
                        (i > 0 || start > 0 ? 1 : 0) -
                        (i < placed.length - 1 ? 1 : 0),
                    )}
                    height={barH}
                    rx={i === placed.length - 1 ? 4 : 0}
                    onPointerEnter={() => setActive(i)}
                  />
                ),
            )}
            {start > 0 && (
              <rect
                className="help-bar is-gray is-quiet"
                x={0}
                y={barY}
                width={Math.max(0, x(start) - 1)}
                height={barH}
              />
            )}
            {thresholds.map((t, i) => (
              <g key={t.label} className="help-chart-marker">
                <line
                  x1={x(t.at)}
                  x2={x(t.at)}
                  y1={barY - 6}
                  y2={barY + barH + 18 + (i % 2) * 14}
                />
                <text
                  x={x(t.at)}
                  y={barY + barH + 30 + (i % 2) * 14}
                  textAnchor={
                    x(t.at) > inner * 0.8 ? "end" : x(t.at) < inner * 0.2 ? "start" : "middle"
                  }
                >
                  {t.label}
                </text>
              </g>
            ))}
            <text className="help-chart-xtick" x={0} y={24}>
              {formatTick(0)}
            </text>
            <text className="help-chart-xtick" x={inner} y={24} textAnchor="end">
              {formatTick(domainMax)}
            </text>
          </g>
        </svg>
        {active != null && placed[active] && (
          <Tooltip
            x={margin.left + x((placed[active].from + placed[active].to) / 2)}
            y={barY + barH + 8}
            width={width}
          >
            <p className="help-chart-tooltip-title">{placed[active].label}</p>
            <p>
              Amount<b>{formatValue(placed[active].amount)}</b>
            </p>
            <p>
              Taxed at<b>{ratesAcross(placed[active].from, placed[active].to).join(", ")}</b>
            </p>
          </Tooltip>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ timeline */

/** Periods (spans) and moments (events) across ages or years. */
export function Timeline({
  from,
  to,
  unit = "age",
  spans = [],
  events = [],
  label,
}: {
  from: number;
  to: number;
  unit?: "age" | "year";
  label: string;
  spans?: { from: number; to: number; label: string; color: SeriesColor; row?: number }[];
  events?: { at: number; label: string }[];
}) {
  const [ref, width] = useWidth();
  const margin = { left: 16, right: 16 };
  const inner = width - margin.left - margin.right;
  const x = scaleLinear().domain([from, to]).range([0, inner]);
  const rows = Math.max(1, ...spans.map((s) => (s.row ?? 0) + 1));
  const eventTiers = 2;
  const top = 18 + eventTiers * 16;
  const rowH = 30;
  const axisY = top + rows * rowH + 6;
  const height = axisY + 30;
  const ticks = x.ticks(Math.max(2, Math.min(10, Math.floor(inner / 64)))).filter(Number.isInteger);
  return (
    <div className="help-chart" ref={ref}>
      <div className="help-chart-stage">
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={label}
        >
          <g transform={`translate(${margin.left},0)`}>
            {events.map((event, i) => {
              const ex = x(event.at);
              const anchor = ex > inner * 0.82 ? "end" : ex < inner * 0.12 ? "start" : "middle";
              const tier = i % eventTiers;
              return (
                <g key={`${event.label}-${i}`} className="help-chart-marker">
                  <line x1={ex} x2={ex} y1={14 + tier * 16 + 6} y2={axisY} />
                  <text x={ex} y={14 + tier * 16} textAnchor={anchor}>
                    {event.label}
                  </text>
                </g>
              );
            })}
            {spans.map((span, i) => {
              const sx = x(span.from),
                ex = x(span.to),
                row = span.row ?? 0;
              const y0 = top + row * rowH;
              return (
                <g key={`${span.label}-${i}`}>
                  <rect
                    className={`help-span is-${span.color}`}
                    x={sx + 1}
                    y={y0}
                    width={Math.max(2, ex - sx - 2)}
                    height={20}
                    rx={4}
                  />
                  <text className="help-span-label" x={sx + 8} y={y0 + 14}>
                    {span.label}
                  </text>
                </g>
              );
            })}
            <line className="help-chart-axis" x1={0} x2={inner} y1={axisY} y2={axisY} />
            {ticks.map((t) => (
              <g key={t} className="help-chart-xtick">
                <line x1={x(t)} x2={x(t)} y1={axisY} y2={axisY + 4} />
                <text x={x(t)} y={axisY + 20} textAnchor="middle">
                  {t}
                </text>
              </g>
            ))}
          </g>
        </svg>
        <p className="help-chart-axis-label">{unit === "age" ? "Age" : "Year"}</p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ waterfall */

/**
 * A running total built step by step: gross income, minus tax, minus spending, equals surplus.
 * Steps with `total` draw from zero to the running total.
 */
export function Waterfall({
  steps,
  format = "usd",
  height = 280,
  label,
}: {
  steps: { label: string; value: number; color?: SeriesColor; total?: boolean }[];
  format?: ValueFormat;
  height?: number;
  label: string;
}) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState<number | null>(null);
  const probe = scaleBand<number>()
    .domain(steps.map((_, i) => i))
    .range([0, width - MARGIN.left - MARGIN.right])
    .paddingOuter(0.1);
  const { angled, extra } = categoryLayout(
    steps.map((step) => step.label),
    probe.step(),
  );
  const chartHeight = height + extra;
  const margin = { ...MARGIN, bottom: 34 };
  const inner = { w: width - margin.left - margin.right, h: height - margin.top - margin.bottom };
  let running = 0;
  const bars = steps.map((step) => {
    if (step.total) return { ...step, from: 0, to: running };
    const from = running;
    running += step.value;
    return { ...step, from, to: running };
  });
  const y = scaleLinear()
    .domain(niceDomain(bars.flatMap((b) => [b.from, b.to])))
    .range([inner.h, 0]);
  const x = scaleBand<number>()
    .domain(steps.map((_, i) => i))
    .range([0, inner.w])
    .paddingInner(0.3)
    .paddingOuter(0.1);
  const w = Math.min(40, x.bandwidth());
  return (
    <div className="help-chart" ref={ref}>
      <div className="help-chart-stage">
        <svg
          width={width}
          height={chartHeight}
          viewBox={`0 0 ${width} ${chartHeight}`}
          role="img"
          aria-label={label}
          tabIndex={0}
          onBlur={() => setActive(null)}
          onPointerLeave={() => setActive(null)}
          onKeyDown={(event) => {
            if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
              event.preventDefault();
              setActive((current) =>
                Math.min(
                  bars.length - 1,
                  Math.max(0, (current ?? -1) + (event.key === "ArrowRight" ? 1 : -1)),
                ),
              );
            }
          }}
        >
          <g transform={`translate(${margin.left},${margin.top})`}>
            {y.ticks(5).map((t) => (
              <g key={t} className={`help-chart-grid${t === 0 ? " is-zero" : ""}`}>
                <line x1={0} x2={inner.w} y1={y(t)} y2={y(t)} />
                <text x={-10} y={y(t)} dy="0.32em" textAnchor="end">
                  {formatTick(t, format)}
                </text>
              </g>
            ))}
            {bars.map((bar, i) => {
              const bx = (x(i) ?? 0) + (x.bandwidth() - w) / 2;
              const top = y(Math.max(bar.from, bar.to)),
                bottom = y(Math.min(bar.from, bar.to));
              const color = bar.color ?? (bar.total ? "gray" : bar.value >= 0 ? "blue" : "orange");
              const next = bars[i + 1];
              return (
                <g
                  key={bar.label}
                  className={active != null && active !== i ? "is-dim" : undefined}
                  onPointerEnter={() => setActive(i)}
                >
                  <rect
                    className="help-chart-hit"
                    x={x(i) ?? 0}
                    y={0}
                    width={x.bandwidth()}
                    height={inner.h}
                  />
                  <rect
                    className={`help-bar is-${color}`}
                    x={bx}
                    y={top}
                    width={w}
                    height={Math.max(1, bottom - top)}
                    rx={3}
                  />
                  {next && !next.total && (
                    <line
                      className="help-chart-connector"
                      x1={bx + w}
                      x2={(x(i + 1) ?? 0) + (x.bandwidth() - w) / 2}
                      y1={y(bar.to)}
                      y2={y(bar.to)}
                    />
                  )}
                  <CategoryLabel
                    x={(x(i) ?? 0) + x.bandwidth() / 2}
                    y={inner.h + 22}
                    text={bar.label}
                    angled={angled}
                  />
                </g>
              );
            })}
          </g>
        </svg>
        {active != null && (
          <Tooltip
            x={margin.left + (x(active) ?? 0) + x.bandwidth() / 2}
            y={margin.top}
            width={width}
          >
            <p className="help-chart-tooltip-title">{bars[active].label}</p>
            <p>
              {bars[active].total ? "Total" : "Change"}
              <b>
                {formatValue(bars[active].total ? bars[active].to : bars[active].value, format)}
              </b>
            </p>
          </Tooltip>
        )}
      </div>
    </div>
  );
}
