import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import MonteCarloDashboard from "./monte_carlo_dashboard";
import { DEFAULT_METHOD_SETTINGS, methodOptions } from "./monte_carlo_method_settings";
import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import type { MonteCarloResult } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const mocks = vi.hoisted(() => ({ run: vi.fn(), trial: vi.fn() }));
const adapter = makeAdapter({ runMonteCarlo: mocks.run, runMonteCarloTrial: mocks.trial });
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

describe("methodOptions", () => {
  it("sends nothing for the default settings", () => {
    expect(methodOptions(DEFAULT_METHOD_SETTINGS)).toEqual({ options: {}, error: null });
  });

  it("sends each method's own fields, normal sources, crypto, thresholds and metrics", () => {
    const { options, error } = methodOptions({
      ...DEFAULT_METHOD_SETTINGS,
      sampling: "historical_sequential",
      onDataEnd: "random_restart",
      iterations: "3",
      sources: {
        ...DEFAULT_METHOD_SETTINGS.sources,
        bonds: { normal: true, mean: "4", stdev: "6.5" },
      },
      cryptoEnabled: true,
      earlyPercent: "25",
      latePercent: "75",
      extraMetrics: ["taxes"],
    });
    expect(error).toBeNull();
    expect(options).toEqual({
      sampling: "historical_sequential",
      on_data_end: "random_restart",
      iterations: 3,
      sources: { bonds: { source: "normal", mean: 4, stdev: 6.5 } },
      crypto: { mean: 15, stdev: 60 },
      outcome_thresholds: {
        failure_early_fraction: 0.25,
        failure_late_fraction: 0.75,
        thin_margin_percent: 25,
        wide_margin_percent: 200,
      },
      extra_metrics: ["taxes"],
    });
    expect(
      methodOptions({ ...DEFAULT_METHOD_SETTINGS, sampling: "moving_block", blockLength: "4" })
        .options,
    ).toEqual({ sampling: "moving_block", block_length: 4 });
  });

  it("sends the chosen retirement milestone with the surplus options", () => {
    expect(
      methodOptions({ ...DEFAULT_METHOD_SETTINGS, retirementMilestoneId: "m1" }).options,
    ).toEqual({ outcome_thresholds: { retirement_milestone_id: "m1" } });
    expect(
      methodOptions({
        ...DEFAULT_METHOD_SETTINGS,
        retirementMilestoneId: "m1",
        thinMarginPercent: "10",
      }).options,
    ).toEqual({
      outcome_thresholds: {
        thin_margin_percent: 10,
        wide_margin_percent: 200,
        retirement_milestone_id: "m1",
      },
    });
  });

  it("reports invalid settings", () => {
    expect(
      methodOptions({ ...DEFAULT_METHOD_SETTINGS, sampling: "moving_block", blockLength: "0" })
        .error,
    ).toMatch(/Block length/);
    expect(
      methodOptions({
        ...DEFAULT_METHOD_SETTINGS,
        sampling: "historical_sequential",
        onDataEnd: "random_restart",
        iterations: "11",
      }).error,
    ).toBe("Runs per start year must be a whole number from 1 to 10.");
    expect(
      methodOptions({
        ...DEFAULT_METHOD_SETTINGS,
        sources: {
          ...DEFAULT_METHOD_SETTINGS.sources,
          stocks: { normal: true, mean: "8", stdev: "-1" },
        },
      }).error,
    ).toMatch(/Stock total return/);
    expect(methodOptions({ ...DEFAULT_METHOD_SETTINGS, earlyPercent: "80" }).error).toMatch(
      /early below late/,
    );
    expect(methodOptions({ ...DEFAULT_METHOD_SETTINGS, thinMarginPercent: "300" }).error).toMatch(
      /thin margin below/,
    );
  });
});

const curves = {
  years: [2030, 2031],
  p10: [1, 2],
  p25: [2, 3],
  p50: [3, 4],
  p75: [4, 5],
  p90: [5, 6],
};
const result = {
  success_rate: 0.5,
  n_trials: 4,
  percentile_curves: curves,
  failure_analysis: [],
  median_final_net_worth: 4,
  p10_final_net_worth: 2,
  p90_final_net_worth: 6,
  sampling: "historical_sequential",
  outcome_detail: {
    failure_timing: {
      early_fraction: 1 / 3,
      late_fraction: 2 / 3,
      early: 1,
      mid: 0,
      late: 1,
      early_rate: 0.5,
      mid_rate: 0,
      late_rate: 0.5,
    },
    surplus: {
      thin_margin_percent: 25,
      wide_margin_percent: 200,
      reference_milestone_id: "r",
      reference_milestone_name: "Retirement",
      thin_margin: 0,
      moderate_margin: 1,
      wide_margin: 1,
      thin_margin_rate: 0,
      moderate_margin_rate: 0.5,
      wide_margin_rate: 0.5,
    },
    definitions: { surplus: "Successful trials by final net worth." },
  },
  metric_percentiles: { taxes: curves },
} as MonteCarloResult;

it("runs historical sequences and shows outcome detail and metric bands", async () => {
  mocks.run.mockReset().mockResolvedValue(result);
  usePlanStore.setState({
    plan: makePlan({ id: "p", name: "Plan" }),
    simulation: null,
    isSimulating: false,
  });
  useSaveStore.setState({ pending: 0 });
  render(<MonteCarloDashboard />);
  fireEvent.change(screen.getByLabelText("Sampling method"), {
    target: { value: "historical_sequential" },
  });
  expect(screen.queryByText(/Minimum block length/)).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("When history runs out"), { target: { value: "stop" } });
  fireEvent.click(screen.getByLabelText("Taxes"));
  fireEvent.click(screen.getByRole("button", { name: "Run Monte Carlo" }));
  await waitFor(() =>
    expect(mocks.run).toHaveBeenCalledWith("p", 1000, {
      block_size_min: 3,
      block_size_max: 7,
      seed: 42,
      failure_mode: "liquid_assets",
      success_targets: null,
      calibrate_to_plan: true,
      sampling: "historical_sequential",
      on_data_end: "stop",
      extra_metrics: ["taxes"],
    }),
  );
  const detail = await screen.findByTestId("outcome-detail");
  expect(detail).toHaveTextContent("Late (from 67% of the plan)");
  expect(detail).toHaveTextContent("versus net worth at Retirement");
  expect(screen.getByTestId("metric-band-taxes")).toHaveTextContent("Taxes (future dollars)");
});
