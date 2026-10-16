import { useCallback, useMemo, useState } from "react";
import { yearBisector } from "@/utils/year_bisector";
import { scaleLinear } from "d3-scale";
import { area, curveLinear, curveMonotoneX, line } from "d3-shape";

import {
  ChartHeader,
  ChartLegend,
  ChartTable,
  TooltipDivider,
  TooltipRow,
  VizTooltip,
  placeTooltip,
} from "@/components/chart_chrome";
import type { YearSnapshot } from "@/types/plan";
import { compactCurrency, fullCurrency, pct } from "@/utils/format";
import { useChartSize } from "@/utils/use_chart_size";
import { useScrubScrollLock } from "@/utils/use_scrub_scroll_lock";

// ---------------------------------------------------------------------------
// Two aligned panels on one x-axis (dollars above, rates below) instead of a
// dual-axis chart, so the two scales never imply a false relationship.
// ---------------------------------------------------------------------------

const PANEL_DOLLARS_HEIGHT = 200;
const PANEL_RATE_HEIGHT = 120;
const PANEL_GAP = 44;
const MARGIN_DESKTOP = { top: 30, right: 64, bottom: 34, left: 60 };
const MARGIN_MOBILE = { top: 28, right: 52, bottom: 30, left: 48 };
const CHART_HEIGHT_BASE = PANEL_DOLLARS_HEIGHT + PANEL_GAP + PANEL_RATE_HEIGHT;

const COLOR_INCOME = "var(--viz-1)";
const COLOR_TAX = "var(--viz-2)";
const COLOR_MARGINAL = "var(--viz-context)";

const annualGross = (snapshot: YearSnapshot) =>
  snapshot.calendar_year_gross_income ?? snapshot.gross_income;

/** Push two end-labels apart when they would overlap. */
function separateLabels(a: number, b: number, minGap = 14): [number, number] {
  if (Math.abs(a - b) >= minGap) return [a, b];
  const mid = (a + b) / 2;
  return a <= b ? [mid - minGap / 2, mid + minGap / 2] : [mid + minGap / 2, mid - minGap / 2];
}

interface TaxOverviewChartProps {
  snapshots: YearSnapshot[];
  /** Year pinned on the dashboard; drawn as a quiet marker when not hovering. */
  selectedYear?: number | null;
}

