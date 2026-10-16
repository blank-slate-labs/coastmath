// TypeScript interfaces matching backend Pydantic schemas

// --- Enums as union types ---

export type FilingStatus =
  "single" | "married_filing_jointly" | "married_filing_separately" | "head_of_household";

export type AccountType =
  | "checking"
  | "savings"
  | "traditional_401k"
  | "roth_401k"
  | "traditional_403b"
  | "roth_403b"
  | "traditional_457b"
  | "roth_457b"
  | "traditional_401a"
  | "traditional_ira"
  | "roth_ira"
  | "taxable_brokerage"
  | "hsa"
  | "five_twenty_nine"
  | "other";

export type CurveType =
  | "inflation"
  | "market_return"
  | "bond_return"
  | "bond_allocation"
  | "dividend_yield"
  | "wage_growth"
  | "cash_yield"
  | "social_security_cola";

export type PlanType = "NOW" | "FIXED_DATE";

export type MilestoneTriggerType =
  "age" | "date" | "net_worth" | "expense_multiple" | "relative" | "conditions";

export type CurveMode = "fixed" | "curve";

/** Opt-in protected cash: skipped by the normal withdrawal order, spent last in this order. */
export interface CashReserveSettings {
  enabled: boolean;
  account_ids: string[];
  /** Protected amount in start-year dollars. */
  reserve_amount: number;
  /** Each year, move cash above the reserve into the allocation rules. Omitted while off. */
  sweep_excess?: boolean;
}

export type SEPPMethod = "fixed_amortization" | "fixed_annuitization" | "rmd_method";

// --- SEPP Settings ---

export interface SEPPSettings {
  enabled: boolean;
  source_account_id: string | null;
  method: SEPPMethod;
  start_age: number;
  interest_rate: number;
  /** Custom yearly payment. Only the approved fixed-amortization amount keeps the 72(t) exemption. */
  annual_amount?: number | null;
}

export interface SEPPPreviewRequest {
  birth_month?: number | null;
  balance: number;
  start_age: number;
  interest_rate: number;
  birth_year?: number | null;
  annual_amount?: number | null;
}

export interface SEPPPreviewYear {
  age: number;
  year: number | null;
  withdrawal: number;
  remaining: number;
}

export interface SEPPPreviewMethod {
  method: SEPPMethod;
  first_year_amount: number;
  schedule: SEPPPreviewYear[];
}

export interface SEPPPreviewResponse {
  single_life_divisor: number;
  end_age: number;
  payment_years: number;
  methods: SEPPPreviewMethod[];
  notes: string[];
  /** Present when the request carried a custom annual amount. */
  custom?: SEPPPreviewCustom | null;
  /** Highest allowed rate for the series' first payment month (5% when unknown). */
  rate_ceiling?: number;
}

export interface SEPPPreviewCustom {
  annual_amount: number;
  /** True only when the amount equals the fixed-amortization payment at a rate of 5% or less. */
  qualifies: boolean;
  approved_amount: number;
  message: string;
}

// --- Withdrawal strategy comparison ---

export type WithdrawalMethod =
  "constant_dollar" | "constant_percentage" | "guyton_klinger" | "vanguard_dynamic" | "rmd_table";

/** Methods a plan can save (plans.withdrawal_strategy); the comparison offers WithdrawalMethod only. */
export type SavedWithdrawalMethod =
  WithdrawalMethod | "fixed_amount" | "one_over_n" | "vpw" | "kitces_ratchet" | "clyatt_95";

/** A minimum or maximum yearly withdrawal: today's dollars, or a decimal share of the portfolio. */
export interface WithdrawalBound {
  unit: "today_dollars" | "portfolio_percent";
  amount: number;
}

/**
 * Saved withdrawal strategy. Rates and shares are decimals; dollar amounts are
 * today's dollars. Older services omit it from plan reads; null clears it.
 */
export interface WithdrawalStrategySettings {
  enabled: boolean;
  method: SavedWithdrawalMethod;
  initial_rate?: number;
  start_milestone_id?: string | null;
  start_age?: number | null;
  upper_guardrail?: number;
  lower_guardrail?: number;
  guardrail_adjustment?: number;
  guardrail_freeze_years?: number;
  floor?: number;
  ceiling?: number;
  fixed_amount?: number;
  fixed_amount_inflation_adjusted?: boolean;
  vpw_stock_return?: number;
  vpw_bond_return?: number;
  ratchet_threshold?: number;
  ratchet_increase?: number;
  ratchet_cooldown_years?: number;
  clyatt_floor?: number;
  minimum?: WithdrawalBound | null;
  maximum?: WithdrawalBound | null;
  income_handling?: "replace_expenses" | "withdrawal_plus_income";
}

export interface WithdrawalCompareRequest {
  methods: WithdrawalMethod[];
  initial_rate: number;
  start_milestone_id?: string | null;
  start_age?: number | null;
  monte_carlo_trials?: number;
  seed?: number | null;
}

export interface WithdrawalSpendingPoint {
  year: number;
  age: number;
  nominal: number;
  real: number;
  planned_nominal: number | null;
  net_worth: number;
}

export interface WithdrawalStrategyOutcome {
  method: string;
  label: string;
  success: boolean;
  failure_year: number | null;
  start_year: number | null;
  first_year_spending: number;
  total_real_spending: number;
  median_real_spending: number;
  min_real_spending: number;
  max_real_spending: number;
  real_spending_drawdown: number;
  years_below_planned: number;
  final_net_worth: number;
  lifetime_taxes: number;
  monte_carlo_success_rate: number | null;
  monte_carlo_p10_final_net_worth: number | null;
  spending_path: WithdrawalSpendingPoint[];
  notes: string[];
}

export interface WithdrawalCompareResponse {
  initial_rate: number;
  planned: WithdrawalStrategyOutcome;
  strategies: WithdrawalStrategyOutcome[];
  caveats: string[];
  method_labels: Record<string, string>;
}

// --- Tax strategy comparison ---

export type TaxStrategyObjective =
  | "net_legacy"
  | "final_net_worth"
  | "lifetime_taxes"
  | "lifetime_taxes_and_healthcare"
  | "lifetime_effective_tax_rate"
  | "total_aca_subsidies"
  | "total_rmd_distributions"
  | "total_irmaa_surcharge";

export type TaxStrategyType = "roth_conversion" | "gain_harvest";

export interface TaxStrategyCompareRequest {
  strategy_type?: TaxStrategyType;
  source_account_id: string;
  target_account_id?: string | null;
  bracket_ceilings: number[];
  magi_cap?: number | null;
  start_milestone_id?: string | null;
  end_milestone_id?: string | null;
  objective: TaxStrategyObjective;
}

export interface TaxStrategyMetrics {
  key: string;
  label: string;
  success: boolean;
  failure_year: number | null;
  lifetime_taxes: number;
  lifetime_healthcare: number;
  final_net_worth: number;
  net_legacy: number;
  total_converted: number;
  conversion_years: number;
  irmaa_years: number;
  aca_credit_lost_years: number;
  peak_marginal_rate: number;
  objective_value: number;
  delta_vs_baseline: number;
  is_best: boolean;
  notes: string[];
  /** Added with the objective search; absent from older servers. */
  lifetime_effective_tax_rate?: number;
  total_aca_subsidies?: number;
  total_rmd_distributions?: number;
  total_irmaa_surcharge?: number;
}

export interface TaxStrategyCompareResponse {
  objective: TaxStrategyObjective;
  objective_description: string;
  baseline_key: string;
  best_key: string | null;
  candidates: TaxStrategyMetrics[];
  caveats: string[];
  proposed_priority: Partial<CashFlowPriorityCreate> | null;
  /** Income tax rate on end-of-plan pre-tax balances in the net legacy and end net worth objectives. Absent from older servers. */
  pre_tax_discount_rate?: number;
}

// --- Bounded strategy search ---

export type StrategyDrawdownPreset = "taxable_first" | "pretax_first" | "roth_before_pretax";

/** Each side is a milestone, a calendar year or the plan holder's age; year and age ends are inclusive. */
export interface StrategySearchWindowRequest {
  start_milestone_id?: string | null;
  end_milestone_id?: string | null;
  start_year?: number | null;
  end_year?: number | null;
  start_age?: number | null;
  end_age?: number | null;
}

export interface StrategySearchRequest {
  objective: TaxStrategyObjective;
  /** Federal bracket rates to try as the tax target; required with any action. */
  bracket_rates: number[];
  conversion?: { source_account_id: string; target_account_id: string } | null;
  harvest?: { source_account_id: string } | null;
  blend_withdrawals?: boolean;
  drawdown_presets?: StrategyDrawdownPreset[];
  windows?: StrategySearchWindowRequest[];
  max_simulations?: number;
}

export interface StrategyPlanChange {
  kind: "add" | "replace";
  target: "priority" | "milestone" | "tax_target" | "blend_drawdown" | "drawdown_order";
  summary: string;
  before: unknown;
  after: unknown;
}

export interface StrategySearchProposal {
  priorities_to_add: CashFlowPriorityCreate[];
  /** Keys to merge into the plan's tax settings, or null. */
  tax_settings: Pick<TaxSettings, "tax_target" | "blend_drawdown_to_tax_target"> | null;
  /** Complete replacement withdrawal order, or null to keep the saved one. */
  drawdown_order: DrawdownEntryCreate[] | null;
  /** Milestones a year or age window adds; `id` is a placeholder the rules refer to. */
  milestones_to_add?: StrategyMilestoneToAdd[];
}

export interface StrategyMilestoneToAdd {
  id: string;
  name: string;
  trigger_type: "date" | "age";
  trigger_value: number | null;
  trigger_date: string | null;
}

export interface StrategySearchCandidate {
  key: string;
  label: string;
  stage: "baseline" | "rate_scan" | "combination";
  rank: number;
  is_baseline: boolean;
  is_best: boolean;
  improves_baseline: boolean;
  success: boolean;
  failure_year: number | null;
  actions: ("conversion" | "harvest" | "blend")[];
  bracket_rate: number | null;
  drawdown_preset: "saved" | StrategyDrawdownPreset;
  window_index: number | null;
  objective_value: number;
  delta_vs_baseline: number;
  lifetime_taxes: number;
  lifetime_healthcare: number;
  final_net_worth: number;
  net_legacy: number;
  lifetime_income: number;
  lifetime_effective_tax_rate: number;
  total_aca_subsidies: number;
  total_rmd_distributions: number;
  total_irmaa_surcharge: number;
  total_converted: number;
  total_harvested: number;
  peak_marginal_rate: number;
  notes: string[];
  changes: StrategyPlanChange[];
  proposal: StrategySearchProposal;
}

export interface StrategySearchCounts {
  max_simulations: number;
  simulated: number;
  stage1_simulated: number;
  stage2_simulated: number;
  cache_hits: number;
  grid_requested: number;
  grid_size: number;
  skipped_by_budget: number;
  screened_out: number;
  budget_exhausted: boolean;
}

export interface StrategySearchResponse {
  objective: TaxStrategyObjective;
  objective_description: string;
  objective_direction: "higher" | "lower";
  baseline_key: string;
  /** Best of the evaluated candidates, never a global optimum; "baseline" means keep the saved plan. */
  best_key: string | null;
  candidates: StrategySearchCandidate[];
  counts: StrategySearchCounts;
  survivor_rates: number[];
  windows: ({
    index: number;
    label: string;
    start_milestone_id: string | null;
    end_milestone_id: string | null;
  } & Pick<StrategySearchWindowRequest, "start_year" | "end_year" | "start_age" | "end_age">)[];
  caveats: string[];
  pre_tax_discount_rate: number;
  /** Allocation revision at search time; the apply save is checked against it. */
  priorities_revision: number;
}

