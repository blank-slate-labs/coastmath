import { it, expect } from "vitest";
import { projectionReport, reportCsv, csvCell } from "./projection_report";
import type { SimulationResult, YearSnapshot } from "@/types/plan";
import { makePlan } from "@/test_support/plan_builder";
import { makeYearSnapshot } from "@/test_support/record_builders";
it("deflates balances, tax liabilities and unfunded spending consistently while preserving rates", () => {
  const plan = makePlan({
    birth_year: 1990,
    assumption_curves: [{ curve_type: "inflation", mode: "fixed", fixed_rate: 0.1 }],
  });
  const snapshot = makeYearSnapshot({
    year: 2026,
    age: 36,
    net_worth: 1100,
    accounts: { a: 990 },
    real_assets_value: 330,
    liabilities_balance: 110,
    tax_balance: 55,
    unfunded_expenses: 55,
    gross_income: 110,
    calendar_year_gross_income: 220,
    expenses: 55,
    taxes: 22,
    federal_tax: 11,
    state_tax: 11,
    capital_gains_tax: 0,
    fica_tax: 0,
    net_cash_flow: 33,
    investment_growth: 110,
    effective_rate: 0.1,
    marginal_rate: 0.3,
    flex_spending_reduction: 11,
    transfers: [],
    cash_flow: null,
  });
  const simulation = {
    metadata: { start_year: 2026 },
    yearly_snapshots: [snapshot, { ...snapshot, year: 2027 }],
  } as SimulationResult;
  const rows = projectionReport(plan, simulation, "inflation_adjusted");
  expect(rows[1].net_worth).toBeCloseTo(1000);
  expect(rows[1].tax_balance).toBeCloseTo(50);
  expect(rows[1].unfunded_spending).toBeCloseTo(50);
  expect(rows[1].effective_tax_percent).toBe(10);
  expect(rows[0].income).toBe(110);
  expect(rows[0].calendar_year_gross_income).toBe(220);
  expect(rows[1].calendar_year_gross_income).toBeCloseTo(200);
  expect(
    rows[1].liquid_assets +
      rows[1].real_assets -
      rows[1].debt -
      rows[1].tax_balance -
      rows[1].unfunded_spending,
  ).toBeCloseTo(rows[1].net_worth);
  expect(reportCsv(rows, "inflation_adjusted", 2026)).toContain('"inflation_adjusted",2026,2027');
  // Older services omit the additive flex increase and leftover spending; both deflate like spending.
  expect(rows[0].flexible_spending_increase).toBe(0);
  expect(rows[0].leftover_spending).toBe(0);
  const flexed = projectionReport(
    plan,
    {
      ...simulation,
      yearly_snapshots: [
        snapshot,
        { ...snapshot, year: 2027, flex_spending_increase: 11, leftover_spending: 22 },
      ],
    },
    "inflation_adjusted",
  );
  expect(flexed[1].flexible_spending_increase).toBeCloseTo(10);
  expect(flexed[1].leftover_spending).toBeCloseTo(20);
  // Older services omit the additive state retirement exclusion; it deflates like the tax lines.
  expect(rows[0].state_retirement_exclusion).toBe(0);
  const excluded = projectionReport(
    plan,
    {
      ...simulation,
      yearly_snapshots: [snapshot, { ...snapshot, year: 2027, state_retirement_exclusion: 22_000 }],
    },
    "inflation_adjusted",
  );
  expect(excluded[1].state_retirement_exclusion).toBeCloseTo(20_000);
  // The Social Security subtraction and Washington excise are additive too.
  expect(rows[0].state_social_security_subtraction).toBe(0);
  expect(rows[0].state_capital_gains_excise).toBe(0);
  const components = projectionReport(
    plan,
    {
      ...simulation,
      yearly_snapshots: [
        snapshot,
        {
          ...snapshot,
          year: 2027,
          state_social_security_subtraction: 11_000,
          state_capital_gains_excise: 5_500,
        },
      ],
    },
    "inflation_adjusted",
  );
  expect(components[1].state_social_security_subtraction).toBeCloseTo(10_000);
  expect(components[1].state_capital_gains_excise).toBeCloseTo(5_000);
  snapshot.cash_flow = {
    income_sources: [
      { name: "RMD", source: "rmd", amount: 40 },
      { name: "SEPP", source: "sepp", amount: 10 },
    ],
    drawdowns: [{ name: "IRA", amount: 50 }],
    contributions: [],
  } as unknown as YearSnapshot["cash_flow"];
  const withdrawals = projectionReport(plan, simulation, "nominal")[0];
  expect(withdrawals.withdrawals).toBe(100);
  expect(withdrawals.mandatory_withdrawals).toBe(50);
});
it("escapes text formulas and quotes without converting negative numbers into strings", () => {
  expect(csvCell(" =SUM(A1:A2)")).toBe('"\' =SUM(A1:A2)"');
  expect(csvCell('a,"b"')).toBe('"a,""b"""');
  expect(csvCell(-25)).toBe("-25");
});
