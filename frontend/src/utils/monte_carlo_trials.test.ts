import { describe, expect, it } from "vitest";

import type { TrialSummaries } from "@/types/plan";
import { ageInYear, endingNetWorthHistogram, filterTrials } from "@/utils/monte_carlo_trials";

function makeTrials(ending: number[], overrides: Partial<TrialSummaries> = {}): TrialSummaries {
  return {
    success: ending.map((v) => v > 0),
    failure_year: ending.map((v) => (v > 0 ? null : 2050)),
    ending_net_worth: ending,
    ending_liquid: ending,
    outcome: ending.map((v) => (v > 0 ? "met_targets" : "funding_failure")),
    milestone_years: {},
    start_year: 2026,
    start_age: 60,
    sparkline_years: [2026, 2060],
    sparklines: ending.map((v) => [1_000_000, v]),
    ...overrides,
  };
}

describe("endingNetWorthHistogram", () => {
  it("puts every trial in exactly one bin and counts failures", () => {
    const ending = Array.from({ length: 200 }, (_, i) => (i - 40) * 10_000);
    const trials = makeTrials(ending);
    const bins = endingNetWorthHistogram(trials);
    const members = bins.flatMap((b) => b.trials).sort((a, b) => a - b);
    expect(members).toEqual(ending.map((_, i) => i));
    expect(bins.reduce((sum, b) => sum + b.failed, 0)).toBe(
      trials.success.filter((ok) => !ok).length,
    );
    for (const bin of bins) {
      for (const i of bin.trials) {
        if (!bin.openLow) expect(ending[i]).toBeGreaterThanOrEqual(bin.x0);
        if (!bin.openHigh) expect(ending[i]).toBeLessThanOrEqual(bin.x1);
      }
    }
  });

  it("keeps extreme trials in open outer bins instead of stretching the axis", () => {
    const ending = [
      ...Array.from({ length: 98 }, (_, i) => 100_000 + i * 1_000),
      -5_000_000,
      90_000_000,
    ];
    const bins = endingNetWorthHistogram(makeTrials(ending));
    expect(bins[0].openLow).toBe(true);
    expect(bins[bins.length - 1].openHigh).toBe(true);
    expect(bins[0].trials).toContain(98);
    expect(bins[bins.length - 1].trials).toContain(99);
    expect(bins[bins.length - 1].x1).toBeLessThan(1_000_000);
  });

  it("handles identical values and an empty run", () => {
    expect(endingNetWorthHistogram(makeTrials([5, 5, 5]))).toHaveLength(1);
    expect(endingNetWorthHistogram(makeTrials([5, 5, 5]))[0].trials).toEqual([0, 1, 2]);
    expect(endingNetWorthHistogram(makeTrials([]))).toEqual([]);
  });
});

describe("filterTrials", () => {
  const trials = makeTrials([300, -10, 200, 100, -20], {
    outcome: [
      "met_targets",
      "funding_failure",
      "survived_below_target",
      "met_targets",
      "funding_failure",
    ],
    milestone_years: { fi: [2030, null, 2041, 2036, null] },
  });

  it("filters by outcome, success and category", () => {
    expect(filterTrials(trials, "all", null, null)).toEqual([0, 1, 2, 3, 4]);
    expect(filterTrials(trials, "success", null, null)).toEqual([0, 2, 3]);
    expect(filterTrials(trials, "failure", null, null)).toEqual([1, 4]);
    expect(filterTrials(trials, "survived_below_target", null, null)).toEqual([2]);
  });

  it("filters by milestone age, using the run's start age", () => {
    expect(ageInYear(trials, 2036)).toBe(70);
    expect(filterTrials(trials, "all", { id: "fi", mode: "by", age: 70 }, null)).toEqual([0, 3]);
    expect(filterTrials(trials, "all", { id: "fi", mode: "after", age: 70 }, null)).toEqual([2]);
    expect(filterTrials(trials, "all", { id: "fi", mode: "never", age: 70 }, null)).toEqual([1, 4]);
    expect(filterTrials(trials, "success", { id: "fi", mode: "any", age: 0 }, null)).toEqual([
      0, 2, 3,
    ]);
  });

  it("combines a histogram bin with other filters and sorts by ending net worth", () => {
    const bin = { x0: 0, x1: 400, openLow: false, openHigh: false, trials: [3, 0, 2], failed: 0 };
    expect(filterTrials(trials, "all", null, bin)).toEqual([0, 2, 3]);
    expect(filterTrials(trials, "met_targets", null, bin)).toEqual([0, 3]);
    expect(filterTrials(trials, "all", null, null, "ending_asc")).toEqual([4, 1, 3, 2, 0]);
    expect(filterTrials(trials, "all", null, null, "ending_desc")).toEqual([0, 2, 3, 1, 4]);
  });
});
