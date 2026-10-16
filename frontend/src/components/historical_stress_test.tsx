import { useCallback, useMemo, useRef, useState, useEffect } from "react";
import { scaleLinear } from "d3-scale";
import { line, curveMonotoneX, area } from "d3-shape";

import { usePlanStore } from "@/stores/plan_store";
import { useStorage } from "@/storage/context";
import type {
  DownturnPathYear,
  HistoricalStressResult,
  ScenarioStressPreset,
  ScenarioStressRequest,
  ScenarioStressResult,
  YearSnapshot,
} from "@/types/plan";
import { ChartLegend } from "@/components/chart_chrome";
import { ChartEmptyState } from "@/components/chart_empty_state";
import MoneyInput from "@/components/money_input";
import { PARTNER_LABEL, PRIMARY_PERSON_LABEL } from "@/domain/person_labels";
import {
  compactCurrency,
  fullCurrency as sharedFullCurrency,
  moneyLabel,
  signedCompactCurrency,
} from "@/utils/format";
import { missingRiskInputs } from "@/utils/plan_inputs";
import { planStatus } from "@/utils/plan_status";
import { historicalYearRanges } from "@/utils/historical_year_ranges";
import { useChartSize, useObservedSize } from "@/utils/use_chart_size";
import { useYearHover } from "@/utils/use_year_hover";
import {
  HoverLine,
  PointerOverlay,
  XAxisTicks,
  YAxisTicks,
  YGridLines,
  chartTickCounts,
} from "@/components/chart_frame";

// ── Notable historical periods ────────────────────────────────────

const PRESETS = [
  { year: 1928, label: "1928 — Great Depression" },
  { year: 1966, label: "1966 — Stagflation Era" },
  { year: 1973, label: "1973 — Oil Crisis" },
  { year: 2000, label: "2000 — Dot-Com Crash" },
  { year: 2007, label: "2007 — Global Financial Crisis" },
  { year: 2020, label: "2020 — COVID Crash" },
] as const;

// ── Hypothetical presets (server applies the overlay; see help) ───

const HYPOTHETICAL: { value: ScenarioStressPreset; label: string }[] = [
  { value: "job_loss", label: "Job loss" },
  { value: "market_crash", label: "Market crash" },
  { value: "downturn", label: "Market downturn" },
  { value: "tech_bust", label: "Tech bust: job loss + crash" },
  { value: "new_child", label: "New child" },
];

const DEFAULT_PARAMS = {
  person: "self" as "self" | "spouse",
  months: "6",
  resume: "80",
  drop: "35",
  childCost: "18000",
  // Market downturn (blank bond / inflation = the plan's assumption).
  years: "3",
  totalDrop: "45",
  recovery: "3",
  bond: "",
  inflation: "",
};

type DownturnShape = Pick<
  typeof DEFAULT_PARAMS,
  "years" | "totalDrop" | "recovery" | "bond" | "inflation"
>;

// Client-side starting points only; the server applies whatever the fields hold.
const DOWNTURN_SHAPES: { label: string; values: DownturnShape }[] = [
  {
    label: "Three tough years",
    values: { years: "3", totalDrop: "45", recovery: "3", bond: "", inflation: "" },
  },
  {
    label: "Lost decade",
    values: { years: "10", totalDrop: "10", recovery: "0", bond: "", inflation: "" },
  },
  {
    label: "Stagflation",
    values: { years: "5", totalDrop: "25", recovery: "0", bond: "-3", inflation: "8" },
  },
  {
    label: "Crash and rebound",
    values: { years: "1", totalDrop: "35", recovery: "2", bond: "", inflation: "" },
  },
];

const isHypothetical = (value: string): value is ScenarioStressPreset =>
  HYPOTHETICAL.some((p) => p.value === value);

function inRange(text: string, min: number, max: number, integer = false): number | null {
  if (text.trim() === "") return null;
  const n = Number(text);
  if (!Number.isFinite(n) || n < min || n > max || (integer && !Number.isInteger(n))) return null;
  return n;
}

type DownturnCheck =
  { fields: Partial<ScenarioStressRequest>; error: null } | { fields: null; error: string };

