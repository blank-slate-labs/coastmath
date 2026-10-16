import { create } from "zustand";

/**
 * Whether the user removed the CoastMath financial independence estimate from
 * a plan's milestones. Display-only, stored per plan in the browser like the
 * metric definitions; it never changes the projection.
 */
interface FiEstimateState {
  hiddenByPlan: Record<string, boolean>;
  setHidden: (planId: string, hidden: boolean) => void;
}

const key = (planId: string) => `coastmath:fi_estimate_hidden:${planId}`;

function readHidden(planId: string): boolean {
  try {
    return localStorage.getItem(key(planId)) === "1";
  } catch {
    return false;
  }
}

export const useFiEstimateStore = create<FiEstimateState>((set) => ({
  hiddenByPlan: {},
  setHidden: (planId, hidden) => {
    try {
      if (hidden) localStorage.setItem(key(planId), "1");
      else localStorage.removeItem(key(planId));
    } catch {
      /* storage unavailable */
    }
    set((s) => ({ hiddenByPlan: { ...s.hiddenByPlan, [planId]: hidden } }));
  },
}));

/** True when the user removed the estimate from this plan. */
export function useFiEstimateHidden(planId: string | null | undefined): boolean {
  return useFiEstimateStore((s) =>
    planId ? (s.hiddenByPlan[planId] ?? readHidden(planId)) : false,
  );
}
