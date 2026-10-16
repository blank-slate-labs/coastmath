import type {
  SpendingCompareResponse,
  SpendingFeedState,
  SpendingOutcome,
} from "@/api/spending_models";

/** Synthetic outcomes: no real plans, accounts or people. */
export function outcome(overrides: Partial<SpendingOutcome> = {}): SpendingOutcome {
  return {
    kind: "months",
    label: "Jun 2026",
    essential_annual: 24000,
    discretionary_annual: 6000,
    take_home_monthly: 4000,
    essential_ratio: 0.8,
    discretionary_ratio: 0.5,
    income_ratio: null,
    projected_take_home_monthly: 5000,
    fi_year: 2040,
    fi_age: 55,
    success: true,
    failure_year: null,
    final_net_worth: 2_000_000,
    net_worth_path: [
      { year: 2026, age: 41, net_worth: 100_000, inflation_factor: 1 },
      { year: 2027, age: 42, net_worth: 200_000, inflation_factor: 1.03 },
      { year: 2028, age: 43, net_worth: 2_000_000, inflation_factor: 1.0609 },
    ],
    monte_carlo_success_rate: null,
    caveats: [],
    months: ["2026-06"],
    source_ids: ["a1"],
    by_category: { groceries: 600, dining: 200 },
    ...overrides,
  };
}

export function comparison(
  overrides: Partial<SpendingCompareResponse> = {},
): SpendingCompareResponse {
  return {
    fingerprint: "f".repeat(64),
    covered_expense_ids: ["e1"],
    spending_feed: false,
    plan: outcome({
      kind: "plan",
      label: "This plan",
      fi_age: 57,
      fi_year: 2042,
      months: null,
      source_ids: null,
      by_category: null,
      final_net_worth: 1_500_000,
      net_worth_path: [
        { year: 2026, age: 41, net_worth: 100_000, inflation_factor: 1 },
        { year: 2027, age: 42, net_worth: 150_000, inflation_factor: 1.03 },
        { year: 2028, age: 43, net_worth: 1_500_000, inflation_factor: 1.0609 },
      ],
    }),
    variants: [
      outcome(),
      outcome({
        label: "Jul 2026",
        months: ["2026-07"],
        fi_age: 58,
        fi_year: 2043,
        success: false,
        failure_year: 2070,
        by_category: { groceries: 900, dining: 100, travel: 50 },
      }),
    ],
    caveats: ["Only the covered spending changes."],
    seed: null,
    ...overrides,
  };
}

export function feedState(overrides: Partial<SpendingFeedState> = {}): SpendingFeedState {
  return {
    plan_id: "plan-1",
    active: false,
    source_ids: [],
    basis: "trailing",
    basis_months: [],
    essential_expense_id: null,
    discretionary_expense_id: null,
    annual_essential: null,
    annual_discretionary: null,
    months_used: 0,
    error: null,
    applied_at: null,
    ...overrides,
  };
}
