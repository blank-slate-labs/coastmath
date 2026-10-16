import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import MonteCarloTrialExplorer, { TRIAL_PAGE_SIZE } from "@/components/monte_carlo_trial_explorer";
import type { MonteCarloResult, MonteCarloTrialDetail, TrialSummaries } from "@/types/plan";

// 30 trials: ending net worth rises with the index; every fifth trial fails.
const N = 30;
const ending = Array.from({ length: N }, (_, i) => (i % 5 === 0 ? -50_000 : 100_000 * i));
const trials: TrialSummaries = {
  success: ending.map((_, i) => i % 5 !== 0),
  failure_year: ending.map((_, i) => (i % 5 === 0 ? 2050 + i : null)),
  ending_net_worth: ending,
  ending_liquid: ending,
  outcome: ending.map((_, i) =>
    i % 5 === 0 ? "funding_failure" : i % 2 ? "survived_below_target" : "met_targets",
  ),
  milestone_years: { fi: ending.map((_, i) => (i % 3 === 0 ? null : 2030 + i)) },
  start_year: 2026,
  start_age: 60,
  sparkline_years: [2026, 2040, 2060],
  sparklines: ending.map((v) => [1_000_000, 900_000, v]),
};
const result = {
  success_rate: 24 / 30,
  n_trials: N,
  percentile_curves: {
    years: [2026, 2060],
    p10: [0, 0],
    p25: [0, 0],
    p50: [1_000_000, 1_200_000],
    p75: [0, 0],
    p90: [0, 0],
  },
  failure_analysis: [],
  median_final_net_worth: 0,
  p10_final_net_worth: 0,
  p90_final_net_worth: 0,
  target_success_rate: 0.4,
  outcome_categories: [
    { key: "met_targets", label: "Met all targets", definition: "", count: 12, rate: 0.4 },
    {
      key: "survived_below_target",
      label: "Survived below target",
      definition: "",
      count: 12,
      rate: 0.4,
    },
    {
      key: "survived_with_spending_cuts",
      label: "Survived with spending cuts",
      definition: "",
      count: 0,
      rate: 0,
    },
    { key: "funding_failure", label: "Funding failure", definition: "", count: 6, rate: 0.2 },
  ],
  milestone_distributions: [
    {
      id: "fi",
      name: "Financial independence",
      reached_trials: 20,
      unreached_trials: 10,
      unreported_trials: 0,
      reach_rate: 2 / 3,
      year_counts: {},
      p10_year: 2032,
      median_year: 2045,
      p90_year: 2055,
    },
  ],
  base_seed: 42,
  trials,
} as MonteCarloResult & { trials: TrialSummaries };

function detailFor(index: number): MonteCarloTrialDetail {
  const failed = index % 5 === 0;
  return {
    index,
    seed: 42 + index,
    success: !failed,
    outcome: trials.outcome[index],
    failure: failed
      ? {
          trial_index: index,
          failure_year: 2050 + index,
          failure_age: 84 + index,
          cause: "liquid_assets_depleted",
          net_worth_at_failure: -1,
        }
      : null,
    ending_net_worth: ending[index],
    ending_liquid: ending[index],
    milestone_years: { fi: trials.milestone_years.fi[index] },
    simulation: {
      metadata: {
        plan_id: "p",
        start_year: 2026,
        end_year: 2060,
        success: !failed,
        failure_year: null,
      },
      yearly_snapshots: [
        { year: 2026, age: 60, net_worth: 1_000_000 },
        { year: 2027, age: 61, net_worth: 700_000 },
        { year: 2060, age: 94, net_worth: ending[index] },
      ],
    } as unknown as MonteCarloTrialDetail["simulation"],
  };
}

const rows = () => within(screen.getByRole("list", { name: "Trials" })).getAllByRole("button");
const rowLabels = () => rows().map((row) => row.textContent?.match(/^Trial \d+/)?.[0]);