// --- Tax suggestions ---

export type TaxSuggestionKey =
  "max_401k" | "backdoor_roth" | "max_hsa" | "mega_backdoor" | "roth_conversion" | "gain_harvest";

/** An allocation rule in CashFlowPriorityCreate fields. "add" inserts it at
 * priority_rank (later rules move down one); "update" sets these fields on the
 * rule currently at priority_rank. */
export interface TaxSuggestedRule {
  change: "add" | "update";
  priority_rank: number;
  priority_type: string;
  target_account_id: string | null;
  source_account_id: string | null;
  source_income_id: string | null;
  conversion_mode: "fixed" | "fill_bracket";
  bracket_ceiling_rate: number | null;
  backdoor_roth: boolean;
}

export interface TaxSuggestion {
  key: TaxSuggestionKey;
  title: string;
  /** Nominal dollars, suggestion minus plan; negative saves tax. */
  lifetime_tax_change: number;
  /** Nominal dollars at the end of the plan, pre-tax balances after income tax at `pre_tax_discount_rate`. */
  end_net_worth_change: number;
  rules: TaxSuggestedRule[];
}

export interface TaxSuggestionsResponse {
  suggestions: TaxSuggestion[];
  /** The heirs' income tax rate when set, else 0.24. Absent from older servers. */
  pre_tax_discount_rate?: number;
}

// --- Health coverage (ACA marketplace + Medicare) ---

export type HealthcareStateGroup = "contiguous" | "alaska" | "hawaii";

export interface LongTermCareBudget {
  monthly_cost: number;
  duration_months: number;
  start_year?: number | null;
  start_month?: number;
  months_before_longevity?: number | null;
  covered_fraction?: number;
  inflation_rate?: number | null;
  amount_reference_year?: number | null;
}

export interface PersonHealthcareSettings {
  owner: "self" | "spouse";
  mode: "off" | "itemized" | "coverage";
  itemized_annual_amount?: number | null;
  itemized_start_age?: number;
  itemized_end_age?: number | null;
  medical_inflation_rate?: number | null;
  aca_enabled?: boolean;
  medicare_enabled?: boolean;
  medicare_start_age?: number;
  medicare_part_b?: boolean;
  medicare_part_d?: boolean;
  medicare_apply_irmaa?: boolean;
  medicare_part_a_premium_monthly?: number;
  /** Medicare-covered quarters for the published Part A premium (40+ none, 30–39 reduced, fewer full); omitted adds none. */
  medicare_part_a_quarters?: number | null;
  medicare_part_d_plan_premium_monthly?: number;
  medicare_supplement_premium_monthly?: number;
  out_of_pocket_annual?: number | null;
  long_term_care?: LongTermCareBudget | null;
}

export interface HealthcareSettings {
  enabled: boolean;
  /** Decimal; null uses the plan inflation rate. */
  medical_inflation_rate: number | null;
  aca_enabled: boolean;
  aca_start_milestone_id: string | null;
  aca_end_milestone_id: string | null;
  /** Annual, today's dollars, for the covered adults at their current ages. */
  aca_benchmark_premium_annual: number;
  aca_plan_premium_annual: number;
  /** Decimal fraction of the estimated credit applied during coverage. */
  aca_advance_credit_fraction: number;
  aca_cover_spouse: boolean;
  aca_dependents: number;
  aca_apply_age_curve: boolean;
  aca_state_group: HealthcareStateGroup;
  medicare_enabled: boolean;
  medicare_part_b: boolean;
  medicare_part_d: boolean;
  /** Monthly per person, today's dollars. */
  medicare_part_d_plan_premium_monthly: number;
  medicare_supplement_premium_monthly: number;
  medicare_apply_irmaa: boolean;
  magi_prior_year: number | null;
  magi_two_years_prior: number | null;
  persons?: PersonHealthcareSettings[];
  magi_prior_year_filing_status?: FilingStatus | null;
  magi_two_years_prior_filing_status?: FilingStatus | null;
}

export interface HealthcareYear {
  aca_covered_adults: number;
  aca_household_size: number;
  aca_magi: number;
  aca_fpl_ratio: number;
  aca_applicable_percentage: number;
  aca_benchmark_premium: number;
  aca_gross_premium: number;
  aca_credit: number;
  aca_net_premium: number;
  /** Premium paid during the coverage year after the advance credit. */
  aca_cash_premium: number;
  aca_eligible: boolean;
  aca_reason: string | null;
  aca_magi_estimate: number;
  aca_credit_advanced: number;
  aca_reconciliation: number;
  medicare_persons: number;
  medicare_magi_used: number;
  medicare_lookback_year: number | null;
  medicare_lookback_source: string;
  medicare_lookback_filing_status?: string | null;
  medicare_part_a?: number;
  itemized_medical?: number;
  out_of_pocket?: number;
  long_term_care_gross?: number;
  long_term_care_covered?: number;
  long_term_care?: number;
  person_costs?: Array<{
    owner: "self" | "spouse";
    mode: string;
    active_fraction: number;
    itemized_medical: number;
    out_of_pocket: number;
    medicare_premiums: number;
    long_term_care_gross: number;
    long_term_care_covered: number;
    long_term_care: number;
    total_excluding_aca: number;
  }>;
  medicare_tier: number;
  medicare_part_b: number;
  medicare_irmaa_part_b: number;
  medicare_irmaa_part_d: number;
  medicare_part_d_plan: number;
  medicare_supplement: number;
  total: number;
}

// --- Estate Settings ---

export type FilingStatusAfterDeath =
  "single" | "head_of_household" | "married_filing_jointly" | "married_filing_separately";

export interface EstateSettings {
  household_lifecycle?: "legacy_primary_endpoint" | "last_survivor_calendar_year_end";
  survivor_social_security_policy?: "off" | "claimed_benefit_at_survivor_fra";
  survivor_social_security_eligibility_confirmed?: boolean;
  survivor_social_security_eligibility_source?: string | null;
  step_up_basis_on_death: boolean;
  filing_status_after_death: FilingStatusAfterDeath;
  /** Only applied when custom_federal_exemption_enabled is true. */
  federal_estate_exemption: number;
  custom_federal_exemption_enabled: boolean;
  portability_election: boolean;
  state_estate_tax_enabled: boolean;
  state_estate_exemption: number;
  /** Decimal rate (0.16 = 16%). */
  state_estate_tax_rate: number;
  settlement_cost_fixed?: number;
  settlement_cost_rate?: number;
  heir_income_tax_rate?: number;
  /** Decimal rate heirs pay on unrealized taxable-account gains; used only when step-up is off. */
  heir_capital_gains_rate?: number;
  /** Percent (0-100) of real asset value paid as selling costs (net legacy only). */
  estate_selling_cost_percent?: number;
  /** Percent (0-100) of the estate after settlement costs left to charity. */
  charitable_bequest_percent?: number;
  /** Step up joint taxable accounts at the first death: half, or all in a community property state. */
  joint_account_step_up?: boolean;
  /** Amount to leave heirs, today's dollars; the Monte Carlo default final net worth target. */
  legacy_target?: number | null;
}

/** Partner profile edited from the plan builder; null removes the partner. */
export interface SpouseUpdate {
  name?: string | null;
  birth_year?: number | null;
  birth_month?: number | null;
  life_expectancy?: number | null;
}

// --- Net Legacy (engine-derived estate breakdown at the holder's death) ---

export interface NetLegacy {
  total_assets: number;
  total_liabilities: number;
  gross_estate: number;
  federal_exemption: number;
  dsue_amount: number;
  federal_taxable_estate: number;
  federal_estate_tax: number;
  state_exemption: number;
  state_taxable_estate: number;
  state_estate_tax: number;
  estate_tax: number;
  net_legacy: number;
  marital_deduction_applied: boolean;
  custom_federal_exemption: boolean;
  death_year: number;
  exclusions: string[];
  debts?: number;
  accrued_taxes?: number;
  settlement_costs?: number;
  taxable_estate_before_exemptions?: number;
  pretax_balance?: number;
  heir_income_tax_deduction_691c?: number;
  heir_income_tax?: number;
  net_to_heirs_after_income_tax?: number;
  /** 529 balances: outside the gross estate but passed on. */
  education_savings_outside_estate?: number;
  charitable_bequest?: number;
  selling_costs?: number;
  unrealized_gains?: number;
  heir_capital_gains_tax?: number;
}

// --- Spending Rules ---

export type SpendingPerformanceMode = "trailing_return" | "all_time_high";
export type SpendingInterpolation = "step" | "linear";

export interface SpendingRuleThreshold {
  threshold: number;
  reduction: number;
}

export type SpendingFlexScope = "expenses" | "strategy_spending" | "leftover_spending";
export type SpendingSurplusMode = "save" | "spend_leftover";

/** Spending rises by `increase` once the portfolio index is `threshold` above its earlier high. */
export interface SpendingUpsidePoint {
  threshold: number;
  increase: number;
}

export interface SpendingRules {
  flex_threshold?: number | null;
  flex_reduction: number;
  lookback_years: number;
  spending_floor?: number;
  performance_mode?: SpendingPerformanceMode;
  interpolation?: SpendingInterpolation;
  thresholds?: SpendingRuleThreshold[];
  start_milestone_id?: string | null;
  end_milestone_id?: string | null;
  /** Opt-in additions; the server omits them while they hold their defaults. */
  upside_thresholds?: SpendingUpsidePoint[];
  flex_scope?: SpendingFlexScope[];
  surplus_mode?: SpendingSurplusMode;
}

export interface YearToDateTax {
  tax_year: number;
  gross_income?: number;
  social_security_income?: number;
  capital_gains?: number;
  qualified_dividends?: number;
  net_investment_income?: number;
  deductions?: number;
  tax_paid?: number;
  state_tax_paid?: number;
  property_tax?: number;
  mortgage_interest?: number;
  w2_income_by_owner?: Partial<Record<"self" | "spouse", number>>;
  self_employment_income_by_owner?: Partial<Record<"self" | "spouse", number>>;
  contributions_by_account?: Record<string, number>;
  employer_contributions_by_account?: Record<string, number>;
  /** Withdrawals already taken; they count toward this year's required distribution. */
  distributions_by_account?: Record<string, number>;
}

export interface HSACoverage {
  owner: "self" | "spouse";
  start_year: number;
  /** Inclusive; absent/null continues through the projection. */
  end_year?: number | null;
  coverage: "self_only" | "family" | "ineligible";
  payroll_funding?: "cafeteria" | "direct" | null;
  /** Unique first-day eligible months 1..12; default all. No last-month rule. */
  eligible_months?: number[];
}

export interface StatePayrollCoverage {
  owner: "self" | "spouse";
  start_year: number;
  /** First covered month in start_year; defaults to January. */
  start_month?: number;
  end_year?: number | null;
  /** Explicit localization of this owner's covered W2 wages. */
  state_code: "CA" | "WA";
  ca_sdi?: boolean;
  wa_paid_leave?: boolean;
  wa_cares?: boolean;
  employer_pays_fraction?: number;
}

