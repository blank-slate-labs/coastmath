import type { PlanData, SimulationResult } from "@/types/plan";
import {
  FI_ESTIMATE_LABEL,
  financialIndependence,
  ownFiMilestone,
} from "@/utils/financial_independence";
import { compactCurrency } from "@/utils/format";

export type TimelineEventKind = "fi" | "milestone" | "rmd" | "shortfall";

/**
 * A dated event worth marking on the projection: the CoastMath FI estimate
 * (kind "fi"), plan milestones, RMDs, shortfall.
 */
export interface TimelineEvent {
  key: string;
  year: number;
  label: string;
  kind: TimelineEventKind;
  /** Longer explanation for a title attribute; never rendered inline. */
  detail?: string;
}

/**
 * Every event that lands inside the projection window, sorted by year.
 * Shared by the net worth chart (markers), the chip timeline and the year ledger
 * so the same list backs all three.
 */
export function timelineEvents(
  plan: PlanData | null,
  simulation: SimulationResult | null,
  { fiEstimateHidden = false }: { fiEstimateHidden?: boolean } = {},
): TimelineEvent[] {
  if (!plan || !simulation) return [];
  const { start_year: start, end_year: end } = simulation.metadata;
  const inWindow = (year: number | null | undefined): year is number =>
    year != null && year >= start && year <= end;

  const events: TimelineEvent[] = [];

  // A user's own FI milestone replaces the estimate, so the plan never shows two.
  const fi = !fiEstimateHidden && !ownFiMilestone(plan) ? financialIndependence(simulation) : null;
  if (fi?.snapshot && fi.target != null) {
    events.push({
      key: "fi",
      year: fi.snapshot.year,
      label: FI_ESTIMATE_LABEL,
      kind: "fi",
      detail: `Cash and investments minus debt at the end of ${fi.basisYear} exceeded ${fi.multiple}× that year's spending (${compactCurrency(fi.target)}). Edit or remove this estimate under Milestones. Income continues until its own end milestone.`,
    });
  }

  for (const outcome of simulation.metadata.milestone_outcomes ?? []) {
    if (!inWindow(outcome.year)) continue;
    events.push({
      key: `milestone-${outcome.id}`,
      year: outcome.year,
      label: outcome.name,
      kind: "milestone",
    });
  }

  const rmdYear = simulation.metadata.rmd_start_age
    ? plan.birth_year + simulation.metadata.rmd_start_age
    : null;
  if (inWindow(rmdYear)) {
    events.push({
      key: "rmd",
      year: rmdYear,
      label: "RMDs begin",
      kind: "rmd",
      detail: `Projected RMD start age ${simulation.metadata.rmd_start_age}, from your birth year.`,
    });
  }

  if (!simulation.metadata.success && inWindow(simulation.metadata.failure_year)) {
    events.push({
      key: "shortfall",
      year: simulation.metadata.failure_year,
      label: "Spending unfunded",
      kind: "shortfall",
    });
  }

  return events.sort((a, b) => a.year - b.year || a.label.localeCompare(b.label));
}
