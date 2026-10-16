import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { setStorageAdapter, usePlanStore } from "./plan_store";
import type { PlanData, SimulationResult } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const plan = makePlan({ id: "p", name: "Plan" });
const oldResult = {
  metadata: { start_year: 2026 },
  yearly_snapshots: [{ year: 2026, net_worth: 100 }],
} as SimulationResult;
const newResult = {
  ...oldResult,
  yearly_snapshots: [{ ...oldResult.yearly_snapshots[0], net_worth: 200 }],
};

beforeEach(() => {
  vi.useFakeTimers();
  usePlanStore.setState({
    plan,
    plans: [plan],
    simulation: oldResult,
    accountsRevision: 0,
    isSimulating: false,
    error: null,
  });
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

it.each(["create", "update", "delete"])(
  "recalculates the whole forecast after account %s",
  async (operation) => {
    const runSimulation = vi.fn().mockResolvedValue(newResult);
    setStorageAdapter(
      makeAdapter({
        createAccount: vi.fn().mockResolvedValue({}),
        updateAccount: vi.fn().mockResolvedValue({}),
        fetchPlan: vi.fn().mockResolvedValue({ ...plan }),
        runSimulation,
      }),
    );
    if (operation === "delete") await usePlanStore.getState().deleteAccount("a");
    else
      await usePlanStore.getState().saveAccount(operation === "create" ? null : "a", {
        name: "Roth",
        account_type: "roth_ira",
        balance: 200,
      });
    expect(usePlanStore.getState().simulation).toBeNull();
    expect(usePlanStore.getState().isSimulating).toBe(true);
    expect(usePlanStore.getState().accountsRevision).toBe(1);
    await vi.advanceTimersByTimeAsync(300);
    expect(runSimulation).toHaveBeenCalledExactlyOnceWith("p");
    expect(usePlanStore.getState().simulation).toEqual(newResult);
  },
);

it("recalculates even while the plan refresh is slow, and ignores an older forecast", async () => {
  let finishOld!: (result: SimulationResult) => void;
  let finishRefresh!: (result: PlanData) => void;
  const runSimulation = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise((r) => {
          finishOld = r;
        }),
    )
    .mockResolvedValue(newResult);
  setStorageAdapter(
    makeAdapter({
      runSimulation,
      updateAccount: vi.fn().mockResolvedValue({}),
      fetchPlan: () =>
        new Promise((r) => {
          finishRefresh = r;
        }),
    }),
  );
  const oldRequest = usePlanStore.getState().runSimulation("p");
  const save = usePlanStore.getState().saveAccount("a", { balance: 200 });
  await vi.advanceTimersByTimeAsync(300);
  expect(usePlanStore.getState().simulation).toEqual(newResult);
  finishOld(oldResult);
  await oldRequest;
  expect(usePlanStore.getState().simulation).toEqual(newResult);
  finishRefresh(plan);
  await save;
  expect(runSimulation).toHaveBeenCalledTimes(2);
});

it("leaves the existing forecast intact when saving fails", async () => {
  setStorageAdapter(
    makeAdapter({ updateAccount: vi.fn().mockRejectedValue(new Error("Save failed")) }),
  );
  await expect(usePlanStore.getState().saveAccount("a", { balance: 200 })).rejects.toThrow(
    "Save failed",
  );
  expect(usePlanStore.getState().simulation).toBe(oldResult);
  expect(usePlanStore.getState().accountsRevision).toBe(0);
});