export default function TaxOverviewChart({
  snapshots,
  selectedYear = null,
}: TaxOverviewChartProps) {
  const { ref: chartRef, width: resolvedWidth, isCompact, isTiny } = useChartSize(960, 400);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const MARGIN = isCompact ? MARGIN_MOBILE : MARGIN_DESKTOP;
  const chartHeight = CHART_HEIGHT_BASE + MARGIN.top + MARGIN.bottom;
  const innerWidth = Math.max(resolvedWidth - MARGIN.left - MARGIN.right, 0);
  const rateOffset = PANEL_DOLLARS_HEIGHT + PANEL_GAP;

  const xScale = useMemo(() => {
    if (snapshots.length === 0) return scaleLinear().domain([0, 1]).range([0, innerWidth]);
    return scaleLinear()
      .domain([snapshots[0].year, snapshots[snapshots.length - 1].year])
      .range([0, innerWidth]);
  }, [snapshots, innerWidth]);

  const yDollars = useMemo(() => {
    const maxValue = Math.max(...snapshots.map((s) => Math.max(annualGross(s), s.taxes)), 0);
    return scaleLinear()
      .domain([0, maxValue * 1.06 || 1000])
      .range([PANEL_DOLLARS_HEIGHT, 0])
      .nice();
  }, [snapshots]);

  const yRate = useMemo(() => {
    const maxRate = Math.max(
      ...snapshots.map((s) => Math.max(s.effective_rate, s.marginal_rate)),
      0.1,
    );
    const cap = Math.min(Math.ceil(maxRate * 10) / 10 + 0.05, 1);
    return scaleLinear().domain([0, cap]).range([PANEL_RATE_HEIGHT, 0]).nice();
  }, [snapshots]);

  const incomeLine = useMemo(
    () =>
      line<YearSnapshot>()
        .x((d) => xScale(d.year))
        .y((d) => yDollars(annualGross(d)))
        .curve(curveMonotoneX)(snapshots) ?? "",
    [snapshots, xScale, yDollars],
  );
  const incomeArea = useMemo(
    () =>
      area<YearSnapshot>()
        .x((d) => xScale(d.year))
        .y0(PANEL_DOLLARS_HEIGHT)
        .y1((d) => yDollars(annualGross(d)))
        .curve(curveMonotoneX)(snapshots) ?? "",
    [snapshots, xScale, yDollars],
  );
  const taxLine = useMemo(
    () =>
      line<YearSnapshot>()
        .x((d) => xScale(d.year))
        .y((d) => yDollars(d.taxes))
        .curve(curveMonotoneX)(snapshots) ?? "",
    [snapshots, xScale, yDollars],
  );
  const taxArea = useMemo(
    () =>
      area<YearSnapshot>()
        .x((d) => xScale(d.year))
        .y0(PANEL_DOLLARS_HEIGHT)
        .y1((d) => yDollars(d.taxes))
        .curve(curveMonotoneX)(snapshots) ?? "",
    [snapshots, xScale, yDollars],
  );
  const effectiveLine = useMemo(
    () =>
      line<YearSnapshot>()
        .x((d) => xScale(d.year))
        .y((d) => yRate(d.effective_rate))
        .curve(curveMonotoneX)(snapshots) ?? "",
    [snapshots, xScale, yRate],
  );
  const marginalLine = useMemo(
    () =>
      line<YearSnapshot>()
        .x((d) => xScale(d.year))
        .y((d) => yRate(d.marginal_rate))
        .curve(curveLinear)(snapshots) ?? "",
    [snapshots, xScale, yRate],
  );

  const xTicks = useMemo(
    () => xScale.ticks(Math.max(2, Math.floor(innerWidth / (isCompact ? 110 : 80)))),
    [innerWidth, isCompact, xScale],
  );
  const dollarTicks = useMemo(() => yDollars.ticks(4), [yDollars]);
  const rateTicks = useMemo(() => yRate.ticks(3), [yRate]);

  const hoverPoint = hoverIndex !== null ? (snapshots[hoverIndex] ?? null) : null;
  const endPoint = snapshots[snapshots.length - 1] ?? null;
  const hitRef = useScrubScrollLock<SVGRectElement>();
  const selectedPoint =
    hoverPoint === null && selectedYear !== null
      ? (snapshots.find((s) => s.year === selectedYear) ?? null)
      : null;

  const handleMouseMove = useCallback(
    (e: React.PointerEvent<SVGRectElement>) => {
      if (snapshots.length === 0) return;
      const rect = e.currentTarget.getBoundingClientRect();
      setHoverIndex(yearBisector(snapshots, xScale.invert(e.clientX - rect.left)));
    },
    [snapshots, xScale],
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<SVGRectElement>) => {
      if (snapshots.length === 0) return;
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        const step = event.key === "ArrowRight" ? 1 : -1;
        setHoverIndex((current) => {
          const next = (current ?? (step > 0 ? -1 : snapshots.length)) + step;
          return Math.max(0, Math.min(snapshots.length - 1, next));
        });
      } else if (event.key === "Escape") {
        setHoverIndex(null);
      }
    },
    [snapshots.length],
  );

  const clearHover = useCallback(() => setHoverIndex(null), []);

  if (snapshots.length === 0) {
    return (
      <div
        ref={chartRef}
        style={{
          height: 320,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-tertiary)",
          fontSize: 14,
        }}
      >
        No simulation data available.
      </div>
    );
  }

  const lifetimeTaxes = snapshots.reduce((sum, s) => sum + s.taxes, 0);
  const lifetimeIncome = snapshots.reduce((sum, s) => sum + annualGross(s), 0);
  const peakTaxYear = snapshots.reduce(
    (best, s) => (s.taxes > best.taxes ? s : best),
    snapshots[0],
  );

  const [incomeLabelY, taxLabelY] = separateLabels(
    yDollars(annualGross(endPoint)),
    yDollars(endPoint.taxes),
  );
  const [effectiveLabelY, marginalLabelY] = separateLabels(
    yRate(endPoint.effective_rate),
    yRate(endPoint.marginal_rate),
  );

  const panelLegendStyle = (top: number): React.CSSProperties => ({
    position: "absolute",
    left: MARGIN.left,
    top,
    fontSize: 11.5,
  });

  const tableRows = snapshots.map((s) => ({
    year: s.year,
    age: s.age,
    income: fullCurrency(annualGross(s)),
    taxes: fullCurrency(s.taxes),
    effective: pct(s.effective_rate),
    marginal: pct(s.marginal_rate),
    deduction: s.deduction_used
      ? `${s.deduction_used === "standard" ? "Standard" : "Itemized"} · ${fullCurrency(s.deduction_amount)}`
      : "—",
  }));

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <ChartHeader title="Calendar-year income & taxes">
        <div
          className="chart-header-stat"
          title="Total taxes over the plan as a share of calendar-year gross income"
        >
          <span className="chart-header-stat-value">{compactCurrency(lifetimeTaxes)}</span>
          <span className="chart-header-stat-label">
            lifetime · {lifetimeIncome > 0 ? pct(lifetimeTaxes / lifetimeIncome) : "—"} of
            calendar-year gross
          </span>
        </div>
      </ChartHeader>

      <div className="viz-plot" onWheel={clearHover}>
        <ChartLegend
          style={panelLegendStyle(MARGIN.top - 24)}
          entries={[
            { label: "Calendar-year gross income", color: COLOR_INCOME, kind: "line" },
            { label: "Total taxes", color: COLOR_TAX, kind: "line" },
          ]}
        />
        <ChartLegend
          style={panelLegendStyle(MARGIN.top + rateOffset - 24)}
          entries={[
            { label: "Effective tax rate", color: COLOR_TAX, kind: "line" },
            { label: "Marginal bracket", color: COLOR_MARGINAL, kind: "dashed" },
          ]}
        />

        <div ref={chartRef} style={{ width: "100%", height: chartHeight }}>
          <svg
            width={resolvedWidth}
            height={chartHeight}
            style={{ maxWidth: "100%", display: "block", overflow: "visible" }}
            role="img"
            aria-label={`Calendar-year income and taxes ${snapshots[0].year} to ${endPoint.year}: gross income, total taxes, effective and marginal tax rates by year`}
          >
            <defs>
              <linearGradient id="taxIncomeWash" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" style={{ stopColor: COLOR_INCOME }} stopOpacity={0.12} />
                <stop offset="100%" style={{ stopColor: COLOR_INCOME }} stopOpacity={0.02} />
              </linearGradient>
              <linearGradient id="taxTaxWash" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" style={{ stopColor: COLOR_TAX }} stopOpacity={0.16} />
                <stop offset="100%" style={{ stopColor: COLOR_TAX }} stopOpacity={0.03} />
              </linearGradient>
            </defs>

            <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
              {/* ---- Panel A: dollars ---- */}
              <g>
                {dollarTicks.map((tick) => (
                  <g key={`d-${tick}`}>
                    <line
                      x1={0}
                      x2={innerWidth}
                      y1={yDollars(tick)}
                      y2={yDollars(tick)}
                      style={{ stroke: tick === 0 ? "var(--viz-axis)" : "var(--viz-grid)" }}
                      shapeRendering="crispEdges"
                    />
                    <text
                      x={-12}
                      y={yDollars(tick)}
                      dy="0.32em"
                      textAnchor="end"
                      fontSize={11}
                      style={{ fill: "var(--text-tertiary)" }}
                    >
                      {compactCurrency(tick)}
                    </text>
                  </g>
                ))}
                <path d={incomeArea} fill="url(#taxIncomeWash)" />
                <path d={taxArea} fill="url(#taxTaxWash)" />
                <path
                  d={incomeLine}
                  fill="none"
                  style={{ stroke: COLOR_INCOME }}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
                <path
                  d={taxLine}
                  fill="none"
                  style={{ stroke: COLOR_TAX }}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />

                {/* End labels */}
                <text
                  x={innerWidth + 8}
                  y={incomeLabelY}
                  dy="0.32em"
                  fontSize={11}
                  fontWeight={600}
                  style={{ fill: "var(--text-primary)" }}
                >
                  {compactCurrency(annualGross(endPoint))}
                </text>
                <text
                  x={innerWidth + 8}
                  y={taxLabelY}
                  dy="0.32em"
                  fontSize={11}
                  fontWeight={600}
                  style={{ fill: "var(--text-primary)" }}
                >
                  {compactCurrency(endPoint.taxes)}
                </text>

                {hoverPoint && (
                  <>
                    <circle
                      cx={xScale(hoverPoint.year)}
                      cy={yDollars(annualGross(hoverPoint))}
                      r={4.5}
                      style={{ fill: COLOR_INCOME, stroke: "var(--surface-card)" }}
                      strokeWidth={2}
                    />
                    <circle
                      cx={xScale(hoverPoint.year)}
                      cy={yDollars(hoverPoint.taxes)}
                      r={4.5}
                      style={{ fill: COLOR_TAX, stroke: "var(--surface-card)" }}
                      strokeWidth={2}
                    />
                  </>
                )}
              </g>

              {/* ---- Panel B: rates ---- */}
              <g transform={`translate(0,${rateOffset})`}>
                {rateTicks.map((tick) => (
                  <g key={`r-${tick}`}>
                    <line
                      x1={0}
                      x2={innerWidth}
                      y1={yRate(tick)}
                      y2={yRate(tick)}
                      style={{ stroke: tick === 0 ? "var(--viz-axis)" : "var(--viz-grid)" }}
                      shapeRendering="crispEdges"
                    />
                    <text
                      x={-12}
                      y={yRate(tick)}
                      dy="0.32em"
                      textAnchor="end"
                      fontSize={11}
                      style={{ fill: "var(--text-tertiary)" }}
                    >
                      {(tick * 100).toFixed(0)}%
                    </text>
                  </g>
                ))}
                <path
                  d={marginalLine}
                  fill="none"
                  style={{ stroke: COLOR_MARGINAL }}
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
                <path
                  d={effectiveLine}
                  fill="none"
                  style={{ stroke: COLOR_TAX }}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />

                <text
                  x={innerWidth + 8}
                  y={effectiveLabelY}
                  dy="0.32em"
                  fontSize={11}
                  fontWeight={600}
                  style={{ fill: "var(--text-primary)" }}
                >
                  {pct(endPoint.effective_rate, 0)}
                </text>
                <text
                  x={innerWidth + 8}
                  y={marginalLabelY}
                  dy="0.32em"
                  fontSize={11}
                  style={{ fill: "var(--text-secondary)" }}
                >
                  {pct(endPoint.marginal_rate, 0)}
                </text>

                {xTicks.map((tick) => (
                  <text
                    key={`x-${tick}`}
                    x={xScale(tick)}
                    y={PANEL_RATE_HEIGHT + 20}
                    textAnchor="middle"
                    fontSize={11}
                    style={{ fill: "var(--text-tertiary)" }}
                  >
                    {tick}
                  </text>
                ))}

                {hoverPoint && (
                  <>
                    <circle
                      cx={xScale(hoverPoint.year)}
                      cy={yRate(hoverPoint.effective_rate)}
                      r={4.5}
                      style={{ fill: COLOR_TAX, stroke: "var(--surface-card)" }}
                      strokeWidth={2}
                    />
                    <circle
                      cx={xScale(hoverPoint.year)}
                      cy={yRate(hoverPoint.marginal_rate)}
                      r={4}
                      style={{ fill: COLOR_MARGINAL, stroke: "var(--surface-card)" }}
                      strokeWidth={2}
                    />
                  </>
                )}
              </g>

              {/* Pinned dashboard year, shown until the pointer takes over */}
              {selectedPoint && (
                <g pointerEvents="none">
                  <line
                    x1={xScale(selectedPoint.year)}
                    x2={xScale(selectedPoint.year)}
                    y1={0}
                    y2={rateOffset + PANEL_RATE_HEIGHT}
                    style={{ stroke: "var(--viz-annotation)" }}
                    strokeWidth={1}
                    strokeDasharray="2 3"
                  />
                  <circle
                    cx={xScale(selectedPoint.year)}
                    cy={yDollars(annualGross(selectedPoint))}
                    r={3.5}
                    style={{ fill: COLOR_INCOME, stroke: "var(--surface-card)" }}
                    strokeWidth={1.5}
                  />
                  <circle
                    cx={xScale(selectedPoint.year)}
                    cy={yDollars(selectedPoint.taxes)}
                    r={3.5}
                    style={{ fill: COLOR_TAX, stroke: "var(--surface-card)" }}
                    strokeWidth={1.5}
                  />
                  <circle
                    cx={xScale(selectedPoint.year)}
                    cy={rateOffset + yRate(selectedPoint.effective_rate)}
                    r={3.5}
                    style={{ fill: COLOR_TAX, stroke: "var(--surface-card)" }}
                    strokeWidth={1.5}
                  />
                </g>
              )}

              {/* Shared crosshair spanning both panels */}
              {hoverPoint && (
                <line
                  x1={xScale(hoverPoint.year)}
                  x2={xScale(hoverPoint.year)}
                  y1={0}
                  y2={rateOffset + PANEL_RATE_HEIGHT}
                  style={{ stroke: "var(--viz-axis)" }}
                  strokeWidth={1}
                  pointerEvents="none"
                />
              )}

              <rect
                width={innerWidth}
                height={rateOffset + PANEL_RATE_HEIGHT}
                fill="transparent"
                ref={hitRef}
                data-hover-target
                tabIndex={0}
                aria-label="Explore income and taxes by year with arrow keys"
                style={{ touchAction: "pan-y", cursor: "crosshair" }}
                onPointerMove={handleMouseMove}
                onPointerLeave={clearHover}
                onPointerCancel={clearHover}
                onKeyDown={handleKeyDown}
                onBlur={clearHover}
              />
            </g>
          </svg>
        </div>

        {hoverPoint &&
          (() => {
            const tooltipWidth = isTiny ? Math.max(200, resolvedWidth - 24) : 240;
            const placement = placeTooltip({
              anchorX: xScale(hoverPoint.year) + MARGIN.left,
              anchorY: yDollars(annualGross(hoverPoint)) + MARGIN.top,
              width: tooltipWidth,
              height: 200,
              containerWidth: resolvedWidth,
              containerHeight: chartHeight,
            });
            return (
              <VizTooltip
                placement={placement}
                width={tooltipWidth}
                title={String(hoverPoint.year)}
                meta={`age ${hoverPoint.age}`}
              >
                <TooltipRow
                  label="Calendar-year gross income"
                  value={fullCurrency(annualGross(hoverPoint))}
                  color={COLOR_INCOME}
                />
                <TooltipRow
                  label="Full-year taxes"
                  value={fullCurrency(hoverPoint.taxes)}
                  color={COLOR_TAX}
                />
                <TooltipRow
                  label="Tax payable / (refund)"
                  value={fullCurrency(hoverPoint.tax_balance ?? 0)}
                  muted
                />
                <TooltipRow
                  label="Unfunded bills"
                  value={fullCurrency(hoverPoint.unfunded_expenses ?? 0)}
                  muted
                />
                <TooltipRow
                  label="Capital loss carryforward"
                  value={fullCurrency(hoverPoint.capital_loss_carryforward ?? 0)}
                  muted
                />
                <TooltipRow
                  label="After tax"
                  value={fullCurrency(annualGross(hoverPoint) - hoverPoint.taxes)}
                  muted
                />
                <TooltipDivider />
                <TooltipRow
                  label="Effective rate"
                  value={pct(hoverPoint.effective_rate)}
                  color={COLOR_TAX}
                />
                <TooltipRow
                  label="Marginal bracket"
                  value={pct(hoverPoint.marginal_rate)}
                  color={COLOR_MARGINAL}
                  muted
                />
                {!isTiny && hoverPoint.deduction_used && (
                  <>
                    <TooltipDivider />
                    <TooltipRow
                      label={`${hoverPoint.deduction_used === "standard" ? "Standard" : "Itemized"} deduction`}
                      value={fullCurrency(hoverPoint.deduction_amount)}
                      muted
                    />
                  </>
                )}
              </VizTooltip>
            );
          })()}
      </div>

      <ChartTable
        caption="Income and taxes by year"
        note={`Peak tax year ${peakTaxYear.year} · ${compactCurrency(peakTaxYear.taxes)}`}
        columns={[
          { key: "year", label: "Year" },
          { key: "age", label: "Age" },
          { key: "income", label: "Calendar-year gross", numeric: true },
          { key: "taxes", label: "Full-year taxes", numeric: true },
          { key: "effective", label: "Effective", numeric: true },
          { key: "marginal", label: "Marginal", numeric: true },
          { key: "deduction", label: "Deduction" },
        ]}
        rows={tableRows}
      />
    </div>
  );
}
