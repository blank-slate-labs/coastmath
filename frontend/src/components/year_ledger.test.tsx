import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import YearLedger, { usedTaxLines, usesEarningsTest } from "./year_ledger";
import type { YearSnapshot } from "@/types/plan";
import { makeYearSnapshot } from "@/test_support/record_builders";
import { adjustTimeline } from "@/utils/currency";

const snapshot = (overrides: Partial<YearSnapshot>): YearSnapshot =>
  makeYearSnapshot({
    year: 2027,
    age: 40,
    gross_income: 120000,
    taxes: 24000,
    federal_tax: 18000,
    state_tax: 4000,
    capital_gains_tax: 0,
    fica_tax: 2000,
    expenses: 60000,
    net_cash_flow: 36000,
    accounts: { a: 300000, b: 100000 },
    real_assets_value: 0,
    liabilities_balance: 0,
    net_worth: 400000,
    effective_rate: 0.2,
    marginal_rate: 0.24,
    deduction_used: "standard",
    deduction_amount: 30000,
    standard_deduction: 30000,
    flex_spending_reduction: 0,
    investment_growth: 25000,
    milestones_triggered: [],
    transfers: [],
    cash_flow: null,
    ...overrides,
  });

const rowValue = (label: string) =>
  screen.getByText(label).closest(".ledger-row")!.querySelector(".ledger-value")!.textContent;