export interface TaxSettings {
  mfs_lived_apart_all_year?: boolean;
  ca_dependents_by_year?: Record<string, number>;
  /** One birth year per child, for the federal child tax credit. */
  dependent_birth_years?: number[];
  hsa_coverage?: HSACoverage[];
  state_payroll_coverage?: StatePayrollCoverage[];
  /** Opening year paid payroll obligations; missing means unpaid. */
  state_payroll_wages_year_to_date?: Partial<Record<"self" | "spouse", number>>;
  state_payroll_paid_year_to_date?: Partial<
    Record<"California SDI" | "Washington Paid Leave" | "Washington Cares", number>
  >;
  /** Unknown when omitted/null; [] explicitly establishes no personal exemption. */
  ca_exemption_eligible_owners?: ("self" | "spouse")[] | null;
  /** Explicit eligible Ohio filers; omitted/null leaves eligibility unknown. */
  oh_exemption_eligible_owners?: ("self" | "spouse")[] | null;
  /** Ohio dependent eligibility applies only to the listed tax years. */
  oh_dependents_by_year?: Record<string, number>;
  mode: "detailed" | "flat";
  ordinary_income_tax_rate: number | null;
  capital_gains_tax_rate: number | null;
  taxable_withholding_rate: number;
  tax_deferred_withholding_rate: number;
  settlement_lag_years: number;
  /** Omitted legacy settings resolve to monthly on the server. */
  cash_flow_frequency?: "annual" | "monthly";
  withdrawal_cash_flow_frequency?: "annual" | "monthly" | null;
  state_brackets?: Array<[number, number]> | null;
  year_to_date?: YearToDateTax | null;
  capital_loss_carryforward?: number;
  /** Federal estimated tax (IRC 6654); omitted or "off" models none. */
  estimated_payments?: EstimatedPayments | null;
  /** Plan-level tax target; omitted or null sets none. */
  tax_target?: TaxTarget | null;
  /** Opt-in first drawdown pass that fills the tax target's room. */
  blend_drawdown_to_tax_target?: boolean;
  /** Household bond target and asset location; omitted or null is per-account. */
  asset_location?: AssetLocation | null;
  /** Opt-in itemized medical expenses above 7.5% of AGI and the self-employed health insurance deduction. */
  medical_expense_deductions?: boolean;
  /** Opt-in state income tax deduction for 529 contributions (supported states only). */
  state_529_deduction?: boolean;
  /** User deductions, credits and surcharges; omitted when empty. */
  adjustments?: TaxAdjustment[];
  /** Whitelisted settings that change from a year or a milestone; omitted when empty. */
  scheduled_changes?: ScheduledTaxChange[];
  /** Opt-in statutory state itemized/standard choice, exemption phaseouts and federal tax subtraction (supported states). */
  state_deduction_rules?: boolean;
  /** Custom federal ordinary-income brackets (upper bound, rate) for every filing status; omitted uses current law. */
  federal_brackets?: Array<[number, number]> | null;
  /** Custom basic federal standard deduction; omitted uses current law. */
  federal_standard_deduction?: number | null;
  /** Custom federal amounts grow with plan inflation unless false (nominal). Omitted means true. */
  federal_overrides_indexed?: boolean;
  /** Assumed owner RMD start ages (70–80) in place of the SECURE 2.0 schedule. */
  rmd_start_ages?: Partial<Record<"self" | "spouse", number>> | null;
}

export type TaxAdjustmentKind = "deduction" | "credit" | "surcharge";
export type TaxAdjustmentScope = "federal" | "state" | "both";
export type TaxSurchargeBase =
  "ordinary_taxable_income" | "taxable_income" | "capital_gains" | "income_tax";

/** One deduction, credit or surcharge over explicit tax years (annual tax-return amounts). */
export interface TaxAdjustment {
  id: string;
  name?: string;
  kind: TaxAdjustmentKind;
  /** Credits and surcharges are "federal" or "state"; deductions may be "both". */
  scope: TaxAdjustmentScope;
  /** Deductions only. */
  deduction_type?: "above_the_line" | "itemized";
  /** Credits only. */
  refundable?: boolean;
  /** Deductions and credits: dollars per applicable year. */
  amount?: number;
  /** Surcharges: decimal rate on `base`, optionally capped at `max_amount`. */
  rate?: number;
  base?: TaxSurchargeBase;
  max_amount?: number;
  /** "today": plan-start dollars indexed with plan inflation. */
  amount_basis: "today" | "nominal";
  owner?: "self" | "spouse" | "household";
  start_year?: number;
  start_milestone_id?: string;
  /** Inclusive. */
  end_year?: number;
  end_milestone_id?: string;
  frequency: "once" | "annual" | "every_n_years";
  interval_years?: number;
}

/** Settings a scheduled change may replace; omitted keys are kept. `state_brackets: []` and `federal_brackets: []` return to the built-in tables. */
export interface ScheduledTaxSettings {
  mode?: "detailed" | "flat";
  ordinary_income_tax_rate?: number;
  capital_gains_tax_rate?: number;
  state_brackets?: Array<[number, number]>;
  adjustments?: TaxAdjustment[];
  state_deduction_rules?: boolean;
  federal_brackets?: Array<[number, number]>;
  federal_standard_deduction?: number;
}

/** Exactly one of `year` or `milestone_id`. Later years win; same-year changes apply in list order. */
export interface ScheduledTaxChange {
  year?: number;
  milestone_id?: string;
  settings: ScheduledTaxSettings;
}

/** Account buckets for the household bond location order. */
export type AccountBucket = "tax_deferred" | "tax_free" | "taxable";

/**
 * "household" treats the plan bond allocation as a target for the pooled
 * accounts together, placing bonds in `bond_location_order` (buckets or
 * account ids). Cash, HSA and crypto accounts are never pooled.
 */
export interface AssetLocation {
  bond_allocation_mode: "per_account" | "household";
  bond_location_order: string[];
  excluded_account_ids?: string[];
}

export type TaxTargetKind =
  "federal_bracket" | "taxable_income" | "magi" | "irmaa_tier" | "aca_fpl_percent";

export interface TaxTarget {
  kind: TaxTargetKind;
  /** federal_bracket: decimal rate of the bracket to stay within, e.g. 0.12. */
  bracket_rate?: number | null;
  /** taxable_income / magi: today's dollars, indexed with plan inflation. */
  amount?: number | null;
  /** irmaa_tier: stay below this surcharge tier (1 = no surcharge). */
  irmaa_tier?: number | null;
  /** aca_fpl_percent: percent of the poverty line, in marketplace-coverage years. */
  aca_fpl_percent?: number | null;
  avoid_niit?: boolean;
  avoid_irmaa?: boolean;
  aca_cap_fpl_percent?: number | null;
}

export type EstimatedTaxStrategy = "off" | "settle_at_filing" | "safe_harbor" | "pay_in_full";

export interface EstimatedPayments {
  strategy: EstimatedTaxStrategy;
  /** The preceding tax year's federal tax and AGI; first plan year only. */
  prior_year_total_tax?: number | null;
  prior_year_agi?: number | null;
}

// --- Local income tax ---

/**
 * A residence's local income tax: a catalog jurisdiction id, or "custom" with
 * at least one positive decimal rate. Custom bases: earned income (wages plus
 * net self-employment profit), state taxable income, and state income tax.
 */
export interface LocalTaxSelection {
  jurisdiction: string;
  earned_income_rate?: number | null;
  taxable_income_rate?: number | null;
  state_tax_surcharge_rate?: number | null;
}

export interface LocalTaxJurisdiction {
  id: string;
  name: string;
  state_code: string;
  components: { label: string; base: string; kind: string }[];
  /** Modeling boundaries, also reported as projection warnings. */
  limitations: string[];
}

export interface LocalTaxCatalog {
  tax_year: number;
  jurisdictions: LocalTaxJurisdiction[];
}

// --- Residency Period ---

export interface ResidencyPeriod {
  id: string;
  plan_id: string;
  /** Null for a period in another country (see `country`). */
  state_code: string | null;
  start_milestone_id: string | null;
  end_milestone_id: string | null;
  start_year: number | null;
  end_year: number | null;
  rank: number;
  /** Older services omit this. */
  local_tax?: LocalTaxSelection | null;
  /** Null: the plan's tax_country and tax_region. */
  country?: TaxCountryCode | null;
  region?: string | null;
}

export interface ResidencyPeriodCreate {
  /** Null for a period in another country (see `country`); required in the US. */
  state_code: string | null;
  start_milestone_id?: string | null;
  end_milestone_id?: string | null;
  start_year?: number | null;
  end_year?: number | null;
  rank?: number;
  /** Omitting it clears the period's locality: the list replaces saved periods. */
  local_tax?: LocalTaxSelection | null;
  country?: TaxCountryCode | null;
  region?: string | null;
}

// --- Milestone ---

export type ConditionMetric =
  | "net_worth"
  | "liquid_net_worth"
  | "account_balance"
  | "total_debt"
  | "annual_spending"
  | "passive_income"
  | "savings_rate";
export type MilestoneCondition =
  | { kind: "age"; owner: "self" | "spouse"; age: number }
  | { kind: "year"; year: number }
  | { kind: "date"; date: string }
  | { kind: "milestone"; milestone_id: string; offset_years?: number }
  | {
      kind: "metric";
      metric: ConditionMetric;
      account_id?: string | null;
      comparator: ">=" | "<=";
      value_unit: "dollars" | "today_dollars" | "percent" | "multiple_of_metric";
      value: number;
      other_metric?: ConditionMetric | null;
      average_years?: number;
    };
export interface MilestoneConditions {
  combinator: "all" | "any";
  items: MilestoneCondition[];
  deadline?: {
    kind: "age" | "year" | "date" | "milestone";
    value: number | string;
    owner?: "self" | "spouse";
    action: "fire" | "miss";
  } | null;
}

export interface Milestone {
  id: string;
  plan_id: string;
  name: string;
  trigger_type: MilestoneTriggerType;
  trigger_value: number | null;
  trigger_date: string | null;
  metric: "liquid_net_worth" | "net_worth" | null;
  expense_multiple: number | null;
  relative_to_id: string | null;
  offset_years: number;
  sort_order: number;
  conditions?: MilestoneConditions | null;
  /** False when switched off: kept with its details but never fires. Absent means on. */
  is_active?: boolean;
}

/** When (if ever) a milestone fired in the latest projection. */
export interface MilestoneOutcome {
  id: string;
  name: string;
  trigger_type: MilestoneTriggerType;
  year: number | null;
  missed_year?: number | null;
}

export interface MilestoneCreate {
  name: string;
  trigger_type: MilestoneTriggerType;
  trigger_value?: number | null;
  trigger_date?: string | null;
  metric?: "liquid_net_worth" | "net_worth" | null;
  expense_multiple?: number | null;
  relative_to_id?: string | null;
  offset_years?: number;
  sort_order?: number;
  conditions?: MilestoneConditions | null;
  is_active?: boolean;
}

export interface MilestoneUpdate {
  name?: string;
  trigger_type?: MilestoneTriggerType;
  trigger_value?: number | null;
  trigger_date?: string | null;
  metric?: "liquid_net_worth" | "net_worth" | null;
  expense_multiple?: number | null;
  relative_to_id?: string | null;
  offset_years?: number;
  sort_order?: number;
  conditions?: MilestoneConditions | null;
  is_active?: boolean;
}

// --- Income ---
/** Unit an income or expense amount was entered in; display only, `annual_amount` stays the wire value. */
export type AmountFrequency =
  "annual" | "quarterly" | "monthly" | "semimonthly" | "biweekly" | "weekly";
