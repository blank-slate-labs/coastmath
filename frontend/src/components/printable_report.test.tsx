import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import PrintableReport from "./printable_report";
import AnnualReport from "./annual_report";
import { setStorageAdapter, usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import type { SimulationResult } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

vi.mock("@/components/net_worth_chart", () => ({ default: () => <div>Net worth chart</div> }));
vi.mock("@/components/tax/tax_overview_chart", () => ({ default: () => <div>Tax chart</div> }));

const plan = makePlan({
  id: "p1",
  name: "Sample plan",
  birth_year: 1980,
  life_expectancy: 90,
  filing_status: "married_filing_jointly",
  state_code: "WA",
  assumption_curves: [
    { id: "a", curve_type: "inflation", mode: "fixed", fixed_rate: 0.025, control_points: [] },
  ],
  milestones: [{ id: "m", name: "Retirement" }],
  income_streams: [{}],
  expenses: [{}, {}],
  spouse: { birth_year: 1982, life_expectancy: 92 },
  healthcare_settings: { enabled: true, aca_enabled: true, medicare_apply_irmaa: true },
  estate_settings: {
    custom_federal_exemption_enabled: false,
    federal_estate_exemption: 15000000,
    state_estate_tax_enabled: true,
    state_estate_tax_rate: 0.2,
    state_estate_exemption: 2193000,
    heir_income_tax_rate: 0.22,
  },
  notes: "Revisit in 2027.",
});

const snap = (year: number, age: number, nw: number) => ({
  year,
  age,
  gross_income: 100000,
  taxes: 20000,
  expenses: 60000,
  net_cash_flow: 20000,
  accounts: { a: nw },
  real_assets_value: 0,
  liabilities_balance: 0,
  net_worth: nw,
  investment_growth: 70000,
  effective_rate: 0.2,
  marginal_rate: 0.22,
  federal_tax: 15000,
  state_tax: 0,
  capital_gains_tax: 0,
  fica_tax: 5000,
  tax_balance: 0,
  unfunded_expenses: 0,
  flex_spending_reduction: 0,
  transfers: [],
  milestones_triggered: [],
  cash_flow: null,
});
const simulation = {
  metadata: {
    plan_id: "p1",
    start_year: 2026,
    end_year: 2027,
    success: true,
    failure_year: null,
    warnings: ["Midyear projection: enter year-to-date income."],
    net_legacy: {
      net_legacy: 1500000,
      heir_income_tax: 50000,
      net_to_heirs_after_income_tax: 1450000,
      exclusions: ["Lifetime gifts are not modeled."],
    },
  },
  yearly_snapshots: [snap(2026, 46, 500000), snap(2027, 47, 600000)],
} as unknown as SimulationResult;

beforeEach(() => {
  usePlanStore.setState({ plan, simulation, currencyMode: "nominal", isSimulating: false });
  useSaveStore.setState({ pending: 0 });
});

it("renders the dated report with assumptions, results, table, notes and caveats", () => {
  const onClose = vi.fn();
  render(<PrintableReport onClose={onClose} now={new Date(2026, 8, 5)} />);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sample plan");
  expect(screen.getByText(/Generated September 5, 2026/)).toBeInTheDocument();
  expect(screen.getByText("Inflation").nextElementSibling).toHaveTextContent("2.5%");
  expect(screen.getByText("Stock price growth").nextElementSibling).toHaveTextContent(
    "7.0% (default)",
  );
  expect(screen.getByText("Plan is funded through the final year")).toBeInTheDocument();
  expect(
    screen.getByText(/Marketplace with premium tax credit, then Medicare with IRMAA/),
  ).toBeInTheDocument();
  expect(screen.getByText(/heirs' income tax 22.0%/)).toBeInTheDocument();
  expect(screen.getByText("$1,450,000")).toBeInTheDocument();
  const table = screen.getByRole("table", { name: "Annual projection" });
  expect(table).toHaveTextContent("2027");
  expect(table).toHaveTextContent("600,000");
  expect(screen.getByText("Revisit in 2027.")).toBeInTheDocument();
  expect(screen.getByText(/Midyear projection/)).toBeInTheDocument();
  expect(screen.getByText(/not a forecast or financial, tax or legal advice/)).toBeInTheDocument();
  expect(screen.getByText("Net worth chart")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Back to the app" }));
  expect(onClose).toHaveBeenCalled();
});

it("asks for a simulation when none exists", () => {
  usePlanStore.setState({ simulation: null } as never);
  render(<PrintableReport onClose={() => {}} />);
  expect(screen.getByText(/Run a plan before printing/)).toBeInTheDocument();
});

it("includes the saved cash yield used by the projection", () => {
  usePlanStore.setState({
    plan: makePlan({
      ...plan,
      assumption_curves: [
        {
          id: "cash",
          curve_type: "cash_yield",
          mode: "fixed",
          fixed_rate: 0.035,
          control_points: [],
        },
      ],
    }),
  });
  render(<PrintableReport onClose={() => {}} />);
  expect(screen.getByText("Cash yield").nextElementSibling).toHaveTextContent("3.5%");
});

it.each(["save", "simulation"])(
  "removes an open printable document during a pending %s and restores it when settled",
  (phase) => {
    render(<PrintableReport onClose={() => {}} />);
    expect(screen.getByRole("table", { name: "Annual projection" })).toBeInTheDocument();
    act(() => {
      if (phase === "save") useSaveStore.setState({ pending: 1 });
      else usePlanStore.setState({ isSimulating: true, plan: { ...plan, name: "Changed inputs" } });
    });
    expect(screen.getByRole("status")).toHaveTextContent("Updating projection");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Print or save as PDF" })).not.toBeInTheDocument();
    act(() => {
      useSaveStore.setState({ pending: 0 });
      usePlanStore.setState({ isSimulating: false });
    });
    const print = vi.spyOn(window, "print").mockImplementation(() => {});
    fireEvent.click(screen.getByRole("button", { name: "Print or save as PDF" }));
    expect(print).toHaveBeenCalledOnce();
    print.mockRestore();
  },
);

it("blocks downloads during saving, the expense debounce, and the request, then exports the new result", async () => {
  vi.useFakeTimers();
  let finish!: (value: SimulationResult) => void;
  const runSimulation = vi.fn(
    () =>
      new Promise<SimulationResult>((resolve) => {
        finish = resolve;
      }),
  );
  setStorageAdapter(
    makeAdapter({
      createExpense: vi.fn().mockResolvedValue({ id: "new", name: "Move", amount: 12000 }),
      runSimulation,
    }),
  );
  try {
    render(<AnnualReport />);
    act(() => useSaveStore.setState({ pending: 1 }));
    expect(screen.getByRole("button", { name: "Download JSON" })).toBeDisabled();
    await act(async () => {
      await usePlanStore.getState().addExpense("p1", { name: "Move", amount: 12000 } as never);
      useSaveStore.setState({ pending: 0 });
    });
    expect(runSimulation).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Download CSV" })).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Updating projection");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(runSimulation).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "Download JSON" })).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await act(async () => {
      finish({
        ...simulation,
        yearly_snapshots: simulation.yearly_snapshots.map((s) => ({ ...s, expenses: 72000 })),
      });
    });
    fireEvent.click(screen.getByRole("button", { name: "Cash flow" }));
    expect(screen.getByRole("table")).toHaveTextContent("72,000");
    expect(screen.getByRole("button", { name: "Download JSON" })).toBeEnabled();
  } finally {
    vi.clearAllTimers();
    vi.useRealTimers();
  }
});

