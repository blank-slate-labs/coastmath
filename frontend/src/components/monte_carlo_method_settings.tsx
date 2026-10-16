import type { MonteCarloOptions, ReturnSources } from "@/api/monte_carlo";
import type { Milestone, MonteCarloExtraMetric, MonteCarloSamplingMethod } from "@/types/plan";

export type SourceKey = "stocks" | "dividend_yield" | "bonds" | "inflation";

interface SourceState {
  normal: boolean;
  mean: string;
  stdev: string;
}

/** Form state for sampling, return sources, crypto, outcome thresholds and extra metrics. */
export interface MethodSettingsState {
  sampling: MonteCarloSamplingMethod;
  blockLength: string;
  onDataEnd: "loop" | "stop" | "random_restart";
  iterations: string;
  sources: Record<SourceKey, SourceState>;
  cryptoEnabled: boolean;
  cryptoMean: string;
  cryptoStdev: string;
  /** Percent of the projection. */
  earlyPercent: string;
  latePercent: string;
  thinMarginPercent: string;
  wideMarginPercent: string;
  /** Surplus reference milestone; empty finds the retirement milestone by name. */
  retirementMilestoneId: string;
  extraMetrics: MonteCarloExtraMetric[];
}

export const SAMPLING_LABELS: Record<MonteCarloSamplingMethod, string> = {
  block_bootstrap: "Block bootstrap (random block lengths, wraps around)",
  moving_block: "Moving blocks (fixed length, no wrap)",
  historical_sequential: "Historical sequences (one trial per start year)",
  random_start: "Random start year, then in order",
  random_years: "Random independent years",
};

export const SOURCE_LABELS: Record<SourceKey, string> = {
  stocks: "Stock total return",
  dividend_yield: "Stock dividend yield",
  bonds: "Bond return",
  inflation: "Inflation",
};

export const METRIC_LABELS: Record<MonteCarloExtraMetric, string> = {
  liquid_net_worth: "Net worth without real assets",
  spending: "Spending",
  taxes: "Taxes",
  income: "Income",
};

/** Suggested starting points for a normal source, percent per year (editable). */
const SOURCE_PLACEHOLDERS: Record<SourceKey, SourceState> = {
  stocks: { normal: false, mean: "10", stdev: "18" },
  dividend_yield: { normal: false, mean: "2", stdev: "1" },
  bonds: { normal: false, mean: "5", stdev: "7" },
  inflation: { normal: false, mean: "3", stdev: "2" },
};

export const DEFAULT_METHOD_SETTINGS: MethodSettingsState = {
  sampling: "block_bootstrap",
  blockLength: "5",
  onDataEnd: "loop",
  iterations: "1",
  sources: SOURCE_PLACEHOLDERS,
  cryptoEnabled: false,
  cryptoMean: "15",
  cryptoStdev: "60",
  earlyPercent: "33.33",
  latePercent: "66.67",
  thinMarginPercent: "25",
  wideMarginPercent: "200",
  retirementMilestoneId: "",
  extraMetrics: [],
};

// The service caps runs per start year so 97 start years times the runs stay within 1,000 trials.
const MAX_RUNS_PER_START_YEAR = 10;

const DEFAULT_THRESHOLDS = { early: 100 / 3, late: 200 / 3, thin: 25, wide: 200 };