/** Income units: also "hourly", where the server sets annual_amount from hourly_rate x hours_per_week x 52. */
export type IncomeAmountFrequency = AmountFrequency | "hourly";

export type IncomeTaxCategory =
  | "employment"
  | "self_employment"
  | "qualified_pension"
  | "investment"
  | "nonqualified_annuity"
  | "other_ordinary"
  | "social_security"
  | "nontaxable";

/** How a Social Security benefit is sized. */
export type SsBenefitBasis = "amount" | "pia";

export interface PensionFormula {
  kind: "flat" | "final_average" | "career_average";
  linked_income_id?: string | null;
  benefit_percent_per_year: number;
  years_of_service_before_plan?: number;
  final_average_years?: number;
  flat_annual_amount?: number | null;
  cola_percent?: number | null;
}
export interface FilingStatusChange {
  year?: number | null;
  milestone_id?: string | null;
  filing_status: FilingStatus;
}

export type GrowthSegmentKind = "percent" | "inflation_offset" | "dollar_change" | "set_amount";

/** One calendar-year span of an income growth schedule; end_year is inclusive, null runs on. */
export interface GrowthSegment {
  start_year: number;
  end_year: number | null;
  kind: GrowthSegmentKind;
  /** Percent per year, percentage points over inflation, dollars per year, or the amount. */
  value: number;
  /** Dollar kinds only: plan-start ("today") or nominal dollars. */
  dollars: "today" | "nominal" | null;
}

/** A former spouse's Social Security record on a PIA-basis benefit. */
export interface ExSpouseRecord {
  pia_monthly: number;
  birth_year: number;
  birth_month: number;
  marriage_years: number | null;
  marriage_lasted_10_years: boolean;
  divorce_year: number;
  divorce_month: number | null;
  /** Null: the former spouse has not claimed. */
  claim_age: number | null;
  /** Null: alive. */
  death_year: number | null;
  /** Year the claimant's current marriage began; null when unknown or unmarried. */
  current_marriage_year: number | null;
  /** Null starts survivor benefits with the claimant's own claim. */
  survivor_claim_age: number | null;
}

export interface Income {
  frequency?: "recurring" | "once";
  recurrence_years?: number | null;
  pension_formula?: PensionFormula | null;
  tax_category?: IncomeTaxCategory | null;
  id: string;
  plan_id: string;
  name: string;
  annual_amount: number;
  /** Null for records saved before units were stored; omitted by older servers. */
  amount_frequency?: IncomeAmountFrequency | null;
  start_milestone_id: string | null;
  end_milestone_id: string | null;
  growth_rate: number | null;
  growth_cap: number | null;
  growth_cap_inflation_linked: boolean;
  withholding_percent: number | null;
  start_month: number | null;
  end_month: number | null;
  is_active: boolean;
  is_social_security: boolean;
  is_earned_income: boolean;
  is_self_employed: boolean;
  owner?: "self" | "spouse";
  /** Social Security only: benefits begin at this age unless a start milestone is set. */
  claiming_age?: number | null;
  /** Social Security only: null or "amount" pays annual_amount; "pia" sizes the benefit from pia_monthly. */
  ss_benefit_basis?: SsBenefitBasis | null;
  /** Monthly PIA at full retirement age, in plan-start dollars. */
  pia_reflects?: "current_record" | "continued_work";
  covered_years_to_date?: number;
  pia_monthly?: number | null;
  /** Percent (0-100) of PIA-basis benefits expected to be paid; null means 100. */
  expected_benefit_percent?: number | null;
  /** Ordered growth segments; null keeps growth_rate or curve growth. Omitted by older servers. */
  growth_schedule?: GrowthSegment[] | null;
  /** PIA-basis Social Security only: former spouse's record. Omitted by older servers. */
  ex_spouse?: ExSpouseRecord | null;
  // Hourly pay (amount_frequency "hourly"); omitted otherwise.
  hourly_rate?: number | null;
  hours_per_week?: number | null;
}

export interface IncomeCreate {
  frequency?: "recurring" | "once";
  recurrence_years?: number | null;
  pension_formula?: PensionFormula | null;
  tax_category?: IncomeTaxCategory | null;
  name: string;
  annual_amount?: number;
  amount_frequency?: IncomeAmountFrequency | null;
  start_milestone_id?: string | null;
  end_milestone_id?: string | null;
  growth_rate?: number | null;
  growth_cap?: number | null;
  growth_cap_inflation_linked?: boolean;
  withholding_percent?: number | null;
  start_month?: number | null;
  end_month?: number | null;
  is_active?: boolean;
  is_social_security?: boolean;
  is_earned_income?: boolean;
  is_self_employed?: boolean;
  owner?: "self" | "spouse";
  claiming_age?: number | null;
  ss_benefit_basis?: SsBenefitBasis | null;
  pia_reflects?: "current_record" | "continued_work";
  covered_years_to_date?: number;
  pia_monthly?: number | null;
  expected_benefit_percent?: number | null;
  growth_schedule?: GrowthSegment[] | null;
  ex_spouse?: ExSpouseRecord | null;
  // Hourly pay (amount_frequency "hourly"); omitted otherwise.
  hourly_rate?: number | null;
  hours_per_week?: number | null;
}

export interface IncomeUpdate {
  frequency?: "recurring" | "once";
  recurrence_years?: number | null;
  pension_formula?: PensionFormula | null;
  tax_category?: IncomeTaxCategory | null;
  name?: string;
  annual_amount?: number;
  amount_frequency?: IncomeAmountFrequency | null;
  start_milestone_id?: string | null;
  end_milestone_id?: string | null;
  growth_rate?: number | null;
  growth_cap?: number | null;
  growth_cap_inflation_linked?: boolean;
  withholding_percent?: number | null;
  start_month?: number | null;
  end_month?: number | null;
  is_active?: boolean;
  is_social_security?: boolean;
  is_earned_income?: boolean;
  is_self_employed?: boolean;
  owner?: "self" | "spouse";
  claiming_age?: number | null;
  ss_benefit_basis?: SsBenefitBasis | null;
  pia_reflects?: "current_record" | "continued_work";
  covered_years_to_date?: number;
  pia_monthly?: number | null;
  expected_benefit_percent?: number | null;
  growth_schedule?: GrowthSegment[] | null;
  ex_spouse?: ExSpouseRecord | null;
  // Hourly pay (amount_frequency "hourly"); omitted otherwise.
  hourly_rate?: number | null;
  hours_per_week?: number | null;
}

// --- Expense ---

export type PayrollTaxTreatment = "pre_tax" | "after_tax";

export interface Expense {
  id: string;
  plan_id: string;
  name: string;
  annual_amount: number;
  /** Null for records saved before units were stored; omitted by older servers. */
  amount_frequency?: AmountFrequency | null;
  start_milestone_id: string | null;
  end_milestone_id: string | null;
  inflation_linked: boolean;
  growth_rate: number | null;
  growth_cap: number | null;
  growth_cap_inflation_linked: boolean;
  recurrence_years: number | null;
  recurrence_growth_rate: number;
  is_payroll_deduction: boolean;
  payroll_tax_treatment: PayrollTaxTreatment;
  /** Which wage bases the deduction reduces; omitted keys keep the treatment default. */
  payroll_tax_elections?: PayrollTaxElections | null;
  tied_income_id: string | null;
  specific_funding_source_id: string | null;
  specific_funding_source_ids: string[] | null;
  start_month: number | null;
  end_month: number | null;
  category: string | null;
  /**
   * Percent (0-100) flexible spending may cut. Null keeps the category's
   * all-or-nothing meaning; when set it wins and the server rewrites
   * `category` to match (>= 50 discretionary). Omitted by older servers.
   */
  discretionary_percent?: number | null;
  /** Qualified higher education expense: 529 withdrawals up to it are tax free. */
  qualified_education?: boolean;
}

/** Explicit wage-base elections for a payroll deduction; an omitted key keeps the default. */
export interface PayrollTaxElections {
  federal?: boolean;
  state?: boolean;
  local?: boolean;
  fica?: boolean;
}

export interface ExpenseCreate {
  name: string;
  annual_amount?: number;
  amount_frequency?: AmountFrequency | null;
  start_milestone_id?: string | null;
  end_milestone_id?: string | null;
  inflation_linked?: boolean;
  growth_rate?: number | null;
  growth_cap?: number | null;
  growth_cap_inflation_linked?: boolean;
  recurrence_years?: number | null;
  recurrence_growth_rate?: number;
  is_payroll_deduction?: boolean;
  payroll_tax_treatment?: PayrollTaxTreatment;
  /** Which wage bases the deduction reduces; omitted keys keep the treatment default. */
  payroll_tax_elections?: PayrollTaxElections | null;
  tied_income_id?: string | null;
  specific_funding_source_id?: string | null;
  specific_funding_source_ids?: string[] | null;
  start_month?: number | null;
  end_month?: number | null;
  category?: string | null;
  discretionary_percent?: number | null;
  qualified_education?: boolean;
}

export interface ExpenseUpdate {
  expected_values?: Partial<ExpenseCreate>;
  name?: string;
  annual_amount?: number;
  amount_frequency?: AmountFrequency | null;
  start_milestone_id?: string | null;
  end_milestone_id?: string | null;
  inflation_linked?: boolean;
  growth_rate?: number | null;
  growth_cap?: number | null;
  growth_cap_inflation_linked?: boolean;
  recurrence_years?: number | null;
  recurrence_growth_rate?: number;
  is_payroll_deduction?: boolean;
  payroll_tax_treatment?: PayrollTaxTreatment;
  /** Which wage bases the deduction reduces; omitted keys keep the treatment default. */
  payroll_tax_elections?: PayrollTaxElections | null;
  tied_income_id?: string | null;
  specific_funding_source_id?: string | null;
  specific_funding_source_ids?: string[] | null;
  start_month?: number | null;
  end_month?: number | null;
  category?: string | null;
  discretionary_percent?: number | null;
  qualified_education?: boolean;
}

// --- Account ---
export interface InheritanceSettings {
  distribution_method?: "automatic" | "life_expectancy" | "ten_year" | "spousal_rollover";
  decedent_birth_year?: number | null;
  decedent_died_after_rbd?: boolean | null;
  beneficiary_is_minor_child?: boolean;
  year_of_death_rmd_remaining?: number;
}
export interface RothSettings {
  contribution_basis: number;
  first_contribution_year: number | null;
  conversions: { year: number; taxable_basis: number; nontaxable_basis: number }[];
}

/** Tax character of bond income as fractions that add up to 1. */
export interface BondIncomeMix {
  treasury: number;
  municipal: number;
  other: number;
}

/** Decimal fixed overrides; null inherits the plan assumption. */
export interface AccountInvestmentSettings {
  stock_growth_rate: number | null;
  dividend_yield: number | null;
  bond_allocation: number | null;
  /** Share of stock dividends that are qualified; null = all qualified. Taxable accounts only. */
  qualified_dividend_ratio?: number | null;
  /** Bond income as a share of the bond sleeve, carved out of bond return; null = none. */
  bond_income_yield?: number | null;
  /** Tax character of bond income; null = all other (taxable) interest. */
  bond_income_mix?: BondIncomeMix | null;
  /** Municipal interest is also exempt from the plan's state tax; null = no. */
  municipal_state_exempt?: boolean | null;
  /** Yearly expense ratio plus advisory fee (0-0.05), charged on the opening balance; null = no fee. */
  annual_fee_rate?: number | null;
  /** Bond share over time (linear between points); replaces bond_allocation. [] clears it. */
  bond_allocation_glide?: BondGlidePoint[] | null;
  /** Flat annual fee in today's dollars, indexed with inflation; null = none. */
  annual_fee_amount?: number | null;
  /** Fee as a decimal share of the year's positive growth; null = none. */
  fee_percent_of_earnings?: number | null;
  /** Taxable brokerage only: false pays dividends and interest to cash (still taxed). Null = true. */
  reinvest_income?: boolean | null;
}

