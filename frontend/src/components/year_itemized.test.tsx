import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import YearItemized, { requestedGap, taxSettlement } from "@/components/year_itemized";
import type { CashFlowBreakdown, NamedAmount, YearSnapshot } from "@/types/plan";
import { makeYearSnapshot } from "@/test_support/record_builders";

const flow = (extra: Partial<CashFlowBreakdown> = {}): CashFlowBreakdown => ({
  income_sources: [
    { name: "Salary", amount: 120000, category: "income" },
    { name: "Old pension", amount: 0.2, category: "income" },
  ],
  gross_income: 120000,
  tax_withheld: 24000,
  payroll_deductions: 0,
  net_pay: 96000,
  tax_delta: 2000,
  expenses: [{ name: "Living", amount: 60000, category: "essential" }],
  contributions: [
    {
      name: "Roth IRA",
      account_id: "r",
      account_name: "Roth IRA",
      amount: 3000,
      requested_amount: 7000,
      category: "contribution",
      source: "priority",
      priority_rank: 1,
    },
    {
      name: "Brokerage",
      account_id: "b",
      account_name: "Brokerage",
      amount: 10000,
      requested_amount: 10000.4,
      category: "contribution",
      source: "priority",
      priority_rank: 2,
    },
  ],
  transfers: [],
  drawdowns: [],
  ...extra,
});

const snapshot = (cashFlow: CashFlowBreakdown | null, taxes = 22000): YearSnapshot =>
  makeYearSnapshot({
    year: 2030,
    age: 40,
    gross_income: 120000,
    taxes,
    federal_tax: taxes,
    state_tax: 0,
    capital_gains_tax: 0,
    fica_tax: 0,
    expenses: 60000,
    net_cash_flow: 38000,
    accounts: {},
    real_assets_value: 0,
    liabilities_balance: 0,
    net_worth: 0,
    effective_rate: 0.18,
    marginal_rate: 0.22,
    deduction_used: "standard",
    deduction_amount: 0,
    standard_deduction: 0,
    flex_spending_reduction: 0,
    investment_growth: 0,
    milestones_triggered: [],
    transfers: [],
    cash_flow: cashFlow,
  });

const row = (amount: number, requested?: number | null): NamedAmount => ({
  name: "Row",
  amount,
  category: null,
  requested_amount: requested,
});

describe("requestedGap", () => {
  it("returns the request only when it differs from the funded amount by at least $0.50", () => {
    expect(requestedGap(row(100, 100.49))).toBeNull();
    expect(requestedGap(row(100, 100.5))).toBe(100.5);
    expect(requestedGap(row(100, 99.5))).toBe(99.5);
    expect(requestedGap(row(0, 6500))).toBe(6500);
    expect(requestedGap(row(100))).toBeNull();
    expect(requestedGap(row(100, null))).toBeNull();
  });
});

describe("taxSettlement", () => {
  it("negates the service's tax delta and hides an exact settlement's remainder", () => {
    const tax = taxSettlement(snapshot(flow()))!;
    expect(tax).toMatchObject({
      total: 22000,
      withheld: 24000,
      paidAtFiling: -2000,
      otherSettlements: 0,
      showsOtherSettlements: false,
    });
    expect(tax.equation).toBe("Total tax = withheld + paid at filing");
  });

  it("shows other settlements, signed, when withholding and filing leave a remainder", () => {
    const tax = taxSettlement(snapshot(flow({ tax_withheld: 10000, tax_delta: -9000 }), 22000))!;
    expect(tax.paidAtFiling).toBe(9000);
    expect(tax.otherSettlements).toBe(3000);
    expect(tax.showsOtherSettlements).toBe(true);
    expect(tax.equation).toBe("Total tax = withheld + paid at filing + other settlements");
    expect(
      taxSettlement(snapshot(flow({ tax_withheld: 22000.3, tax_delta: 0 }), 22000))!
        .showsOtherSettlements,
    ).toBe(false);
  });

  it("needs item-level cash flow", () => {
    expect(taxSettlement(snapshot(null))).toBeNull();
  });
});