it("removes the printable results after a failed recalculation", async () => {
  setStorageAdapter(
    makeAdapter({ runSimulation: vi.fn().mockRejectedValue(new Error("Simulation failed")) }),
  );
  render(<PrintableReport onClose={() => {}} />);
  await act(async () => {
    await usePlanStore.getState().runSimulation("p1");
  });
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Print or save as PDF" })).not.toBeInTheDocument();
});

describe("estate row by US coverage", () => {
  const abroad = {
    id: "r1",
    plan_id: "p1",
    state_code: null,
    local_tax: null,
    country: "FR",
    region: null,
    start_milestone_id: null,
    start_year: 2030,
  };
  const estateRow = () => screen.getByText("Estate").nextElementSibling;

  it("shows the US exemptions without a note in a US plan", () => {
    render(<PrintableReport onClose={() => {}} />);
    expect(estateRow()).toHaveTextContent(
      "Statutory federal exemption, state estate tax 20.0% above $2.2M, heirs' income tax 22.0%",
    );
    expect(
      screen.queryByText(/applies only to a death in a year you live in the US/),
    ).not.toBeInTheDocument();
  });

  it("leaves out the US exemptions in a plan with no US year", () => {
    usePlanStore.setState({ plan: makePlan({ ...plan, tax_country: "FR" }) });
    render(<PrintableReport onClose={() => {}} />);
    expect(estateRow()).toHaveTextContent(/^No US estate tax, heirs' income tax 22.0%$/);
    expect(estateRow()).not.toHaveTextContent(/exemption/);
  });

  it("keeps the US exemptions in a plan that moves abroad, with a note about US years", () => {
    usePlanStore.setState({
      plan: makePlan({ ...plan, tax_country: "US", residency_periods: [abroad] }),
    });
    render(<PrintableReport onClose={() => {}} />);
    expect(estateRow()).toHaveTextContent("Statutory federal exemption");
    expect(estateRow()).toHaveTextContent(
      /US estate tax, including the exemptions above, applies only to a death in a year you live in the US/,
    );
  });
});

describe("tax mode row by country", () => {
  const abroad = {
    id: "r1",
    plan_id: "p1",
    state_code: null,
    local_tax: null,
    country: "FR",
    region: null,
    start_milestone_id: null,
    start_year: 2030,
  };
  const taxModeRow = () => screen.getByText("Tax mode").nextElementSibling;

  it("names US brackets in a US plan", () => {
    render(<PrintableReport onClose={() => {}} />);
    expect(taxModeRow()).toHaveTextContent(
      /^Federal and state brackets \(2026 data, indexed with inflation\)$/,
    );
  });

  it("names the country's rules in a plan with no US year", () => {
    usePlanStore.setState({ plan: makePlan({ ...plan, tax_country: "FR" }) });
    render(<PrintableReport onClose={() => {}} />);
    expect(taxModeRow()).toHaveTextContent(/^France resident tax rules$/);
  });

  it("says custom rules for the user-defined country", () => {
    usePlanStore.setState({ plan: makePlan({ ...plan, tax_country: "XX" }) });
    render(<PrintableReport onClose={() => {}} />);
    expect(taxModeRow()).toHaveTextContent(/^Custom rules$/);
  });

  it("lists each country of a plan that moves, with the US tax mode for US years", () => {
    usePlanStore.setState({
      plan: makePlan({
        ...plan,
        tax_country: "US",
        tax_settings: { mode: "flat" },
        residency_periods: [abroad],
      }),
    });
    render(<PrintableReport onClose={() => {}} />);
    expect(taxModeRow()).toHaveTextContent(
      /^United States: Flat rates; France resident tax rules$/,
    );
  });
});