/** One account glide path point: exactly one of `year` or the owner's `age`. */
export interface BondGlidePoint {
  year?: number | null;
  age?: number | null;
  bond_allocation: number;
}

/**
 * When voluntary withdrawals from an account may start; null: any time.
 * Exactly the field `unlock` names is set. `age` is the owner's age (a joint
 * account uses the primary person). RMDs are still taken while locked.
 */
export interface WithdrawalLock {
  unlock: "age" | "milestone" | "year";
  age?: number | null;
  milestone_id?: string | null;
  year?: number | null;
}

/** Per-account distribution facts: Rule of 55 separation year, spouse as sole beneficiary (RMD table). */
export interface AccountDistributionSettings {
  /** Calendar year of separation from the employer that sponsors this 401(k)/403(b)/401(a). */
  separation_year?: number | null;
  spouse_sole_beneficiary?: boolean;
}

export interface Account {
  distribution_settings?: AccountDistributionSettings | null;
  withdrawal_lock?: WithdrawalLock | null;
  inherited_year?: number | null;
  beneficiary_type?: "spouse" | "edb" | "non_edb";
  inheritance_settings?: InheritanceSettings | null;
  roth_settings?: RothSettings | null;
  investment_settings?: AccountInvestmentSettings | null;
  plan_id?: string | null;
  id: string;
  user_id: string;
  name: string;
  account_type: AccountType;
  balance: number;
  owner: string;
  cost_basis?: number | null;
  /** Contributions the state of residence already taxed (traditional retirement accounts). */
  state_taxed_basis?: number | null;
  /** "<CC>:<kind_id>" from the registry; null for a US account type. */
  intl_account_kind?: string | null;
  /** Liquid net worth override: null/omitted is liquid unless withdrawal-locked; true always; false never. */
  include_in_liquid?: boolean | null;
}

export interface AccountCreate {
  distribution_settings?: AccountDistributionSettings | null;
  withdrawal_lock?: WithdrawalLock | null;
  inherited_year?: number | null;
  beneficiary_type?: "spouse" | "edb" | "non_edb";
  inheritance_settings?: InheritanceSettings | null;
  roth_settings?: RothSettings | null;
  investment_settings?: AccountInvestmentSettings | null;
  name: string;
  account_type: AccountType;
  balance?: number;
  owner?: string;
  cost_basis?: number | null;
  state_taxed_basis?: number | null;
  intl_account_kind?: string | null;
  include_in_liquid?: boolean | null;
}

export interface AccountUpdate {
  distribution_settings?: AccountDistributionSettings | null;
  withdrawal_lock?: WithdrawalLock | null;
  inherited_year?: number | null;
  beneficiary_type?: "spouse" | "edb" | "non_edb";
  inheritance_settings?: InheritanceSettings | null;
  roth_settings?: RothSettings | null;
  investment_settings?: AccountInvestmentSettings | null;
  name?: string;
  account_type?: AccountType;
  balance?: number;
  owner?: string;
  cost_basis?: number | null;
  state_taxed_basis?: number | null;
  intl_account_kind?: string | null;
  include_in_liquid?: boolean | null;
}

// --- Real Asset ---
export type AssetTaxTreatment = "unspecified" | "personal_use" | "investment" | "rental";
export type RentalPropertyClass = "residential" | "nonresidential";

/**
 * Planned purchase, selling-cost, rental and home-sale fields. All optional;
 * blank keeps the earlier behavior. Dollar amounts are today's dollars; rates
 * are decimals except purchase_loan_rate, an annual percent like a liability.
 */
export interface RealEstateSettings {
  purchase_year?: number | null;
  purchase_month?: number | null;
  purchase_price?: number | null;
  down_payment_amount?: number | null;
  down_payment_rate?: number | null;
  closing_costs?: number | null;
  purchase_funding_account_id?: string | null;
  purchase_loan_rate?: number | null;
  purchase_loan_term_months?: number | null;
  selling_cost_rate?: number | null;
  rental_income?: number | null;
  /** Blank follows inflation. */
  rental_income_growth_rate?: number | null;
  rental_expenses?: number | null;
  /** Share of collected rent; replaces rental_expenses when set. */
  rental_expense_rate?: number | null;
  vacancy_rate?: number | null;
  rental_property_class?: RentalPropertyClass | null;
  land_value_rate?: number | null;
  building_basis?: number | null;
  prior_depreciation?: number | null;
  qbi_eligible?: boolean;
  rental_active_participation?: boolean;
  suspended_passive_loss?: number | null;
  owned_since_year?: number | null;
  owned_since_month?: number | null;
  primary_residence_since_year?: number | null;
  primary_residence_since_month?: number | null;
  /**
   * Mixed use (rentals): share of the property rented out, a decimal. Blank
   * means fully rented. Rent and fixed rental expenses are entered as if the
   * whole property were rented and are scaled by the share.
   */
  rental_use_rate?: number | null;
  /** Steps that change the rental share from a given year on. */
  rental_use_schedule?: RentalUseStep[] | null;
}

export interface RentalUseStep {
  year: number;
  /** Decimal share rented out from this year on. */
  rate: number;
}

export interface RealAsset extends RealEstateSettings {
  tax_treatment?: AssetTaxTreatment;
  adjusted_basis?: number | null;
  id: string;
  plan_id: string;
  name: string;
  current_value: number;
  annual_appreciation_rate: number;
  is_primary_residence: boolean;
  auto_liquidate_on_depletion: boolean;
  liquidation_target_account_id: string | null;
  annual_property_tax: number;
  annual_maintenance: number;
  property_tax_rate: number | null;
  maintenance_rate: number | null;
  insurance_rate: number | null;
  sale_year: number | null;
  sale_month: number;
}

export interface RealAssetCreate extends RealEstateSettings {
  tax_treatment?: AssetTaxTreatment;
  adjusted_basis?: number | null;
  name: string;
  current_value: number;
  annual_appreciation_rate?: number;
  is_primary_residence?: boolean;
  auto_liquidate_on_depletion?: boolean;
  liquidation_target_account_id?: string | null;
  annual_property_tax?: number;
  annual_maintenance?: number;
  property_tax_rate?: number | null;
  maintenance_rate?: number | null;
  insurance_rate?: number | null;
  sale_year?: number | null;
  sale_month?: number;
}

export interface RealAssetUpdate extends RealEstateSettings {
  tax_treatment?: AssetTaxTreatment;
  adjusted_basis?: number | null;
  name?: string;
  current_value?: number;
  annual_appreciation_rate?: number;
  is_primary_residence?: boolean;
  auto_liquidate_on_depletion?: boolean;
  liquidation_target_account_id?: string | null;
  annual_property_tax?: number;
  annual_maintenance?: number;
  property_tax_rate?: number | null;
  maintenance_rate?: number | null;
  insurance_rate?: number | null;
  sale_year?: number | null;
  sale_month?: number;
}

// --- Liability ---

export type PaymentType = "fixed" | "percent_of_balance" | "custom";

/** IRC 108(a)(1) grounds the user may declare; the plan records the declaration only. */
export type ForgivenessExclusionBasis =
  | "bankruptcy"
  | "insolvency"
  | "qualified_farm_debt"
  | "qualified_real_property_business_debt"
  | "qualified_principal_residence"
  | "other_declared";

/** One-time cancellation of a loan, fired by a year or a milestone (exactly one). */
export interface LiabilityForgiveness {
  year?: number | null;
  milestone_id?: string | null;
  /** Omitted cancels the whole remaining balance. */
  amount?: number | null;
  /** Forgiven debt is taxable income unless the user declares an exclusion. */
  tax_treatment?: "taxable" | "declared_exclusion";
  /** With a declared exclusion: omitted declares all of the cancelled amount excluded. */
  excluded_amount?: number | null;
  exclusion_basis?: ForgivenessExclusionBasis | null;
}

export interface Liability {
  id: string;
  plan_id: string;
  name: string;
  principal_balance: number;
  interest_rate: number;
  term_months: number | null;
  monthly_payment: number | null;
  payment_type: PaymentType;
  extra_payment: number;
  payoff_milestone_id: string | null;
  offset_account_id: string | null;
  linked_asset_id: string | null;
  forgiveness?: LiabilityForgiveness | null;
  // Repeat and interest options; omitted by the server at their defaults (monthly, no repeat).
  interest_method?: InterestMethod;
  /** Take the loan again every N years on its original terms (start-year dollars). */
  recurrence_years?: number | null;
  /** Last calendar year an occurrence can start. */
  recurrence_end_year?: number | null;
  /** No occurrence starts once this milestone is reached. */
  recurrence_end_milestone_id?: string | null;
}

export interface LiabilityCreate {
  name: string;
  principal_balance: number;
  interest_rate: number;
  term_months?: number | null;
  monthly_payment?: number | null;
  payment_type?: PaymentType;
  extra_payment?: number;
  payoff_milestone_id?: string | null;
  offset_account_id?: string | null;
  linked_asset_id?: string | null;
  forgiveness?: LiabilityForgiveness | null;
  interest_method?: InterestMethod;
  /** Take the loan again every N years on its original terms (start-year dollars). */
  recurrence_years?: number | null;
  /** Last calendar year an occurrence can start. */
  recurrence_end_year?: number | null;
  /** No occurrence starts once this milestone is reached. */
  recurrence_end_milestone_id?: string | null;
}

export interface LiabilityUpdate {
  name?: string;
  principal_balance?: number;
  interest_rate?: number;
  term_months?: number | null;
  monthly_payment?: number | null;
  payment_type?: PaymentType;
  extra_payment?: number;
  payoff_milestone_id?: string | null;
  offset_account_id?: string | null;
  linked_asset_id?: string | null;
  forgiveness?: LiabilityForgiveness | null;
  interest_method?: InterestMethod;
  /** Take the loan again every N years on its original terms (start-year dollars). */
  recurrence_years?: number | null;
  /** Last calendar year an occurrence can start. */
  recurrence_end_year?: number | null;
  /** No occurrence starts once this milestone is reached. */
  recurrence_end_milestone_id?: string | null;
}

// --- Cash Flow Priority ---

export interface AllocationFields {
  allocation_mode?: "remaining" | "percentage" | "amount";
  allocation_value?: number | null;
}

/** One band of a match formula, 0..100 percents: match_percent of deferrals on the next up_to_percent_of_pay of pay. */
export interface EmployerMatchTier {
  match_percent: number;
  up_to_percent_of_pay: number;
}

/** Employer contribution formula on an income_percent payroll rule. */
export interface EmployerMatch {
  tiers: EmployerMatchTier[];
  /** Annual cap in today's dollars, indexed with inflation. */
  cap_amount?: number | null;
  /** Percent of pay contributed regardless of employee deferrals. */
  nonelective_percent?: number;
  /** Annualize the match; false matches each pay period. */
  true_up?: boolean;
  /** Employer money goes to the owner's Roth account in the same plan. */
  roth?: boolean;
}