/** Mirrors the server bounds for the downturn fields; blank bond / inflation are omitted. */
function checkDownturn(params: typeof DEFAULT_PARAMS): DownturnCheck {
  const fail = (error: string): DownturnCheck => ({ fields: null, error });
  const years = inRange(params.years, 1, 10, true);
  if (years === null) return fail("Years of decline: a whole number from 1 to 10.");
  const drop = inRange(params.totalDrop, 1, 90);
  if (drop === null) return fail("Total stock decline: 1% to 90%.");
  const recovery = inRange(params.recovery, 0, 10, true);
  if (recovery === null) return fail("Recovery years: a whole number from 0 to 10.");
  const fields: Partial<ScenarioStressRequest> = {
    stock_drop_percent: drop,
    downturn_years: years,
    recovery_years: recovery,
  };
  if (params.bond.trim() !== "") {
    const bond = inRange(params.bond, -50, 50);
    if (bond === null) return fail("Bond return: −50% to 50%, or blank.");
    fields.bond_return_percent = bond;
  }
  if (params.inflation.trim() !== "") {
    const inflation = inRange(params.inflation, -10, 30);
    if (inflation === null) return fail("Inflation: −10% to 30%, or blank.");
    fields.inflation_percent = inflation;
  }
  return { fields, error: null };
}

const MARGIN = { top: 20, right: 30, bottom: 40, left: 60 };

// Axis ticks use the app's one compact format: the sign leads the symbol ("-$20.0M").
const currencyFormat = compactCurrency;

const fullCurrencyFormat = (value: number): string => sharedFullCurrency(value);

// ── Component ─────────────────────────────────────────────────────

