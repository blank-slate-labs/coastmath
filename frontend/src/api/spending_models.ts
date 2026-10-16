import { api } from "./client";

/**
 * Spending models (backend `app/routers/spending_models.py`) and provider-neutral
 * spending feeds (`app/routers/ledger_feeds.py`). Amounts are in the plan's currency.
 */
export type FuturePhases = "scale" | "as_planned";
export type IncomeMode = "as_planned" | "scale_to_take_home";

export interface AmountsVariant {
  kind: "amounts";
  label?: string;
  essential_annual: number;
  discretionary_annual: number;
  take_home_monthly?: number | null;
}
/** One to twelve complete `YYYY-MM` months; accounts default to the plan's feed or spending accounts. */
export interface MonthsVariant {
  kind: "months";
  label?: string;
  months: string[];
  source_ids?: string[];
}
export type SpendingVariant = AmountsVariant | MonthsVariant;

export interface NetWorthPoint {
  year: number;
  age: number;
  net_worth: number;
  inflation_factor: number;
}
export interface SpendingOutcome {
  kind: "plan" | "amounts" | "months";
  label: string;
  essential_annual: number;
  discretionary_annual: number;
  take_home_monthly: number | null;
  essential_ratio: number | null;
  discretionary_ratio: number | null;
  income_ratio: number | null;
  projected_take_home_monthly: number;
  fi_year: number | null;
  fi_age: number | null;
  success: boolean;
  failure_year: number | null;
  final_net_worth: number;
  net_worth_path: NetWorthPoint[];
  monte_carlo_success_rate: number | null;
  caveats: string[];
  /** Months variants: the months, the accounts read and mean monthly spending per category. */
  months?: string[] | null;
  source_ids?: string[] | null;
  by_category?: Record<string, number> | null;
}
export interface SpendingCompareRequest {
  variants: SpendingVariant[];
  future_phases?: FuturePhases;
  income?: IncomeMode;
  monte_carlo_trials?: number;
  seed?: number | null;
}
export interface SpendingCompareResponse {
  fingerprint: string;
  covered_expense_ids: string[];
  spending_feed: boolean;
  plan: SpendingOutcome;
  variants: SpendingOutcome[];
  caveats: string[];
  seed: number | null;
}
export interface SpendingApplyRequest {
  variant: SpendingVariant;
  future_phases?: FuturePhases;
  expected_fingerprint: string;
}
export interface SpendingApplyResponse {
  fingerprint: string;
  updated_expense_ids: string[];
  created_expense_ids: string[];
  essential_ratio: number | null;
  discretionary_ratio: number | null;
  /** "months" when the plan's spending from transactions now follows the chosen months. */
  basis?: string | null;
}

export type FeedBasis = "trailing" | "months";
export interface SpendingFeedState {
  plan_id: string;
  active: boolean;
  source_ids: string[];
  basis: FeedBasis;
  basis_months: string[];
  essential_expense_id: string | null;
  discretionary_expense_id: string | null;
  annual_essential: number | null;
  annual_discretionary: number | null;
  months_used: number;
  error: string | null;
  applied_at: string | null;
}
export interface SpendingFeedUpdate {
  source_ids: string[];
  acknowledge_existing_expenses?: boolean;
  basis?: FeedBasis;
  months?: string[];
}

export const spendingModels = {
  compare: (planId: string, body: SpendingCompareRequest): Promise<SpendingCompareResponse> =>
    api.post(`/plans/${planId}/spending-models/compare`, body).then((r) => r.data),
  apply: (planId: string, body: SpendingApplyRequest): Promise<SpendingApplyResponse> =>
    api.post(`/plans/${planId}/spending-models/apply`, body).then((r) => r.data),
};

export const spendingFeeds = {
  get: (planId: string): Promise<SpendingFeedState> =>
    api.get(`/ledger/spending-feeds/${planId}`).then((r) => r.data),
  put: (planId: string, body: SpendingFeedUpdate): Promise<SpendingFeedState> =>
    api.put(`/ledger/spending-feeds/${planId}`, body).then((r) => r.data),
  stop: (planId: string): Promise<void> =>
    api.delete(`/ledger/spending-feeds/${planId}`).then(() => undefined),
};

/** The shared error envelope's code (`CONFLICT`, `MONTH_INCOMPLETE`, …), when the server sent one. */
export function apiErrorCode(error: unknown): string | null {
  const code = (error as { response?: { data?: { error?: { code?: unknown } } } })?.response?.data
    ?.error?.code;
  return typeof code === "string" ? code : null;
}
