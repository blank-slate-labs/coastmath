import { bisectRight, quantileSorted } from "d3-array";
import { scaleLinear } from "d3-scale";

import type { TrialSummaries } from "@/types/plan";

/** "all", "success", "failure", or an `outcome_categories` key. */
export type OutcomeFilter = string;

export type MilestoneMode = "any" | "by" | "after" | "never";

export interface MilestoneFilter {
  id: string;
  mode: MilestoneMode;
  age: number;
}

export interface HistogramBin {
  /** Lower edge, inclusive. The first bin also holds every value below it when `openLow`. */
  x0: number;
  /** Upper edge, exclusive except for the last bin. The last bin also holds values above it when `openHigh`. */
  x1: number;
  openLow: boolean;
  openHigh: boolean;
  /** Trial indices in this bin. */
  trials: number[];
  failed: number;
}

/** The primary person's age in a calendar year of the run. */
export function ageInYear(trials: TrialSummaries, year: number): number {
  return trials.start_age + (year - trials.start_year);
}

/**
 * Bins of ending net worth over the 2nd to 98th percentile, so a few extreme
 * trials do not squeeze everyone else into one bar. Trials beyond that range
 * join the outer bins, which are marked open.
 */
export function endingNetWorthHistogram(trials: TrialSummaries, target = 20): HistogramBin[] {
  const values = trials.ending_net_worth;
  if (values.length === 0) return [];
  const sorted = [...values].sort((a, b) => a - b);
  const lo = quantileSorted(sorted, 0.02) ?? sorted[0];
  const hi = quantileSorted(sorted, 0.98) ?? sorted[sorted.length - 1];
  let edges = lo < hi ? scaleLinear().domain([lo, hi]).nice(target).ticks(target) : [];
  if (edges.length < 2) edges = lo < hi ? [lo, hi] : [lo, lo];
  const count = Math.max(edges.length - 1, 1);
  const bins: HistogramBin[] = Array.from({ length: count }, (_, i) => ({
    x0: edges[i],
    x1: edges[Math.min(i + 1, edges.length - 1)],
    openLow: false,
    openHigh: false,
    trials: [],
    failed: 0,
  }));
  values.forEach((value, index) => {
    const bin = bins[Math.min(Math.max(bisectRight(edges, value) - 1, 0), count - 1)];
    bin.trials.push(index);
    if (!trials.success[index]) bin.failed += 1;
  });
  bins[0].openLow = sorted[0] < edges[0];
  bins[count - 1].openHigh = sorted[sorted.length - 1] > edges[edges.length - 1];
  return bins;
}

export function matchesOutcome(
  trials: TrialSummaries,
  index: number,
  outcome: OutcomeFilter,
): boolean {
  if (outcome === "all") return true;
  if (outcome === "success") return trials.success[index];
  if (outcome === "failure") return !trials.success[index];
  return trials.outcome[index] === outcome;
}

export function matchesMilestone(
  trials: TrialSummaries,
  index: number,
  filter: MilestoneFilter | null,
): boolean {
  if (!filter || filter.mode === "any") return true;
  const year = trials.milestone_years[filter.id]?.[index] ?? null;
  if (filter.mode === "never") return year === null;
  if (year === null) return false;
  const age = ageInYear(trials, year);
  return filter.mode === "by" ? age <= filter.age : age > filter.age;
}

export type TrialSort = "index" | "ending_asc" | "ending_desc";

/** Trial indices that pass every filter, in the requested order. */
export function filterTrials(
  trials: TrialSummaries,
  outcome: OutcomeFilter,
  milestone: MilestoneFilter | null,
  bin: HistogramBin | null,
  sort: TrialSort = "index",
): number[] {
  const pool = bin
    ? [...bin.trials].sort((a, b) => a - b)
    : trials.ending_net_worth.map((_, i) => i);
  const matches = pool.filter(
    (i) => matchesOutcome(trials, i, outcome) && matchesMilestone(trials, i, milestone),
  );
  if (sort === "ending_asc")
    matches.sort((a, b) => trials.ending_net_worth[a] - trials.ending_net_worth[b] || a - b);
  if (sort === "ending_desc")
    matches.sort((a, b) => trials.ending_net_worth[b] - trials.ending_net_worth[a] || a - b);
  return matches;
}
