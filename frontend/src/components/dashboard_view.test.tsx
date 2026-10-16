import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { usePlanStore } from "@/stores/plan_store";
import type { Account, SimulationResult, YearSnapshot } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";
import { makeYearSnapshot } from "@/test_support/record_builders";

// One stable storage value, as the provider memoizes it.
const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
const listAccounts = adapter.listAccounts;

class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", MockResizeObserver);

const year = (y: number, netWorth: number, extra: Partial<YearSnapshot> = {}): YearSnapshot =>
  makeYearSnapshot({
    year: y,
    age: y - 1990,
    gross_income: 100000,
    taxes: 20000,
    federal_tax: 15000,
    state_tax: 3000,
    capital_gains_tax: 0,
    fica_tax: 2000,
    expenses: 50000,
    net_cash_flow: 30000,
    accounts: { a: netWorth },
    real_assets_value: 0,
    liabilities_balance: 0,
    net_worth: netWorth,
    effective_rate: 0.2,
    marginal_rate: 0.22,
    deduction_used: "standard",
    deduction_amount: 30000,
    standard_deduction: 30000,
    flex_spending_reduction: 0,
    investment_growth: 5000,
    milestones_triggered: [],
    transfers: [],
    cash_flow: {
      income_sources: [{ name: "Salary", amount: 100000, category: "income" }],
      gross_income: 100000,
      tax_withheld: 20000,
      payroll_deductions: 0,
      net_pay: 80000,
      tax_delta: 0,
      expenses: [{ name: "Living", amount: 50000, category: "essential" }],
      contributions: [
        {
          name: "Brokerage",
          account_name: "Brokerage",
          amount: 30000,
          category: "contribution",
          source: "priority",
          priority_rank: 1,
        },
      ],
      transfers: [],
      drawdowns: [],
      graph: {
        nodes: [
          { id: "hub:gross", name: "Gross income", group: "hub" },
          { id: "hub:cash", name: "After-tax cash", group: "hub" },
          { id: "income:Salary", name: "Salary", group: "income" },
          { id: "tax:taxes", name: "Taxes", group: "tax" },
          { id: "expense:Living", name: "Living", group: "spending" },
          { id: "to:a", name: "Brokerage", group: "saving" },
        ],
        links: [
          { source: "income:Salary", target: "hub:gross", amount: 100000 },
          { source: "hub:gross", target: "tax:taxes", amount: 20000 },
          { source: "hub:gross", target: "hub:cash", amount: 80000 },
          { source: "hub:cash", target: "expense:Living", amount: 50000 },
          { source: "hub:cash", target: "to:a", amount: 30000 },
        ],
      },
    },
    ...extra,
  });

const plan = makePlan({
  id: "p1",
  user_id: "u",
  name: "Plan",
  birth_year: 1990,
  life_expectancy: 90,
  created_at: "2026-01-01",
});

const simulation = {
  initial_snapshot: {
    as_of: "2026-09-06",
    accounts: { a: 90000 },
    real_assets_value: 0,
    liabilities_balance: 0,
    net_worth: 90000,
  },
  metadata: {
    plan_id: "p1",
    start_year: 2026,
    end_year: 2028,
    success: true,
    failure_year: null,
    net_legacy: null,
    rmd_start_age: null,
    start_date: "2026-09-06",
    first_year_fraction: 0.32,
    warnings: ["Inflation defaults to 3%."],
    milestone_outcomes: [{ id: "m1", name: "Retirement", trigger_type: "age", year: 2028 }],
  },
  yearly_snapshots: [year(2026, 100000), year(2027, 140000), year(2028, 190000)],
} as unknown as SimulationResult;

beforeEach(() => {
  vi.mocked(listAccounts).mockResolvedValue([]);
  adapter.listProgressPoints.mockResolvedValue([]);
  usePlanStore.setState({
    plan,
    plans: [plan],
    simulation,
    currencyMode: "nominal",
    baselineSimulation: null,
    compareMode: false,
  });
});

