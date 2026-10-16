import { describe, expect, it, vi } from "vitest";

import type { Expense, Income, Milestone, PlanData, YearSnapshot } from "@/types/plan";
import { makeAdapter } from "./adapter_stub";
import { deferred } from "./deferred";
import { makePlan } from "./plan_builder";
import {
  makeExpense,
  makeIncome,
  makeMilestone,
  makeTaxSettings,
  makeYearSnapshot,
} from "./record_builders";
import { mockStorageContext, mockStorageContextOver } from "./storage_mock";

const REQUIRED: (keyof PlanData)[] = [
  "id",
  "user_id",
  "name",
  "plan_type",
  "start_date",
  "snapshot_conditions",
  "birth_year",
  "filing_status",
  "state_code",
  "life_expectancy",
  "created_at",
  "milestones",
  "income_streams",
  "expenses",
  "priorities",
  "drawdown_order",
  "assumption_curves",
  "real_assets",
  "liabilities",
  "residency_periods",
  "spouse",
  "sepp_settings",
  "spending_rules",
  "tax_settings",
  "estate_settings",
  "baseline_plan_id",
];

describe("makePlan", () => {
  it("sets every required field and leaves optional ones absent", () => {
    const plan = makePlan();
    for (const key of REQUIRED) expect(plan).toHaveProperty(key);
    expect(Object.keys(plan).sort()).toEqual([...REQUIRED].sort());
  });

  it("applies overrides and gives each plan its own records", () => {
    const plan = makePlan({
      id: "p",
      birth_year: 1966,
      milestones: [{ id: "m", name: "Retirement" }],
    });
    expect(plan).toMatchObject({ id: "p", birth_year: 1966, name: "My Plan" });
    expect(plan.milestones).toEqual([{ id: "m", name: "Retirement" }]);
    makePlan().expenses.push({} as PlanData["expenses"][number]);
    expect(makePlan().expenses).toEqual([]);
  });
});

describe("makeAdapter", () => {
  it("resolves lists empty and writes to undefined, and keeps a given mock", async () => {
    const updatePlan = vi.fn();
    const adapter = makeAdapter({
      updatePlan,
      runSimulation: async () => ({ yearly_snapshots: [] }) as never,
    });
    await expect(adapter.listAccounts()).resolves.toEqual([]);
    await expect(adapter.deleteExpense("p", "e")).resolves.toBeUndefined();
    await expect(adapter.listLocalTaxJurisdictions()).resolves.toMatchObject({ jurisdictions: [] });
    expect(adapter.updatePlan).toBe(updatePlan);
    await expect(adapter.runSimulation("p")).resolves.toEqual({ yearly_snapshots: [] });
    expect(adapter.runSimulation).toHaveBeenCalledWith("p");
    adapter.listAccounts.mockReset();
    await expect(adapter.listAccounts()).resolves.toEqual([]);
  });
});

describe("deferred", () => {
  it("stays pending until resolved, and rejects with the given reason", async () => {
    const pending = deferred<number>();
    let settled: number | undefined;
    void pending.promise.then((value) => (settled = value));
    await Promise.resolve();
    expect(settled).toBeUndefined();
    pending.resolve(7);
    await expect(pending.promise).resolves.toBe(7);
    expect(settled).toBe(7);

    const failing = deferred<number>();
    failing.reject(new Error("no"));
    await expect(failing.promise).rejects.toThrow("no");
  });
});

describe("makeTaxSettings", () => {
  it("returns detailed-mode settings and applies overrides", () => {
    expect(makeTaxSettings()).toEqual({
      mode: "detailed",
      ordinary_income_tax_rate: null,
      capital_gains_tax_rate: null,
      taxable_withholding_rate: 0,
      tax_deferred_withholding_rate: 0,
      settlement_lag_years: 0,
      cash_flow_frequency: "monthly",
      dependent_birth_years: [2019],
    });
    expect(makeTaxSettings({ mode: "flat", ordinary_income_tax_rate: 0.2 })).toMatchObject({
      mode: "flat",
      ordinary_income_tax_rate: 0.2,
      settlement_lag_years: 0,
    });
    makeTaxSettings().dependent_birth_years?.push(2021);
    expect(makeTaxSettings().dependent_birth_years).toEqual([2019]);
  });
});

