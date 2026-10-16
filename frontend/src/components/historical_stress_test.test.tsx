import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { vi, it, expect } from "vitest";
import HistoricalStressTest from "./historical_stress_test";
import { usePlanStore } from "@/stores/plan_store";
import type { SimulationResult } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";
const mocks = vi.hoisted(() => ({ run: vi.fn(), runScenario: vi.fn() }));
const adapter = makeAdapter({ runStressTest: mocks.run, runScenarioStressTest: mocks.runScenario });
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
it("runs the selected historical year and discards an old request when the scenario changes", async () => {
  let reject!: (value: Error) => void;
  mocks.run.mockReturnValue(
    new Promise((_, r) => {
      reject = r;
    }),
  );
  usePlanStore.setState({ plan: makePlan({ id: "p" }), simulation: null });
  render(<HistoricalStressTest />);
  fireEvent.click(screen.getByRole("button", { name: "Run Stress Test" }));
  expect(mocks.run).toHaveBeenCalledWith("p", 1966);
  fireEvent.change(screen.getByLabelText("Stress scenario"), { target: { value: "custom" } });
  fireEvent.change(screen.getByLabelText("Historical start year"), { target: { value: "1987.5" } });
  expect(screen.getByRole("button", { name: "Run Stress Test" })).toBeDisabled();
  await act(async () => reject(new Error("Old request failed")));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
it("reports minimum annual balances and compares the same year with the steady forecast", async () => {
  const snapshots = [
    { year: 2026, age: 36, net_worth: 100000, accounts: { cash: 50000 } },
    { year: 2027, age: 37, net_worth: 80000, accounts: { cash: 20000 } },
  ];
  mocks.run.mockResolvedValue({
    metadata: { historical_start_year: 1966, years_used: [1966, 1967], wrapped: false },
    simulation_result: { metadata: { success: true }, yearly_snapshots: snapshots },
  });
  usePlanStore.setState({
    plan: makePlan({ id: "p" }),
    simulation: {
      yearly_snapshots: snapshots.map((s) => ({ ...s, net_worth: 150000, expenses: 40000 })),
    } as unknown as SimulationResult,
  });
  render(<HistoricalStressTest />);
  fireEvent.click(screen.getByRole("button", { name: "Run Stress Test" }));
  expect(await screen.findByText(/Lowest year-end net worth/)).toHaveTextContent("$80,000");
  expect(screen.getByText(/Lowest year-end cash/)).toHaveTextContent("$20,000");
  expect(screen.getByText(/below the steady-return forecast/)).toHaveTextContent(
    "2027 net worth, below the steady-return forecast: -$70k",
  );
  expect(screen.queryByText(/intra-year/)).toBeNull();
});
it("compares a replay with the forecast in start-year dollars, each by its own inflation", async () => {
  // The replay's inflation doubled prices; the forecast's raised them half as much.
  const replay = [
    { year: 2026, age: 36, net_worth: 100000, accounts: { cash: 100000 }, inflation_factor: 1 },
    { year: 2027, age: 37, net_worth: 400000, accounts: { cash: 400000 }, inflation_factor: 2 },
  ];
  mocks.run.mockResolvedValue({
    metadata: { historical_start_year: 1966, years_used: [1966, 1967], wrapped: false },
    simulation_result: { metadata: { success: true }, yearly_snapshots: replay },
  });
  usePlanStore.setState({
    plan: makePlan({ id: "p" }),
    simulation: {
      yearly_snapshots: replay.map((s) => ({
        ...s,
        net_worth: 150000,
        expenses: 40000,
        inflation_factor: s.year === 2027 ? 1.5 : 1,
      })),
    } as unknown as SimulationResult,
  });
  render(<HistoricalStressTest />);
  fireEvent.click(screen.getByRole("button", { name: "Run Stress Test" }));
  // $400k / 2 − $150k / 1.5 = +$100k; nominal would read +$250k.
  expect(await screen.findByText(/above the steady-return forecast/)).toHaveTextContent("+$100k");
  // Net worth and liquid lows are the same figure here, so only one line states it.
  expect(screen.queryByText(/Lowest year-end cash/)).toBeNull();
});
it("groups historical and hypothetical scenarios and sends preset parameters", async () => {
  const snapshots = [{ year: 2027, age: 37, net_worth: 90000, accounts: { cash: 30000 } }];
  mocks.runScenario.mockResolvedValue({
    metadata: {
      preset: "tech_bust",
      start_year: 2027,
      person: "spouse",
      months_without_pay: 9,
      resume_percent: 70,
      stock_drop_percent: 40,
      child_annual_cost: null,
      child_cost_years: null,
    },
    simulation_result: { metadata: { success: true }, yearly_snapshots: snapshots },
  });
  usePlanStore.setState({
    plan: makePlan({ id: "p", spouse: { name: "Sam" } }),
    simulation: {
      metadata: { start_year: 2026 },
      yearly_snapshots: [],
    } as unknown as SimulationResult,
  });
  render(<HistoricalStressTest />);
  const select = screen.getByLabelText("Stress scenario");
  const groups = within(select).getAllByRole("group");
  expect(groups.map((g) => g.getAttribute("label"))).toEqual(["Historical", "Hypothetical"]);
  expect(
    within(groups[1])
      .getAllByRole("option")
      .map((o) => o.textContent),
  ).toEqual([
    "Job loss",
    "Market crash",
    "Market downturn",
    "Tech bust: job loss + crash",
    "New child",
  ]);

  fireEvent.change(select, { target: { value: "tech_bust" } });
  expect(screen.getByLabelText("Start year")).toHaveValue(2026);
  expect(screen.queryByLabelText("Annual child cost")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Start year"), { target: { value: "2027" } });
  fireEvent.change(screen.getByLabelText("Person"), { target: { value: "spouse" } });
  fireEvent.change(screen.getByLabelText("Months without pay"), { target: { value: "9" } });
  fireEvent.change(screen.getByLabelText("New pay percent"), { target: { value: "70" } });
  fireEvent.change(screen.getByLabelText("Stock drop percent"), { target: { value: "40" } });
  fireEvent.click(screen.getByRole("button", { name: "Run Stress Test" }));
  expect(mocks.runScenario).toHaveBeenCalledWith("p", {
    preset: "tech_bust",
    start_year: 2027,
    person: "spouse",
    months_without_pay: 9,
    resume_percent: 70,
    stock_drop_percent: 40,
  });
  expect(await screen.findByText("Tech bust: job loss + crash")).toBeInTheDocument();
  expect(screen.getByText("Stress scenario")).toBeInTheDocument();

  fireEvent.change(select, { target: { value: "new_child" } });
  expect(screen.queryByLabelText("Months without pay")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Annual child cost"), { target: { value: "" } });
  expect(screen.getByRole("button", { name: "Run Stress Test" })).toBeDisabled();
});

const downturnSnapshots = [{ year: 2027, age: 37, net_worth: 90000, accounts: { cash: 30000 } }];
const downturnPath = [
  {
    year: 2027,
    stock_return: Math.pow(0.55, 1 / 3) - 1,
    bond_return: 0.04,
    inflation: 0.025,
    phase: "downturn",
  },
  {
    year: 2028,
    stock_return: Math.pow(0.55, 1 / 3) - 1,
    bond_return: 0.04,
    inflation: 0.025,
    phase: "downturn",
  },
  {
    year: 2029,
    stock_return: Math.pow(0.55, 1 / 3) - 1,
    bond_return: 0.04,
    inflation: 0.025,
    phase: "downturn",
  },
  {
    year: 2030,
    stock_return: 1 / 0.55 - 1,
    bond_return: 0.04,
    inflation: 0.025,
    phase: "recovery",
  },
];
function renderDownturn() {
  usePlanStore.setState({
    plan: makePlan({ id: "p" }),
    simulation: {
      metadata: { start_year: 2026 },
      yearly_snapshots: [],
    } as unknown as SimulationResult,
  });
  render(<HistoricalStressTest />);
  fireEvent.change(screen.getByLabelText("Stress scenario"), { target: { value: "downturn" } });
  return screen.getByRole("button", { name: "Run Stress Test" });
}
it("fills downturn fields from quick shapes and omits blank bond and inflation", async () => {
  mocks.runScenario.mockReset();
  mocks.runScenario.mockResolvedValue({
    metadata: {
      preset: "downturn",
      start_year: 2027,
      person: null,
      months_without_pay: null,
      resume_percent: null,
      stock_drop_percent: 45,
      child_annual_cost: null,
      child_cost_years: null,
      downturn_years: 3,
      recovery_years: 1,
      bond_return_percent: null,
      inflation_percent: null,
      downturn_path: downturnPath,
    },
    simulation_result: { metadata: { success: true }, yearly_snapshots: downturnSnapshots },
  });
  const run = renderDownturn();
  expect(screen.queryByLabelText("Stock drop percent")).not.toBeInTheDocument();
  expect(
    screen.getByText("Blank bond return or inflation uses the plan's assumption."),
  ).toBeInTheDocument();
  const shapes = within(screen.getByRole("group", { name: "Downturn shapes" }));
  expect(shapes.getByRole("button", { name: "Three tough years" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  fireEvent.click(shapes.getByRole("button", { name: "Stagflation" }));
  expect(screen.getByLabelText("Years of decline")).toHaveValue(5);
  expect(screen.getByLabelText("Total stock decline percent")).toHaveValue(25);
  expect(screen.getByLabelText("Recovery years")).toHaveValue(0);
  expect(screen.getByLabelText("Bond return percent")).toHaveValue(-3);
  expect(screen.getByLabelText("Inflation percent")).toHaveValue(8);
  expect(shapes.getByRole("button", { name: "Stagflation" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  fireEvent.click(run);
  expect(mocks.runScenario).toHaveBeenLastCalledWith("p", {
    preset: "downturn",
    start_year: 2026,
    stock_drop_percent: 25,
    downturn_years: 5,
    recovery_years: 0,
    bond_return_percent: -3,
    inflation_percent: 8,
  });

  fireEvent.click(shapes.getByRole("button", { name: "Lost decade" }));
  expect(screen.getByLabelText("Bond return percent")).toHaveValue(null);
  fireEvent.change(screen.getByLabelText("Start year"), { target: { value: "2027" } });
  fireEvent.change(screen.getByLabelText("Years of decline"), { target: { value: "3" } });
  fireEvent.change(screen.getByLabelText("Total stock decline percent"), {
    target: { value: "45" },
  });
  fireEvent.change(screen.getByLabelText("Recovery years"), { target: { value: "1" } });
  expect(
    shapes.getAllByRole("button").every((b) => b.getAttribute("aria-pressed") === "false"),
  ).toBe(true);
  fireEvent.click(run);
  expect(mocks.runScenario).toHaveBeenLastCalledWith("p", {
    preset: "downturn",
    start_year: 2027,
    stock_drop_percent: 45,
    downturn_years: 3,
    recovery_years: 1,
  });

  const chart = await screen.findByRole("img", {
    name: /Stock index from 100 to 55 at the low, 100 after 2030/,
  });
  expect(chart.querySelectorAll("path")).toHaveLength(4);
  expect(screen.getByText("Decline")).toBeInTheDocument();
  expect(screen.getByText("Recovery")).toBeInTheDocument();
  expect(screen.getByText("Pre-downturn level")).toBeInTheDocument();
  expect(screen.getByText("Market downturn", { selector: "span" })).toBeInTheDocument();
});
it("disables Run with an inline message when a downturn field is out of range", () => {
  const run = renderDownturn();
  const cases: [string, string, RegExp][] = [
    ["Years of decline", "11", /Years of decline/],
    ["Years of decline", "2.5", /Years of decline/],
    ["Total stock decline percent", "95", /Total stock decline/],
    ["Recovery years", "", /Recovery years/],
    ["Bond return percent", "60", /Bond return/],
    ["Inflation percent", "-11", /Inflation/],
    ["Start year", "", /Start year/],
  ];
  for (const [field, value, message] of cases) {
    fireEvent.click(screen.getByRole("button", { name: "Three tough years" }));
    fireEvent.change(screen.getByLabelText("Start year"), { target: { value: "2026" } });
    fireEvent.change(screen.getByLabelText(field), { target: { value } });
    expect(run).toBeDisabled();
    expect(run).toHaveAccessibleDescription(message);
  }
  fireEvent.change(screen.getByLabelText("Start year"), { target: { value: "2026" } });
  expect(run).toBeEnabled();
  expect(document.getElementById("downturn-error")).toBeNull();
});
it("draws a decline-only path without a recovery legend and leaves other presets without a path chart", async () => {
  mocks.runScenario.mockReset();
  mocks.runScenario
    .mockResolvedValueOnce({
      metadata: {
        preset: "downturn",
        start_year: 2027,
        person: null,
        months_without_pay: null,
        resume_percent: null,
        stock_drop_percent: 45,
        child_annual_cost: null,
        child_cost_years: null,
        downturn_path: downturnPath.slice(0, 3),
      },
      simulation_result: { metadata: { success: true }, yearly_snapshots: downturnSnapshots },
    })
    .mockResolvedValueOnce({
      metadata: {
        preset: "market_crash",
        start_year: 2026,
        person: null,
        months_without_pay: null,
        resume_percent: null,
        stock_drop_percent: 35,
        child_annual_cost: null,
        child_cost_years: null,
      },
      simulation_result: { metadata: { success: true }, yearly_snapshots: downturnSnapshots },
    });
  const run = renderDownturn();
  fireEvent.click(run);
  expect(
    await screen.findByRole("img", { name: /from 100 to 55 at the low, 55 after 2029/ }),
  ).toBeInTheDocument();
  expect(screen.queryByText("Recovery")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Stress scenario"), { target: { value: "market_crash" } });
  expect(screen.queryByLabelText("Years of decline")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Run Stress Test" }));
  expect(mocks.runScenario).toHaveBeenLastCalledWith("p", {
    preset: "market_crash",
    start_year: 2026,
    stock_drop_percent: 35,
  });
  expect(await screen.findByText("Market crash", { selector: "span" })).toBeInTheDocument();
  expect(screen.queryByRole("img", { name: /Stock index/ })).not.toBeInTheDocument();
});

it("waits for spending and a way to fund it before a stress test can run", () => {
  usePlanStore.setState({
    plan: makePlan({ id: "p" }),
    simulation: {
      metadata: { start_year: 2026 },
      yearly_snapshots: [
        {
          year: 2026,
          age: 36,
          net_worth: 0,
          expenses: 0,
          gross_income: 0,
          accounts: {},
          real_assets_value: 0,
          liabilities_balance: 0,
        },
      ],
    } as unknown as SimulationResult,
  });
  render(<HistoricalStressTest />);
  expect(screen.getByRole("button", { name: "Run Stress Test" })).toBeDisabled();
  expect(screen.getByText("No accounts, income or expenses yet.")).toBeInTheDocument();
});
