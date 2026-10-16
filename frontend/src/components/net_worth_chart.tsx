import React, { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { yearBisector } from "@/utils/year_bisector";
import { scaleLinear } from "d3-scale";
import { area, curveMonotoneX, line } from "d3-shape";

import CompareOverlay from "@/components/compare_overlay";
import {
  ChartHeader,
  ChartLegend,
  ChartTable,
  SegmentedControl,
  TooltipDivider,
  TooltipRow,
  VizTooltip,
  placeTooltip,
  type LegendEntry,
} from "@/components/chart_chrome";
import { usePlanStore } from "@/stores/plan_store";
import { useStorage } from "@/storage/context";
import { useFiEstimateHidden } from "@/stores/fi_estimate_store";
import { resolveFinancialIndependence } from "@/utils/financial_independence";
import type { ProgressPoint, YearDelta } from "@/types/plan";
import { adjustTimeline, type CurrencyMode } from "@/utils/currency";
import { calendarDate, compactCurrency, dollarsOr, fullCurrency, pct } from "@/utils/format";
import { timelineEvents, type TimelineEvent } from "@/utils/timeline_events";
import { useAdjustedTimeline } from "@/utils/use_adjusted_timeline";
import { useChartSize } from "@/utils/use_chart_size";
import { usePlanAccounts } from "@/utils/use_plan_accounts";
import { useScrubScrollLock } from "@/utils/use_scrub_scroll_lock";
import { accountTypeLabel } from "@/domain/account_types";

const CHART_HEIGHT = 380;
const MARGIN_DESKTOP = { top: 26, right: 72, bottom: 36, left: 58 };
const MARGIN_MOBILE = { top: 24, right: 52, bottom: 32, left: 46 };

const SERIES_COLOR = "var(--brand-primary)";
const RECORDED_COLOR = "var(--viz-2)";
const BASELINE_COLOR = "var(--viz-context)";

interface NetWorthChartProps {
  /** Pinned year. When `onSelectYear` is given the chart is controlled: the
   *  crosshair follows the selected (or hovered) year and no tooltip renders,
   *  because a ledger beside the chart shows that year instead. */
  selectedYear?: number | null;
  onSelectYear?: (year: number) => void;
  hoverYear?: number | null;
  onHoverYear?: (year: number | null) => void;
  /** Events to mark on the curve; computed from the plan when omitted. */
  events?: TimelineEvent[];
  /** Extra header controls, rendered before the currency toggle. */
  toolbar?: ReactNode;
}

export default function NetWorthChart({
  selectedYear = null,
  onSelectYear,
  hoverYear = null,
  onHoverYear,
  events: eventsProp,
  toolbar,
}: NetWorthChartProps = {}) {
  const { simulation, plan, currencyMode, deflators, data } = useAdjustedTimeline();
  const { adapter } = useStorage();
  const setCurrencyMode = usePlanStore((s) => s.setCurrencyMode);
  const baselineSimulation = usePlanStore((s) => s.baselineSimulation);
  const compareMode = usePlanStore((s) => s.compareMode);
  const fiEstimateHidden = useFiEstimateHidden(plan?.id);
  const controlled = typeof onSelectYear === "function";

  const {
    ref: chartRef,
    width: resolvedChartWidth,
    isCompact: isCompactChart,
    isTiny: isTinyChart,
  } = useChartSize(960, CHART_HEIGHT);
  const chartHeight = isTinyChart ? 220 : isCompactChart ? 300 : CHART_HEIGHT;
  const [internalHoverIndex, setInternalHoverIndex] = useState<number | null>(null);
  const [progressPoints, setProgressPoints] = useState<ProgressPoint[]>([]);
  const [hoveredPoint, setHoveredPoint] = useState<ProgressPoint | null>(null);
  const { accounts } = usePlanAccounts(adapter, plan?.id);

  useEffect(() => {
    adapter
      .listProgressPoints()
      .then(setProgressPoints)
      .catch(() => {});
  }, [adapter]);

  const accountTypeById = useMemo(() => {
    const map = new Map<string, string>();
    for (const acct of accounts) map.set(acct.id, acct.account_type);
    return map;
  }, [accounts]);

  const events = useMemo(
    () => eventsProp ?? timelineEvents(plan, simulation, { fiEstimateHidden }),
    [eventsProp, plan, simulation, fiEstimateHidden],
  );

  const baselineData = useMemo(() => {
    if (!compareMode || !baselineSimulation) return [];
    const currentYears = new Map(
      (simulation?.yearly_snapshots ?? []).map((point, index) => [
        point.year,
        deflators[index] ?? 1,
      ]),
    );
    const shared = baselineSimulation.yearly_snapshots.filter((point) =>
      currentYears.has(point.year),
    );
    return adjustTimeline(
      shared,
      shared.map((point) => currentYears.get(point.year)!),
      currencyMode,
    );
  }, [baselineSimulation, compareMode, simulation, deflators, currencyMode]);

  const delta: YearDelta[] = useMemo(() => {
    if (!compareMode || baselineData.length === 0) return [];
    const baselineMap = new Map(baselineData.map((point) => [point.year, point.net_worth]));
    return data
      .filter((point) => baselineMap.has(point.year))
      .map((point) => ({
        year: point.year,
        currentNetWorth: point.net_worth,
        baselineNetWorth: baselineMap.get(point.year)!,
        delta: point.net_worth - baselineMap.get(point.year)!,
      }));
  }, [baselineData, compareMode, data]);

  // Actual balances on the projection start date, plotted as the curve's origin.
  // Integer x = December 31 of that year, so today sits a fraction before the first year-end.
  const origin = useMemo(() => {
    const initial = simulation?.initial_snapshot;
    if (!initial || data.length === 0) return null;
    const fraction = simulation?.metadata.first_year_fraction ?? 1;
    return {
      x: data[0].year - Math.min(Math.max(fraction, 0), 1),
      net_worth: initial.net_worth,
      as_of: initial.as_of,
    };
  }, [simulation, data]);

  const MARGIN = isCompactChart ? MARGIN_MOBILE : MARGIN_DESKTOP;
  const innerWidth = Math.max(resolvedChartWidth - MARGIN.left - MARGIN.right, 0);
  const innerHeight = Math.max(chartHeight - MARGIN.top - MARGIN.bottom, 0);

  const xScale = useMemo(() => {
    if (data.length === 0) return scaleLinear().domain([0, 1]).range([0, innerWidth]);
    return scaleLinear()
      .domain([origin?.x ?? data[0].year, data[data.length - 1].year])
      .range([0, innerWidth]);
  }, [data, innerWidth, origin]);

  const yScale = useMemo(() => {
    if (data.length === 0) return scaleLinear().domain([0, 1]).range([innerHeight, 0]);
    const allValues = [...data.map((p) => p.net_worth), ...baselineData.map((p) => p.net_worth)];
    if (origin) allValues.push(origin.net_worth);
    const min = Math.min(...allValues, 0);
    const max = Math.max(...allValues, 0);
    const padding = (max - min) * 0.08 || 1000;
    return scaleLinear()
      .domain([min < 0 ? min - padding : 0, max + padding])
      .range([innerHeight, 0])
      .nice();
  }, [baselineData, data, innerHeight, origin]);

  type CurvePoint = { x: number; y: number };
  const curvePoints: CurvePoint[] = useMemo(() => {
    const points = data.map((point) => ({ x: point.year, y: point.net_worth }));
    return origin ? [{ x: origin.x, y: origin.net_worth }, ...points] : points;
  }, [data, origin]);

  const pathD = useMemo(() => {
    const generator = line<CurvePoint>()
      .x((point) => xScale(point.x))
      .y((point) => yScale(point.y))
      .curve(curveMonotoneX);
    return generator(curvePoints) ?? "";
  }, [curvePoints, xScale, yScale]);

  const areaD = useMemo(() => {
    const baseline = yScale(Math.max(yScale.domain()[0], 0));
    const generator = area<CurvePoint>()
      .x((point) => xScale(point.x))
      .y0(baseline)
      .y1((point) => yScale(point.y))
      .curve(curveMonotoneX);
    return generator(curvePoints) ?? "";
  }, [curvePoints, xScale, yScale]);

  const [domainStart, domainEnd] = xScale.domain();
  const xTicks = useMemo(() => {
    const tickSpacing = isCompactChart ? 110 : 80;
    return xScale.ticks(Math.max(2, Math.floor(innerWidth / tickSpacing))).filter(Number.isInteger);
  }, [innerWidth, isCompactChart, xScale]);

  const yTicks = useMemo(
    () => yScale.ticks(Math.max(2, Math.floor(innerHeight / 60))),
    [innerHeight, yScale],
  );

  // One marker per year; several events in one year share a marker.
  const markers = useMemo(() => {
    const byYear = new Map<number, TimelineEvent[]>();
    for (const event of events) {
      const point = data.find((p) => p.year === event.year);
      if (!point) continue;
      byYear.set(event.year, [...(byYear.get(event.year) ?? []), event]);
    }
    return Array.from(byYear.entries()).map(([year, list]) => ({
      year,
      net_worth: data.find((p) => p.year === year)!.net_worth,
      events: list,
      critical: list.some((e) => e.kind === "shortfall"),
    }));
  }, [events, data]);

  const yearIndex = useMemo(() => new Map(data.map((point, index) => [point.year, index])), [data]);
  const activeYear = controlled ? (hoverYear ?? selectedYear) : null;
  const hoverIndex = controlled
    ? activeYear !== null
      ? (yearIndex.get(activeYear) ?? null)
      : null
    : internalHoverIndex;
  const hoverPoint = hoverIndex !== null ? (data[hoverIndex] ?? null) : null;
  const endPoint = data.length > 0 ? data[data.length - 1] : null;
  const hitRef = useScrubScrollLock<SVGRectElement>();

  const indexAt = useCallback(
    (event: React.PointerEvent<SVGRectElement> | React.MouseEvent<SVGRectElement>) => {
      const rect = event.currentTarget.getBoundingClientRect();
      return yearBisector(data, xScale.invert(event.clientX - rect.left));
    },
    [data, xScale],
  );

  const handleMouseMove = useCallback(
    (event: React.PointerEvent<SVGRectElement>) => {
      if (data.length === 0) return;
      const index = indexAt(event);
      if (controlled) onHoverYear?.(data[index].year);
      else setInternalHoverIndex(index);
    },
    [controlled, data, indexAt, onHoverYear],
  );

  const handleClick = useCallback(
    (event: React.MouseEvent<SVGRectElement>) => {
      if (!controlled || data.length === 0) return;
      onSelectYear?.(data[indexAt(event)].year);
    },
    [controlled, data, indexAt, onSelectYear],
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<SVGRectElement>) => {
      if (data.length === 0) return;
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        event.preventDefault();
        const step = event.key === "ArrowRight" ? 1 : -1;
        if (controlled) {
          const current = selectedYear !== null ? (yearIndex.get(selectedYear) ?? null) : null;
          const next = Math.max(
            0,
            Math.min(data.length - 1, (current ?? (step > 0 ? -1 : data.length)) + step),
          );
          onSelectYear?.(data[next].year);
        } else {
          setInternalHoverIndex((current) => {
            const next = (current ?? (step > 0 ? -1 : data.length)) + step;
            return Math.max(0, Math.min(data.length - 1, next));
          });
        }
      } else if (event.key === "Escape") {
        if (controlled) onHoverYear?.(null);
        else setInternalHoverIndex(null);
      }
    },
    [controlled, data, onHoverYear, onSelectYear, selectedYear, yearIndex],
  );

  const clearHover = useCallback(() => {
    if (controlled) onHoverYear?.(null);
    else setInternalHoverIndex(null);
    setHoveredPoint(null);
  }, [controlled, onHoverYear]);

  const visibleProgressPoints = useMemo(
    () =>
      progressPoints.filter((point) => {
        const year = new Date(point.recorded_date).getFullYear();
        return year >= domainStart && year <= domainEnd;
      }),
    [progressPoints, domainStart, domainEnd],
  );

  if (!simulation || data.length === 0) {
    return (
      <div
        style={{
          minHeight: 420,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 10,
          color: "var(--text-tertiary)",
          fontSize: 14,
        }}
      >
        <svg
          width="42"
          height="42"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--gray-300)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M3 3v18h18" />
          <path d="m19 9-5 5-4-4-3 3" />
        </svg>
        No projection yet.
      </div>
    );
  }

  const startPoint = data[0];
  const legendEntries: LegendEntry[] = [];
  if (compareMode && baselineData.length > 0) {
    legendEntries.push({ label: "This plan", color: SERIES_COLOR, kind: "line" });
    legendEntries.push({
      label:
        delta.length > 0 && delta.every((d) => Math.abs(d.delta) < 0.005)
          ? "Baseline (identical)"
          : "Baseline",
      color: BASELINE_COLOR,
      kind: "dashed",
    });
  }
  if (visibleProgressPoints.length > 0) {
    if (legendEntries.length === 0)
      legendEntries.push({ label: "Projected", color: SERIES_COLOR, kind: "line" });
    legendEntries.push({ label: "Recorded", color: RECORDED_COLOR, kind: "dot" });
  }

  const meta = currencyMode === "inflation_adjusted" ? `${startPoint.year} dollars` : undefined;

  const tableRows = data.map((point) => {
    // Income is the simulated period's; only a partial first year has a
    // different calendar-year figure, shown under it in that row alone.
    const calendar = point.calendar_year_gross_income;
    const partialYear = calendar != null && Math.abs(calendar - point.gross_income) >= 0.5;
    return {
      year: `Dec 31, ${point.year}`,
      age: point.age,
      net_worth: fullCurrency(point.net_worth),
      income: partialYear ? (
        <>
          {fullCurrency(point.gross_income)}
          <span style={{ display: "block", fontSize: 11, color: "var(--text-secondary)" }}>
            {fullCurrency(calendar)} calendar year
          </span>
        </>
      ) : (
        fullCurrency(point.gross_income)
      ),
      expenses: fullCurrency(point.expenses),
      taxes: fullCurrency(point.taxes),
      cash_flow: fullCurrency(point.net_cash_flow),
    };
  });

  const fi = resolveFinancialIndependence(plan, simulation, fiEstimateHidden);
  const endLabelClashesWithMarker = markers.some((m) => m.year === endPoint!.year);
  // Keep the terminal value inside the SVG on narrow screens: flip it to the
  // left of the marker when it would run past the right edge.
  const endLabel = endPoint ? compactCurrency(endPoint.net_worth) : "";
  const endLabelFlipped =
    endPoint !== null &&
    xScale(endPoint.year) + 10 + endLabel.length * 7.5 > innerWidth + MARGIN.right - 4;
  const originLabelAbove = origin ? yScale(origin.net_worth) > 24 : false;

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <ChartHeader title="Net worth" subtitle={meta}>
        <div className="chart-header-tools">
          {toolbar}
          <SegmentedControl<CurrencyMode>
            ariaLabel="Currency mode"
            value={currencyMode}
            onChange={setCurrencyMode}
            options={[
              { value: "nominal", label: dollarsOr("Future dollars", "Future (nominal)") },
              { value: "inflation_adjusted", label: dollarsOr("Today's $", "Today's money") },
            ]}
          />
        </div>
      </ChartHeader>

      {legendEntries.length >= 2 && <ChartLegend entries={legendEntries} />}

      <div className="viz-plot" onWheel={clearHover}>
        <div ref={chartRef} style={{ width: "100%", height: chartHeight }}>
          <svg
            width={resolvedChartWidth}
            height={chartHeight}
            style={{ maxWidth: "100%", display: "block", overflow: "visible" }}
            role="img"
            aria-label={`Net worth projection ${startPoint.year} to ${endPoint!.year}: ${compactCurrency(origin?.net_worth ?? startPoint.net_worth)} growing to ${compactCurrency(endPoint!.net_worth)}${fi?.year != null ? `, financial independence reached in ${fi.year}` : ""}`}
          >
            <defs>
              <linearGradient id="netWorthAreaGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" style={{ stopColor: SERIES_COLOR }} stopOpacity={0.16} />
                <stop offset="100%" style={{ stopColor: SERIES_COLOR }} stopOpacity={0.01} />
              </linearGradient>
            </defs>

            <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
              {yTicks.map((tick) => (
                <line
                  key={`grid-${tick}`}
                  x1={0}
                  x2={innerWidth}
                  y1={yScale(tick)}
                  y2={yScale(tick)}
                  style={{ stroke: tick === 0 ? "var(--viz-axis)" : "var(--viz-grid)" }}
                  strokeWidth={1}
                  shapeRendering="crispEdges"
                />
              ))}

              <path d={areaD} fill="url(#netWorthAreaGradient)" />

              {compareMode && delta.length > 0 && (
                <CompareOverlay
                  baselineTimeline={baselineData}
                  delta={delta}
                  innerWidth={innerWidth}
                  innerHeight={innerHeight}
                  xScale={xScale}
                  yScale={yScale}
                  hoverYear={hoverPoint?.year ?? null}
                />
              )}

              {/* Crosshair sits under the series so the line stays legible. */}
              {hoverPoint && (
                <line
                  x1={xScale(hoverPoint.year)}
                  x2={xScale(hoverPoint.year)}
                  y1={0}
                  y2={innerHeight}
                  style={{
                    stroke:
                      controlled && hoverYear === null
                        ? "var(--text-secondary)"
                        : "var(--viz-axis)",
                  }}
                  strokeWidth={1}
                  shapeRendering="crispEdges"
                />
              )}

              <path
                d={pathD}
                fill="none"
                style={{ stroke: SERIES_COLOR }}
                strokeWidth={2.25}
                strokeLinejoin="round"
                strokeLinecap="round"
              />

              {/* Where the plan starts: actual balances on the start date. */}
              {origin && (
                <g>
                  <circle
                    cx={xScale(origin.x)}
                    cy={yScale(origin.net_worth)}
                    r={3.5}
                    style={{ fill: "var(--surface-card)", stroke: SERIES_COLOR }}
                    strokeWidth={2}
                  />
                  <text
                    x={xScale(origin.x) + 8}
                    y={yScale(origin.net_worth) + (originLabelAbove ? -10 : 14)}
                    textAnchor="start"
                    fontSize={11}
                    fontWeight={600}
                    style={{ fill: "var(--text-secondary)" }}
                  >
                    {compactCurrency(origin.net_worth)}
                  </text>
                </g>
              )}

              {/* Event markers */}
              {markers.map((marker) => {
                const active = hoverPoint?.year === marker.year;
                return (
                  <g key={marker.year} className="nw-marker">
                    <title>
                      {marker.events.map((e) => `${e.label} · ${marker.year}`).join("\n")}
                    </title>
                    <circle
                      cx={xScale(marker.year)}
                      cy={yScale(marker.net_worth)}
                      r={active ? 6 : 4.5}
                      style={{
                        fill: marker.critical ? "var(--viz-critical)" : "var(--surface-card)",
                        stroke: marker.critical ? "var(--viz-critical)" : SERIES_COLOR,
                      }}
                      strokeWidth={2}
                    />
                  </g>
                );
              })}

              {/* End marker + direct label */}
              {endPoint && (
                <g>
                  <circle
                    cx={xScale(endPoint.year)}
                    cy={yScale(endPoint.net_worth)}
                    r={4}
                    style={{ fill: SERIES_COLOR, stroke: "var(--surface-card)" }}
                    strokeWidth={2}
                  />
                  <text
                    x={xScale(endPoint.year) + (endLabelFlipped ? -10 : 10)}
                    y={
                      yScale(endPoint.net_worth) +
                      (endLabelClashesWithMarker || endLabelFlipped ? -12 : 0)
                    }
                    dy="0.32em"
                    textAnchor={endLabelFlipped ? "end" : "start"}
                    fontSize={12}
                    fontWeight={600}
                    style={{ fill: "var(--text-primary)" }}
                  >
                    {endLabel}
                  </text>
                </g>
              )}

              {/* X axis */}
              <line
                x1={0}
                x2={innerWidth}
                y1={innerHeight}
                y2={innerHeight}
                style={{ stroke: "var(--viz-axis)" }}
                strokeWidth={1}
                shapeRendering="crispEdges"
              />
              {xTicks.map((tick) => (
                <text
                  key={`x-${tick}`}
                  x={xScale(tick)}
                  y={innerHeight + 20}
                  textAnchor="middle"
                  fontSize={11}
                  style={{ fill: "var(--text-tertiary)" }}
                >
                  {tick}
                </text>
              ))}
              {/* Y axis labels */}
              {yTicks.map((tick) => (
                <text
                  key={`y-${tick}`}
                  x={-12}
                  y={yScale(tick)}
                  dy="0.32em"
                  textAnchor="end"
                  fontSize={11}
                  style={{ fill: "var(--text-tertiary)" }}
                >
                  {compactCurrency(tick)}
                </text>
              ))}

              {/* Active point */}
              {hoverPoint && (
                <circle
                  cx={xScale(hoverPoint.year)}
                  cy={yScale(hoverPoint.net_worth)}
                  r={5}
                  style={{ fill: SERIES_COLOR, stroke: "var(--surface-card)" }}
                  strokeWidth={2}
                />
              )}

              <rect
                width={innerWidth}
                height={innerHeight}
                fill="transparent"
                ref={hitRef}
                data-hover-target
                tabIndex={0}
                aria-label={
                  controlled
                    ? "Choose a year with arrow keys or by clicking the chart"
                    : "Explore net worth by year with arrow keys"
                }
                style={{ touchAction: "pan-y", cursor: controlled ? "pointer" : "crosshair" }}
                onPointerMove={handleMouseMove}
                onPointerLeave={clearHover}
                onPointerCancel={clearHover}
                onClick={handleClick}
                onKeyDown={handleKeyDown}
                onBlur={controlled ? undefined : clearHover}
              />

              {/* Recorded net worth points */}
              {visibleProgressPoints.map((point) => {
                const year = new Date(point.recorded_date).getFullYear();
                return (
                  <g key={point.id}>
                    <circle
                      cx={xScale(year)}
                      cy={yScale(point.net_worth)}
                      r={12}
                      fill="transparent"
                      style={{ cursor: "pointer" }}
                      onPointerEnter={() => setHoveredPoint(point)}
                      onPointerLeave={() => setHoveredPoint(null)}
                    />
                    <circle
                      cx={xScale(year)}
                      cy={yScale(point.net_worth)}
                      r={4}
                      pointerEvents="none"
                      style={{ fill: RECORDED_COLOR, stroke: "var(--surface-card)" }}
                      strokeWidth={2}
                    />
                  </g>
                );
              })}
            </g>
          </svg>
        </div>

        {!controlled &&
          hoverPoint &&
          !hoveredPoint &&
          (() => {
            const tooltipWidth = isTinyChart ? Math.max(200, resolvedChartWidth - 24) : 272;
            const tooltipHeight = isTinyChart ? 190 : 320;
            const placement = placeTooltip({
              anchorX: xScale(hoverPoint.year) + MARGIN.left,
              anchorY: yScale(hoverPoint.net_worth) + MARGIN.top,
              width: tooltipWidth,
              height: tooltipHeight,
              containerWidth: resolvedChartWidth,
              containerHeight: chartHeight,
            });
            const pointDelta = compareMode
              ? delta.find((d) => d.year === hoverPoint.year)
              : undefined;
            const drawdownTotal = (hoverPoint.cash_flow?.drawdowns ?? []).reduce(
              (s, d) => s + d.amount,
              0,
            );
            const totalsByType = new Map<string, number>();
            let accountTotal = 0;
            for (const [acctId, balance] of Object.entries(hoverPoint.accounts)) {
              accountTotal += balance;
              const type = accountTypeById.get(acctId) ?? "other";
              totalsByType.set(type, (totalsByType.get(type) ?? 0) + balance);
            }
            const accountRows = Array.from(totalsByType.entries())
              .filter(([, balance]) => balance !== 0)
              .sort((a, b) => b[1] - a[1]);

            return (
              <VizTooltip
                placement={placement}
                width={tooltipWidth}
                maxHeight={chartHeight - 16}
                title={`December 31, ${hoverPoint.year}`}
                meta={`Estimated · age ${hoverPoint.age}${hoverIndex === 0 && simulation.metadata.start_date ? ` · activity since ${calendarDate(simulation.metadata.start_date)}` : ""}`}
              >
                <TooltipRow
                  label="Net worth"
                  value={fullCurrency(hoverPoint.net_worth)}
                  color={SERIES_COLOR}
                  emphasis
                />
                {pointDelta && (
                  <>
                    <TooltipRow
                      label="Baseline"
                      value={fullCurrency(pointDelta.baselineNetWorth)}
                      color={BASELINE_COLOR}
                      muted
                    />
                    <TooltipRow
                      label="Difference"
                      value={`${pointDelta.delta >= 0 ? "+" : "−"}${fullCurrency(Math.abs(pointDelta.delta))}`}
                    />
                  </>
                )}
                <TooltipDivider />
                <TooltipRow label="Income" value={fullCurrency(hoverPoint.gross_income)} muted />
                <TooltipRow
                  label="Calendar-year gross"
                  value={fullCurrency(
                    hoverPoint.calendar_year_gross_income ?? hoverPoint.gross_income,
                  )}
                  muted
                />
                <TooltipRow
                  label="Full-year taxes"
                  value={
                    (hoverPoint.calendar_year_gross_income ?? hoverPoint.gross_income) > 0
                      ? `${fullCurrency(hoverPoint.taxes)} · ${pct(hoverPoint.taxes / (hoverPoint.calendar_year_gross_income ?? hoverPoint.gross_income))}`
                      : fullCurrency(hoverPoint.taxes)
                  }
                  muted
                />
                <TooltipRow label="Expenses" value={fullCurrency(hoverPoint.expenses)} muted />
                {drawdownTotal > 0 && (
                  <TooltipRow label="Withdrawals" value={fullCurrency(drawdownTotal)} muted />
                )}
                <TooltipRow
                  label="Investment growth"
                  value={fullCurrency(hoverPoint.investment_growth)}
                  muted
                />
                {!isTinyChart && accountRows.length > 0 && (
                  <>
                    <TooltipDivider />
                    <TooltipRow label="Accounts" value={fullCurrency(accountTotal)} />
                    {accountRows.map(([type, balance]) => (
                      <TooltipRow
                        key={type}
                        label={accountTypeLabel(type, "Other")}
                        value={fullCurrency(balance)}
                        sub
                      />
                    ))}
                  </>
                )}
              </VizTooltip>
            );
          })()}

        {hoveredPoint &&
          (() => {
            const year = new Date(hoveredPoint.recorded_date).getFullYear();
            const tooltipWidth = 220;
            const placement = placeTooltip({
              anchorX: xScale(year) + MARGIN.left,
              anchorY: yScale(hoveredPoint.net_worth) + MARGIN.top,
              width: tooltipWidth,
              height: 120,
              containerWidth: resolvedChartWidth,
              containerHeight: chartHeight,
            });
            const breakdown = Object.entries(hoveredPoint.assets_breakdown);
            return (
              <VizTooltip
                placement={placement}
                width={tooltipWidth}
                title="Recorded"
                meta={hoveredPoint.recorded_date}
              >
                <TooltipRow
                  label="Net worth"
                  value={fullCurrency(hoveredPoint.net_worth)}
                  color={RECORDED_COLOR}
                  emphasis
                />
                {breakdown.map(([key, value]) => (
                  <TooltipRow key={key} label={key} value={fullCurrency(value as number)} sub />
                ))}
              </VizTooltip>
            );
          })()}
      </div>

      {controlled && selectedYear !== null && (
        <input
          type="range"
          className="year-scrubber"
          data-sample-view
          min={startPoint.year}
          max={endPoint!.year}
          step={1}
          value={selectedYear}
          aria-label="Plan year"
          aria-valuetext={`${selectedYear}, age ${data.find((p) => p.year === selectedYear)?.age ?? ""}`}
          onChange={(e) => onSelectYear?.(Number(e.target.value))}
          style={{ marginLeft: MARGIN.left, width: innerWidth || undefined }}
        />
      )}

      {/* Chip timeline: the legend for the markers, in the order they happen. */}
      {events.length > 0 && (
        <ol className="event-strip" aria-label="Plan events">
          {events.map((event) => {
            const active = hoverPoint?.year === event.year;
            const content = (
              <>
                <span className={`event-dot kind-${event.kind}`} aria-hidden="true" />
                <span className="event-label">{event.label}</span>
                <span className="event-year">{event.year}</span>
              </>
            );
            return (
              <li key={event.key}>
                {controlled ? (
                  <button
                    type="button"
                    className={`event-chip${active ? " is-active" : ""}`}
                    title={event.detail}
                    aria-pressed={selectedYear === event.year}
                    onClick={() => onSelectYear?.(event.year)}
                    onPointerEnter={() => onHoverYear?.(event.year)}
                    onPointerLeave={() => onHoverYear?.(null)}
                    onFocus={() => onHoverYear?.(event.year)}
                    onBlur={() => onHoverYear?.(null)}
                  >
                    {content}
                  </button>
                ) : (
                  <span className="event-chip" title={event.detail}>
                    {content}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      )}

      <details style={{ fontSize: 12, color: "var(--text-secondary)" }}>
        <summary>{dollarsOr("About dollar display", "About amount display")}</summary>
        <p style={{ margin: 0 }}>
          Applies to overview charts and reports.{" "}
          {dollarsOr("Today’s dollars use", "Today’s money uses")} the plan’s start year.
        </p>
      </details>

      <ChartTable
        caption="Net worth by year"
        note={
          fi && fi.year == null ? "Financial independence is not reached within this plan." : ""
        }
        columns={[
          { key: "year", label: "Year" },
          { key: "age", label: "Age" },
          { key: "net_worth", label: "Net worth", numeric: true },
          { key: "income", label: "Income", numeric: true },
          { key: "expenses", label: "Expenses", numeric: true },
          { key: "taxes", label: "Full-year taxes", numeric: true },
          { key: "cash_flow", label: "Cash flow", numeric: true },
        ]}
        rows={tableRows}
      />
    </div>
  );
}