describe("YearItemized", () => {
  it("lists the year's items, notes a request only where funding fell short of it, and reconciles the tax", () => {
    render(<YearItemized snapshot={snapshot(flow())} />);
    expect(screen.getByText("Itemized").closest("details")).not.toHaveAttribute("open");
    const groups = screen.getByRole("group", { name: "Itemized cash flow, 2030" });

    const income = within(groups).getByRole("group", { name: "Income received" });
    expect(within(income).getByText("Salary").closest(".ledger-row")).toHaveTextContent("$120,000");
    expect(within(income).queryByText("Old pension")).not.toBeInTheDocument();
    expect(within(groups).getByRole("group", { name: "Spending" })).toHaveTextContent(
      "Living$60,000",
    );
    expect(within(groups).getByRole("group", { name: "Account withdrawals" })).toHaveTextContent(
      "None. Required distributions count as income.",
    );

    const contributions = within(groups).getByRole("group", { name: "Contributions" });
    expect(within(contributions).getByText("Roth IRA").closest(".ledger-row")).toHaveTextContent(
      "Roth IRARequested $7,000$3,000",
    );
    expect(within(contributions).getByText("Brokerage").closest(".ledger-row")).toHaveTextContent(
      /^Brokerage\$10,000$/,
    );
    expect(within(contributions).getAllByText(/^Requested/)).toHaveLength(1);
    expect(within(groups).queryByRole("group", { name: "Transfers" })).not.toBeInTheDocument();

    const tax = within(groups).getByRole("group", { name: "Tax" });
    expect(within(tax).getByText("Total tax").closest(".ledger-row")).toHaveTextContent("$22,000");
    expect(within(tax).getByText("Withheld").closest(".ledger-row")).toHaveTextContent("$24,000");
    const refund = within(tax).getByText("Refund at filing").closest(".ledger-row")!;
    expect(refund).toHaveTextContent("−$2,000");
    expect(refund.querySelector(".ledger-value")).toHaveClass("is-positive");
    expect(within(tax).queryByText("Other tax settlements")).not.toBeInTheDocument();
    expect(within(tax).getByText("Total tax = withheld + paid at filing")).toBeInTheDocument();
  });

  it("shows a payment at filing, other settlements, withdrawals and transfers when the year has them", () => {
    render(
      <YearItemized
        snapshot={snapshot(
          flow({
            tax_withheld: 10000,
            tax_delta: -13000,
            drawdowns: [
              {
                name: "Brokerage",
                account_id: "b",
                account_name: "Brokerage",
                amount: 15000,
                category: null,
              },
            ],
            transfers: [
              {
                source_account_id: "t",
                target_account_id: "r",
                amount: 7000,
                source_account_name: "Traditional IRA",
                target_account_name: "Roth IRA",
              },
            ],
          }),
          22000,
        )}
      />,
    );
    const tax = screen.getByRole("group", { name: "Tax" });
    expect(within(tax).getByText("Paid at filing").closest(".ledger-row")).toHaveTextContent(
      "$13,000",
    );
    const other = within(tax).getByText("Other tax settlements").closest(".ledger-row")!;
    expect(other).toHaveTextContent("−$1,000");
    expect(other.querySelector(".ledger-value")).toHaveClass("is-positive");
    expect(
      within(tax).getByText("Total tax = withheld + paid at filing + other settlements"),
    ).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Account withdrawals" })).toHaveTextContent(
      "Brokerage$15,000",
    );
    expect(screen.getByRole("group", { name: "Transfers" })).toHaveTextContent(
      "Traditional IRA → Roth IRA$7,000",
    );
  });

  it("renders nothing for a year without item-level cash flow", () => {
    const { container } = render(<YearItemized snapshot={snapshot(null)} />);
    expect(container).toBeEmptyDOMElement();
  });
});
