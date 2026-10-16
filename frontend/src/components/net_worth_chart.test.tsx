import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import * as fs from "fs";
import * as path from "path";

import type { SimulationResult } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";
import { makeYearSnapshot } from "@/test_support/record_builders";

// ── Store mock state ──────────────────────────────────────────────

let mockStoreState: Record<string, unknown> = {};

vi.mock("@/stores/plan_store", () => ({
  usePlanStore: (selector: (s: Record<string, unknown>) => unknown) => selector(mockStoreState),
}));

// One stable storage value, as the provider memoizes it.
const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

// Mock ResizeObserver
class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", MockResizeObserver);

// ── Fixtures ──────────────────────────────────────────────────────

const simulation: SimulationResult = {
  metadata: {
    plan_id: "plan-1",
    start_year: 2024,
    end_year: 2064,
    success: true,
    failure_year: null,
    net_legacy: null,
    rmd_start_age: null,
  },
  yearly_snapshots: [
    makeYearSnapshot({
      year: 2024,
      age: 30,
      gross_income: 100000,
      calendar_year_gross_income: 200000,
      taxes: 20000,
      federal_tax: 14000,
      state_tax: 4000,
      capital_gains_tax: 0,
      fica_tax: 2000,
      expenses: 40000,
      net_cash_flow: 40000,
      accounts: {},
      net_worth: 100000,
      milestones_triggered: [],
    }),
    makeYearSnapshot({
      year: 2025,
      age: 31,
      gross_income: 103000,
      taxes: 21000,
      federal_tax: 14700,
      state_tax: 4200,
      capital_gains_tax: 0,
      fica_tax: 2100,
      expenses: 41000,
      net_cash_flow: 41000,
      accounts: {},
      net_worth: 150000,
      milestones_triggered: [],
    }),
    makeYearSnapshot({
      year: 2026,
      age: 32,
      gross_income: 106000,
      taxes: 22000,
      federal_tax: 15400,
      state_tax: 4400,
      capital_gains_tax: 0,
      fica_tax: 2200,
      expenses: 42000,
      net_cash_flow: 42000,
      accounts: {},
      net_worth: 210000,
      milestones_triggered: [],
    }),
  ],
};

const plan = makePlan({
  assumption_curves: [
    {
      id: "c1",
      plan_id: "plan-1",
      curve_type: "inflation",
      mode: "fixed",
      fixed_rate: 0.03,
      control_points: [],
    },
  ],
});

// ── Tests ─────────────────────────────────────────────────────────

