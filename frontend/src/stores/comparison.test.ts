import { afterEach, expect, it, vi } from "vitest";
import { setStorageAdapter, usePlanStore } from "./plan_store";
import type { SimulationResult } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";
const plan = makePlan({ id: "p", name: "Plan" });
const sim = {
  yearly_snapshots: [{ year: 2026, net_worth: 100 }],
  metadata: { start_year: 2026 },
} as SimulationResult;
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

it("retains a captured baseline through same-plan refresh and clears it on switching plans", async () => {
  vi.useFakeTimers();
  setStorageAdapter(makeAdapter({ fetchPlan: vi.fn(async (id: string) => ({ ...plan, id })) }));
  usePlanStore.setState({ plan, simulation: sim, isSimulating: false });
  usePlanStore.getState().saveBaseline();
  expect(usePlanStore.getState().baselineSimulation).not.toBe(sim);
  await usePlanStore.getState().loadPlan("p");
  expect(usePlanStore.getState().baselineSimulation).toEqual(sim);
  expect(usePlanStore.getState().isSimulating).toBe(true);
  await usePlanStore.getState().loadPlan("other");
  expect(usePlanStore.getState().baselineSimulation).toBeNull();
  expect(usePlanStore.getState().simulation).toBeNull();
});

it("cannot resurrect a cleared comparison after its request finishes", async () => {
  let resolve!: (value: unknown) => void;
  setStorageAdapter(
    makeAdapter({
      fetchCompare: () =>
        new Promise((r) => {
          resolve = r;
        }),
    }),
  );
  usePlanStore.setState({ plan, simulation: sim });
  const request = usePlanStore.getState().setBaselinePlan("baseline");
  usePlanStore.getState().clearBaseline();
  resolve({ baseline: sim });
  await request;
  expect(usePlanStore.getState().compareMode).toBe(false);
  expect(usePlanStore.getState().baselineSimulation).toBeNull();
});

it("clears the old forecast after failed recalculation so it cannot be captured or exported", async () => {
  vi.useFakeTimers();
  setStorageAdapter(
    makeAdapter({ runSimulation: vi.fn().mockRejectedValue(new Error("Calculation failed")) }),
  );
  usePlanStore.setState({ plan, simulation: sim, baselineSimulation: null, isSimulating: false });
  await usePlanStore.getState().runSimulation("p");
  expect(usePlanStore.getState().simulation).toBeNull();
  usePlanStore.getState().saveBaseline();
  expect(usePlanStore.getState().baselineSimulation).toBeNull();
  // The failure is stated where the results would be, not as a passing toast.
  expect(usePlanStore.getState().simulationError).toBe("The projection could not run.");
});
