import type { PlanData } from "@/types/plan";

/**
 * Nested records may be partial, since a test names only the fields its component reads,
 * and string fields take any string, so a fixture may hold a value the type does not.
 * Field names are still checked.
 */
type Loose<T> = T extends string
  ? string
  : T extends (infer U)[]
    ? Loose<U>[]
    : T extends object
      ? { [K in keyof T]?: Loose<T[K]> }
      : T;

export type PlanOverrides = { [K in keyof PlanData]?: Loose<PlanData[K]> };

/**
 * A complete `PlanData`: a new single-filer plan as the planner creates it, with no
 * records and no saved settings. Optional fields stay absent, as an older service
 * sends them. Overrides replace top-level fields.
 */
export function makePlan(overrides: PlanOverrides = {}): PlanData {
  const plan: PlanData = {
    id: "plan",
    user_id: "user",
    name: "My Plan",
    plan_type: "NOW",
    start_date: null,
    snapshot_conditions: {},
    birth_year: 1980,
    filing_status: "single",
    state_code: null,
    life_expectancy: 95,
    created_at: "2026-01-01T00:00:00Z",
    milestones: [],
    income_streams: [],
    expenses: [],
    priorities: [],
    drawdown_order: [],
    assumption_curves: [],
    real_assets: [],
    liabilities: [],
    residency_periods: [],
    spouse: null,
    sepp_settings: null,
    spending_rules: null,
    tax_settings: null,
    estate_settings: null,
    baseline_plan_id: null,
  };
  return { ...plan, ...overrides } as PlanData;
}
