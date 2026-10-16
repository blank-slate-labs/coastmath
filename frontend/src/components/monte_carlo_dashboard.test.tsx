import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, it, expect } from "vitest";
import MonteCarloDashboard from "./monte_carlo_dashboard";
import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import type { MonteCarloResult, SimulationResult } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";
const mocks = vi.hoisted(() => ({ run: vi.fn(), trial: vi.fn() }));
const adapter = makeAdapter({ runMonteCarlo: mocks.run, runMonteCarloTrial: mocks.trial });
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
const plan = makePlan({ id: "p", name: "Original" });

it("passes seed and failure definition and ignores a run from an edited plan", async () => {
  let reject!: (error: Error) => void;
  mocks.run.mockReturnValue(
    new Promise((_, r) => {
      reject = r;
    }),
  );
  usePlanStore.setState({ plan, simulation: null });
  render(<MonteCarloDashboard />);
  fireEvent.change(screen.getByLabelText("Random seed"), { target: { value: "123" } });
  fireEvent.change(screen.getByLabelText("Failure definition"), { target: { value: "net_worth" } });
  fireEvent.click(screen.getByRole("button", { name: "Run Monte Carlo" }));
  expect(mocks.run).toHaveBeenCalledWith("p", 1000, {
    block_size_min: 3,
    block_size_max: 7,
    seed: 123,
    failure_mode: "net_worth",
    success_targets: null,
    calibrate_to_plan: true,
  });
  act(() => usePlanStore.setState({ plan: { ...plan, name: "Edited" } }));
  expect(screen.getByRole("status")).toHaveTextContent("previous run cleared");
  await act(async () => reject(new Error("Old run failed")));
  expect(screen.queryByText("Old run failed")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Run Monte Carlo" })).toBeEnabled();
});

it("waits for the forecast refresh before permitting a run", async () => {
  mocks.run.mockReset().mockRejectedValue(new Error("Test response"));
  usePlanStore.setState({ plan, simulation: null, isSimulating: true });
  render(<MonteCarloDashboard />);
  const run = screen.getByRole("button", { name: "Run Monte Carlo" });
  expect(run).toBeDisabled();
  fireEvent.click(run);
  expect(mocks.run).not.toHaveBeenCalled();
  expect(screen.getByRole("status")).toHaveTextContent("Updating forecast");
  act(() => usePlanStore.setState({ isSimulating: false }));
  expect(run).toBeEnabled();
  fireEvent.click(run);
  await screen.findByText("Test response");
});

it("blocks a run while the edit is still saving, before forecast refresh starts", async () => {
  mocks.run.mockReset();
  usePlanStore.setState({ plan, simulation: null, isSimulating: false });
  useSaveStore.setState({ pending: 1 });
  render(<MonteCarloDashboard />);
  const run = screen.getByRole("button", { name: "Run Monte Carlo" });
  expect(run).toBeDisabled();
  fireEvent.click(run);
  expect(mocks.run).not.toHaveBeenCalled();
  act(() => {
    usePlanStore.setState({ isSimulating: true });
    useSaveStore.setState({ pending: 0 });
  });
  expect(run).toBeDisabled();
  act(() => usePlanStore.setState({ isSimulating: false }));
  expect(run).toBeEnabled();
});

it("reports a current failure and enables retry", async () => {
  mocks.run.mockRejectedValue(new Error("Connection failed"));
  usePlanStore.setState({ plan, simulation: null });
  render(<MonteCarloDashboard />);
  fireEvent.click(screen.getByRole("button", { name: "Run Monte Carlo" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Connection failed"));
  expect(screen.getByRole("button", { name: "Run Monte Carlo" })).toBeEnabled();
});

it("sends explicit success targets when a terminal target or cut rule is set", async () => {
  mocks.run.mockReset().mockResolvedValue({
    success_rate: 1,
    n_trials: 10,
    percentile_curves: { years: [2030], p10: [1], p25: [1], p50: [1], p75: [1], p90: [1] },
    failure_analysis: [],
    median_final_net_worth: 1,
    p10_final_net_worth: 1,
    p90_final_net_worth: 1,
    funding_success_rate: 1,
    target_success_rate: 0.6,
    outcome_categories: [
      {
        key: "met_targets",
        label: "Met all targets",
        definition: "No funding failure, final net worth of at least $1,000,000 (nominal).",
        count: 6,
        rate: 0.6,
      },
      {
        key: "survived_below_target",
        label: "Survived below target",
        definition: "Below target.",
        count: 4,
        rate: 0.4,
      },
      {
        key: "funding_failure",
        label: "Funding failure",
        definition: "Depleted.",
        count: 0,
        rate: 0,
      },
    ],
    definitions: {
      success_rate: "Share of trials with no funding failure.",
      target_success_rate: "Share meeting every target.",
    },
  });
  usePlanStore.setState({ plan, simulation: null });
  render(<MonteCarloDashboard />);
  fireEvent.change(screen.getByLabelText("Final net worth target"), {
    target: { value: "1000000" },
  });
  fireEvent.click(screen.getByLabelText("Count flexible-spending cuts as a shortfall"));
  fireEvent.click(screen.getByRole("button", { name: "Run Monte Carlo" }));
  await waitFor(() =>
    expect(mocks.run).toHaveBeenCalledWith("p", 1000, {
      block_size_min: 3,
      block_size_max: 7,
      seed: 42,
      failure_mode: "liquid_assets",
      success_targets: { terminal_net_worth_min: 1000000, count_spending_cuts_as_shortfall: true },
      calibrate_to_plan: true,
    }),
  );
  expect(await screen.findByText("Target success rate")).toBeInTheDocument();
  expect(screen.getByText("60.0%")).toBeInTheDocument();
  const categories = screen.getByTestId("outcome-categories");
  expect(categories).toHaveTextContent("Met all targets");
  expect(categories).toHaveTextContent("6 · 60.0%");
  expect(categories).toHaveTextContent("Funding failure");
  expect(categories).toHaveTextContent("Survived below target");
});

const fundedResult: MonteCarloResult = {
  success_rate: 1,
  funding_success_rate: 1,
  n_trials: 1000,
  percentile_curves: { years: [2030], p10: [100], p25: [100], p50: [100], p75: [100], p90: [100] },
  failure_analysis: [],
  median_final_net_worth: 100,
  p10_final_net_worth: 100,
  p90_final_net_worth: 100,
};

it("sends custom block lengths and clears completed results when either bound changes", async () => {
  mocks.run.mockReset().mockResolvedValue(fundedResult);
  usePlanStore.setState({ plan, simulation: null, isSimulating: false });
  useSaveStore.setState({ pending: 0 });
  render(<MonteCarloDashboard />);
  const minimum = screen.getByLabelText("Minimum block length (years)");
  const maximum = screen.getByLabelText("Maximum block length (years)");
  expect(minimum).toHaveValue(3);
  expect(maximum).toHaveValue(7);
  fireEvent.change(minimum, { target: { value: "10" } });
  fireEvent.change(maximum, { target: { value: "12" } });
  expect(
    screen.getByText(/Block bootstrap of 10–12 consecutive historical years/),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Run Monte Carlo" }));
  await screen.findByText("Funding success rate");
  expect(mocks.run).toHaveBeenLastCalledWith(
    "p",
    1000,
    expect.objectContaining({ block_size_min: 10, block_size_max: 12 }),
  );

  for (const [input, value] of [
    [minimum, "9"],
    [maximum, "9"],
  ] as const) {
    fireEvent.change(input, { target: { value } });
    expect(screen.queryByText("Funding success rate")).not.toBeInTheDocument();
    expect(screen.getByText(/previous run cleared/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run Monte Carlo" }));
    await screen.findByText("Funding success rate");
  }
  expect(mocks.run).toHaveBeenLastCalledWith(
    "p",
    1000,
    expect.objectContaining({ block_size_min: 9, block_size_max: 9 }),
  );
  expect(screen.getByText(/Block bootstrap of 9 consecutive historical years/)).toBeInTheDocument();
});

it.each([
  ["", "7"],
  ["3", ""],
  ["0", "7"],
  ["3", "31"],
  ["-1", "7"],
  ["1.5", "7"],
  ["3", "7.5"],
  ["8", "7"],
])("retains invalid block range %s–%s and prevents a request", (minimum, maximum) => {
  mocks.run.mockReset();
  usePlanStore.setState({ plan, simulation: null, isSimulating: false });
  useSaveStore.setState({ pending: 0 });
  render(<MonteCarloDashboard />);
  const minInput = screen.getByLabelText("Minimum block length (years)");
  const maxInput = screen.getByLabelText("Maximum block length (years)");
  fireEvent.change(minInput, { target: { value: minimum } });
  fireEvent.change(maxInput, { target: { value: maximum } });
  expect(minInput).toHaveValue(minimum === "" ? null : Number(minimum));
  expect(maxInput).toHaveValue(maximum === "" ? null : Number(maximum));
  expect(screen.getByRole("alert")).toHaveTextContent(
    /Block lengths must|Minimum block length must/,
  );
  const run = screen.getByRole("button", { name: "Run Monte Carlo" });
  expect(run).toBeDisabled();
  fireEvent.click(run);
  expect(mocks.run).not.toHaveBeenCalled();
  fireEvent.change(minInput, { target: { value: "1" } });
  fireEvent.change(maxInput, { target: { value: "30" } });
  expect(run).toBeEnabled();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("keeps selected block lengths after a failed request so the same run can be retried", async () => {
  mocks.run
    .mockReset()
    .mockRejectedValueOnce(new Error("Connection failed"))
    .mockResolvedValueOnce(fundedResult);
  usePlanStore.setState({ plan, simulation: null, isSimulating: false });
  useSaveStore.setState({ pending: 0 });
  render(<MonteCarloDashboard />);
  fireEvent.change(screen.getByLabelText("Minimum block length (years)"), {
    target: { value: "1" },
  });
  fireEvent.change(screen.getByLabelText("Maximum block length (years)"), {
    target: { value: "1" },
  });
  expect(screen.getByText(/Block bootstrap of 1 consecutive historical year;/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Run Monte Carlo" }));
  await screen.findByText("Connection failed");
  expect(screen.getByLabelText("Minimum block length (years)")).toHaveValue(1);
  expect(screen.getByLabelText("Maximum block length (years)")).toHaveValue(1);
  fireEvent.click(screen.getByRole("button", { name: "Run Monte Carlo" }));
  await screen.findByText("Funding success rate");
  expect(mocks.run.mock.calls[0]).toEqual(mocks.run.mock.calls[1]);
});

it("ignores an earlier response after the plan changes and a new block range is selected", async () => {
  let resolveOld!: (value: MonteCarloResult) => void;
  let resolveNew!: (value: MonteCarloResult) => void;
  mocks.run
    .mockReset()
    .mockReturnValueOnce(
      new Promise<MonteCarloResult>((resolve) => {
        resolveOld = resolve;
      }),
    )
    .mockReturnValueOnce(
      new Promise<MonteCarloResult>((resolve) => {
        resolveNew = resolve;
      }),
    );
  usePlanStore.setState({ plan, simulation: null, isSimulating: false });
  useSaveStore.setState({ pending: 0 });
  render(<MonteCarloDashboard />);
  fireEvent.click(screen.getByRole("button", { name: "Run Monte Carlo" }));
  expect(screen.getByLabelText("Minimum block length (years)")).toBeDisabled();
  expect(screen.getByLabelText("Maximum block length (years)")).toBeDisabled();
  act(() => usePlanStore.setState({ plan: { ...plan, name: "Updated" } }));
  fireEvent.change(screen.getByLabelText("Maximum block length (years)"), {
    target: { value: "30" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Run Monte Carlo" }));
  await act(async () => resolveOld(fundedResult));
  expect(screen.queryByText("Funding success rate")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Running..." })).toBeDisabled();
  await act(async () => resolveNew(fundedResult));
  expect(await screen.findByText("Funding success rate")).toBeInTheDocument();
  expect(mocks.run).toHaveBeenLastCalledWith(
    "p",
    1000,
    expect.objectContaining({ block_size_min: 3, block_size_max: 30 }),
  );
});

it("starts the final net worth target at the saved legacy target in final-year dollars", async () => {
  mocks.run.mockReset().mockResolvedValue(fundedResult);
  const simulation = {
    yearly_snapshots: [
      { inflation_factor: 1, expenses: 1, gross_income: 1 },
      { inflation_factor: 1.5, expenses: 1, gross_income: 1 },
    ],
  } as unknown as SimulationResult;
  usePlanStore.setState({
    plan: makePlan({ ...plan, estate_settings: { legacy_target: 1_000_000 } }),
    simulation,
    isSimulating: false,
  });
  useSaveStore.setState({ pending: 0 });
  render(<MonteCarloDashboard />);
  const input = screen.getByLabelText("Final net worth target");
  expect(input).toHaveValue("1,500,000");
  fireEvent.click(screen.getByRole("button", { name: "Run Monte Carlo" }));
  await waitFor(() =>
    expect(mocks.run).toHaveBeenLastCalledWith(
      "p",
      1000,
      expect.objectContaining({
        success_targets: {
          terminal_net_worth_min: 1_500_000,
          count_spending_cuts_as_shortfall: false,
        },
      }),
    ),
  );
  // Clearing it runs without a target, as before.
  fireEvent.change(input, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Run Monte Carlo" }));
  await waitFor(() =>
    expect(mocks.run).toHaveBeenLastCalledWith(
      "p",
      1000,
      expect.objectContaining({ success_targets: null }),
    ),
  );
});

it("replays a selected trial with the run's own settings and reported seed", async () => {
  const trials = {
    success: [true, false],
    failure_year: [null, 2051],
    ending_net_worth: [500_000, -20_000],
    ending_liquid: [400_000, -20_000],
    outcome: ["met_targets", "funding_failure"],
    milestone_years: {},
    start_year: 2030,
    start_age: 60,
    sparkline_years: [2030, 2060],
    sparklines: [
      [100, 500_000],
      [100, -20_000],
    ],
  };
  mocks.run.mockReset().mockResolvedValue({
    ...fundedResult,
    n_trials: 2,
    success_rate: 0.5,
    base_seed: 987654321,
    trials,
  });
  mocks.trial.mockReset().mockReturnValue(new Promise(() => {}));
  usePlanStore.setState({ plan, simulation: null, isSimulating: false });
  useSaveStore.setState({ pending: 0 });
  render(<MonteCarloDashboard />);
  fireEvent.change(screen.getByLabelText("Random seed"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Run Monte Carlo" }));
  await screen.findByText("Explore individual trials");
  fireEvent.click(screen.getByRole("button", { name: /^Trial 2/ }));
  expect(mocks.trial).toHaveBeenCalledWith("p", 1, 2, 987654321, mocks.run.mock.calls[0][2]);
  expect(mocks.run.mock.calls[0][2]).toEqual(expect.objectContaining({ seed: null }));
  // A settings change clears the run, and with it the explorer.
  fireEvent.change(screen.getByLabelText("Random seed"), { target: { value: "5" } });
  expect(screen.queryByText("Explore individual trials")).not.toBeInTheDocument();
});

it("omits the explorer for a result without trial summaries", async () => {
  mocks.run.mockReset().mockResolvedValue(fundedResult);
  usePlanStore.setState({ plan, simulation: null, isSimulating: false });
  useSaveStore.setState({ pending: 0 });
  render(<MonteCarloDashboard />);
  fireEvent.click(screen.getByRole("button", { name: "Run Monte Carlo" }));
  await screen.findByText("Funding success rate");
  expect(screen.queryByText("Explore individual trials")).not.toBeInTheDocument();
});

it("does not run an empty plan, and names what it lacks", () => {
  mocks.run.mockReset();
  const empty = {
    yearly_snapshots: [
      { expenses: 0, gross_income: 0, accounts: {}, real_assets_value: 0, liabilities_balance: 0 },
    ],
  } as unknown as SimulationResult;
  usePlanStore.setState({ plan, simulation: empty, isSimulating: false });
  useSaveStore.setState({ pending: 0 });
  render(<MonteCarloDashboard />);
  const run = screen.getByRole("button", { name: "Run Monte Carlo" });
  expect(run).toBeDisabled();
  expect(run).toHaveAccessibleDescription("No accounts, income or expenses yet.");
  fireEvent.click(run);
  expect(mocks.run).not.toHaveBeenCalled();
});
