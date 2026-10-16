import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ChartEmptyState } from "@/components/chart_empty_state";
import IQRSparkline from "@/components/iqr_sparkline";
import MonteCarloFanChart from "@/components/monte_carlo_fan_chart";
import type { PercentileCurve } from "@/components/monte_carlo_fan_chart";
import MonteCarloSummary from "@/components/monte_carlo_summary";
import MilestoneOutcomes from "@/components/milestone_outcomes";
import MoneyInput from "@/components/money_input";
import MonteCarloTrialExplorer from "@/components/monte_carlo_trial_explorer";
import {
  DEFAULT_METHOD_SETTINGS,
  MonteCarloMethodSettings,
  SAMPLING_LABELS,
  methodOptions,
} from "@/components/monte_carlo_method_settings";
import type { MethodSettingsState } from "@/components/monte_carlo_method_settings";
import {
  MonteCarloMetricBands,
  MonteCarloOutcomeDetail,
} from "@/components/monte_carlo_outcome_detail";
import type { MonteCarloOptions } from "@/api/monte_carlo";
import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import type { MonteCarloResult, TrialSummaries } from "@/types/plan";
import { moneyLabel } from "@/utils/format";
import { missingRiskInputs } from "@/utils/plan_inputs";

// The service accepts at most 1,000 trials: more outlast the proxy's 100 s limit on production.
const TRIAL_OPTIONS = [100, 500, 1000];

function toPercentileCurves(result: MonteCarloResult): PercentileCurve[] {
  const curves = result.percentile_curves;
  return [
    { label: "p10", values: curves.p10 },
    { label: "p25", values: curves.p25 },
    { label: "p50", values: curves.p50 },
    { label: "p75", values: curves.p75 },
    { label: "p90", values: curves.p90 },
  ];
}

function stopTimer(timer: { current: ReturnType<typeof setInterval> | null }) {
  if (timer.current) clearInterval(timer.current);
  timer.current = null;
}