describe("MonteCarloTrialExplorer", () => {
  it("pages the list instead of rendering every trial", () => {
    render(<MonteCarloTrialExplorer result={result} loadTrial={vi.fn()} />);
    expect(rows()).toHaveLength(TRIAL_PAGE_SIZE);
    expect(screen.getByText(/30 of 30 trials match/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(rows()).toHaveLength(N - TRIAL_PAGE_SIZE);
    expect(rowLabels()[0]).toBe("Trial 21");
  });

  it("filters the list by a histogram bar and clears on a second click", () => {
    render(<MonteCarloTrialExplorer result={result} loadTrial={vi.fn()} />);
    const bars = within(
      screen.getByRole("group", { name: "Ending net worth by trial" }),
    ).getAllByRole("button");
    const failedBar = bars[0];
    expect(failedBar).toHaveAccessibleName(/6 trials, 6 failed/);
    fireEvent.click(failedBar);
    expect(failedBar).toHaveAttribute("aria-pressed", "true");
    expect(rowLabels()).toEqual([
      "Trial 1",
      "Trial 6",
      "Trial 11",
      "Trial 16",
      "Trial 21",
      "Trial 26",
    ]);
    fireEvent.click(failedBar);
    expect(failedBar).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText(/30 of 30 trials match/)).toBeInTheDocument();
  });

  it("filters by outcome, category and milestone timing", () => {
    render(<MonteCarloTrialExplorer result={result} loadTrial={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Outcome"), { target: { value: "failure" } });
    expect(screen.getByText(/6 of 30 trials match/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Outcome"), {
      target: { value: "survived_below_target" },
    });
    expect(screen.getByText(/12 of 30 trials match/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Outcome"), { target: { value: "all" } });

    fireEvent.change(screen.getByLabelText("Milestone timing"), { target: { value: "never" } });
    expect(screen.getByText(/10 of 30 trials match/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Milestone timing"), { target: { value: "by" } });
    // Defaults to the age at the median year: 2045 is age 79.
    expect(screen.getByLabelText("Milestone age")).toHaveValue(79);
    fireEvent.change(screen.getByLabelText("Milestone age"), { target: { value: "65" } });
    // Trial index i reaches it in 2030 + i, at age 64 + i; index 0 never does.
    expect(rowLabels()).toEqual(["Trial 2"]);
    fireEvent.change(screen.getByLabelText("Milestone timing"), { target: { value: "after" } });
    expect(screen.getByText(/19 of 30 trials match/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByText(/30 of 30 trials match/)).toBeInTheDocument();
  });

  it("loads the selected trial and renders its path and key years", async () => {
    const loadTrial = vi.fn((index: number) => Promise.resolve(detailFor(index)));
    render(<MonteCarloTrialExplorer result={result} loadTrial={loadTrial} />);
    fireEvent.click(rows()[5]);
    expect(loadTrial).toHaveBeenCalledWith(5);
    expect(
      within(screen.getByRole("region", { name: "Trial detail" })).getByRole("status"),
    ).toHaveTextContent("Replaying trial 6");
    await screen.findByRole("table");
    const panel = screen.getByRole("region", { name: "Trial detail" });
    expect(within(panel).getByText("Trial 6")).toBeInTheDocument();
    expect(within(panel).getByRole("img", { name: /failing in 2055/ })).toBeInTheDocument();
    const table = within(panel).getByRole("table");
    expect(within(table).getByText("Failure")).toBeInTheDocument();
    expect(within(table).getByText("Largest one-year fall")).toBeInTheDocument();
    expect(within(table).getByText("Financial independence")).toBeInTheDocument();
    expect(rows()[5]).toHaveAttribute("aria-pressed", "true");
  });

  it("ignores a late response for a trial that is no longer selected", async () => {
    const pending: Record<number, (detail: MonteCarloTrialDetail) => void> = {};
    const loadTrial = vi.fn(
      (index: number) =>
        new Promise<MonteCarloTrialDetail>((resolve) => {
          pending[index] = resolve;
        }),
    );
    render(<MonteCarloTrialExplorer result={result} loadTrial={loadTrial} />);
    fireEvent.click(rows()[1]);
    fireEvent.click(rows()[2]);
    await act(async () => pending[2](detailFor(2)));
    expect(await screen.findByText("Trial 3", { selector: "h4" })).toBeInTheDocument();
    await act(async () => pending[1](detailFor(1)));
    expect(screen.queryByText("Trial 2", { selector: "h4" })).not.toBeInTheDocument();
    expect(screen.getByText("Trial 3", { selector: "h4" })).toBeInTheDocument();
  });

  it("shows a replay error with a retry", async () => {
    const loadTrial = vi
      .fn()
      .mockRejectedValueOnce(new Error("Replay failed"))
      .mockResolvedValueOnce(detailFor(3));
    render(<MonteCarloTrialExplorer result={result} loadTrial={loadTrial} />);
    fireEvent.click(rows()[3]);
    expect(await screen.findByRole("alert")).toHaveTextContent("Replay failed");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(loadTrial).toHaveBeenCalledTimes(2);
  });

  it("lists trials without replay when the run reported no seed", () => {
    render(<MonteCarloTrialExplorer result={result} />);
    expect(rows()[0]).toBeDisabled();
    expect(screen.getByText(/Run again to open/)).toBeInTheDocument();
  });
});