export type ContributionLimitMode = "irs" | "custom";

export interface CashFlowPriority extends AllocationFields {
  id: string;
  plan_id: string;
  priority_rank: number;
  target_account_id: string | null;
  /** debt_payment rules: the loan paid down. */
  target_liability_id?: string | null;
  max_annual_amount: number | null;
  priority_type: string | null;
  source_account_id: string | null;
  source_income_id: string | null;
  employee_rate: number;
  employer_match_rate: number;
  target_balance: number | null;
  conversion_mode?: "fixed" | "fill_bracket";
  /** Decimal federal bracket rate, e.g. 0.22. */
  bracket_ceiling_rate?: number | null;
  magi_cap?: number | null;
  /** Roth IRA rules: nondeductible IRA contribution converted at once; skips the income phaseout. */
  backdoor_roth?: boolean;
  /** Conversion / harvest rules: size from the plan tax target instead of the rule's own ceiling. */
  use_plan_tax_target?: boolean;
  start_milestone_id?: string | null;
  end_milestone_id?: string | null;
  /** Payroll rules: replaces employer_match_rate when set. */
  employer_match?: EmployerMatch | null;
  limit_mode?: ContributionLimitMode;
  /** With limit_mode "custom": a lower annual ceiling in today's dollars. */
  custom_annual_limit?: number | null;
  /** Contribution, payroll and debt payment rules: run ahead of other surplus rules and draw any surplus shortfall from the withdrawal order. Older services omit it (false). */
  withdraw_if_short?: boolean;
  /** income_percent rules funded with income: cut a flat employer rate in proportion when pay cannot fund the elected deferral. */
  reduce_employer_contribution?: boolean;
  transfer_frequency?: TransferFrequency;
}

export interface CashFlowPriorityCreate extends AllocationFields {
  priority_rank: number;
  target_account_id?: string | null;
  target_liability_id?: string | null;
  max_annual_amount?: number | null;
  priority_type?: string | null;
  source_account_id?: string | null;
  source_income_id?: string | null;
  employee_rate?: number;
  employer_match_rate?: number;
  target_balance?: number | null;
  conversion_mode?: "fixed" | "fill_bracket";
  bracket_ceiling_rate?: number | null;
  magi_cap?: number | null;
  backdoor_roth?: boolean;
  use_plan_tax_target?: boolean;
  start_milestone_id?: string | null;
  end_milestone_id?: string | null;
  employer_match?: EmployerMatch | null;
  limit_mode?: ContributionLimitMode;
  custom_annual_limit?: number | null;
  withdraw_if_short?: boolean;
  reduce_employer_contribution?: boolean;
  transfer_frequency?: TransferFrequency;
}

// --- Drawdown Order ---

export interface DrawdownEntry {
  id: string;
  plan_id: string;
  rank: number;
  source_account_id: string | null;
}

export interface DrawdownEntryCreate {
  rank: number;
  source_account_id?: string | null;
}

// --- Assumption Curve ---

export interface ControlPoint {
  x: number;
  y: number;
}

export interface AssumptionCurve {
  id: string;
  plan_id: string;
  curve_type: CurveType;
  mode: CurveMode;
  fixed_rate: number | null;
  control_points: ControlPoint[];
}

export interface AssumptionCurveCreate {
  curve_type: CurveType;
  mode?: CurveMode;
  fixed_rate?: number | null;
  control_points?: ControlPoint[];
}

export interface AssumptionCurveUpdate {
  curve_type?: CurveType;
  mode?: CurveMode;
  fixed_rate?: number | null;
  control_points?: ControlPoint[];
}

// --- Spouse ---

export interface Spouse {
  id: string;
  plan_id: string;
  name: string | null;
  birth_year: number | null;
  birth_month?: number | null;
  life_expectancy: number | null;
  income_streams: unknown[];
  retirement_milestone_id: string | null;
}

// --- Plan ---

export interface PlanData {
  filing_status_changes?: FilingStatusChange[] | null;
  profile_name?: string | null;
  client_id?: string | null;
  /** Set on a scenario: the Main plan whose changes it receives. Absent and null both mean an ordinary plan. */
  parent_plan_id?: string | null;
  priorities_revision?: number;
  id: string;
  user_id: string;
  name: string;
  plan_type: PlanType;
  start_date: string | null;
  snapshot_conditions: Record<string, unknown>;
  birth_year: number;
  birth_month?: number | null;
  filing_status: FilingStatus;
  state_code: string | null;
  /** Locality of state_code; residency periods carry their own. Older services omit this. */
  local_tax?: LocalTaxSelection | null;
  life_expectancy: number;
  created_at: string;
  // Edit-window fields are decided by the server; clients only format them.
  // Older services omit them.
  archived_at?: string | null;
  edit_window_ends_at?: string | null;
  edit_notice_seen_at?: string | null;
  edit_grace_ends_at?: string | null;
  /** Null where the route did not evaluate it. */
  editable?: boolean | null;
  milestones: Milestone[];
  income_streams: Income[];
  expenses: Expense[];
  priorities: CashFlowPriority[];
  drawdown_order: DrawdownEntry[];
  assumption_curves: AssumptionCurve[];
  /** Decimal engine defaults; saved curves take precedence. Older services omit this. */
  assumption_defaults?: Partial<Record<CurveType, number>>;
  real_assets: RealAsset[];
  liabilities: Liability[];
  residency_periods: ResidencyPeriod[];
  spouse: Spouse | null;
  sepp_settings: SEPPSettings | null;
  cash_reserve_settings?: CashReserveSettings | null;
  spending_rules: SpendingRules | null;
  tax_settings: TaxSettings | null;
  estate_settings: EstateSettings | null;
  /** Plain-text assumptions record. */
  notes?: string | null;
  healthcare_settings?: HealthcareSettings | null;
  withdrawal_strategy?: WithdrawalStrategySettings | null;
  // International plans: a missing value means a US plan in USD.
  tax_country?: TaxCountryCode;
  tax_region?: string | null;
  /** ISO 4217; display only. */
  currency?: string;
  intl_settings?: IntlSettings | null;
  /** Backend PlanRead.baseline_plan_id (app/schemas/plan.py); the plan's saved comparison baseline. */
  baseline_plan_id: string | null;
}

export type PlanSummary = Pick<
  PlanData,
  "id" | "client_id" | "name" | "plan_type" | "created_at" | "parent_plan_id"
>;

/** GET /plans/archived: identity only. Restoring one is subject to the access policy. */
export interface ArchivedPlanSummary {
  id: string;
  client_id: string | null;
  name: string;
  created_at: string;
  archived_at: string;
}

export interface PlanCreate {
  filing_status_changes?: FilingStatusChange[] | null;
  profile_name?: string | null;
  client_id?: string | null;
  name: string;
  plan_type?: PlanType;
  start_date?: string | null;
  snapshot_conditions?: Record<string, unknown>;
  birth_year: number;
  birth_month?: number | null;
  filing_status?: FilingStatus;
  state_code?: string | null;
  /** Sending state_code alone clears a saved locality from another state. */
  local_tax?: LocalTaxSelection | null;
  life_expectancy?: number;
  sepp_settings?: SEPPSettings | null;
  cash_reserve_settings?: CashReserveSettings | null;
  spending_rules?: SpendingRules | null;
  tax_settings?: TaxSettings | null;
  estate_settings?: EstateSettings | null;
  spouse?: SpouseUpdate | null;
  notes?: string | null;
  healthcare_settings?: HealthcareSettings | null;
  withdrawal_strategy?: WithdrawalStrategySettings | null;
  residency_periods?: ResidencyPeriodCreate[];
  /** Seeds an age-triggered "Retirement" milestone unless the plan starts at or after that age. */
  retirement_milestone_age?: number | null;
  tax_country?: TaxCountryCode;
  tax_region?: string | null;
  currency?: string;
  intl_settings?: IntlSettings | null;
  /** Backend PlanUpdate.baseline_plan_id (app/schemas/plan.py); omit to leave it unchanged. */
  baseline_plan_id?: string | null;
}

/**
 * New-plan goals (POST /plans/{id}/intake). Every answer is optional; null leaves
 * the plan unchanged. Spending and travel are annual, in today's dollars; giving is
 * annual and nominal. Resubmitting updates the items the intake named.
 */
export interface PlanIntake {
  retirement_age?: number | null;
  retirement_spending?: number | null;
  travel_budget?: number | null;
  travel_until_age?: number | null;
  charitable_giving?: number | null;
  /** Today's dollars; saved as estate_settings.legacy_target. */
  legacy_target?: number | null;
}

// --- Cash Flow Breakdown (Sankey data) ---

export interface TransferFlow {
  source_account_id: string;
  target_account_id: string;
  amount: number;
  source_account_name: string | null;
  target_account_name: string | null;
}

export interface NamedAmount {
  account_id?: string | null;
  account_name?: string | null;
  source?:
    "priority" | "payroll" | "employer" | "default_sink" | "reinvestment" | "rmd" | "sepp" | null;
  priority_rank?: number | null;
  requested_amount?: number | null;
  limited_by?: string[];
  funding_reasons?: (
    | "insufficient_surplus"
    | "earlier_rules"
    | "ownership"
    | "income_eligibility"
    | "compensation"
    | "contribution_limit"
    | "annual_maximum"
    | "target_balance"
    | "zero_request"
    | "inactive_rule"
    | "loan_paid_off"
    | "withdrawal_shortfall"
  )[];
  name: string;
  amount: number;
  category: string | null;
  /** Expense rows with a discretionary percent only: the discretionary part of `amount`; the rest is essential. */
  discretionary_amount?: number;
}

export type CashFlowGroup = "income" | "tax" | "saving" | "spending" | "shortfall" | "hub";

/** `id` is stable from year to year: hub:gross, hub:cash, income:<name>, to:<account id>, tax:taxes… */
export interface CashFlowNode {
  id: string;
  name: string;
  group: CashFlowGroup;
}

export interface CashFlowLink {
  source: string;
  target: string;
  amount: number;
}

/** The year as a Sankey graph, routed by the service: sources → Gross income → After-tax cash → destinations. */
export interface CashFlowGraph {
  nodes: CashFlowNode[];
  links: CashFlowLink[];
}

export interface CashFlowBreakdown {
  income_sources: NamedAmount[];
  gross_income: number;
  tax_withheld: number;
  payroll_deductions: number;
  net_pay: number;
  early_withdrawal_penalty?: number;
  /** Balance at filing (refund positive), after any estimated payments. */
  tax_delta: number;
  expenses: NamedAmount[];
  /** Expenses deducted from pay, included in payroll_deductions; omitted when empty. */
  payroll_expenses?: NamedAmount[];
  contributions: NamedAmount[];
  transfers: TransferFlow[];
  drawdowns: NamedAmount[];
  /** Older services and hand-built fixtures omit it. */
  graph?: CashFlowGraph;
  /** Estimated-tax figures; the service omits each one when it is zero. */
  estimated_tax_payments?: number;
  required_annual_payment?: number;
  /** Included in the year's taxes; a separate outflow from tax_delta. */
  underpayment_penalty?: number;
}

// --- Simulation ---