export default function HistoricalStressTest() {
  const plan = usePlanStore((s) => s.plan);
  const simulation = usePlanStore((s) => s.simulation);
  // A stress test needs spending and a way to fund it, as Monte Carlo does.
  const missingInputs = missingRiskInputs(simulation);
  const { adapter } = useStorage();
  const requestId = useRef(0);

  const [selectedPreset, setSelectedPreset] = useState<string>("1966");
  const [customYear, setCustomYear] = useState<string>("");
  const planStartYear = simulation?.metadata?.start_year ?? new Date().getFullYear();
  const [startYear, setStartYear] = useState<string>(String(planStartYear));
  const [params, setParams] = useState(DEFAULT_PARAMS);
  // Follow the plan's first year once the projection loads.
  useEffect(() => setStartYear(String(planStartYear)), [planStartYear]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<HistoricalStressResult | ScenarioStressResult | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  // The chart container mounts with a result.
  const size = useObservedSize(containerRef, result);

  const hypothetical = isHypothetical(selectedPreset) ? selectedPreset : null;

  const downturnError = useMemo<string | null>(() => {
    if (hypothetical !== "downturn") return null;
    if (inRange(startYear, 1900, 2300, true) === null) return "Start year: a whole year.";
    return checkDownturn(params).error;
  }, [hypothetical, startYear, params]);

  const scenarioRequest = useMemo<ScenarioStressRequest | null>(() => {
    if (!hypothetical) return null;
    const start = inRange(startYear, 1900, 2300, true);
    if (start === null) return null;
    const body: ScenarioStressRequest = { preset: hypothetical, start_year: start };
    if (hypothetical === "downturn") {
      const check = checkDownturn(params);
      return check.fields ? { ...body, ...check.fields } : null;
    }
    if (hypothetical === "job_loss" || hypothetical === "tech_bust") {
      const months = inRange(params.months, 1, 60, true);
      const resume = inRange(params.resume, 0, 200);
      if (months === null || resume === null) return null;
      Object.assign(body, {
        person: params.person,
        months_without_pay: months,
        resume_percent: resume,
      });
    }
    if (hypothetical === "market_crash" || hypothetical === "tech_bust") {
      const drop = inRange(params.drop, 1, 90);
      if (drop === null) return null;
      body.stock_drop_percent = drop;
    }
    if (hypothetical === "new_child") {
      const cost = inRange(params.childCost, 0, 1_000_000);
      if (cost === null) return null;
      body.child_annual_cost = cost;
    }
    return body;
  }, [hypothetical, startYear, params]);

  const resolvedYear = useMemo<number | null>(() => {
    if (isHypothetical(selectedPreset)) return null;
    if (selectedPreset === "custom") {
      const n = Number(customYear);
      return Number.isInteger(n) && n >= 1928 && n <= 2024 ? n : null;
    }
    if (selectedPreset) {
      return parseInt(selectedPreset, 10);
    }
    return null;
  }, [selectedPreset, customYear]);

  useEffect(() => {
    requestId.current += 1;
    setResult(null);
    setError(null);
    setIsLoading(false);
    return () => {
      requestId.current += 1;
    };
  }, [plan, simulation, resolvedYear, scenarioRequest]);

  const canRun = hypothetical ? scenarioRequest !== null : resolvedYear !== null && !missingInputs;

  const handleRun = useCallback(async () => {
    if (!plan || (resolvedYear === null && scenarioRequest === null)) return;
    const id = ++requestId.current;
    setResult(null);
    setIsLoading(true);
    setError(null);
    try {
      const res = scenarioRequest
        ? await adapter.runScenarioStressTest(plan.id, scenarioRequest)
        : await adapter.runStressTest(plan.id, resolvedYear as number);
      if (id === requestId.current) setResult(res);
    } catch (err) {
      if (id !== requestId.current) return;
      setError(err instanceof Error ? err.message : "Stress test failed");
      setResult(null);
    } finally {
      if (id === requestId.current) setIsLoading(false);
    }
  }, [plan, resolvedYear, scenarioRequest, adapter]);

  // ── Chart data & scales ───────────────────────────────────────

  const data = useMemo(() => result?.simulation_result.yearly_snapshots ?? [], [result]);
  const baseline = useMemo(() => {
    const sharedYears = new Set(data.map((s) => s.year));
    return simulation?.yearly_snapshots.filter((s) => sharedYears.has(s.year)) ?? [];
  }, [data, simulation]);
  const lowest = data.reduce<YearSnapshot | null>(
    (min, s) => (!min || s.net_worth < min.net_worth ? s : min),
    null,
  );
  const lowestLiquid = data.reduce<{ year: number; value: number } | null>((min, s) => {
    const value = Object.values(s.accounts).reduce((sum, b) => sum + b, 0);
    return !min || value < min.value ? { year: s.year, value } : min;
  }, null);
  const baselineEnd = baseline[baseline.length - 1];
  const stressEnd = data.find((s) => s.year === baselineEnd?.year);
  // A replay carries its own historical inflation, so nominal ends are not comparable: compare each
  // path in start-year dollars, deflated by that path's inflation.
  const real = (s: YearSnapshot) => s.net_worth / (s.inflation_factor || 1);
  const endDelta = baselineEnd && stressEnd ? real(stressEnd) - real(baselineEnd) : null;

  const innerWidth = size.width - MARGIN.left - MARGIN.right;
  const innerHeight = size.height - MARGIN.top - MARGIN.bottom;

  const xScale = useMemo(() => {
    if (data.length === 0) return scaleLinear().domain([0, 1]).range([0, innerWidth]);
    const years = data.map((d) => d.year);
    return scaleLinear()
      .domain([Math.min(...years), Math.max(...years)])
      .range([0, innerWidth]);
  }, [data, innerWidth]);

  const yScale = useMemo(() => {
    if (data.length === 0) return scaleLinear().domain([0, 1]).range([innerHeight, 0]);
    const values = [...data, ...baseline].map((d) => d.net_worth);
    const min = Math.min(...values, 0);
    const max = Math.max(...values, 0);
    const padding = (max - min) * 0.1 || 1000;
    return scaleLinear()
      .domain([min < 0 ? min - padding : 0, max + padding])
      .range([innerHeight, 0])
      .nice();
  }, [data, baseline, innerHeight]);

  const pathD = useMemo(() => {
    const gen = line<YearSnapshot>()
      .x((d) => xScale(d.year))
      .y((d) => yScale(d.net_worth))
      .curve(curveMonotoneX);
    return gen(data) ?? "";
  }, [data, xScale, yScale]);
  const baselinePath =
    line<YearSnapshot>()
      .x((d) => xScale(d.year))
      .y((d) => yScale(d.net_worth))
      .curve(curveMonotoneX)(baseline) ?? "";

  const areaD = useMemo(() => {
    const gen = area<YearSnapshot>()
      .x((d) => xScale(d.year))
      .y0(innerHeight)
      .y1((d) => yScale(d.net_worth))
      .curve(curveMonotoneX);
    return gen(data) ?? "";
  }, [data, xScale, yScale, innerHeight]);

  const tickCounts = chartTickCounts(innerWidth, innerHeight);
  const xTicks = useMemo(() => xScale.ticks(tickCounts.x), [xScale, tickCounts.x]);
  const yTicks = useMemo(() => yScale.ticks(tickCounts.y), [yScale, tickCounts.y]);

  const { hoverIndex, handleMouseMove, handleMouseLeave, clearHover } = useYearHover(data, xScale);
  // A new plan, projection or period drops the hover along with the result.
  useEffect(() => clearHover(), [plan, simulation, resolvedYear, scenarioRequest, clearHover]);

  const hoverPoint = hoverIndex !== null ? data[hoverIndex] : null;

  // ── Metadata label ────────────────────────────────────────────

  const historical = result && "historical_start_year" in result.metadata ? result.metadata : null;
  const scenario = result && "preset" in result.metadata ? result.metadata : null;

  const periodLabel = useMemo(() => {
    if (scenario)
      return HYPOTHETICAL.find((p) => p.value === scenario.preset)?.label ?? scenario.preset;
    if (!historical) return null;
    const yr = historical.historical_start_year;
    const preset = PRESETS.find((p) => p.year === yr);
    return preset ? preset.label : `Custom — ${yr}`;
  }, [historical, scenario]);

  // ── Render ────────────────────────────────────────────────────

  if (!plan) {
    return (
      <ChartEmptyState
        message="Select a plan first to run stress tests."
        icon={
          <>
            <path d="m2 12 5.25-4.5L10 10l4-6 4 4 4-4" />
            <path d="m2 18 5.25-4.5L10 16l4-6 4 4 4-4" />
          </>
        }
      />
    );
  }

  return (
    <div>
      {/* Controls */}
      <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
        {hypothetical
          ? moneyLabel(
              "Changes only the preset's inputs; every other year keeps the plan's own assumptions. Nominal dollars.",
            )
          : moneyLabel(
              "Replays historical stock, bond, inflation and dividend yield series. Nominal dollars.",
            )}
      </p>
      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div>
            <label style={{ marginBottom: 6 }}>Scenario</label>
            <select
              aria-label="Stress scenario"
              data-sample-view
              value={selectedPreset}
              onChange={(e) => setSelectedPreset(e.target.value)}
              style={{ minWidth: 260 }}
            >
              <option value="">Select a scenario...</option>
              <optgroup label="Historical">
                {PRESETS.map((p) => (
                  <option key={p.year} value={String(p.year)}>
                    {p.label}
                  </option>
                ))}
                <option value="custom">Custom Year</option>
              </optgroup>
              <optgroup label="Hypothetical">
                {HYPOTHETICAL.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </optgroup>
            </select>
          </div>

          {selectedPreset === "custom" && (
            <div>
              <label style={{ marginBottom: 6 }}>Year (1928–2024)</label>
              <input
                aria-label="Historical start year"
                type="number"
                min={1928}
                max={2024}
                value={customYear}
                onChange={(e) => setCustomYear(e.target.value)}
                placeholder="e.g. 1987"
                style={{ width: 140 }}
              />
            </div>
          )}

          {hypothetical && (
            <ScenarioFields
              preset={hypothetical}
              startYear={startYear}
              onStartYear={setStartYear}
              params={params}
              onParams={(patch) => setParams((p) => ({ ...p, ...patch }))}
              hasPartner={!!plan.spouse}
            />
          )}

          <button
            type="submit"
            onClick={handleRun}
            disabled={isLoading || !canRun}
            aria-describedby={
              downturnError ? "downturn-error" : missingInputs ? "stress-missing-inputs" : undefined
            }
            style={{ padding: "10px 20px" }}
          >
            {isLoading ? "Running..." : "Run Stress Test"}
          </button>
          {missingInputs && (
            <span
              id="stress-missing-inputs"
              style={{ fontSize: 13, color: "var(--text-secondary)" }}
            >
              {missingInputs}
            </span>
          )}
        </div>
        {downturnError && (
          <p
            id="downturn-error"
            style={{ margin: "10px 0 0", color: "var(--color-danger)", fontSize: 13 }}
          >
            {downturnError}
          </p>
        )}
      </div>

      {/* Error */}
      {error && (
        <div
          role="alert"
          style={{
            padding: "12px 16px",
            marginBottom: 20,
            background: "var(--color-danger-light)",
            border: "1px solid rgba(239, 68, 68, 0.2)",
            borderRadius: "var(--radius-md)",
            color: "var(--color-danger)",
            fontSize: 13,
            fontWeight: 500,
          }}
        >
          {error}
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div
          style={{
            textAlign: "center",
            padding: 48,
            color: "var(--text-tertiary)",
            fontSize: 14,
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              border: "3px solid var(--gray-200)",
              borderTopColor: "var(--chart-orange)",
              borderRadius: "50%",
              animation: "spin 0.8s linear infinite",
              margin: "0 auto 12px",
            }}
          />
          Running stress test...
        </div>
      )}

      {/* Results */}
      {result && !isLoading && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <p>
              Lowest year-end net worth:{" "}
              <strong>{fullCurrencyFormat(lowest?.net_worth ?? 0)}</strong> in {lowest?.year}.
            </p>
            {lowestLiquid &&
              (lowestLiquid.year !== lowest?.year ||
                Math.round(lowestLiquid.value) !== Math.round(lowest?.net_worth ?? 0)) && (
                <p>
                  Lowest year-end cash and investments:{" "}
                  <strong>{fullCurrencyFormat(lowestLiquid.value)}</strong> in {lowestLiquid.year}.
                </p>
              )}
            {endDelta !== null && baselineEnd && (
              <p>
                {baselineEnd.year} net worth, {endDelta >= 0 ? "above" : "below"} the steady-return
                forecast: <strong>{signedCompactCurrency(endDelta)}</strong> (
                {moneyLabel("today's dollars")}, each path deflated by its own inflation).
              </p>
            )}
            <ChartLegend
              entries={[
                {
                  label: scenario ? "Stress scenario" : "Historical replay",
                  color: "var(--chart-orange)",
                  kind: "line",
                },
                ...(baseline.length
                  ? [
                      {
                        label: "Steady-return forecast",
                        color: "var(--text-tertiary)",
                        kind: "dashed" as const,
                      },
                    ]
                  : []),
              ]}
            />
          </div>
          {/* Metadata banner */}
          <div
            className="card"
            style={{
              display: "flex",
              gap: 20,
              marginBottom: 20,
              padding: "14px 20px",
              fontSize: 13,
              color: "var(--text-secondary)",
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            <span>
              <strong style={{ color: "var(--text-primary)" }}>Period:</strong> {periodLabel}
            </span>
            {historical && (
              <span>
                <strong style={{ color: "var(--text-primary)" }}>Years:</strong>{" "}
                {historicalYearRanges(historical.years_used)}
              </span>
            )}
            {scenario && (
              <span>
                <strong style={{ color: "var(--text-primary)" }}>Starts:</strong>{" "}
                {scenario.start_year}
              </span>
            )}
            {historical?.wrapped && (
              <span
                style={{
                  color: "var(--chart-amber)",
                  background: "var(--color-warning-light)",
                  padding: "2px 10px",
                  borderRadius: "var(--radius-full)",
                  fontSize: 12,
                  fontWeight: 500,
                }}
              >
                History exhausted: the sequence repeats from 1928. Later years are a stitched
                scenario, not one continuous historical period.
              </span>
            )}
            {(() => {
              const status = planStatus(result.simulation_result);
              if (!status) return null;
              const palette = {
                success: {
                  color: "var(--chart-green)",
                  background: "var(--color-success-light)",
                  word: "Survived",
                },
                warning: {
                  color: "var(--chart-orange)",
                  background: "var(--color-warning-light)",
                  word: "Survived, but",
                },
                danger: {
                  color: "var(--chart-red)",
                  background: "var(--color-danger-light)",
                  word: "Failed",
                },
              }[status.tone];
              return (
                <span style={{ marginLeft: "auto" }} title={status.detail}>
                  <strong style={{ color: "var(--text-primary)" }}>Outcome:</strong>{" "}
                  <span
                    style={{
                      color: palette.color,
                      fontWeight: 700,
                      background: palette.background,
                      padding: "2px 10px",
                      borderRadius: "var(--radius-full)",
                    }}
                  >
                    {status.tone === "success"
                      ? "Survived: spending funded, net worth positive"
                      : `${palette.word}: ${status.label.charAt(0).toLowerCase()}${status.label.slice(1)}`}
                  </span>
                </span>
              );
            })()}
          </div>

          {scenario?.downturn_path && scenario.downturn_path.length > 0 && (
            <DownturnPathChart path={scenario.downturn_path} />
          )}

          {/* Chart */}
          <div className="card">
            <div ref={containerRef} style={{ width: "100%", height: 380, position: "relative" }}>
              {size.width > 0 && size.height > 0 && data.length > 0 && (
                <>
                  <svg width={size.width} height={size.height}>
                    <defs>
                      <linearGradient id="stressGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--chart-orange)" stopOpacity="0.15" />
                        <stop offset="100%" stopColor="var(--chart-orange)" stopOpacity="0.01" />
                      </linearGradient>
                    </defs>
                    <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
                      <YGridLines
                        ticks={yTicks}
                        yScale={yScale}
                        width={innerWidth}
                        stroke="var(--gray-100)"
                        strokeDasharray={null}
                        strokeWidth={1}
                      />

                      {/* Zero line */}
                      {yScale.domain()[0] < 0 && yScale.domain()[1] > 0 && (
                        <line
                          x1={0}
                          x2={innerWidth}
                          y1={yScale(0)}
                          y2={yScale(0)}
                          stroke="var(--gray-400)"
                          strokeWidth={1}
                          strokeDasharray="4 2"
                        />
                      )}

                      {/* Area fill */}
                      <path d={areaD} fill="url(#stressGrad)" />
                      {baseline.length > 0 && (
                        <path
                          d={baselinePath}
                          fill="none"
                          stroke="var(--text-tertiary)"
                          strokeWidth={2}
                          strokeDasharray="6 4"
                        />
                      )}

                      {/* Net worth line */}
                      <path
                        d={pathD}
                        fill="none"
                        stroke="var(--chart-orange)"
                        strokeWidth={2.5}
                        strokeLinejoin="round"
                        strokeLinecap="round"
                      />

                      <XAxisTicks
                        ticks={xTicks}
                        xScale={xScale}
                        y={innerHeight}
                        tickLine={false}
                        fill="var(--gray-400)"
                        fontFamily="var(--font-sans)"
                      />
                      <YAxisTicks
                        ticks={yTicks}
                        yScale={yScale}
                        format={currencyFormat}
                        tickLine={false}
                        fill="var(--gray-400)"
                        fontFamily="var(--font-sans)"
                      />

                      {/* Hover indicator */}
                      {hoverPoint && (
                        <>
                          <HoverLine
                            x={xScale(hoverPoint.year)}
                            height={innerHeight}
                            stroke="var(--gray-300)"
                          />
                          <circle
                            cx={xScale(hoverPoint.year)}
                            cy={yScale(hoverPoint.net_worth)}
                            r={6}
                            fill="var(--chart-orange)"
                            stroke="#fff"
                            strokeWidth={2.5}
                            pointerEvents="none"
                          />
                        </>
                      )}

                      <PointerOverlay
                        width={innerWidth}
                        height={innerHeight}
                        onMouseMove={handleMouseMove}
                        onMouseLeave={handleMouseLeave}
                      />
                    </g>
                  </svg>

                  {/* Hover tooltip */}
                  {hoverPoint && (
                    <div
                      style={{
                        position: "absolute",
                        left: xScale(hoverPoint.year) + MARGIN.left + 12,
                        top: yScale(hoverPoint.net_worth) + MARGIN.top - 10,
                        background: "var(--gray-900)",
                        color: "#fff",
                        padding: "8px 14px",
                        borderRadius: "var(--radius-md)",
                        fontSize: 12,
                        lineHeight: 1.5,
                        pointerEvents: "none",
                        whiteSpace: "nowrap",
                        boxShadow: "var(--shadow-lg)",
                      }}
                    >
                      <div style={{ fontWeight: 600 }}>
                        {hoverPoint.year}{" "}
                        <span style={{ color: "var(--gray-400)", fontWeight: 400 }}>
                          (age {hoverPoint.age})
                        </span>
                      </div>
                      <div style={{ fontVariantNumeric: "tabular-nums" }}>
                        Net Worth: {fullCurrencyFormat(hoverPoint.net_worth)}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ── Hypothetical preset inputs ────────────────────────────────────

const smallInput = { width: 110 } as const;

function ScenarioFields({
  preset,
  startYear,
  onStartYear,
  params,
  onParams,
  hasPartner,
}: {
  preset: ScenarioStressPreset;
  startYear: string;
  onStartYear: (value: string) => void;
  params: typeof DEFAULT_PARAMS;
  onParams: (patch: Partial<typeof DEFAULT_PARAMS>) => void;
  hasPartner: boolean;
}) {
  const jobLoss = preset === "job_loss" || preset === "tech_bust";
  const crash = preset === "market_crash" || preset === "tech_bust";
  return (
    <>
      <div>
        <label style={{ marginBottom: 6 }}>Start year</label>
        <input
          aria-label="Start year"
          type="number"
          step={1}
          value={startYear}
          onChange={(e) => onStartYear(e.target.value)}
          style={smallInput}
        />
      </div>
      {jobLoss && hasPartner && (
        <div>
          <label style={{ marginBottom: 6 }}>Person</label>
          <select
            aria-label="Person"
            value={params.person}
            onChange={(e) => onParams({ person: e.target.value as "self" | "spouse" })}
          >
            <option value="self">{PRIMARY_PERSON_LABEL}</option>
            <option value="spouse">{PARTNER_LABEL}</option>
          </select>
        </div>
      )}
      {jobLoss && (
        <>
          <div>
            <label style={{ marginBottom: 6 }}>Months without pay</label>
            <input
              aria-label="Months without pay"
              type="number"
              min={1}
              max={60}
              step={1}
              value={params.months}
              onChange={(e) => onParams({ months: e.target.value })}
              style={smallInput}
            />
          </div>
          <div>
            <label style={{ marginBottom: 6 }}>New pay (% of old)</label>
            <input
              aria-label="New pay percent"
              type="number"
              min={0}
              max={200}
              value={params.resume}
              onChange={(e) => onParams({ resume: e.target.value })}
              style={smallInput}
            />
          </div>
        </>
      )}
      {crash && (
        <div>
          <label style={{ marginBottom: 6 }}>Stock drop (%)</label>
          <input
            aria-label="Stock drop percent"
            type="number"
            min={1}
            max={90}
            value={params.drop}
            onChange={(e) => onParams({ drop: e.target.value })}
            style={smallInput}
          />
        </div>
      )}
      {preset === "downturn" && <DownturnFields params={params} onParams={onParams} />}
      {preset === "new_child" && (
        <div>
          <label style={{ marginBottom: 6 }}>{moneyLabel("Annual cost (today's $)")}</label>
          <MoneyInput
            aria-label="Annual child cost"
            min={0}
            step={500}
            value={params.childCost}
            onValueChange={(value) => onParams({ childCost: value })}
            style={{ width: 130 }}
          />
        </div>
      )}
    </>
  );
}

function DownturnFields({
  params,
  onParams,
}: {
  params: typeof DEFAULT_PARAMS;
  onParams: (patch: Partial<typeof DEFAULT_PARAMS>) => void;
}) {
  const fields: {
    key: keyof DownturnShape;
    label: string;
    aria: string;
    min: number;
    max: number;
    step?: number;
  }[] = [
    { key: "years", label: "Years of decline", aria: "Years of decline", min: 1, max: 10, step: 1 },
    {
      key: "totalDrop",
      label: "Total stock decline (%)",
      aria: "Total stock decline percent",
      min: 1,
      max: 90,
    },
    { key: "recovery", label: "Recovery years", aria: "Recovery years", min: 0, max: 10, step: 1 },
    { key: "bond", label: "Bond return (%/yr)", aria: "Bond return percent", min: -50, max: 50 },
    { key: "inflation", label: "Inflation (%/yr)", aria: "Inflation percent", min: -10, max: 30 },
  ];
  const matches = (shape: DownturnShape) =>
    (Object.keys(shape) as (keyof DownturnShape)[]).every(
      (key) => params[key].trim() === shape[key],
    );
  return (
    <>
      {fields.map((f) => (
        <div key={f.key}>
          <label style={{ marginBottom: 6 }}>{f.label}</label>
          <input
            aria-label={f.aria}
            type="number"
            min={f.min}
            max={f.max}
            step={f.step ?? "any"}
            value={params[f.key]}
            placeholder={f.key === "bond" || f.key === "inflation" ? "Plan" : undefined}
            onChange={(e) => onParams({ [f.key]: e.target.value })}
            style={smallInput}
          />
        </div>
      ))}
      <div style={{ flexBasis: "100%", display: "grid", gap: 8 }}>
        <div className="seg-control task-tabs" role="group" aria-label="Downturn shapes">
          {DOWNTURN_SHAPES.map((shape) => (
            <button
              key={shape.label}
              type="button"
              className="seg-option"
              aria-pressed={matches(shape.values)}
              onClick={() => onParams(shape.values)}
            >
              {shape.label}
            </button>
          ))}
        </div>
        <p className="allocation-help" style={{ margin: 0 }}>
          Blank bond return or inflation uses the plan&apos;s assumption.
        </p>
      </div>
    </>
  );
}

// ── Downturn shock chart ──────────────────────────────────────────

const PATH_MARGIN = { top: 16, right: 16, bottom: 28, left: 40 };
const PATH_HEIGHT = 180;
const PHASE_COLOR = { downturn: "var(--chart-red)", recovery: "var(--chart-green)" } as const;

/** Stock index (100 at the downturn's start) through each shocked year, from the server's path. */
function DownturnPathChart({ path }: { path: DownturnPathYear[] }) {
  const { ref, width } = useChartSize(480, PATH_HEIGHT);
  const points = useMemo(() => {
    let index = 100;
    const out = [{ x: path[0].year, value: index, phase: path[0].phase }];
    for (const entry of path) {
      index *= 1 + entry.stock_return;
      out.push({ x: entry.year + 1, value: index, phase: entry.phase });
    }
    return out;
  }, [path]);
  const innerWidth = Math.max(0, width - PATH_MARGIN.left - PATH_MARGIN.right);
  const innerHeight = PATH_HEIGHT - PATH_MARGIN.top - PATH_MARGIN.bottom;
  const x = scaleLinear()
    .domain([points[0].x, points[points.length - 1].x])
    .range([0, innerWidth]);
  const values = points.map((p) => p.value);
  const y = scaleLinear()
    .domain([Math.min(...values, 100), Math.max(...values, 100)])
    .range([innerHeight, 0])
    .nice();
  const segment = line<{ x: number; value: number }>()
    .x((p) => x(p.x))
    .y((p) => y(p.value));
  const trough = points.reduce((min, p) => (p.value < min.value ? p : min), points[0]);
  const end = points[points.length - 1];
  const yearTicks = x
    .ticks(Math.max(2, Math.min(points.length, Math.floor(innerWidth / 56))))
    .filter(Number.isInteger);
  const label = `Stock index from 100 to ${trough.value.toFixed(0)} at the low, ${end.value.toFixed(0)} after ${path[path.length - 1].year}.`;
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <ChartLegend
        entries={[
          { label: "Decline", color: PHASE_COLOR.downturn, kind: "line" },
          ...(path.some((p) => p.phase === "recovery")
            ? [{ label: "Recovery", color: PHASE_COLOR.recovery, kind: "line" as const }]
            : []),
          { label: "Pre-downturn level", color: "var(--text-tertiary)", kind: "dashed" as const },
        ]}
      />
      <div ref={ref} style={{ width: "100%", height: PATH_HEIGHT }}>
        <svg width={width} height={PATH_HEIGHT} role="img" aria-label={label}>
          <g transform={`translate(${PATH_MARGIN.left},${PATH_MARGIN.top})`}>
            {y.ticks(4).map((tick) => (
              <g key={tick} transform={`translate(0,${y(tick)})`}>
                <line x2={innerWidth} stroke="var(--gray-100)" />
                <text
                  x={-8}
                  dy="0.32em"
                  textAnchor="end"
                  fontSize={11}
                  fill="var(--gray-400)"
                  fontFamily="var(--font-sans)"
                >
                  {tick}
                </text>
              </g>
            ))}
            <line
              x2={innerWidth}
              y1={y(100)}
              y2={y(100)}
              stroke="var(--text-tertiary)"
              strokeDasharray="6 4"
            />
            {points.slice(1).map((p, i) => (
              <path
                key={p.x}
                d={segment([points[i], p]) ?? ""}
                fill="none"
                stroke={PHASE_COLOR[p.phase]}
                strokeWidth={2.5}
                strokeLinecap="round"
              />
            ))}
            {points.map((p) => (
              <circle
                key={p.x}
                cx={x(p.x)}
                cy={y(p.value)}
                r={3}
                fill={p.x === points[0].x ? "var(--text-tertiary)" : PHASE_COLOR[p.phase]}
              >
                <title>{`${p.x === points[0].x ? `Start of ${p.x}` : `End of ${p.x - 1}`}: ${p.value.toFixed(1)}`}</title>
              </circle>
            ))}
            {yearTicks.map((tick) => (
              <text
                key={tick}
                x={x(tick)}
                y={innerHeight + 18}
                textAnchor="middle"
                fontSize={11}
                fill="var(--gray-400)"
                fontFamily="var(--font-sans)"
              >
                {tick}
              </text>
            ))}
          </g>
        </svg>
      </div>
    </div>
  );
}
