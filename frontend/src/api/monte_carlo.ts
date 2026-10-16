import { api } from "@/api/client";
import type {
  MonteCarloExtraMetric,
  MonteCarloResult,
  MonteCarloSamplingMethod,
  MonteCarloTrialDetail,
  SuccessTargets,
} from "@/types/plan";

/** Mean and standard deviation in percent per year. */
export interface NormalDistribution {
  mean: number;
  stdev: number;
}

export type ReturnSource = { source: "historical" } | ({ source: "normal" } & NormalDistribution);

export interface ReturnSources {
  /** Stock total return (price plus dividends). */
  stocks?: ReturnSource;
  dividend_yield?: ReturnSource;
  bonds?: ReturnSource;
  inflation?: ReturnSource;
}

export interface OutcomeThresholds {
  failure_early_fraction?: number;
  failure_late_fraction?: number;
  thin_margin_percent?: number;
  wide_margin_percent?: number;
  /** Surplus reference milestone; omitted finds the retirement milestone by name. */
  retirement_milestone_id?: string;
}

export interface MonteCarloOptions {
  block_size_min?: number;
  block_size_max?: number;
  seed?: number | null;
  failure_mode?: "liquid_assets" | "net_worth";
  success_targets?: SuccessTargets | null;
  /** Shift sampled history so its compound return matches the plan's assumptions (default true). */
  calibrate_to_plan?: boolean;
  /** Omitted: block bootstrap. Send each method's own fields only with that method. */
  sampling?: MonteCarloSamplingMethod;
  block_length?: number;
  on_data_end?: "loop" | "stop" | "random_restart";
  iterations?: number;
  sources?: ReturnSources;
  /** Return distribution for cryptocurrency accounts. */
  crypto?: NormalDistribution;
  outcome_thresholds?: OutcomeThresholds;
  extra_metrics?: MonteCarloExtraMetric[];
}

/** The request body for a run; the read-only sample answers only the body it stored. */
export function monteCarloRequestBody(nTrials: number = 1000, options: MonteCarloOptions = {}) {
  return { n_trials: nTrials, block_size_min: 3, block_size_max: 7, ...options };
}

export async function runMonteCarlo(
  planId: string,
  nTrials: number = 1000,
  options: MonteCarloOptions = {},
): Promise<MonteCarloResult> {
  const resp = await api.post<MonteCarloResult>(
    `/plans/${planId}/monte-carlo`,
    monteCarloRequestBody(nTrials, options),
  );
  return resp.data;
}

/** Replays one trial of a run: send that run's settings and the `base_seed` it returned. */
export async function runMonteCarloTrial(
  planId: string,
  index: number,
  nTrials: number,
  baseSeed: number,
  options: MonteCarloOptions = {},
): Promise<MonteCarloTrialDetail> {
  const resp = await api.post<MonteCarloTrialDetail>(
    `/plans/${planId}/monte-carlo/trials/${index}`,
    { ...monteCarloRequestBody(nTrials, options), base_seed: baseSeed },
  );
  return resp.data;
}
