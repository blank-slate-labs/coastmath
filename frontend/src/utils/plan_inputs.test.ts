import { describe, expect, it } from "vitest";
import type { SimulationResult } from "@/types/plan";
import { isEmptyProjection, missingRiskInputs } from "./plan_inputs";

const year = (overrides: Record<string, unknown> = {}) => ({
  expenses: 0,
  gross_income: 0,
  accounts: {},
  real_assets_value: 0,
  liabilities_balance: 0,
  ...overrides,
});
const projection = (...years: Record<string, unknown>[]) =>
  ({ yearly_snapshots: years.map(year) }) as unknown as SimulationResult;

describe("plan inputs", () => {
  it("treats rows of $0 as no projection", () => {
    expect(isEmptyProjection(projection({}, {}))).toBe(true);
    expect(isEmptyProjection(null)).toBe(true);
    expect(isEmptyProjection(projection({}, { accounts: { a: 0 } }))).toBe(false);
    expect(isEmptyProjection(projection({ liabilities_balance: 1000 }))).toBe(false);
  });

  it("names what a risk result lacks", () => {
    expect(missingRiskInputs(projection({}))).toBe("No accounts, income or expenses yet.");
    expect(missingRiskInputs(projection({ expenses: 40_000 }))).toBe("No accounts or income yet.");
    expect(missingRiskInputs(projection({ gross_income: 90_000 }))).toBe("No expenses yet.");
    expect(missingRiskInputs(projection({ accounts: { a: 10 } }))).toBe("No expenses yet.");
    expect(missingRiskInputs(projection({ expenses: 40_000, accounts: { a: 10 } }))).toBeNull();
    expect(missingRiskInputs(projection({ expenses: 40_000, gross_income: 90_000 }))).toBeNull();
  });
});
