import { useMemo } from "react";

import { usePlanStore } from "@/stores/plan_store";
import { adjustTimeline, buildDeflators } from "@/utils/currency";

/**
 * The current simulation's yearly snapshots in the store's currency mode,
 * plus the deflators used so callers can convert amounts the timeline
 * adjustment does not touch (drawdown flows, contribution flows).
 */
export function useAdjustedTimeline() {
  const simulation = usePlanStore((s) => s.simulation);
  const plan = usePlanStore((s) => s.plan);
  const currencyMode = usePlanStore((s) => s.currencyMode);

  const inflationCurve = useMemo(
    () => plan?.assumption_curves?.find((c) => c.curve_type === "inflation"),
    [plan],
  );

  const deflators = useMemo(
    () =>
      buildDeflators(
        inflationCurve,
        0.03,
        simulation?.metadata.start_year ?? 0,
        simulation?.yearly_snapshots?.length ?? 0,
        plan?.birth_year ?? 0,
      ),
    [inflationCurve, simulation, plan?.birth_year],
  );

  const data = useMemo(
    () => adjustTimeline(simulation?.yearly_snapshots ?? [], deflators, currencyMode),
    [currencyMode, deflators, simulation],
  );

  /** Factor to divide a nominal amount from year index `i` by in the current mode. */
  const factorAt = (index: number): number =>
    currencyMode === "nominal" ? 1 : (deflators[index] ?? 1);

  return { simulation, plan, currencyMode, deflators, data, factorAt };
}