describe("storage context mocks", () => {
  it("reads the adapter on every call", () => {
    let adapter = makeAdapter();
    const context = mockStorageContext(() => adapter);
    expect(context.useStorage()).toEqual({ adapter, sample: false });
    adapter = makeAdapter();
    expect(context.useStorage().adapter).toBe(adapter);
    expect(mockStorageContext(null, { sample: () => true }).useStorage()).toEqual({
      adapter: undefined,
      sample: true,
    });
  });

  it("falls back to the real hook while no adapter is given", () => {
    const real = { adapter: makeAdapter(), sample: true };
    let stub: object | null = null;
    const context = mockStorageContextOver({ useStorage: () => real, other: 1 }, () => stub);
    expect(context.useStorage()).toBe(real);
    expect(context.other).toBe(1);
    stub = makeAdapter();
    expect(context.useStorage()).toEqual({ adapter: stub, sample: false });
  });
});

/** The members of T that are not optional. */
type RequiredKeys<T> = { [K in keyof T]-?: object extends Pick<T, K> ? never : K }[keyof T];

// `satisfies` fails tsc when a type gains or loses a required member.
const MILESTONE = {
  id: 1,
  plan_id: 1,
  name: 1,
  trigger_type: 1,
  trigger_value: 1,
  trigger_date: 1,
  metric: 1,
  expense_multiple: 1,
  relative_to_id: 1,
  offset_years: 1,
  sort_order: 1,
} satisfies Record<RequiredKeys<Milestone>, 1>;
const INCOME = {
  id: 1,
  plan_id: 1,
  name: 1,
  annual_amount: 1,
  start_milestone_id: 1,
  end_milestone_id: 1,
  growth_rate: 1,
  growth_cap: 1,
  growth_cap_inflation_linked: 1,
  withholding_percent: 1,
  start_month: 1,
  end_month: 1,
  is_active: 1,
  is_social_security: 1,
  is_earned_income: 1,
  is_self_employed: 1,
} satisfies Record<RequiredKeys<Income>, 1>;
const EXPENSE = {
  id: 1,
  plan_id: 1,
  name: 1,
  annual_amount: 1,
  start_milestone_id: 1,
  end_milestone_id: 1,
  inflation_linked: 1,
  growth_rate: 1,
  growth_cap: 1,
  growth_cap_inflation_linked: 1,
  recurrence_years: 1,
  recurrence_growth_rate: 1,
  is_payroll_deduction: 1,
  payroll_tax_treatment: 1,
  tied_income_id: 1,
  specific_funding_source_id: 1,
  specific_funding_source_ids: 1,
  start_month: 1,
  end_month: 1,
  category: 1,
} satisfies Record<RequiredKeys<Expense>, 1>;
const SNAPSHOT = {
  year: 1,
  age: 1,
  gross_income: 1,
  taxes: 1,
  federal_tax: 1,
  state_tax: 1,
  capital_gains_tax: 1,
  fica_tax: 1,
  expenses: 1,
  net_cash_flow: 1,
  accounts: 1,
  real_assets_value: 1,
  liabilities_balance: 1,
  net_worth: 1,
  effective_rate: 1,
  marginal_rate: 1,
  deduction_used: 1,
  deduction_amount: 1,
  standard_deduction: 1,
  flex_spending_reduction: 1,
  strategy_spending: 1,
  planned_expenses: 1,
  investment_growth: 1,
  milestones_triggered: 1,
  transfers: 1,
  cash_flow: 1,
} satisfies Record<RequiredKeys<YearSnapshot>, 1>;

describe.each([
  [
    "makeMilestone",
    makeMilestone,
    MILESTONE,
    { id: "fi", trigger_type: "expense_multiple", expense_multiple: 25 },
  ],
  [
    "makeIncome",
    makeIncome,
    INCOME,
    { id: "salary", annual_amount: 90000, is_earned_income: true },
  ],
  [
    "makeExpense",
    makeExpense,
    EXPENSE,
    { id: "rent", annual_amount: 18000, category: "essential" },
  ],
  [
    "makeYearSnapshot",
    makeYearSnapshot,
    SNAPSHOT,
    { year: 2030, net_worth: 1000, strategy_spending: 500 },
  ],
] as [string, (overrides?: object) => object, object, object][])(
  "%s",
  (_name, make, required, overrides) => {
    it("sets every required field and leaves optional ones absent", () => {
      expect(Object.keys(make()).sort()).toEqual(Object.keys(required).sort());
    });

    it("applies overrides over the defaults", () => {
      const record = make(overrides);
      expect(record).toMatchObject(overrides);
      expect(Object.keys(record).sort()).toEqual(Object.keys(required).sort());
      expect(make()).not.toMatchObject(overrides);
    });
  },
);