describe("DashboardView", () => {
  it("names what an empty plan lacks instead of drawing rows of $0", async () => {
    const zero = (y: number) =>
      year(y, 0, { gross_income: 0, expenses: 0, net_cash_flow: 0, accounts: {} });
    usePlanStore.setState({
      simulation: { ...simulation, yearly_snapshots: [zero(2026), zero(2027)] } as SimulationResult,
    });
    const { default: DashboardView } = await import("./dashboard_view");
    render(<DashboardView onEditAllocation={() => {}} />);
    expect(screen.getByRole("status")).toHaveTextContent("No accounts, income or expenses yet.");
    expect(
      screen.queryByRole("complementary", { name: /Year 2026 details/ }),
    ).not.toBeInTheDocument();
  });

  it("uses plan-scoped account names and updates projected balances with year and dollar mode", async () => {
    vi.mocked(listAccounts).mockResolvedValue([
      { id: "a", name: "Retirement brokerage", balance: 1 } as Account,
    ]);
    const { default: DashboardView } = await import("./dashboard_view");
    render(<DashboardView onEditAllocation={() => {}} />);
    const ledger = screen.getByRole("complementary", { name: /Year 2026 details/ });
    const account = await within(ledger).findByText("Retirement brokerage");
    expect(account.closest(".ledger-row")).toHaveTextContent("$100,000");
    expect(listAccounts).toHaveBeenCalledWith("p1");
    fireEvent.click(screen.getByRole("button", { name: "Next year" }));
    expect(account.closest(".ledger-row")).toHaveTextContent("$140,000");
    act(() => usePlanStore.setState({ currencyMode: "inflation_adjusted" }));
    expect(account.closest(".ledger-row")).toHaveTextContent("$135,922");
    expect(within(ledger).getByText("2026 dollars")).toBeInTheDocument();
  });

  it("opens on the first year and moves every panel to the year chosen on the chart", async () => {
    const { default: DashboardView } = await import("./dashboard_view");
    render(<DashboardView onEditAllocation={() => {}} />);

    const ledger = screen.getByRole("complementary", { name: /Year 2026 details/ });
    expect(within(ledger).getByText("2026")).toBeInTheDocument();
    expect(within(ledger).getByText("Change").closest(".ledger-row")).toHaveTextContent("+$10,000");
    // The partial year is stated once, in the year panel; the diagram's subtitle does not repeat it.
    expect(screen.getByText(/^2026 · age 36$/)).toBeInTheDocument();
    expect(screen.getByText(/Sep 6 – Dec 31 · 32% of year/)).toBeInTheDocument();
    expect(screen.getByText("Model assumptions and limitations (1)")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Retirement/ }));
    expect(screen.getByRole("complementary", { name: /Year 2028 details/ })).toBeInTheDocument();
    expect(screen.getByText(/^2028 · age 38$/)).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Plan year" })).toHaveValue("2028");
    expect(screen.getByRole("slider", { name: "Age", hidden: true })).toHaveAttribute(
      "aria-valuetext",
      "Age 38, 2028",
    );
    expect(
      screen.queryByRole("slider", { name: "Cash flow year", hidden: true }),
    ).not.toBeInTheDocument();
  });

  it("previews a hovered chip in the ledger without moving the pinned year", async () => {
    const { default: DashboardView } = await import("./dashboard_view");
    render(<DashboardView onEditAllocation={() => {}} />);
    const chip = screen.getByRole("button", { name: /Retirement/ });
    fireEvent.pointerEnter(chip);
    expect(screen.getByRole("complementary", { name: /Year 2028 details/ })).toHaveClass(
      "is-preview",
    );
    fireEvent.pointerLeave(chip);
    expect(screen.getByRole("complementary", { name: /Year 2026 details/ })).not.toHaveClass(
      "is-preview",
    );
    expect(screen.getByRole("slider", { name: "Plan year" })).toHaveValue("2026");
  });

  it("steps the year with the ledger arrows", async () => {
    const { default: DashboardView } = await import("./dashboard_view");
    render(<DashboardView onEditAllocation={() => {}} />);
    expect(screen.getByRole("button", { name: "Previous year" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next year" }));
    expect(screen.getByRole("complementary", { name: /Year 2027 details/ })).toBeInTheDocument();
  });

  it("scrubs cash flow through retirement from the pinned age bar and synchronizes the other year controls", async () => {
    const retired = {
      ...simulation.yearly_snapshots[2].cash_flow!,
      income_sources: [],
      gross_income: 0,
      net_pay: 0,
      tax_withheld: 0,
      contributions: [],
      drawdowns: [{ name: "Retirement savings", amount: 50000, category: null }],
      graph: {
        nodes: [
          { id: "hub:cash", name: "After-tax cash", group: "hub" as const },
          { id: "from:a", name: "Retirement savings", group: "saving" as const },
          { id: "expense:Living", name: "Living", group: "spending" as const },
        ],
        links: [
          { source: "from:a", target: "hub:cash", amount: 50000 },
          { source: "hub:cash", target: "expense:Living", amount: 50000 },
        ],
      },
    };
    usePlanStore.setState({
      simulation: {
        ...simulation,
        yearly_snapshots: [
          ...simulation.yearly_snapshots.slice(0, 2),
          year(2028, 190000, { cash_flow: retired }),
        ],
      },
    });
    const { default: DashboardView } = await import("./dashboard_view");
    render(<DashboardView onEditAllocation={() => {}} />);
    const slider = screen.getByRole("slider", { name: "Age", hidden: true });
    expect(slider).toHaveAttribute("aria-valuetext", "Age 36, 2026");
    expect(screen.getByRole("button", { name: "Previous age", hidden: true })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "List" }));
    fireEvent.change(slider, { target: { value: "2" } });
    expect(screen.getByRole("slider", { name: "Plan year" })).toHaveValue("2028");
    expect(screen.getByRole("complementary", { name: /Year 2028 details/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next age", hidden: true })).toBeDisabled();
    const flows = screen.getByLabelText("Cash flows for 2028");
    expect(within(flows).getByText("Retirement savings")).toBeInTheDocument();
    expect(within(flows).queryByText("Salary")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Previous age", hidden: true }));
    expect(slider).toHaveAttribute("aria-valuetext", "Age 37, 2027");
    expect(screen.getByText(/^2027 · age 37$/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("slider", { name: "Plan year" }), {
      target: { value: "2026" },
    });
    expect(slider).toHaveValue("0");
  });

  it("uses available snapshots, shows missing breakdowns, and resets a shortened horizon", async () => {
    usePlanStore.setState({
      simulation: {
        ...simulation,
        yearly_snapshots: [simulation.yearly_snapshots[0], year(2028, 190000, { cash_flow: null })],
      },
    });
    const { default: DashboardView } = await import("./dashboard_view");
    render(<DashboardView onEditAllocation={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Next age", hidden: true }));
    expect(screen.getByText("No cash flow breakdown available for 2028.")).toBeInTheDocument();
    expect(screen.queryByText("Itemized")).not.toBeInTheDocument();
    act(() =>
      usePlanStore.setState({
        simulation: { ...simulation, yearly_snapshots: [simulation.yearly_snapshots[0]] },
      }),
    );
    expect(screen.getByRole("slider", { name: "Age", hidden: true })).toBeDisabled();
    expect(screen.getByRole("slider", { name: "Age", hidden: true })).toHaveAttribute(
      "aria-valuetext",
      "Age 36, 2026",
    );
    expect(screen.getByRole("button", { name: "Previous age", hidden: true })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next age", hidden: true })).toBeDisabled();
  });

  it("itemizes the selected year's cash flow under the diagram in nominal dollars", async () => {
    const { default: DashboardView } = await import("./dashboard_view");
    render(<DashboardView onEditAllocation={() => {}} />);
    expect(screen.getByRole("group", { name: "Itemized cash flow, 2026" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next year" }));
    act(() => usePlanStore.setState({ currencyMode: "inflation_adjusted" }));
    const itemized = screen.getByRole("group", { name: "Itemized cash flow, 2027" });
    expect(within(itemized).getByRole("group", { name: "Income received" })).toHaveTextContent(
      "Salary$100,000",
    );
    expect(within(itemized).getByRole("group", { name: "Tax" })).toHaveTextContent(
      "Total tax$20,000Withheld$20,000Paid at filing$0",
    );
  });

  it("asks for earlier-year inputs to replace the estimate when the opening year was imputed", async () => {
    const midyear = {
      ...simulation,
      metadata: {
        ...simulation.metadata,
        warnings: [
          "Midyear projection: income and tax before the start date are estimated pro rata.",
        ],
      },
    };
    usePlanStore.setState({
      simulation: {
        ...midyear,
        yearly_snapshots: [
          year(2026, 100000, { post_start_taxes: 6400, warnings: ["ytd_imputed_pro_rata"] }),
          ...simulation.yearly_snapshots.slice(1),
        ],
      },
    });
    const { default: DashboardView } = await import("./dashboard_view");
    const { unmount } = render(<DashboardView onEditAllocation={() => {}} />);
    const notice = screen.getByRole("complementary", { name: "Review earlier tax-year inputs" });
    expect(notice).toHaveTextContent(
      "Enter earlier income and tax paid to replace the pro-rata estimate.",
    );
    expect(within(notice).getByRole("button", { name: "Review tax history" })).toBeInTheDocument();
    unmount();
    // Nothing imputed: the zero-history wording stays.
    usePlanStore.setState({ simulation: midyear });
    render(<DashboardView onEditAllocation={() => {}} />);
    expect(
      screen.getByRole("complementary", { name: "Review earlier tax-year inputs" }),
    ).toHaveTextContent("Enter earlier income and tax paid; missing history is zero.");
  });

  it("draws account composition once opened, sharing the selected year and dollar mode with the hero", async () => {
    vi.mocked(listAccounts).mockResolvedValue([
      { id: "a", name: "Retirement brokerage", balance: 1 } as Account,
    ]);
    const { default: DashboardView } = await import("./dashboard_view");
    render(<DashboardView onEditAllocation={() => {}} />);
    const card = screen.getByText("Where the money sits").closest("details")!;
    expect(
      screen.queryByRole("complementary", { name: /Account balances/ }),
    ).not.toBeInTheDocument();
    card.open = true;
    fireEvent(card, new Event("toggle"));

    const readout = await screen.findByRole("complementary", { name: "Account balances, 2026" });
    expect(
      (await within(readout).findByText("Retirement brokerage")).closest(".ledger-row"),
    ).toHaveTextContent("$100,000");
    fireEvent.click(screen.getByRole("button", { name: "Next year" }));
    expect(readout).toHaveAccessibleName("Account balances, 2027");
    act(() => usePlanStore.setState({ currencyMode: "inflation_adjusted" }));
    expect(
      within(readout).getByText("Retirement brokerage").closest(".ledger-row"),
    ).toHaveTextContent("$135,922");
    expect(within(readout).getByText("2026 dollars")).toBeInTheDocument();

    const chart = screen.getByRole("img", { name: /^Year-end balance of each account/ });
    fireEvent.keyDown(chart.querySelector("[data-hover-target]")!, { key: "ArrowRight" });
    expect(screen.getByRole("complementary", { name: /Year 2028 details/ })).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Plan year" })).toHaveValue("2028");
    expect(readout).toHaveAccessibleName("Account balances, 2028");
  });
});