describe("NetWorthChart", () => {
  it("labels the first point as a December 31 estimate and shows its actual projection start date", async () => {
    mockStoreState = {
      simulation: { ...simulation, metadata: { ...simulation.metadata, start_date: "2024-09-05" } },
      plan,
      currencyMode: "nominal",
      setCurrencyMode: vi.fn(),
    };
    const { default: NetWorthChart } = await import("./net_worth_chart");
    const { container } = render(<NetWorthChart />);
    const target = container.querySelector('rect[fill="transparent"]');
    expect(target).not.toBeNull();
    fireEvent.keyDown(target!, { key: "ArrowRight" });
    expect(screen.getByText("December 31, 2024")).toBeInTheDocument();
    expect(screen.getByText(/activity since September 5, 2024/)).toBeInTheDocument();
    expect(screen.getByText("Calendar-year gross").nextElementSibling).toHaveTextContent(
      "$200,000",
    );
    expect(screen.getByText("Full-year taxes").nextElementSibling).toHaveTextContent(
      "$20,000 · 10.0%",
    );
    expect(screen.queryByText("Start of 2024")).not.toBeInTheDocument();
  });

  it("shows one income column, with the calendar-year figure only in the partial first year", async () => {
    mockStoreState = { simulation, plan, currencyMode: "nominal", setCurrencyMode: vi.fn() };
    const { default: NetWorthChart } = await import("./net_worth_chart");
    render(<NetWorthChart />);
    fireEvent.click(screen.getByRole("button", { name: "Show data table" }));
    const table = screen.getByRole("table", { name: "Net worth by year" });
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(headers).toEqual([
      "Year",
      "Age",
      "Net worth",
      "Income",
      "Expenses",
      "Full-year taxes",
      "Cash flow",
    ]);
    const [, first, second] = within(table).getAllByRole("row");
    const income = (row: HTMLElement) => within(row).getAllByRole("cell")[3];
    expect(income(first)).toHaveTextContent("$100,000$200,000 calendar year");
    expect(income(second)).toHaveTextContent(/^\$103,000$/);
  });

  it("in controlled mode reports the chosen year instead of showing a tooltip", async () => {
    const onSelectYear = vi.fn();
    const onHoverYear = vi.fn();
    mockStoreState = { simulation, plan, currencyMode: "nominal", setCurrencyMode: vi.fn() };
    const { default: NetWorthChart } = await import("./net_worth_chart");
    const { container } = render(
      <NetWorthChart
        selectedYear={2024}
        onSelectYear={onSelectYear}
        onHoverYear={onHoverYear}
        events={[{ key: "m", year: 2025, label: "Retirement", kind: "milestone" }]}
      />,
    );
    const target = container.querySelector('rect[fill="transparent"]')!;
    fireEvent.keyDown(target, { key: "ArrowRight" });
    expect(onSelectYear).toHaveBeenCalledWith(2025);
    expect(screen.queryByText("December 31, 2024")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Retirement/ }));
    expect(onSelectYear).toHaveBeenLastCalledWith(2025);

    const scrubber = screen.getByRole("slider", { name: "Plan year" }) as HTMLInputElement;
    expect(scrubber.value).toBe("2024");
    fireEvent.change(scrubber, { target: { value: "2026" } });
    expect(onSelectYear).toHaveBeenLastCalledWith(2026);
  });

  it("names the currency modes in dollars for USD plans and as money in other currencies", async () => {
    mockStoreState = { simulation, plan, currencyMode: "nominal", setCurrencyMode: vi.fn() };
    const { default: NetWorthChart } = await import("./net_worth_chart");
    const { setDisplayCurrency } = await import("@/utils/format");
    const view = render(<NetWorthChart />);
    expect(screen.getByRole("button", { name: "Future dollars" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Today's $" })).toBeInTheDocument();
    view.unmount();
    setDisplayCurrency("EUR");
    try {
      render(<NetWorthChart />);
      expect(screen.getByRole("button", { name: "Future (nominal)" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Today's money" })).toBeInTheDocument();
      expect(screen.getByText("About amount display")).toBeInTheDocument();
    } finally {
      setDisplayCurrency(null);
    }
  });

  it("starts the curve at the actual balance on the projection start date", async () => {
    mockStoreState = {
      simulation: {
        ...simulation,
        initial_snapshot: {
          as_of: "2024-09-05",
          accounts: {},
          real_assets_value: 0,
          liabilities_balance: 0,
          net_worth: 80000,
        },
        metadata: { ...simulation.metadata, start_date: "2024-09-05", first_year_fraction: 0.32 },
      },
      plan,
      currencyMode: "nominal",
      setCurrencyMode: vi.fn(),
    };
    const { default: NetWorthChart } = await import("./net_worth_chart");
    render(<NetWorthChart />);
    expect(screen.getByText("$80k")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /\$80k growing to \$210k/ })).toBeInTheDocument();
  });

  beforeEach(() => {
    mockStoreState = {
      simulation: null,
      plan: null,
      currencyMode: "nominal",
      setCurrencyMode: vi.fn(),
    };
  });

  it('renders "No simulation data" when simulation is null', async () => {
    // Dynamic import to pick up mock state
    const { default: NetWorthChart } = await import("./net_worth_chart");
    render(<NetWorthChart />);

    expect(screen.getByText("No projection yet.")).toBeInTheDocument();
  });

  it("renders SVG with path when simulation data exists", async () => {
    mockStoreState = {
      simulation,
      plan,
      currencyMode: "nominal",
      setCurrencyMode: vi.fn(),
    };

    const { default: NetWorthChart } = await import("./net_worth_chart");
    const { container } = render(<NetWorthChart />);

    expect(screen.queryByText("No projection yet.")).not.toBeInTheDocument();
    expect(screen.getByText("Net worth")).toBeInTheDocument();
    expect(container.querySelector("svg path")).toBeInTheDocument();
  });

  it("does not use D3 DOM manipulation (d3.select / d3.append)", () => {
    const source = fs.readFileSync(path.resolve(__dirname, "./net_worth_chart.tsx"), "utf-8");

    expect(source).not.toMatch(/d3\.select/);
    expect(source).not.toMatch(/d3\.append/);
    expect(source).not.toMatch(/\.select\s*\(/);
    expect(source).not.toMatch(/\.append\s*\(\s*["']/);
  });
});