export default function MonteCarloDashboard() {
  const plan = usePlanStore((s) => s.plan);
  const simulation = usePlanStore((s) => s.simulation);
  const isSimulating = usePlanStore((s) => s.isSimulating);
  const isSaving = useSaveStore((s) => s.pending > 0);
  const isUpdating = isSaving || isSimulating;
  const { adapter } = useStorage();
  const [seed, setSeed] = useState("42");
  const [blockMin, setBlockMin] = useState("3");
  const [blockMax, setBlockMax] = useState("7");
  const blockRangeError = [blockMin, blockMax].some(
    (value) =>
      value.trim() === "" ||
      !Number.isInteger(Number(value)) ||
      Number(value) < 1 ||
      Number(value) > 30,
  )
    ? "Block lengths must be whole numbers from 1 to 30."
    : Number(blockMin) > Number(blockMax)
      ? "Minimum block length must not exceed maximum."
      : null;
  const blockRangeLabel = blockRangeError
    ? null
    : Number(blockMin) === Number(blockMax)
      ? `${Number(blockMin)}`
      : `${Number(blockMin)}–${Number(blockMax)}`;
  const [terminalTarget, setTerminalTarget] = useState("");
  // The plan's legacy target is in today's dollars; the input is nominal in the final
  // year, so inflate it by the engine's factor for that year. Edits here are per run.
  const legacyTarget = plan?.estate_settings?.legacy_target;
  const snapshots = simulation?.yearly_snapshots ?? [];
  const finalInflation = snapshots[snapshots.length - 1]?.inflation_factor;
  const savedTerminalTarget =
    legacyTarget != null && finalInflation != null
      ? String(Math.round(legacyTarget * finalInflation))
      : null;
  useEffect(() => {
    if (savedTerminalTarget !== null) setTerminalTarget(savedTerminalTarget);
  }, [plan?.id, savedTerminalTarget]);
  const [countCuts, setCountCuts] = useState(false);
  const [calibrateToPlan, setCalibrateToPlan] = useState(true);
  const [failureMode, setFailureMode] = useState<"liquid_assets" | "net_worth">("liquid_assets");
  // Per-run settings like the others above: kept while the page is open, not saved to the plan.
  const [methodSettings, setMethodSettings] =
    useState<MethodSettingsState>(DEFAULT_METHOD_SETTINGS);
  const method = useMemo(() => methodOptions(methodSettings), [methodSettings]);
  const usesBlockRange = methodSettings.sampling === "block_bootstrap";
  const settingsError = (usesBlockRange ? blockRangeError : null) ?? method.error;
  const requestId = useRef(0);
  const hasRun = useRef(false);
  const [notice, setNotice] = useState<string | null>(null);

  const [result, setResult] = useState<MonteCarloResult | null>(null);
  // The settings the shown result ran with; a trial replay must send the same ones.
  const [runOptions, setRunOptions] = useState<MonteCarloOptions | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [nTrials, setNTrials] = useState(1000);
  const [error, setError] = useState<string | null>(null);
  const [fanChartWidth, setFanChartWidth] = useState(760);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const chartWrapRef = useRef<HTMLDivElement>(null);

  // Which input cleared a run: the plan (an edit anywhere) or this tab's run settings.
  const lastInputs = useRef({ plan, simulation });
  useEffect(() => {
    requestId.current += 1;
    const planChanged =
      lastInputs.current.plan !== plan || lastInputs.current.simulation !== simulation;
    lastInputs.current = { plan, simulation };
    if (hasRun.current) {
      setNotice(
        planChanged
          ? "Plan changed; previous run cleared. Run again after the forecast updates."
          : "Settings changed; previous run cleared.",
      );
      hasRun.current = false;
    }
    setResult(null);
    setIsRunning(false);
    setError(null);
    stopTimer(timerRef);
    return () => {
      requestId.current += 1;
      stopTimer(timerRef);
    };
  }, [
    plan,
    simulation,
    nTrials,
    seed,
    blockMin,
    blockMax,
    failureMode,
    terminalTarget,
    countCuts,
    calibrateToPlan,
    methodSettings,
  ]);

  useEffect(() => {
    const element = chartWrapRef.current;
    if (!element) return;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      setFanChartWidth(Math.max(entry.contentRect.width - 8, 320));
    });

    observer.observe(element);
    return () => observer.disconnect();
  }, [result]);

  // An empty or unfunded plan "fails" every trial; it has no risk to measure yet.
  const missingInputs = missingRiskInputs(simulation);

  const handleRun = useCallback(async () => {
    if (!plan || isUpdating || settingsError || missingInputs) return;

    if (
      seed !== "" &&
      (!Number.isInteger(Number(seed)) || Number(seed) < 0 || Number(seed) > 2147483647)
    ) {
      setError("Seed must be a whole number from 0 to 2147483647, or blank for a random run.");
      return;
    }
    if (
      terminalTarget !== "" &&
      (!Number.isFinite(Number(terminalTarget)) || Number(terminalTarget) < 0)
    ) {
      setError(
        "Final net worth target must be zero or a positive dollar amount, or blank for none.",
      );
      return;
    }
    const id = ++requestId.current;
    hasRun.current = true;
    setNotice(null);
    setResult(null);
    setIsRunning(true);
    setError(null);
    setElapsedMs(0);

    const start = Date.now();
    stopTimer(timerRef);
    timerRef.current = setInterval(() => {
      setElapsedMs(Date.now() - start);
    }, 100);

    try {
      const targets =
        terminalTarget !== "" || countCuts
          ? {
              terminal_net_worth_min: terminalTarget === "" ? null : Number(terminalTarget),
              count_spending_cuts_as_shortfall: countCuts,
            }
          : null;
      const options: MonteCarloOptions = {
        block_size_min: Number(blockMin),
        block_size_max: Number(blockMax),
        seed: seed === "" ? null : Number(seed),
        failure_mode: failureMode,
        success_targets: targets,
        calibrate_to_plan: calibrateToPlan,
        ...method.options,
      };
      const response = await adapter.runMonteCarlo(plan.id, nTrials, options);
      if (id === requestId.current) {
        setRunOptions(options);
        setResult(response);
      }
    } catch (err) {
      if (id === requestId.current)
        setError(err instanceof Error ? err.message : "Monte Carlo simulation failed");
    } finally {
      // A superseded run leaves the timer and running state to the run that replaced it.
      if (id === requestId.current) {
        stopTimer(timerRef);
        setElapsedMs(Date.now() - start);
        setIsRunning(false);
      }
    }
  }, [
    nTrials,
    plan,
    adapter,
    seed,
    blockMin,
    blockMax,
    settingsError,
    method,
    failureMode,
    terminalTarget,
    countCuts,
    calibrateToPlan,
    isUpdating,
    missingInputs,
  ]);

  const planId = plan?.id;
  const baseSeed = result?.base_seed;
  const loadTrial = useMemo(() => {
    if (!planId || !result || baseSeed == null || !runOptions) return undefined;
    return (index: number) =>
      adapter.runMonteCarloTrial(planId, index, result.n_trials, baseSeed, runOptions);
  }, [adapter, planId, result, baseSeed, runOptions]);

  if (!plan) {
    return (
      <ChartEmptyState
        message="Select a plan to run Monte Carlo simulation."
        icon={
          <>
            <path d="M2 20h.01" />
            <path d="M7 20v-4" />
            <path d="M12 20v-8" />
            <path d="M17 20V8" />
            <path d="M22 4v16" />
          </>
        }
      />
    );
  }

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <div className="page-header" style={{ marginBottom: 0 }}>
        <div className="page-header-copy">
          <h2 className="page-title">Monte Carlo</h2>
        </div>
      </div>

      <div className="mc-run-bar">
        <button
          type="button"
          className="btn-primary"
          onClick={handleRun}
          disabled={isRunning || isUpdating || !!settingsError || !!missingInputs}
          aria-describedby={missingInputs ? "mc-missing-inputs" : undefined}
          style={{ minHeight: 42, padding: "0 22px", fontSize: 14 }}
        >
          {isRunning ? "Running..." : "Run Monte Carlo"}
        </button>

        {missingInputs ? (
          <span id="mc-missing-inputs">{missingInputs}</span>
        ) : (
          <span>
            {methodSettings.sampling === "historical_sequential"
              ? "One trial per historical start year"
              : `${nTrials.toLocaleString()} trials`}{" "}
            ·{" "}
            {failureMode === "liquid_assets"
              ? "Liquid-assets funding test"
              : "Net-worth funding test"}
            {terminalTarget !== "" || countCuts ? " · Additional targets set" : ""}
          </span>
        )}
      </div>
      {/* The result card shows the rate; only assistive tech hears it announced. */}
      <div
        className="sr-only"
        role={result && !isRunning ? "status" : undefined}
        aria-live="polite"
        aria-atomic="true"
      >
        {result &&
          !isRunning &&
          `${(result.success_rate * 100).toFixed(1)}% of trials funded spending.`}
      </div>
      <details className="card mc-settings">
        <summary>Run settings and success criteria</summary>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 20,
            flexWrap: "wrap",
          }}
        >
          <label
            style={{
              margin: 0,
              display: "flex",
              alignItems: "center",
              gap: 12,
              color: "var(--text-secondary)",
            }}
          >
            Trials
            <input
              disabled={isRunning}
              type="range"
              min={0}
              max={TRIAL_OPTIONS.length - 1}
              step={1}
              value={TRIAL_OPTIONS.indexOf(nTrials)}
              onChange={(e) => setNTrials(TRIAL_OPTIONS[Number(e.target.value)])}
              style={{ width: 160 }}
            />
            <span
              style={{
                minWidth: 56,
                color: "var(--text-primary)",
                fontWeight: 700,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {nTrials.toLocaleString()}
            </span>
          </label>

          <label>
            Random seed (blank for random)
            <input
              aria-label="Random seed"
              type="number"
              min={0}
              max={2147483647}
              value={seed}
              disabled={isRunning}
              onChange={(e) => setSeed(e.target.value)}
            />
          </label>
          {usesBlockRange && (
            <>
              <label>
                Minimum block length (years)
                <input
                  type="number"
                  min={1}
                  max={30}
                  step={1}
                  value={blockMin}
                  disabled={isRunning}
                  aria-invalid={!!blockRangeError}
                  aria-describedby={blockRangeError ? "mc-block-error" : undefined}
                  onChange={(e) => setBlockMin(e.target.value)}
                />
              </label>
              <label>
                Maximum block length (years)
                <input
                  type="number"
                  min={1}
                  max={30}
                  step={1}
                  value={blockMax}
                  disabled={isRunning}
                  aria-invalid={!!blockRangeError}
                  aria-describedby={blockRangeError ? "mc-block-error" : undefined}
                  onChange={(e) => setBlockMax(e.target.value)}
                />
              </label>
              {blockRangeError && (
                <p id="mc-block-error" role="alert">
                  {blockRangeError}
                </p>
              )}
            </>
          )}
          <label>
            Failure definition
            <select
              value={failureMode}
              disabled={isRunning}
              onChange={(e) => setFailureMode(e.target.value as typeof failureMode)}
            >
              <option value="liquid_assets">Liquid assets depleted / spending unfunded</option>
              <option value="net_worth">Net worth depleted / spending unfunded</option>
            </select>
          </label>
          <label>
            {moneyLabel("Final net worth target ($, nominal, optional)")}
            <MoneyInput
              aria-label="Final net worth target"
              min={0}
              step={10000}
              value={terminalTarget}
              disabled={isRunning}
              onValueChange={setTerminalTarget}
              placeholder="None"
            />
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={countCuts}
              disabled={isRunning}
              onChange={(e) => setCountCuts(e.target.checked)}
            />
            Count flexible-spending cuts as a shortfall
          </label>
          <label
            style={{ display: "flex", alignItems: "center", gap: 8 }}
            title="Centers historical stock returns, bond returns and inflation around this plan's yearly assumptions. Individual trials and the median balance can differ from the steady-return forecast. Untick to sample historical rates without adjustment."
          >
            <input
              type="checkbox"
              checked={calibrateToPlan}
              disabled={isRunning}
              onChange={(e) => setCalibrateToPlan(e.target.checked)}
            />
            Calibrate sampled returns to this plan's assumptions
          </label>
        </div>
        <MonteCarloMethodSettings
          value={methodSettings}
          onChange={setMethodSettings}
          disabled={isRunning}
          milestones={plan?.milestones}
        />
        {method.error && <p role="alert">{method.error}</p>}
      </details>
      <details className="mc-methodology">
        <summary>How this test works</summary>
        <p>
          {!usesBlockRange
            ? `${SAMPLING_LABELS[methodSettings.sampling]}; `
            : blockRangeLabel
              ? `Block bootstrap of ${blockRangeLabel} consecutive historical ${blockRangeLabel === "1" ? "year" : "years"}; `
              : "Block bootstrap; "}
          historical stocks, bonds and inflation vary together. Stock returns split into price
          growth and dividends using that year's S&P 500 dividend yield.
        </p>
        <p>
          Calibration centers historical returns and inflation on the plan's assumptions; turn it
          off for unadjusted history.
        </p>
      </details>

      {isUpdating && <p role="status">Updating forecast…</p>}
      {notice && <p role="status">{notice}</p>}
      {error && (
        <div
          role="alert"
          style={{
            padding: "12px 16px",
            borderRadius: 16,
            border: "1px solid rgba(239, 68, 68, 0.18)",
            background: "var(--color-danger-light)",
            color: "var(--color-danger)",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {error}
        </div>
      )}

      {isRunning && !result && (
        <div
          className="card"
          role="status"
          aria-live="polite"
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
              borderTopColor: "var(--brand-primary)",
              borderRadius: "50%",
              animation: "spin 0.8s linear infinite",
              margin: "0 auto 12px",
            }}
          />
          Running {nTrials.toLocaleString()} trials… {(elapsedMs / 1000).toFixed(0)} seconds
          elapsed.
        </div>
      )}

      {result && !isRunning && (
        <>
          <div className="card" id="market_results" tabIndex={-1}>
            <MonteCarloSummary result={result} />
          </div>

          <MilestoneOutcomes outcomes={result.milestone_distributions ?? []} />

          {result.outcome_detail && <MonteCarloOutcomeDetail detail={result.outcome_detail} />}

          <div className="card">
            <div className="card-header">
              <div>
                <h3 style={{ margin: 0, fontSize: 18 }}>Net worth projection</h3>
              </div>
            </div>

            <div ref={chartWrapRef} style={{ width: "100%", overflow: "hidden" }}>
              <MonteCarloFanChart
                percentileCurves={toPercentileCurves(result)}
                years={result.percentile_curves.years}
                width={fanChartWidth}
                height={400}
              />
            </div>
          </div>

          {result.metric_percentiles && (
            <MonteCarloMetricBands metrics={result.metric_percentiles} width={fanChartWidth} />
          )}

          {result.trials && (
            <MonteCarloTrialExplorer
              result={result as MonteCarloResult & { trials: TrialSummaries }}
              loadTrial={loadTrial}
            />
          )}

          <div className="card">
            <div className="card-header" style={{ marginBottom: 12 }}>
              <div>
                <h3 style={{ margin: 0, fontSize: 18 }}>Middle 50% of outcomes</h3>
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <IQRSparkline
                p25={result.percentile_curves.p25}
                p50={result.percentile_curves.p50}
                p75={result.percentile_curves.p75}
                width={220}
                height={52}
              />
              <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
                P25–P75 interquartile range
              </span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