function parse(value: string): number | null {
  if (value.trim() === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function inRange(value: number | null, min: number, max: number): value is number {
  return value !== null && value >= min && value <= max;
}

/**
 * Request fields for the chosen settings. Only non-default fields are sent, so
 * the default form produces the original request body exactly.
 */
export function methodOptions(state: MethodSettingsState): {
  options: Partial<MonteCarloOptions>;
  error: string | null;
} {
  const options: Partial<MonteCarloOptions> = {};
  if (state.sampling !== "block_bootstrap") options.sampling = state.sampling;
  if (state.sampling === "moving_block") {
    const length = parse(state.blockLength);
    if (!inRange(length, 1, 30) || !Number.isInteger(length))
      return { options, error: "Block length must be a whole number from 1 to 30." };
    options.block_length = length;
  }
  if (state.sampling === "historical_sequential") {
    options.on_data_end = state.onDataEnd;
    if (state.onDataEnd === "random_restart") {
      const iterations = parse(state.iterations);
      if (!inRange(iterations, 1, MAX_RUNS_PER_START_YEAR) || !Number.isInteger(iterations))
        return {
          options,
          error: `Runs per start year must be a whole number from 1 to ${MAX_RUNS_PER_START_YEAR}.`,
        };
      if (iterations > 1) options.iterations = iterations;
    }
  }
  const sources: ReturnSources = {};
  for (const key of Object.keys(SOURCE_LABELS) as SourceKey[]) {
    const source = state.sources[key];
    if (!source.normal) continue;
    const mean = parse(source.mean);
    const stdev = parse(source.stdev);
    if (!inRange(mean, -50, 200) || !inRange(stdev, 0, 200)) {
      return {
        options,
        error: `${SOURCE_LABELS[key]}: mean must be from -50% to 200% and standard deviation from 0% to 200%.`,
      };
    }
    sources[key] = { source: "normal", mean, stdev };
  }
  if (Object.keys(sources).length) options.sources = sources;
  if (state.cryptoEnabled) {
    const mean = parse(state.cryptoMean);
    const stdev = parse(state.cryptoStdev);
    if (!inRange(mean, -50, 200) || !inRange(stdev, 0, 200))
      return {
        options,
        error: "Crypto mean must be from -50% to 200% and standard deviation from 0% to 200%.",
      };
    options.crypto = { mean, stdev };
  }
  const early = parse(state.earlyPercent);
  const late = parse(state.latePercent);
  const thin = parse(state.thinMarginPercent);
  const wide = parse(state.wideMarginPercent);
  if (!inRange(early, 0.01, 99.99) || !inRange(late, 0.01, 99.99) || early >= late) {
    return {
      options,
      error: "Failure timing cut-offs must be between 0% and 100%, early below late.",
    };
  }
  if (!inRange(thin, 0, 10000) || !inRange(wide, 0, 10000) || thin >= wide) {
    return {
      options,
      error: "Surplus cut-offs must be from 0% to 10,000%, thin margin below wide margin.",
    };
  }
  const defaultTiming =
    Math.abs(early - DEFAULT_THRESHOLDS.early) < 0.01 &&
    Math.abs(late - DEFAULT_THRESHOLDS.late) < 0.01;
  if (!defaultTiming || thin !== DEFAULT_THRESHOLDS.thin || wide !== DEFAULT_THRESHOLDS.wide) {
    options.outcome_thresholds = defaultTiming
      ? { thin_margin_percent: thin, wide_margin_percent: wide }
      : {
          failure_early_fraction: early / 100,
          failure_late_fraction: late / 100,
          thin_margin_percent: thin,
          wide_margin_percent: wide,
        };
  }
  if (state.retirementMilestoneId) {
    options.outcome_thresholds = {
      ...options.outcome_thresholds,
      retirement_milestone_id: state.retirementMilestoneId,
    };
  }
  if (state.extraMetrics.length) options.extra_metrics = [...state.extraMetrics];
  return { options, error: null };
}

const row = { display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" as const };
const narrow = { width: 90 };

/** Sampling method, return sources, crypto, outcome cut-offs and extra metrics. */
export function MonteCarloMethodSettings({
  value,
  onChange,
  disabled,
  milestones = [],
}: {
  value: MethodSettingsState;
  onChange: (next: MethodSettingsState) => void;
  disabled: boolean;
  /** The plan's milestones, for the surplus reference choice. */
  milestones?: Pick<Milestone, "id" | "name">[];
}) {
  const set = (patch: Partial<MethodSettingsState>) => onChange({ ...value, ...patch });
  const setSource = (key: SourceKey, patch: Partial<SourceState>) =>
    set({ sources: { ...value.sources, [key]: { ...value.sources[key], ...patch } } });
  const allNormal = (Object.keys(SOURCE_LABELS) as SourceKey[]).every(
    (key) => value.sources[key].normal,
  );
  return (
    <div style={{ display: "grid", gap: 14, marginTop: 14 }}>
      <fieldset style={row}>
        <legend>Return sampling</legend>
        <label>
          Sampling method
          <select
            aria-label="Sampling method"
            value={value.sampling}
            disabled={disabled}
            onChange={(e) => set({ sampling: e.target.value as MonteCarloSamplingMethod })}
          >
            {(Object.keys(SAMPLING_LABELS) as MonteCarloSamplingMethod[]).map((key) => (
              <option key={key} value={key}>
                {SAMPLING_LABELS[key]}
              </option>
            ))}
          </select>
        </label>
        {value.sampling === "moving_block" && (
          <label>
            Block length (years)
            <input
              aria-label="Block length"
              type="number"
              min={1}
              max={30}
              step={1}
              style={narrow}
              value={value.blockLength}
              disabled={disabled}
              onChange={(e) => set({ blockLength: e.target.value })}
            />
          </label>
        )}
        {value.sampling === "historical_sequential" && (
          <>
            <label>
              When history runs out
              <select
                aria-label="When history runs out"
                value={value.onDataEnd}
                disabled={disabled}
                onChange={(e) =>
                  set({ onDataEnd: e.target.value as MethodSettingsState["onDataEnd"] })
                }
              >
                <option value="loop">Loop back to the first year</option>
                <option value="stop">Only start years with enough data</option>
                <option value="random_restart">Switch to a random year</option>
              </select>
            </label>
            {value.onDataEnd === "random_restart" && (
              <label>
                Runs per start year
                <input
                  aria-label="Runs per start year"
                  type="number"
                  min={1}
                  max={MAX_RUNS_PER_START_YEAR}
                  step={1}
                  style={narrow}
                  value={value.iterations}
                  disabled={disabled}
                  onChange={(e) => set({ iterations: e.target.value })}
                />
              </label>
            )}
            <small>
              The trial count is the number of start years
              {value.onDataEnd === "random_restart" ? " times the runs per start year" : ""}; the
              Trials setting does not apply.
            </small>
          </>
        )}
        {allNormal && (
          <small>
            Every variable uses a normal distribution, so the sampling method has no effect.
          </small>
        )}
      </fieldset>

      <fieldset style={{ display: "grid", gap: 8 }}>
        <legend>Return sources</legend>
        {(Object.keys(SOURCE_LABELS) as SourceKey[]).map((key) => {
          const source = value.sources[key];
          return (
            <div key={key} style={row}>
              <label>
                {SOURCE_LABELS[key]}
                <select
                  aria-label={`${SOURCE_LABELS[key]} source`}
                  value={source.normal ? "normal" : "historical"}
                  disabled={disabled}
                  onChange={(e) => setSource(key, { normal: e.target.value === "normal" })}
                >
                  <option value="historical">Historical</option>
                  <option value="normal">Normal distribution</option>
                </select>
              </label>
              {source.normal && (
                <>
                  <label>
                    Mean (%)
                    <input
                      aria-label={`${SOURCE_LABELS[key]} mean`}
                      type="number"
                      step={0.1}
                      style={narrow}
                      value={source.mean}
                      disabled={disabled}
                      onChange={(e) => setSource(key, { mean: e.target.value })}
                    />
                  </label>
                  <label>
                    Std. dev. (%)
                    <input
                      aria-label={`${SOURCE_LABELS[key]} standard deviation`}
                      type="number"
                      min={0}
                      step={0.1}
                      style={narrow}
                      value={source.stdev}
                      disabled={disabled}
                      onChange={(e) => setSource(key, { stdev: e.target.value })}
                    />
                  </label>
                </>
              )}
            </div>
          );
        })}
        <small>
          Normal draws are independent each year and of each other, and calibration does not adjust
          them.
        </small>
        <div style={row}>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={value.cryptoEnabled}
              disabled={disabled}
              onChange={(e) => set({ cryptoEnabled: e.target.checked })}
            />
            Separate crypto return distribution
          </label>
          {value.cryptoEnabled && (
            <>
              <label>
                Mean (%)
                <input
                  aria-label="Crypto mean"
                  type="number"
                  step={0.1}
                  style={narrow}
                  value={value.cryptoMean}
                  disabled={disabled}
                  onChange={(e) => set({ cryptoMean: e.target.value })}
                />
              </label>
              <label>
                Std. dev. (%)
                <input
                  aria-label="Crypto standard deviation"
                  type="number"
                  min={0}
                  step={0.1}
                  style={narrow}
                  value={value.cryptoStdev}
                  disabled={disabled}
                  onChange={(e) => set({ cryptoStdev: e.target.value })}
                />
              </label>
            </>
          )}
        </div>
      </fieldset>

      <fieldset style={row}>
        <legend>Outcome detail</legend>
        <label>
          Early failure before (% of plan)
          <input
            aria-label="Early failure cut-off"
            type="number"
            min={0}
            max={100}
            step={1}
            style={narrow}
            value={value.earlyPercent}
            disabled={disabled}
            onChange={(e) => set({ earlyPercent: e.target.value })}
          />
        </label>
        <label>
          Late failure from (% of plan)
          <input
            aria-label="Late failure cut-off"
            type="number"
            min={0}
            max={100}
            step={1}
            style={narrow}
            value={value.latePercent}
            disabled={disabled}
            onChange={(e) => set({ latePercent: e.target.value })}
          />
        </label>
        <label>
          Thin margin below (% of retirement net worth)
          <input
            aria-label="Thin margin cut-off"
            type="number"
            min={0}
            step={5}
            style={narrow}
            value={value.thinMarginPercent}
            disabled={disabled}
            onChange={(e) => set({ thinMarginPercent: e.target.value })}
          />
        </label>
        <label>
          Wide margin above (% of retirement net worth)
          <input
            aria-label="Wide margin cut-off"
            type="number"
            min={0}
            step={5}
            style={narrow}
            value={value.wideMarginPercent}
            disabled={disabled}
            onChange={(e) => set({ wideMarginPercent: e.target.value })}
          />
        </label>
        <label>
          Retirement milestone
          <select
            aria-label="Retirement milestone"
            value={value.retirementMilestoneId}
            disabled={disabled}
            onChange={(e) => set({ retirementMilestoneId: e.target.value })}
          >
            <option value="">Automatic (named for retirement)</option>
            {milestones.map((milestone) => (
              <option key={milestone.id} value={milestone.id}>
                {milestone.name}
              </option>
            ))}
            {value.retirementMilestoneId &&
              !milestones.some((m) => m.id === value.retirementMilestoneId) && (
                <option value={value.retirementMilestoneId}>Removed milestone (automatic)</option>
              )}
          </select>
        </label>
      </fieldset>

      <fieldset style={row}>
        <legend>Extra percentile charts</legend>
        {(Object.keys(METRIC_LABELS) as MonteCarloExtraMetric[]).map((metric) => (
          <label key={metric} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={value.extraMetrics.includes(metric)}
              disabled={disabled}
              onChange={(e) =>
                set({
                  extraMetrics: e.target.checked
                    ? [...value.extraMetrics, metric]
                    : value.extraMetrics.filter((m) => m !== metric),
                })
              }
            />
            {METRIC_LABELS[metric]}
          </label>
        ))}
      </fieldset>
    </div>
  );
}
