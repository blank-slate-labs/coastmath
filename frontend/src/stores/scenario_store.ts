import { useEffect } from "react";
import { create } from "zustand";

import type { StorageAdapter } from "@/storage/adapter";
import type { PlanInheritance, ScenarioItemState } from "@/types/scenario";
import { usePlanStore } from "@/stores/plan_store";
import { saveRequestKey, useSaveStore } from "@/stores/save_store";

/**
 * What a scenario changed relative to its Main plan, keyed by plan ID. Only
 * the open scenario is fetched; plan data itself stays in the plan store.
 */
interface InheritanceEntry {
  data: PlanInheritance | null;
  loading: boolean;
  /** The last read failed; the planner keeps working and offers a retry. */
  failed: boolean;
}

interface ScenarioState {
  byPlan: Record<string, InheritanceEntry>;
  load: (adapter: StorageAdapter, planId: string) => Promise<void>;
  /**
   * Runs a change (reset, restore, sync), stores the inheritance it returns,
   * then reloads the plan so the planner and forecast show the new values.
   * Rejects with the server's error; nothing is stored on failure.
   */
  change: (planId: string, run: () => Promise<PlanInheritance>) => Promise<void>;
  clear: (planId: string) => void;
}

const requests = new Map<string, number>();
const nextRequest = (planId: string) => {
  const request = (requests.get(planId) ?? 0) + 1;
  requests.set(planId, request);
  return request;
};

export const useScenarioStore = create<ScenarioState>()((set) => ({
  byPlan: {},
  load: async (adapter, planId) => {
    const request = nextRequest(planId);
    set((s) => ({
      byPlan: {
        ...s.byPlan,
        [planId]: { data: s.byPlan[planId]?.data ?? null, loading: true, failed: false },
      },
    }));
    try {
      const data = await adapter.fetchInheritance(planId);
      if (requests.get(planId) !== request) return;
      set((s) => ({ byPlan: { ...s.byPlan, [planId]: { data, loading: false, failed: false } } }));
    } catch {
      if (requests.get(planId) !== request) return;
      set((s) => ({
        byPlan: { ...s.byPlan, [planId]: { data: null, loading: false, failed: true } },
      }));
    }
  },
  change: async (planId, run) => {
    // A change supersedes any read in flight.
    const request = nextRequest(planId);
    const data = await run();
    if (requests.get(planId) === request)
      set((s) => ({ byPlan: { ...s.byPlan, [planId]: { data, loading: false, failed: false } } }));
    await reloadPlan(planId);
  },
  clear: (planId) => {
    nextRequest(planId);
    set((s) => {
      const byPlan = { ...s.byPlan };
      delete byPlan[planId];
      return { byPlan };
    });
  },
}));

/** Re-reads the open plan (and its accounts) after the server changed its values. */
export async function reloadPlan(planId: string) {
  const store = usePlanStore.getState();
  if (store.plan?.id !== planId) return;
  usePlanStore.setState((s) => ({ accountsRevision: s.accountsRevision + 1 }));
  await store.loadPlan(planId);
}

/** Counts every difference from Main: plan fields plus each item not following Main. */
export function changeCount(data: PlanInheritance): number {
  return data.plan_fields.length + data.items.filter((item) => item.state !== "inherited").length;
}

/** The badge state of one row of the open plan, or null when it follows Main. */
export function useRowScenarioState(
  rowId: string | null | undefined,
): Exclude<ScenarioItemState, "inherited" | "removed"> | null {
  const planId = usePlanStore((s) => (s.plan?.parent_plan_id ? s.plan.id : null));
  return useScenarioStore((s) => {
    if (!planId || !rowId) return null;
    const state = s.byPlan[planId]?.data?.items.find((item) => item.row_id === rowId)?.state;
    return state === "changed" || state === "scenario_only" ? state : null;
  });
}

/**
 * Keeps the open scenario's inheritance current: fetched when the scenario
 * opens and again after each confirmed save while it is open.
 */
export function useInheritanceSync(adapter: StorageAdapter) {
  const planId = usePlanStore((s) => s.plan?.id);
  const parentId = usePlanStore((s) => s.plan?.parent_plan_id);
  const lastSavedAt = useSaveStore((s) => s.lastSavedAt);
  const lastSavedKey = useSaveStore((s) => s.lastSavedKey);
  const load = useScenarioStore((s) => s.load);
  useEffect(() => {
    if (!planId || !parentId) return;
    // The plan's own deletion is confirmed before the plan store closes it; there is nothing left to read.
    if (lastSavedKey === saveRequestKey("delete", `/plans/${planId}`)) return;
    void load(adapter, planId);
  }, [adapter, planId, parentId, lastSavedAt, lastSavedKey, load]);
}