describe("YearLedger", () => {
  it("lists withheld benefits in the active dollar mode and keeps the row in every year", () => {
    const props = { previous: null, isFirstYear: false, accountNames: {} };
    const withheld = snapshot({ ss_earnings_test_withheld: 4000 });
    const { rerender } = render(<YearLedger {...props} snapshot={withheld} factor={2} />);
    expect(rowValue("Social Security withheld")).toBe("$2,000");
    rerender(<YearLedger {...props} snapshot={snapshot({})} />);
    expect(screen.queryByText("Social Security withheld")).not.toBeInTheDocument();
    rerender(
      <YearLedger
        {...props}
        snapshot={snapshot({})}
        earningsTest={usesEarningsTest([withheld, snapshot({})])}
      />,
    );
    expect(rowValue("Social Security withheld")).toBe("$0");
  });
  it("shows investment fees only when charged, deflated in today's dollars", () => {
    const props = {
      previous: null,
      isFirstYear: false,
      accountNames: { a: "Brokerage", b: "Roth IRA" },
    };
    const { rerender } = render(<YearLedger {...props} snapshot={snapshot({})} />);
    expect(screen.queryByText("Investment fees")).not.toBeInTheDocument();
    const charged = snapshot({ investment_fees: 4000 });
    rerender(<YearLedger {...props} snapshot={charged} />);
    expect(rowValue("Investment fees")).toBe("−$4,000");
    rerender(
      <YearLedger
        {...props}
        snapshot={adjustTimeline([charged], [2], "inflation_adjusted")[0]}
        factor={2}
      />,
    );
    expect(rowValue("Investment fees")).toBe("−$2,000");
  });

  it("shows every projected account, including depleted and unknown accounts, in the active dollar mode", () => {
    const nominal = snapshot({
      accounts: { a: 300000, b: 0, missing: 100000 },
      real_assets_value: 200000,
      liabilities_balance: 50000,
      net_worth: 550000,
    });
    const props = {
      previous: null,
      isFirstYear: false,
      accountNames: { a: "Brokerage", b: "Roth IRA", unrelated: "Other plan account" },
    };
    const { rerender } = render(<YearLedger {...props} snapshot={nominal} />);
    expect(rowValue("Brokerage")).toBe("$300,000");
    expect(rowValue("Roth IRA")).toBe("$0");
    expect(rowValue("Account missing")).toBe("$100,000");
    expect(screen.queryByText("Other plan account")).not.toBeInTheDocument();
    const adjusted = adjustTimeline([nominal], [2], "inflation_adjusted")[0];
    rerender(<YearLedger {...props} snapshot={adjusted} factor={2} dollarLabel="2026 dollars" />);
    expect(rowValue("Brokerage")).toBe("$150,000");
    expect(rowValue("Cash & investments")).toBe("$200,000");
    expect(rowValue("Real assets")).toBe("$100,000");
    expect(rowValue("Debts")).toBe("−$25,000");
    expect(rowValue("Net worth")).toBe("$275,000");
    fireEvent.click(screen.getByText("Tax breakdown"));
    expect(rowValue("Federal income tax")).toBe("$9,000");
    expect(rowValue("State income tax")).toBe("$2,000");
    expect(rowValue("FICA")).toBe("$1,000");
    expect(rowValue("Marginal rate")).toBe("24.0%");
    rerender(
      <YearLedger {...props} snapshot={snapshot({ year: 2028, accounts: { a: 320000 } })} />,
    );
    expect(rowValue("Brokerage")).toBe("$320,000");
    expect(screen.queryByText("Roth IRA")).not.toBeInTheDocument();
  });

  it("lists the year's balances and flows, with change against the prior year", () => {
    render(
      <YearLedger
        snapshot={snapshot({})}
        previous={snapshot({ year: 2026, net_worth: 350000 })}
        isFirstYear={false}
      />,
    );
    expect(screen.getByText("2027")).toBeInTheDocument();
    expect(rowValue("Net worth")).toBe("$400,000");
    expect(rowValue("Change")).toBe("+$50,000");
    expect(rowValue("Cash & investments")).toBe("$400,000");
    expect(rowValue("Income")).toBe("$120,000");
    expect(rowValue("Taxes")).toBe("$24,000");
    expect(rowValue("Effective rate")).toBe("20.0%");
    expect(rowValue("Spending")).toBe("$60,000");
    expect(rowValue("Net cash flow")).toBe("+$36,000");
    expect(rowValue("Savings rate excl. payroll")).toBe("30%");
    expect(rowValue("Withdrawals")).toBe("$0");
    expect(rowValue("Withdrawal rate")).toBe("0.0%");
    expect(screen.queryByText("Real assets")).not.toBeInTheDocument();
  });

  it("measures the first year against the actual starting balance and shows the partial period", () => {
    render(
      <YearLedger
        snapshot={snapshot({ year: 2026, age: 39, net_worth: 370000 })}
        previous={null}
        initial={{ net_worth: 350000, accounts: { a: 350000 }, as_of: "2026-09-06" }}
        startDate="2026-09-06"
        yearFraction={0.32}
        isFirstYear
      />,
    );
    expect(rowValue("Change")).toBe("+$20,000");
    // The period and its share of the year are stated once, in the header.
    expect(screen.getByText("age 39 · Sep 6 – Dec 31 · 32% of year")).toBeInTheDocument();
    expect(screen.queryByText("Partial year")).not.toBeInTheDocument();
    expect(rowValue("Income pace")).toBe("$375,000");
    expect(rowValue("Spending pace")).toBe("$187,500");
    // Full-year figures form their own group, apart from the period's amounts.
    const fullYear = screen.getByText("Income pace").closest(".ledger-pace")!;
    expect(fullYear).not.toHaveAttribute("aria-hidden", "true");
    expect(fullYear).toHaveTextContent("Full year");
    expect(fullYear).toHaveTextContent("Taxes");
  });

  it("shows withdrawals and their rate in drawdown years, converted to the currency mode", () => {
    const drawdownYear = snapshot({
      year: 2060,
      age: 73,
      gross_income: 30000,
      net_cash_flow: -40000,
      cash_flow: {
        income_sources: [],
        gross_income: 30000,
        tax_withheld: 0,
        payroll_deductions: 0,
        net_pay: 30000,
        tax_delta: 0,
        expenses: [],
        contributions: [],
        transfers: [],
        drawdowns: [{ name: "IRA", amount: 50000, category: "drawdown" }],
      },
    });
    render(
      <YearLedger
        snapshot={drawdownYear}
        previous={snapshot({ year: 2059, accounts: { a: 1000000 } })}
        factor={2}
        previousFactor={2}
        isFirstYear={false}
      />,
    );
    expect(rowValue("Withdrawals")).toBe("$25,000");
    expect(rowValue("Withdrawal rate")).toBe("2.5%");
    expect(rowValue("Net cash flow")).toBe("-$40,000");
    expect(rowValue("Savings rate excl. payroll")).toBe("0%");
    // Pace rows keep their space outside the partial first year, hidden.
    expect(screen.getByText("Income pace").closest(".ledger-pace")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });

  it("shows a rule funding shortfall in display dollars, apart from unfunded spending", () => {
    render(
      <YearLedger
        snapshot={snapshot({ rule_funding_shortfall: 2200 })}
        previous={null}
        isFirstYear={false}
        factor={1.1}
      />,
    );
    expect(rowValue("Rule funding shortfall")).toBe("$2,000");
    expect(screen.queryByText("Unfunded spending")).not.toBeInTheDocument();
  });

  it("flags unfunded spending and lists the year's events", () => {
    const onStep = vi.fn();
    render(
      <YearLedger
        snapshot={snapshot({ unfunded_expenses: 5000, tax_balance: -1200 })}
        previous={null}
        isFirstYear={false}
        events={[
          { key: "fi", year: 2027, label: "Financial independence", kind: "fi" },
          { key: "x", year: 2030, label: "Later", kind: "milestone" },
        ]}
        onStep={onStep}
        canStepBack={false}
      />,
    );
    expect(rowValue("Unfunded spending")).toBe("$5,000");
    expect(rowValue("Tax refund")).toBe("$1,200");
    // Later years' chips stay mounted (hidden) to reserve their height.
    const shown = screen.getByRole("list", { name: "Events this year" });
    expect(within(shown).getByText("Financial independence")).toBeInTheDocument();
    expect(within(shown).queryByText("Later")).not.toBeInTheDocument();
    expect(screen.getByText("Later").closest("ul")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("button", { name: "Previous year" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next year" }));
    expect(onStep).toHaveBeenCalledWith(1);
  });

  it("keeps the withdrawal rate the same in nominal and today's dollars", () => {
    const year = snapshot({
      year: 2052,
      age: 60,
      gross_income: 0,
      net_cash_flow: -162218,
      cash_flow: {
        income_sources: [],
        gross_income: 0,
        tax_withheld: 0,
        payroll_deductions: 0,
        net_pay: 0,
        tax_delta: 0,
        expenses: [],
        contributions: [],
        transfers: [],
        drawdowns: [{ name: "Brokerage", amount: 162218, category: "drawdown" }],
      },
    });
    const opening = 3956537; // nominal cash and investments at the start of 2052
    const nominal = render(
      <YearLedger
        snapshot={year}
        previous={snapshot({ year: 2051, accounts: { a: opening } })}
        isFirstYear={false}
      />,
    );
    expect(rowValue("Withdrawal rate")).toBe("4.1%");
    nominal.unmount();
    // Today's dollars: this year deflated by 2.1566, last year by 2.0938.
    render(
      <YearLedger
        snapshot={year}
        previous={snapshot({ year: 2051, accounts: { a: opening / 2.0938 } })}
        factor={2.1566}
        previousFactor={2.0938}
        isFirstYear={false}
      />,
    );
    expect(rowValue("Withdrawals")).toBe("$75,219");
    expect(rowValue("Withdrawal rate")).toBe("4.1%");
  });

  it("lists the same tax lines in every year when given the projection's set", () => {
    const working = snapshot({ year: 2030, fica_tax: 2000, capital_gains_tax: 0 });
    const retired = snapshot({ year: 2060, fica_tax: 0, state_tax: 0, capital_gains_tax: 3000 });
    const taxLines = usedTaxLines([working, retired]);
    expect(taxLines).toEqual(["federal_tax", "state_tax", "capital_gains_tax", "fica_tax"]);
    const labels = () =>
      [...document.querySelectorAll(".ledger-tax-details .ledger-label")].map(
        (label) => label.textContent,
      );
    const { rerender } = render(
      <YearLedger snapshot={working} previous={null} isFirstYear={false} taxLines={taxLines} />,
    );
    const shape = labels();
    expect(rowValue("Capital gains tax")).toBe("$0");
    rerender(
      <YearLedger snapshot={retired} previous={null} isFirstYear={false} taxLines={taxLines} />,
    );
    expect(labels()).toEqual(shape);
    expect(rowValue("FICA")).toBe("$0");
    expect(rowValue("Capital gains tax")).toBe("$3,000");
    // Without the set, only the year's nonzero lines are listed.
    rerender(<YearLedger snapshot={retired} previous={null} isFirstYear={false} />);
    expect(screen.queryByText("FICA")).not.toBeInTheDocument();
  });

  it("labels an imputed opening year with the share of full-year taxes after the start date", () => {
    const imputedNominal = snapshot({
      year: 2026,
      taxes: 35710,
      federal_tax: 21940,
      fica_tax: 13770,
      post_start_taxes: 11153,
      warnings: ["ytd_imputed_pro_rata"],
    });
    const imputed = adjustTimeline([imputedNominal], [2], "inflation_adjusted")[0];
    const { rerender } = render(
      <YearLedger
        snapshot={imputed}
        previous={null}
        startDate="2026-09-09"
        yearFraction={0.3123}
        factor={2}
        isFirstYear
      />,
    );
    expect(rowValue("Taxes")).toBe("$17,855");
    expect(rowValue("Taxes after start")).toBe("+$5,577");
    expect(screen.getByText("Taxes after start").closest(".ledger-row")).toHaveAttribute(
      "title",
      "Pro-rata estimate; state payroll costs appear with spending.",
    );
    // Entered history uses the full-year liability less actual prior payments.
    const entered = adjustTimeline(
      [snapshot({ year: 2026, taxes: 35710, post_start_taxes: 11153 })],
      [2],
      "inflation_adjusted",
    )[0];
    rerender(
      <YearLedger
        snapshot={entered}
        previous={null}
        startDate="2026-09-09"
        yearFraction={0.3123}
        factor={2}
        isFirstYear
      />,
    );
    expect(rowValue("Taxes after start")).toBe("+$5,577");
    expect(screen.getByText("Taxes after start").closest(".ledger-row")).toHaveAttribute(
      "title",
      "Full-year taxes less amounts paid before the start.",
    );
    rerender(
      <YearLedger
        snapshot={snapshot({ year: 2026, taxes: 35710 })}
        previous={null}
        startDate="2026-09-09"
        yearFraction={0.3123}
        isFirstYear
      />,
    );
    expect(screen.queryByText("Taxes after start")).not.toBeInTheDocument();
    rerender(<YearLedger snapshot={imputed} previous={null} isFirstYear={false} />);
    expect(screen.queryByText(/estimated pro rata/)).not.toBeInTheDocument();
  });
});