export interface YearSnapshot {
  tax_balance?: number;
  unfunded_expenses?: number;
  capital_loss_carryforward?: number;
  /** Cumulative plan inflation applied this year; first year 1.0 (same anchor as buildDeflators). Older services omit it. */
  inflation_factor?: number | null;
  year: number;
  age: number;
  gross_income: number;
  taxes: number;
  federal_tax: number;
  state_tax: number;
  local_tax?: number;
  /** State retirement-income subtraction already taken in computing state_tax. Older services omit it. */
  state_retirement_exclusion?: number;
  /** State subtraction of federally taxable Social Security behind state_tax. Older services omit it. */
  ss_earnings_test_withheld?: number;
  state_social_security_subtraction?: number;
  /** State capital gains excise (Washington), included in state_tax. Older services omit it. */
  state_capital_gains_excise?: number;
  /** User tax adjustments behind taxes: federal deductions taken, credits used (including any refunded part) and surcharges added. Older services omit them. */
  tax_adjustment_deductions?: number;
  tax_adjustment_credits?: number;
  tax_adjustment_surcharge?: number;
  /** Rental properties: collected rent, cash expenses (operating, property tax and upkeep, loan interest), depreciation, the net amount in AGI after passive loss rules and suspended losses carried forward. Older services omit them. */
  rental_income?: number;
  rental_expenses?: number;
  rental_depreciation?: number;
  rental_taxable_income?: number;
  suspended_passive_losses?: number;
  /** Real property sale gain from depreciation, taxed at no more than 25%. */
  unrecaptured_section_1250_gain?: number;
  /** Cash paid for planned purchases (down payment or price, plus closing costs). */
  real_estate_purchases?: number;
  /** Withdraw-if-short rule amounts, within their limits, that neither surplus nor withdrawals could fund. Not unfunded spending. Older services omit it. */
  rule_funding_shortfall?: number;
  /** Calendar-year income basis used by full-year tax lines and effective_rate. */
  calendar_year_gross_income?: number | null;
  niit_tax?: number;
  amt_tax?: number;
  early_withdrawal_penalty?: number;
  capital_gains_tax: number;
  fica_tax: number;
  expenses: number;
  net_cash_flow: number;
  accounts: Record<string, number>;
  real_assets_value: number;
  liabilities_balance: number;
  /** Loan principal cancelled this year (a debt forgiveness event); no cash arrives. */
  debt_forgiven?: number;
  /** The part of the cancelled debt counted as taxable income. */
  debt_forgiveness_taxable?: number;
  net_worth: number;
  effective_rate: number;
  marginal_rate: number;
  deduction_used: string;
  deduction_amount: number;
  standard_deduction: number;
  flex_spending_reduction: number;
  /** Extra spending from an upside multiplier above 1; absent from older responses. */
  flex_spending_increase?: number;
  /** Surplus cash counted as spending (surplus_mode "spend_leftover"); absent from older responses. */
  leftover_spending?: number;
  /** Backend YearSnapshot.strategy_spending (coastmath/schemas/simulation.py); withdrawal-strategy spending that replaced planned expenses, null without a strategy. */
  strategy_spending: number | null;
  /** Backend YearSnapshot.planned_expenses (coastmath/schemas/simulation.py); the plan's own ordinary expenses the strategy replaced, null without a strategy. */
  planned_expenses: number | null;
  investment_growth: number;
  /** Account fees deducted this year; already netted out of investment_growth. Absent from older responses. */
  investment_fees?: number;
  milestones_triggered: string[];
  healthcare?: HealthcareYear | null;
  harvested_gains?: number;
  /** Room below the year's effective tax target before target-sized strategies; absent without a target. */
  tax_target_room?: number | null;
  /** Gross shortfall withdrawals taken by the tax-target first pass; absent when zero. */
  tax_target_blended_withdrawals?: number;
  /** Household asset location: each pooled account's bond share this year; empty in per-account mode. */
  bond_allocation_by_account?: Record<string, number>;
  transfers: TransferFlow[];
  cash_flow: CashFlowBreakdown | null;
  /** Opening-year full-year tax liability less taxes paid before plan start; signed for a refund. */
  post_start_taxes?: number | null;
  /** Stable codes for the year's modeling basis, e.g. "ytd_imputed_pro_rata". */
  warnings?: string[];
  /** The country whose regime taxed this year. */
  tax_country?: TaxCountryCode;
  /** Empty in US years. */
  intl_tax_lines?: IntlTaxLine[];
  /** Zero in US years; all included in `taxes`. */
  national_income_tax?: number;
  regional_income_tax?: number;
  social_contributions?: number;
  wealth_tax?: number;
  transaction_tax?: number;
  benefit_recovery_tax?: number;
}

/** Client-derived compare series (NetWorthChart, CompareOverlay); the wire row is CompareYearDelta. */
export interface YearDelta {
  year: number;
  currentNetWorth: number;
  baselineNetWorth: number;
  delta: number;
}

/** Wire row of CompareResponse.delta (backend coastmath/schemas/simulation.py YearDelta). */
export interface CompareYearDelta {
  year: number;
  current_net_worth: number;
  baseline_net_worth: number;
  /** current_net_worth - baseline_net_worth. */
  difference: number;
}

export interface SimMetadata {
  start_date?: string | null;
  first_year_fraction?: number;
  warnings?: string[];
  plan_id: string;
  start_year: number;
  end_year: number;
  success: boolean;
  failure_year: number | null;
  net_legacy: NetLegacy | null;
  milestone_outcomes?: MilestoneOutcome[];
  /** CoastMath's FI estimate, computed by the engine; absent from older servers. */
  fi_estimate?: FiEstimate | null;
  rmd_start_age: number | null;
  /** Backend SimMetadata.locked_sections (coastmath/schemas/simulation.py); always empty. */
  locked_sections?: string[];
}

/**
 * The year a 25× liquid-minus-debt expense-multiple milestone would fire.
 * `target` is in `basis_year` nominal dollars; all three are null when the
 * projection never reaches it.
 */
export interface FiEstimate {
  year: number | null;
  basis_year: number | null;
  target: number | null;
  multiple: number;
}

export interface SimulationResult {
  initial_snapshot?: {
    as_of: string;
    accounts: Record<string, number>;
    real_assets_value: number;
    liabilities_balance: number;
    net_worth: number;
  } | null;
  metadata: SimMetadata;
  yearly_snapshots: YearSnapshot[];
}

export interface CompareResponse {
  current: SimulationResult;
  baseline: SimulationResult;
  delta: CompareYearDelta[];
}

// --- Historical Stress Test ---

export interface HistoricalStressMetadata {
  historical_start_year: number;
  years_used: number[];
  wrapped: boolean;
}

export interface HistoricalStressResult {
  simulation_result: SimulationResult;
  metadata: HistoricalStressMetadata;
}

export type ScenarioStressPreset =
  "job_loss" | "market_crash" | "tech_bust" | "new_child" | "downturn";

export interface ScenarioStressRequest {
  preset: ScenarioStressPreset;
  start_year: number;
  person?: "self" | "spouse";
  months_without_pay?: number;
  resume_percent?: number;
  stock_drop_percent?: number;
  /** Plan-start-year dollars, inflation-linked. */
  child_annual_cost?: number;
  /** downturn: stock_drop_percent is the cumulative decline over these years (1–10). */
  downturn_years?: number;
  /** downturn: years back to the pre-downturn stock level (0–10). */
  recovery_years?: number;
  /** downturn years only; omitted = the plan's assumption. */
  bond_return_percent?: number;
  inflation_percent?: number;
}

/** One shocked year, decimal rates; stock_return is before partial-year annualization. */
export interface DownturnPathYear {
  year: number;
  stock_return: number;
  bond_return: number;
  inflation: number;
  phase: "downturn" | "recovery";
}

export interface ScenarioStressMetadata {
  preset: ScenarioStressPreset;
  start_year: number;
  person: "self" | "spouse" | null;
  months_without_pay: number | null;
  resume_percent: number | null;
  stock_drop_percent: number | null;
  child_annual_cost: number | null;
  child_cost_years: number | null;
  downturn_years?: number | null;
  recovery_years?: number | null;
  bond_return_percent?: number | null;
  inflation_percent?: number | null;
  downturn_path?: DownturnPathYear[] | null;
}

export interface ScenarioStressResult {
  simulation_result: SimulationResult;
  metadata: ScenarioStressMetadata;
}

// --- Monte Carlo ---

export interface FailureDetail {
  trial_index: number;
  failure_year: number;
  failure_age: number;
  cause: string;
  net_worth_at_failure: number;
}

export interface PercentileCurves {
  years: number[];
  p10: number[];
  p25: number[];
  p50: number[];
  p75: number[];
  p90: number[];
}

export interface SuccessTargets {
  /** Nominal dollars in the final projection year. */
  terminal_net_worth_min: number | null;
  count_spending_cuts_as_shortfall: boolean;
}

export interface OutcomeCategory {
  key: string;
  label: string;
  definition: string;
  count: number;
  rate: number;
}

export interface MilestoneDistribution {
  id: string;
  name: string;
  reached_trials: number;
  unreached_trials: number;
  unreported_trials: number;
  reach_rate: number | null;
  year_counts: Record<string, number>;
  p10_year: number | null;
  median_year: number | null;
  p90_year: number | null;
}

export type MonteCarloSamplingMethod =
  "block_bootstrap" | "moving_block" | "historical_sequential" | "random_start" | "random_years";
export type MonteCarloExtraMetric = "liquid_net_worth" | "spending" | "taxes" | "income";

/** Failed trials by the share of the projection completed before the failure year. */
export interface FailureTiming {
  early_fraction: number;
  late_fraction: number;
  early: number;
  mid: number;
  late: number;
  /** Shares of failed trials. */
  early_rate: number;
  mid_rate: number;
  late_rate: number;
}

/** Successful trials by final net worth relative to net worth at retirement (today's dollars). */
export interface SurplusClasses {
  thin_margin_percent: number;
  wide_margin_percent: number;
  reference_milestone_id: string | null;
  reference_milestone_name: string | null;
  thin_margin: number;
  moderate_margin: number;
  wide_margin: number;
  /** Shares of successful trials. */
  thin_margin_rate: number;
  moderate_margin_rate: number;
  wide_margin_rate: number;
}

export interface OutcomeDetail {
  failure_timing: FailureTiming;
  surplus: SurplusClasses;
  definitions: Record<string, string>;
}

export interface MonteCarloResult {
  /** Funding success rate: trials with no failure under the chosen failure mode. */
  success_rate: number;
  n_trials: number;
  percentile_curves: PercentileCurves;
  failure_analysis: FailureDetail[];
  median_final_net_worth: number;
  p10_final_net_worth: number;
  p90_final_net_worth: number;
  funding_success_rate?: number;
  target_success_rate?: number | null;
  outcome_categories?: OutcomeCategory[];
  success_targets?: SuccessTargets | null;
  definitions?: Record<string, string>;
  milestone_distributions?: MilestoneDistribution[];
  /** Trial 0's seed; trial i uses base_seed + i. Absent from older servers. */
  base_seed?: number | null;
  /** Per-trial summaries. Absent from older servers and stored results. */
  trials?: TrialSummaries | null;
  /** Sampling method the run used. Absent from older servers. */
  sampling?: MonteCarloSamplingMethod | null;
  outcome_detail?: OutcomeDetail | null;
  /** Per-year percentiles of requested extra metrics, nominal dollars. */
  metric_percentiles?: Partial<Record<MonteCarloExtraMetric, PercentileCurves>> | null;
  /** Backend MonteCarloResult.distributions_locked (coastmath/schemas/monte_carlo.py); always false. */
  distributions_locked?: boolean;
}

