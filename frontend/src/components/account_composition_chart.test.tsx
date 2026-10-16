import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AccountCompositionChart, {
  compositionSeries,
  type AccountLabel,
} from "@/components/account_composition_chart";
import type { YearSnapshot } from "@/types/plan";
import { makeYearSnapshot } from "@/test_support/record_builders";

class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", MockResizeObserver);

const year = (y: number, accounts: Record<string, number>): YearSnapshot => {
  const total = Object.values(accounts).reduce((sum, value) => sum + value, 0);
  return makeYearSnapshot({
    year: y,
    age: y - 1990,
    gross_income: 0,
    taxes: 0,
    federal_tax: 0,
    state_tax: 0,
    capital_gains_tax: 0,
    fica_tax: 0,
    expenses: 0,
    net_cash_flow: 0,
    accounts,
    real_assets_value: 0,
    liabilities_balance: 0,
    net_worth: total,
    effective_rate: 0,
    marginal_rate: 0,
    deduction_used: "standard",
    deduction_amount: 0,
    standard_deduction: 0,
    flex_spending_reduction: 0,
    investment_growth: 0,
    milestones_triggered: [],
    transfers: [],
    cash_flow: null,
  });
};

const accounts: AccountLabel[] = [
  { id: "k401", name: "401(k)" },
  { id: "roth", name: "Roth IRA" },
  { id: "cash", name: "Emergency fund" },
];

const data = [
  year(2026, { k401: 100000, roth: 20000, cash: 0, zz999999xyz: 500 }),
  year(2027, { k401: 120000, roth: 25000, cash: 0, zz999999xyz: 600 }),
  year(2028, { k401: 150000, roth: 31000, cash: 0, zz999999xyz: 700 }),
];

describe("compositionSeries", () => {
  it("stacks accounts in the plan's order, colours them by that order and names unknown IDs", () => {
    const series = compositionSeries(data, accounts);
    expect(series.map((band) => [band.name, band.color])).toEqual([
      ["401(k)", "var(--viz-1)"],
      ["Roth IRA", "var(--viz-2)"],
      ["Account zz999999", "var(--viz-3)"],
    ]);
  });

  it("folds accounts past the eighth into one neutral band", () => {
    const many = Array.from({ length: 10 }, (_, i) => ({ id: `a${i}`, name: `Account ${i + 1}` }));
    const series = compositionSeries(
      [year(2026, Object.fromEntries(many.map((a, i) => [a.id, 1000 * (i + 1)])))],
      many,
    );
    expect(series).toHaveLength(8);
    expect(series.slice(0, 7).map((band) => band.color)).toEqual(
      [1, 2, 3, 4, 5, 6, 7].map((i) => `var(--viz-${i})`),
    );
    expect(series[7]).toEqual({
      key: "other",
      name: "Other accounts",
      color: "var(--viz-context)",
      members: ["a7", "a8", "a9"],
    });
  });
});

describe("AccountCompositionChart", () => {
  it("reads out the selected year's balances, top band first, with the dollar mode", () => {
    render(
      <AccountCompositionChart
        data={data}
        accounts={accounts}
        selectedYear={2027}
        onSelectYear={() => {}}
        dollarLabel="2026 dollars"
      />,
    );
    const readout = screen.getByRole("complementary", { name: "Account balances, 2027" });
    expect(within(readout).getByText("age 37")).toBeInTheDocument();
    expect(within(readout).getByText("2026 dollars")).toBeInTheDocument();
    expect(
      within(readout).getByText("Cash & investments").closest(".ledger-row"),
    ).toHaveTextContent("$145,600");
    const rows = Array.from(readout.querySelectorAll(".ledger-row")).map((row) => row.textContent);
    expect(rows).toEqual([
      "Cash & investments$145,600",
      "Account zz999999$600",
      "Roth IRA$25,000",
      "401(k)$120,000",
    ]);
    expect(within(readout).queryByText("Emergency fund")).not.toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /stacked: \$121k in 2026 to \$182k in 2028, 2026 dollars/ }),
    ).toBeInTheDocument();
    expect(document.querySelectorAll("path[data-band]")).toHaveLength(3);
  });

  it("previews a hovered year, pins a clicked year and steps with the keyboard", () => {
    const onSelectYear = vi.fn();
    render(
      <AccountCompositionChart
        data={data}
        accounts={accounts}
        selectedYear={2026}
        onSelectYear={onSelectYear}
        dollarLabel="Future dollars"
      />,
    );
    const target = screen.getByRole("img").querySelector("[data-hover-target]")!;
    // Fallback width 720 less margins leaves a 646px plot spanning 2026–2028.
    fireEvent.click(target, { clientX: 646 });
    expect(onSelectYear).toHaveBeenLastCalledWith(2028);
    fireEvent.click(target, { clientX: 300 });
    expect(onSelectYear).toHaveBeenLastCalledWith(2027);
    fireEvent.keyDown(target, { key: "ArrowRight" });
    expect(onSelectYear).toHaveBeenLastCalledWith(2027);
    fireEvent.keyDown(target, { key: "ArrowLeft" });
    expect(onSelectYear).toHaveBeenLastCalledWith(2026);
    fireEvent.keyDown(target, { key: "End" });
    expect(onSelectYear).toHaveBeenLastCalledWith(2028);

    const move = new MouseEvent("pointermove", { bubbles: true, clientX: 646 });
    fireEvent(target, move);
    const preview = screen.getByRole("complementary", { name: "Account balances, 2028" });
    expect(preview).toHaveClass("is-preview");
    fireEvent.keyDown(target, { key: "Escape" });
    expect(screen.getByRole("complementary", { name: "Account balances, 2026" })).not.toHaveClass(
      "is-preview",
    );
  });

  it("lists each folded account under Other accounts", () => {
    const many = Array.from({ length: 9 }, (_, i) => ({ id: `a${i}`, name: `Fund ${i + 1}` }));
    render(
      <AccountCompositionChart
        data={[year(2026, Object.fromEntries(many.map((a, i) => [a.id, 1000 * (i + 1)])))]}
        accounts={many}
        selectedYear={2026}
        onSelectYear={() => {}}
        dollarLabel="Future dollars"
      />,
    );
    const readout = screen.getByRole("complementary", { name: "Account balances, 2026" });
    expect(within(readout).getByText("Other accounts").closest(".ledger-row")).toHaveTextContent(
      "$17,000",
    );
    expect(within(readout).getByText("Fund 9").closest(".ledger-row")).toHaveClass("is-sub");
    expect(within(readout).getByText("Fund 8").closest(".ledger-row")).toHaveTextContent("$8,000");
  });

  it("names what is missing when no account has a balance", () => {
    render(
      <AccountCompositionChart
        data={[year(2026, { cash: 0 })]}
        accounts={accounts}
        selectedYear={2026}
        onSelectYear={() => {}}
        dollarLabel="Future dollars"
      />,
    );
    expect(screen.getByText("No account balances.")).toBeInTheDocument();
  });
});
