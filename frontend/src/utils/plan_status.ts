import type { SimulationResult } from "@/types/plan";

export type PlanStatusTone = "success" | "warning" | "danger";

export interface PlanStatus {
  /** Short pill text identifying the forecast outcome. */
  label: string;
  tone: PlanStatusTone;
  /** One or two sentences naming the criteria behind the label. */
  detail: string;
}

/** Beyond this the projection is numerically meaningless (a runaway balance). */
export const IMPLAUSIBLE_DOLLARS = 1e15;

/**
 * Status for a deterministic projection. Three separate conditions are
 * checked, in order of severity, so a positive label can never hide a
 * failing one:
 *   1. every yearly value is finite and plausible,
 *   2. spending is funded every year (the engine's ``success`` flag),
 *   3. total net worth (including property, minus debt) never goes negative.
 */
export function planStatus(result: SimulationResult | null | undefined): PlanStatus | null {
  if (!result) return null;
  const snapshots = result.yearly_snapshots ?? [];
  const meta = result.metadata;

  const implausible = snapshots.find((s) =>
    [
      s.net_worth,
      s.liabilities_balance,
      s.real_assets_value,
      ...Object.values(s.accounts ?? {}),
    ].some((v) => v != null && (!Number.isFinite(v) || Math.abs(v) > IMPLAUSIBLE_DOLLARS)),
  );
  if (implausible) {
    return {
      label: `Projection invalid from ${implausible.year}`,
      tone: "danger",
      detail:
        "A balance grew beyond any plausible value. Check loan rates, growth rates and payment settings; no figure on this page can be trusted until the projection is repaired.",
    };
  }

  if (!meta.success) {
    return meta.failure_year
      ? {
          label: `Spending unfunded from ${meta.failure_year}`,
          tone: "danger",
          detail:
            "Cash and investments run out before the plan ends, so some spending goes unpaid in this steady-return projection.",
        }
      : {
          label: "Needs review",
          tone: "warning",
          detail: "The projection reported a failure without a year. Review the plan inputs.",
        };
  }

  const insolvent = snapshots.find((s) => s.net_worth < 0);
  if (insolvent) {
    return {
      label: `Net worth negative from ${insolvent.year}`,
      tone: "warning",
      detail:
        "Spending stays funded in this steady-return projection, but debts exceed everything owned from that year. This is not on track.",
    };
  }

  return {
    label: "Steady-return forecast: funded",
    tone: "success",
    detail:
      "Spending is funded every year and total net worth stays positive in this single steady-return projection. It is not a probability; see Monte Carlo for risk.",
  };
}