/** Parallel arrays: position i in every column describes trial index i. */
export interface TrialSummaries {
  success: boolean[];
  /** First failed year; null for a successful trial. */
  failure_year: (number | null)[];
  /** Nominal net worth in the final projection year. */
  ending_net_worth: number[];
  ending_liquid: number[];
  /** An `outcome_categories` key. */
  outcome: string[];
  /** Milestone id to the year it fired per trial; null when not reached. */
  milestone_years: Record<string, (number | null)[]>;
  start_year: number;
  /** The primary person's age in `start_year`. */
  start_age: number;
  sparkline_years: number[];
  /** Nominal net worth at `sparkline_years`, rounded to three significant figures. */
  sparklines: number[][];
}

/** One trial replayed exactly, with its full projection. */
export interface MonteCarloTrialDetail {
  index: number;
  seed: number;
  success: boolean;
  failure: FailureDetail | null;
  outcome: string;
  ending_net_worth: number;
  ending_liquid: number;
  milestone_years: Record<string, number | null>;
  simulation: SimulationResult;
  /** First historical year of a chronological trial; null for other methods. */
  historical_start_year?: number | null;
}

// --- Progress Point ---

export interface ProgressPoint {
  id: string;
  user_id: string;
  recorded_date: string;
  net_worth: number;
  assets_breakdown: Record<string, unknown>;
  liabilities_breakdown: Record<string, unknown>;
  auto_logged: boolean;
}

export interface ProgressPointCreate {
  recorded_date: string;
  net_worth?: number;
  assets_breakdown?: Record<string, unknown>;
  liabilities_breakdown?: Record<string, unknown>;
  auto_logged?: boolean;
}

// --- User ---

export interface User {
  capabilities?: string[];
  is_anonymous?: boolean;
  is_demo?: boolean;
  firebase_authenticated?: boolean;
  deletion_pending?: boolean;
  auth_providers?: ("apple" | "google" | "email")[];
  id: string;
  email: string;
  display_name: string | null;
  avatar_url: string | null;
  created_at: string;
}

// === International plans (intl_web_ui) ===================================
// Tax country, region and display currency for plans of people who live
// outside the US, plus the GET /tax-regimes registry. The plan, residency,
// account and year-snapshot fields are declared on those interfaces. Every
// field is optional: older services omit them, and a missing value means a US
// plan in USD.

/** ISO 3166-1 alpha-2, or "XX" for a user-defined ("Other") country. */
export type TaxCountryCode = string;
export type IntlAccountCategory = "taxable" | "tax_deferred" | "tax_free" | "cash";
export type IntlPerson = "self" | "spouse";

/** One government benefit paid by a registered rule ("<CC>:<rule_id>"). */
export interface IntlBenefit {
  rule: string;
  owner: IntlPerson;
  start_age: number | null;
  start_milestone_id: string | null;
  /** Validated by the rule's params model; see TaxRegimeBenefitRule.params_schema. */
  params: Record<string, unknown>;
}

/** A regime document for the custom ("XX") country; the server validates it. */
export type IntlRegimeDocument = Record<string, unknown>;

/** Unused contribution room at the plan's start for an account kind whose room carries forward. */
export interface IntlStartingRoom {
  /** "<CC>:<kind_id>" of a kind with `carries_room`. */
  kind: string;
  owner: IntlPerson;
  /** Room carried in from earlier years, before the first plan year's new room. */
  amount: number;
}

export interface IntlSettings {
  benefits?: IntlBenefit[];
  custom_regime?: IntlRegimeDocument | null;
  wealth_tax?: Record<string, unknown> | null;
  transaction_tax?: Record<string, unknown> | null;
  /** Omitted when none is entered. */
  starting_room?: IntlStartingRoom[];
  /** Earned income in the year before the plan starts, by person (first-year percent limits). */
  prior_year_earned_income?: Partial<Record<IntlPerson, number>> | null;
}

export type IntlTaxLineCategory =
  | "income_national"
  | "income_regional"
  | "income_local"
  | "social_contribution"
  | "levy"
  | "wealth"
  | "transaction"
  | "credit"
  | "benefit_recovery";

export interface IntlTaxLine {
  code: string;
  label: string;
  category: IntlTaxLineCategory | string;
  person: IntlPerson | null;
  amount: number;
}

export interface TaxRegimeAccountKind {
  /** "<CC>:<kind_id>", as saved in Account.intl_account_kind. */
  id: string;
  label: string;
  category: IntlAccountCategory;
  /** Key rules in plain words, when the registry supplies them. */
  description?: string | null;
  rules?: string[];
  /** Unused contribution room carries forward (the plan can enter its starting room). */
  carries_room?: boolean;
  /** Room is a percent of the prior year's earned income. */
  uses_prior_year_income?: boolean;
}

export interface TaxRegimeBenefitRule {
  id: string;
  label: string;
  /** JSON Schema of the rule's params model. */
  params_schema: Record<string, unknown>;
}

export interface TaxRegimeCountry {
  code: TaxCountryCode;
  name: string;
  /** Null for the custom country, whose currency is the plan's choice. */
  currency: string | null;
  filing_unit: string | null;
  regions: { code: string; name: string }[];
  /** The region a new plan or move starts in; the first region when absent. */
  default_region?: string | null;
  /** True for the custom ("Other") country. */
  custom?: boolean;
  account_kinds: TaxRegimeAccountKind[];
  benefit_rules: TaxRegimeBenefitRule[];
  spec_years: number[];
  approximations: string[];
}

export interface TaxRegimeRegistry {
  countries: TaxRegimeCountry[];
}
// === End international plans ===============================================

// === Cash-flow input options ===============================================
/** How a loan's interest accrues: monthly amortization, simple interest on principal, or daily (actual/365). */
export type InterestMethod = "monthly" | "simple" | "daily";

/** Transfer rules: annual (default, omitted) or monthly over the rule's active months. */
export type TransferFrequency = "annual" | "monthly";
// === End cash-flow input options ===========================================

// === Plan accuracy (POST /plans/{id}/plan-checks) ===========================
export type PlanCheckKey =
  | "accounts_entered"
  | "expenses_entered"
  | "social_security_self"
  | "social_security_spouse"
  | "earned_income_ends"
  | "pre_medicare_coverage"
  | "balances_current";
export type PlanReviewKey =
  | "high_real_stock_return"
  | "low_inflation"
  | "event_never_runs"
  | "milestone_missed"
  | "zero_social_security"
  | "cost_basis_assumed";

/** One applicable completeness check. */
export interface PlanCheck {
  key: PlanCheckKey;
  weight: number;
  passes: boolean;
}

/** A failing completeness check ("missing") or an unscored "review" item. */
export interface PlanCheckItem {
  key: PlanCheckKey | PlanReviewKey;
  kind: "missing" | "review";
  /** The plan editor section that fixes it (a PlanSectionKey). */
  section:
    | "plan_details"
    | "assumptions"
    | "milestones"
    | "income"
    | "expenses"
    | "accounts"
    | "healthcare";
  title: string;
  target_id?: string | null;
  person?: "self" | "spouse" | null;
}

export interface PlanChecksResponse {
  /** Weighted share of applicable checks that pass, 0-100. */
  score: number;
  checks: PlanCheck[];
  /** Missing items by check weight, then review items. */
  items: PlanCheckItem[];
}
// === End plan accuracy =====================================================

// === Social Security claiming-age explorer ==================================
// POST /api/plans/{plan_id}/social-security/claiming (backend/app/routers/ss_claiming.py).

export type ClaimingOwner = "self" | "spouse";
export type ClaimingNotAdjustableReason =
  | "no_benefit"
  | "multiple_benefits"
  | "already_claimed"
  | "unresolved_claim_date"
  | "missing_birth_year"
  | "no_candidate_ages";

export interface ClaimingPerson {
  owner: ClaimingOwner;
  adjustable: boolean;
  /** Why the claiming age is not varied; null when adjustable. */
  reason: ClaimingNotAdjustableReason | null;
  income_id: string | null;
  birth_year: number | null;
  birth_month: number;
  full_retirement_age: number | null;
  /** Fractional age of the planned first payment month. */
  current_claim_age: number | null;
  candidate_ages: number[];
  benefit_basis: "amount" | "pia" | null;
  /**
   * The earnings test, counting this person's earnings, withholds benefits
   * before full retirement age in the current plan or a compared run.
   * Additive; older services omit it.
   */
  earnings_test_withholds?: boolean;
}

export interface ClaimingRun {
  claim_ages: Partial<Record<ClaimingOwner, number>>;
  /** Own retirement benefit at claim, annual, plan-start dollars. */
  first_year_benefits: Partial<Record<ClaimingOwner, number>>;
  /** Household Social Security received in each of `years`, nominal. */
  social_security_by_year: number[];
  lifetime_social_security: number;
  lifetime_taxes: number;
  end_net_worth: number;
  /** End net worth less income tax at pre_tax_discount_rate on pre-tax balances; the ranking basis. */
  end_net_worth_after_tax: number;
  success: boolean;
  failure_year: number | null;
  /** This run minus the current run, nominal. */
  end_net_worth_after_tax_change: number;
  lifetime_social_security_change: number;
}

/** Income update fields that adopt one claiming age; annual_amount only for amount-basis benefits. */
export interface ClaimingIncomeChanges {
  claiming_age: number;
  start_milestone_id: null;
  start_month: null;
  annual_amount?: number;
}

export interface ClaimingPatch {
  owner: ClaimingOwner;
  claiming_age: number;
  income_id: string;
  changes: ClaimingIncomeChanges;
}

export interface ClaimingExplorerResponse {
  persons: ClaimingPerson[];
  years: number[];
  /** The plan as saved; null when no person is adjustable. */
  current: ClaimingRun | null;
  /** Ascending ages; with two people, self's age is the outer loop. */
  runs: ClaimingRun[];
  best_index: number | null;
  best_end_net_worth_after_tax_change: number | null;
  best_lifetime_social_security_change: number | null;
  pre_tax_discount_rate: number;
  patches: ClaimingPatch[];
}
// === End Social Security claiming-age explorer ==============================

// === Wellness scorecard (POST /plans/{id}/wellness) ========================
export type WellnessKey =
  | "savings_rate"
  | "emergency_fund"
  | "debt_to_income"
  | "savings_to_income"
  | "withdrawal_rate"
  | "guaranteed_income"
  | "pre_tax_share"
  | "funded_years"
  | "fi_timing";
export type WellnessStatus = "strong" | "fair" | "needs_attention" | "not_applicable";
export type WellnessUnit =
  "percent" | "months" | "ratio" | "multiple" | "currency" | "year" | "age";

/** "higher": at or above strong_at is strong, at or above fair_at is fair; "lower" mirrors it. */
export interface WellnessBands {
  better: "higher" | "lower";
  fair_at: number;
  strong_at: number;
}

export interface WellnessMetric {
  key: WellnessKey;
  label: string;
  /** percent and ratio are decimals (0.2 = 20%); year is a calendar year; currency is basis_year nominal. */
  value: number | null;
  unit: WellnessUnit;
  status: WellnessStatus;
  bands: WellnessBands | null;
  basis_year: number | null;
  /** Plan section (PlanSectionKey) whose inputs drive the metric. */
  section: string | null;
}

export interface WellnessResponse {
  start_year: number;
  metrics: WellnessMetric[];
}
// === End wellness scorecard =================================================
