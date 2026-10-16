import type { Expense, Income, Milestone, TaxSettings, YearSnapshot } from "@/types/plan";

/*
 * Complete records for tests. Each fills every required member with the value the
 * service gives a new record (no amount, no growth, no timing) and spreads overrides
 * on top, so a fixture names only the fields its test is about. Optional members stay
 * absent, as an older service sends them.
 */

/** An age milestone at 65. */
export function makeMilestone(overrides: Partial<Milestone> = {}): Milestone {
  return {
    id: "milestone",
    plan_id: "plan",
    name: "Retirement",
    trigger_type: "age",
    trigger_value: 65,
    trigger_date: null,
    metric: null,
    expense_multiple: null,
    relative_to_id: null,
    offset_years: 0,
    sort_order: 0,
    ...overrides,
  };
}

/** An active ordinary income with no amount, growth or timing. */
export function makeIncome(overrides: Partial<Income> = {}): Income {
  return {
    id: "income",
    plan_id: "plan",
    name: "Income",
    annual_amount: 0,
    start_milestone_id: null,
    end_milestone_id: null,
    growth_rate: null,
    growth_cap: null,
    growth_cap_inflation_linked: false,
    withholding_percent: null,
    start_month: null,
    end_month: null,
    is_active: true,
    is_social_security: false,
    is_earned_income: false,
    is_self_employed: false,
    ...overrides,
  };
}

/** An inflation-linked expense with no amount, growth, timing or funding source. */
export function makeExpense(overrides: Partial<Expense> = {}): Expense {
  return {
    id: "expense",
    plan_id: "plan",
    name: "Expense",
    annual_amount: 0,
    start_milestone_id: null,
    end_milestone_id: null,
    inflation_linked: true,
    growth_rate: null,
    growth_cap: null,
    growth_cap_inflation_linked: false,
    recurrence_years: null,
    recurrence_growth_rate: 0,
    is_payroll_deduction: false,
    payroll_tax_treatment: "pre_tax",
    tied_income_id: null,
    specific_funding_source_id: null,
    specific_funding_source_ids: null,
    start_month: null,
    end_month: null,
    category: null,
    ...overrides,
  };
}

/** A projection year with every flow and balance at zero and no strategy. */
export function makeYearSnapshot(overrides: Partial<YearSnapshot> = {}): YearSnapshot {
  return {
    year: 2026,
    age: 40,
    gross_income: 0,
    taxes: 0,
    federal_tax: 0,
    state_tax: 0,
    capital_gains_tax: 0,
    fica_tax: 0,
    expenses: 0,
    net_cash_flow: 0,
    accounts: {},
    real_assets_value: 0,
    liabilities_balance: 0,
    net_worth: 0,
    effective_rate: 0,
    marginal_rate: 0,
    deduction_used: "standard",
    deduction_amount: 0,
    standard_deduction: 0,
    flex_spending_reduction: 0,
    strategy_spending: null,
    planned_expenses: null,
    investment_growth: 0,
    milestones_triggered: [],
    transfers: [],
    cash_flow: null,
    ...overrides,
  };
}

/**
 * Detailed-mode tax settings with no flat rates, withholding or settlement lag, monthly
 * cash flow and one child born in 2019.
 */
export function makeTaxSettings(overrides: Partial<TaxSettings> = {}): TaxSettings {
  return {
    mode: "detailed",
    ordinary_income_tax_rate: null,
    capital_gains_tax_rate: null,
    taxable_withholding_rate: 0,
    tax_deferred_withholding_rate: 0,
    settlement_lag_years: 0,
    cash_flow_frequency: "monthly",
    dependent_birth_years: [2019],
    ...overrides,
  };
}
