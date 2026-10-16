import type {
  Milestone,
  MilestoneCreate,
  PlanData,
  SimulationResult,
  YearSnapshot,
} from "@/types/plan";

/** The preset multiple for a user's own FI milestone; the engine reports the estimate's own. */
export const FI_MULTIPLE = 25;

/** Label for the automatic estimate, distinct from any milestone the user creates. */
export const FI_ESTIMATE_LABEL = "Financial independence (CoastMath estimate)";

/** The milestone the estimate becomes when the user takes it over. */
export const FI_ESTIMATE_PRESET: MilestoneCreate = {
  name: "Financial independence",
  trigger_type: "expense_multiple",
  trigger_value: null,
  trigger_date: null,
  metric: "liquid_net_worth",
  expense_multiple: FI_MULTIPLE,
  relative_to_id: null,
  offset_years: 0,
};

export interface FinancialIndependenceEstimate {
  /** The projected year the estimate lands, or null when it is never reached. */
  snapshot: YearSnapshot | null;
  basisYear: number | null;
  /** In `basisYear` nominal dollars. */
  target: number | null;
  multiple: number;
}

/**
 * CoastMath's financial independence estimate, as the engine computed it
 * (`metadata.fi_estimate`). The engine applies its expense-multiple milestone
 * rule at 25× on liquid accounts minus debt, so converting the estimate into
 * a real milestone never moves its year. Results without the field show no
 * estimate. It is a display threshold: it does not stop income.
 */
export function financialIndependence(
  result: SimulationResult | null,
): FinancialIndependenceEstimate {
  const estimate = result?.metadata.fi_estimate;
  const snapshot =
    estimate?.year != null
      ? (result?.yearly_snapshots.find((s) => s.year === estimate.year) ?? null)
      : null;
  if (!estimate || !snapshot)
    return {
      snapshot: null,
      basisYear: null,
      target: null,
      multiple: estimate?.multiple ?? FI_MULTIPLE,
    };
  return {
    snapshot,
    basisYear: estimate.basis_year,
    target: estimate.target,
    multiple: estimate.multiple,
  };
}

/** The first user milestone of the financial independence (expense multiple) type. */
export function ownFiMilestone(plan: PlanData | null): Milestone | null {
  const own = (plan?.milestones ?? []).filter((m) => m.trigger_type === "expense_multiple");
  return own.sort((a, b) => a.sort_order - b.sort_order)[0] ?? null;
}

export type ResolvedFinancialIndependence =
  | { source: "milestone"; milestone: Milestone; year: number | null }
  | { source: "estimate"; year: number | null; age: number | null };

/**
 * The plan's financial independence date: the user's own FI milestone when one
 * exists, otherwise the CoastMath estimate unless the user removed it.
 */
export function resolveFinancialIndependence(
  plan: PlanData | null,
  result: SimulationResult | null,
  estimateHidden: boolean,
): ResolvedFinancialIndependence | null {
  const own = ownFiMilestone(plan);
  if (own) {
    const outcome = result?.metadata.milestone_outcomes?.find((o) => o.id === own.id);
    return { source: "milestone", milestone: own, year: outcome?.year ?? null };
  }
  if (estimateHidden) return null;
  const { snapshot } = financialIndependence(result);
  return { source: "estimate", year: snapshot?.year ?? null, age: snapshot?.age ?? null };
}
