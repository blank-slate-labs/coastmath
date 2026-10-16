import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setStorageAdapter, usePlanStore } from "./plan_store";
import type { StorageAdapter } from "@/storage/adapter";
import type { PlanData, SimulationResult } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan as buildPlan } from "@/test_support/plan_builder";
import { deferred } from "@/test_support/deferred";
const makePlan = (id = "p") => buildPlan({ id, name: id, priorities_revision: 0 });
const forecast = {
  yearly_snapshots: [{ year: 2026, net_worth: 12345 }],
  metadata: { start_year: 2026 },
} as SimulationResult;
const state = () => usePlanStore.getState();
let storage: Record<string, ReturnType<typeof vi.fn>>;
beforeEach(() => {
  vi.useFakeTimers();
  const plan = makePlan();
  usePlanStore.setState({
    ...usePlanStore.getInitialState(),
    plan,
    plans: [plan],
    simulation: forecast,
  });
  storage = makeAdapter({
    runSimulation: vi.fn().mockResolvedValue(forecast),
    fetchPlan: vi.fn().mockResolvedValue(plan),
  });
  setStorageAdapter(storage as unknown as StorageAdapter);
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});
it.each(["deleteIncome", "deleteMilestone"] as const)(
  "%s refreshes allocation revision and cleared references before the next save",
  async (operation) => {
    storage[operation] = vi.fn().mockResolvedValue(undefined);
    const rules = [
      { id: "rule", target_account_id: "cash", source_income_id: null, start_milestone_id: null },
    ];
    const latest = { ...makePlan(), priorities: rules, priorities_revision: 6 };
    storage.fetchPlan.mockResolvedValue(latest);
    await state()[operation]("p", "deleted");
    expect(storage.fetchPlan).toHaveBeenCalledExactlyOnceWith("p");
    expect(state().plan).toEqual(latest);
    storage.updatePriorities = vi.fn().mockResolvedValue({ items: rules, revision: 7 });
    await state().updatePriorities("p", [], state().plan!.priorities_revision!);
    expect(storage.updatePriorities).toHaveBeenCalledExactlyOnceWith("p", [], 6);
  },
);
// Only the remote boundary is controlled; collection transitions and timers are real.
for (const [entity, collection] of [
  ["Milestone", "milestones"],
  ["Income", "income_streams"],
  ["Expense", "expenses"],
  ["RealAsset", "real_assets"],
  ["Liability", "liabilities"],
] as const) {
  for (const operation of ["add", "update", "delete"] as const) {
    const method = `${operation}${entity}` as keyof ReturnType<typeof state>;
    const remote = `${operation === "add" ? "create" : operation}${entity}`;
    const original = { id: "existing", name: "Original", annual_amount: 100 };
    const neighbor = { id: "neighbor", name: "Unchanged", annual_amount: 200 };
    const saved = {
      id: operation === "add" ? "new" : "existing",
      name: "Saved",
      annual_amount: 350,
    };
    const data = { name: "Saved", annual_amount: 350 };
    const args =
      operation === "add" ? [data] : operation === "update" ? ["existing", data] : ["existing"];
    const expected =
      operation === "add"
        ? [original, neighbor, saved]
        : operation === "update"
          ? [saved, neighbor]
          : [neighbor];
    const invoke = () =>
      (state()[method] as (planId: string, ...args: unknown[]) => Promise<void>)("p", ...args);
    describe(`${method}`, () => {
      beforeEach(() => {
        usePlanStore.setState({ plan: { ...makePlan(), [collection]: [original, neighbor] } });
        storage.fetchPlan.mockResolvedValue({ ...makePlan(), [collection]: expected });
      });
      it("applies the saved response and recalculates once after 300ms", async () => {
        storage[remote] = vi.fn().mockResolvedValue(saved);
        await invoke();
        expect(storage[remote]).toHaveBeenCalledExactlyOnceWith("p", ...args);
        expect(state().plan?.[collection]).toEqual(expected);
        expect(state().isSimulating).toBe(true);
        await vi.advanceTimersByTimeAsync(299);
        expect(storage.runSimulation).not.toHaveBeenCalled();
        await vi.advanceTimersByTimeAsync(1);
        expect(storage.runSimulation).toHaveBeenCalledExactlyOnceWith("p");
        expect(state().simulation).toEqual(forecast);
      });
      it("retains saved state on rejection and supports retry", async () => {
        storage[remote] = vi
          .fn()
          .mockRejectedValueOnce(new Error("Save unavailable"))
          .mockResolvedValue(saved);
        const previous = state().plan;
        await invoke();
        expect(state().plan).toBe(previous);
        expect(state().error).toBe("Save unavailable");
        expect(storage.runSimulation).not.toHaveBeenCalled();
        await invoke();
        expect(state().plan?.[collection]).toEqual(expected);
      });
      it("does not apply a late save or simulate after switching plans", async () => {
        const pending = deferred<typeof saved>();
        storage[remote] = vi.fn().mockReturnValue(pending.promise);
        const request = invoke();
        const other = makePlan("other");
        usePlanStore.setState({ plan: other });
        pending.resolve(saved);
        await request;
        await vi.advanceTimersByTimeAsync(300);
        expect(state().plan).toBe(other);
        expect(storage.runSimulation).not.toHaveBeenCalled();
      });
    });
  }
}
it("coalesces rapid successful edits into one fresh simulation", async () => {
  storage.updateIncome = vi.fn().mockResolvedValue({ id: "i", annual_amount: 200 });
  await state().updateIncome("p", "i", { annual_amount: 200 });
  await vi.advanceTimersByTimeAsync(200);
  await state().updateIncome("p", "i", { annual_amount: 300 });
  await vi.advanceTimersByTimeAsync(299);
  expect(storage.runSimulation).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1);
  expect(storage.runSimulation).toHaveBeenCalledExactlyOnceWith("p");
});
it.each(["resolve", "reject"] as const)(
  "ignores an old forecast that %ss while the next plan loads",
  async (outcome) => {
    const old = deferred<SimulationResult>(),
      next = deferred<PlanData>();
    storage.runSimulation.mockReturnValueOnce(old.promise);
    storage.fetchPlan.mockReturnValueOnce(next.promise);
    const simulation = state().runSimulation("p"),
      loading = state().loadPlan("other");
    if (outcome === "resolve") old.resolve(forecast);
    else old.reject(new Error("Old failure"));
    await simulation;
    expect(state().simulation).toBeNull();
    expect(state().error).toBeNull();
    next.resolve(makePlan("other"));
    await loading;
    await vi.advanceTimersByTimeAsync(300);
    expect(state().plan?.id).toBe("other");
    expect(storage.runSimulation).toHaveBeenLastCalledWith("other");
    expect(state().isSimulating).toBe(false);
  },
);
it("records the requested plan before its fetch resolves", async () => {
  const next = deferred<PlanData>();
  storage.fetchPlan.mockReturnValueOnce(next.promise);
  const loading = state().loadPlan("other");
  expect(state().activePlanId).toBe("other");
  expect(state().plan?.id).toBe("p");
  next.resolve(makePlan("other"));
  await loading;
  expect(state().plan?.id).toBe("other");
});
it("cancels queued work at the start of a plan switch", async () => {
  await state().loadPlan("p");
  const next = deferred<PlanData>();
  storage.fetchPlan.mockReturnValueOnce(next.promise);
  const loading = state().loadPlan("other");
  await vi.advanceTimersByTimeAsync(300);
  expect(storage.runSimulation).not.toHaveBeenCalled();
  next.resolve(makePlan("other"));
  await loading;
  await vi.advanceTimersByTimeAsync(300);
  expect(storage.runSimulation).toHaveBeenCalledExactlyOnceWith("other");
});
it.each(["resolve", "reject"] as const)("ignores an older plan load that %ss", async (outcome) => {
  const old = deferred<PlanData>();
  storage.fetchPlan.mockReturnValueOnce(old.promise).mockResolvedValueOnce(makePlan("new"));
  const loading = state().loadPlan("old");
  await state().loadPlan("new");
  if (outcome === "resolve") old.resolve(makePlan("old"));
  else old.reject("old error");
  await loading;
  expect(state().plan?.id).toBe("new");
  expect(state().error).toBeNull();
});
it("does not start a simulation for an inactive plan", async () => {
  await state().runSimulation("other");
  expect(storage.runSimulation).not.toHaveBeenCalled();
  expect(state().isSimulating).toBe(false);
});
it("clears the displayed forecast as soon as saved inputs change", async () => {
  storage.updatePlan = vi.fn().mockResolvedValue({ ...makePlan(), name: "Changed" });
  await state().updatePlan("p", { name: "Changed" });
  expect(state().simulation).toBeNull();
  expect(state().isSimulating).toBe(true);
});
it("does not let an older error timer erase a newer failure", async () => {
  storage.fetchPlans = vi
    .fn()
    .mockRejectedValueOnce(new Error("First"))
    .mockRejectedValueOnce("Second");
  await state().loadPlans();
  await vi.advanceTimersByTimeAsync(4000);
  await state().loadPlans();
  await vi.advanceTimersByTimeAsync(1000);
  expect(state().error).toBe("An unexpected error occurred");
  await vi.advanceTimersByTimeAsync(4000);
  expect(state().error).toBeNull();
});
it("loads, creates, updates and deletes plans without changing unrelated entries", async () => {
  const other = makePlan("other");
  storage.fetchPlans = vi.fn().mockResolvedValue([makePlan(), other]);
  await state().loadPlans();
  expect(state().plans).toEqual([makePlan(), other]);
  const created = makePlan("new");
  storage.createPlan = vi.fn().mockResolvedValue(created);
  storage.fetchPlan.mockResolvedValueOnce(created);
  await state().createPlan({ name: "new", birth_year: 1990 });
  expect(state().plan).toEqual(created);
  expect(state().plans).toHaveLength(3);
  expect(state().simulation).toBeNull();
  await vi.advanceTimersByTimeAsync(300);
  storage.updatePlan = vi.fn().mockResolvedValue({ ...other, name: "Renamed" });
  await state().updatePlan("other", { name: "Renamed" });
  expect(state().plan).toEqual(created);
  expect(state().plans[1].name).toBe("Renamed");
  storage.deletePlan = vi.fn().mockResolvedValue(undefined);
  await state().deletePlan("other");
  expect(state().plans.map((p) => p.id)).toEqual(["p", "new"]);
  expect(state().plan).toEqual(created);
  expect(state().simulation).toBe(forecast);
  await state().deletePlan("new");
  expect(state().plan).toBeNull();
  expect(state().simulation).toBeNull();
});
it.each(["createPlan", "updatePlan", "deletePlan", "loadPlan"] as const)(
  "%s failure retains persisted state and reports the error",
  async (operation) => {
    storage[operation === "loadPlan" ? "fetchPlan" : operation] = vi
      .fn()
      .mockRejectedValue(new Error("Unavailable"));
    const plan = state().plan,
      plans = state().plans;
    if (operation === "createPlan") await state().createPlan({ name: "New", birth_year: 1990 });
    else if (operation === "updatePlan") await state().updatePlan("p", { name: "Changed" });
    else await state()[operation]("p");
    expect(state().plan).toBe(plan);
    expect(state().plans).toBe(plans);
    expect(state().error).toBe("Unavailable");
  },
);
for (const operation of [
  "updatePriorities",
  "updateDrawdownOrder",
  "updateResidencyPeriods",
] as const) {
  const items = [{ account_id: "a", priority_rank: 1, state_code: "CA" }];
  const invoke = () =>
    (state()[operation] as (id: string, rows: unknown[], revision: number) => Promise<void>)(
      "p",
      items,
      7,
    );
  const remote = operation === "updateResidencyPeriods" ? "updatePlan" : operation;
  const response =
    operation === "updatePriorities"
      ? { items, revision: 8 }
      : operation === "updateResidencyPeriods"
        ? { ...makePlan(), residency_periods: items }
        : items;
  it(`${operation} applies confirmed server data and uses the exact revision/body`, async () => {
    storage[remote] = vi.fn().mockResolvedValue(response);
    await invoke();
    expect(storage[remote]).toHaveBeenCalledExactlyOnceWith(
      "p",
      ...(operation === "updatePriorities"
        ? [items, 7]
        : operation === "updateResidencyPeriods"
          ? [{ residency_periods: items }]
          : [items]),
    );
    expect(
      state().plan?.[
        operation === "updatePriorities"
          ? "priorities"
          : operation === "updateResidencyPeriods"
            ? "residency_periods"
            : "drawdown_order"
      ],
    ).toEqual(items);
    if (operation === "updatePriorities") expect(state().plan?.priorities_revision).toBe(8);
    await vi.advanceTimersByTimeAsync(300);
    expect(storage.runSimulation).toHaveBeenCalledExactlyOnceWith("p");
  });
  it(`${operation} does not overwrite state or auto-retry on failure`, async () => {
    storage[remote] = vi.fn().mockRejectedValue(new Error("Review latest saved rules"));
    const previous = state().plan;
    if (operation === "updateResidencyPeriods")
      await expect(invoke()).rejects.toThrow("Review latest saved rules");
    else await invoke();
    expect(state().plan).toBe(previous);
    expect(state().error).toBe("Review latest saved rules");
    await vi.advanceTimersByTimeAsync(1000);
    expect(storage[remote]).toHaveBeenCalledTimes(1);
    expect(storage.runSimulation).not.toHaveBeenCalled();
  });
  it(`${operation} cannot replace another plan after a late response`, async () => {
    const pending = deferred<unknown>();
    storage[remote] = vi.fn().mockReturnValue(pending.promise);
    const saving = invoke();
    const other = makePlan("other");
    usePlanStore.setState({ plan: other, plans: [makePlan(), other] });
    pending.resolve(response);
    await saving;
    expect(state().plan).toBe(other);
    expect(storage.runSimulation).not.toHaveBeenCalled();
  });
}
it("refreshes accounts without an active plan and reports a failed plan refresh", async () => {
  storage.createAccount = vi.fn().mockResolvedValue({ id: "a" });
  usePlanStore.setState({ plan: null });
  await state().saveAccount(null, { name: "Cash", account_type: "savings", balance: 100 });
  expect(state().accountsRevision).toBe(1);
  expect(storage.fetchPlan).not.toHaveBeenCalled();
  usePlanStore.setState({ plan: makePlan() });
  storage.fetchPlan.mockRejectedValue(new Error("Refresh unavailable"));
  await state().saveAccount(null, { name: "Cash", account_type: "savings", balance: 200 });
  expect(state().accountsRevision).toBe(2);
  expect(state().error).toBe("Refresh unavailable");
  await vi.advanceTimersByTimeAsync(300);
  expect(state().simulation).toEqual(forecast);
});
it("discards an account refresh when another plan has loaded", async () => {
  const refresh = deferred<PlanData>();
  storage.fetchPlan.mockReturnValueOnce(refresh.promise).mockResolvedValueOnce(makePlan("other"));
  storage.deleteAccount = vi.fn().mockResolvedValue(undefined);
  const deleting = state().deleteAccount("a");
  await Promise.resolve();
  await state().loadPlan("other");
  refresh.resolve(makePlan());
  await deleting;
  expect(state().plan?.id).toBe("other");
  expect(state().accountsRevision).toBe(1);
});
it("compares a selected baseline and recovers from comparison failure", async () => {
  storage.fetchCompare = vi
    .fn()
    .mockResolvedValueOnce({ baseline: forecast })
    .mockRejectedValueOnce(new Error("Comparison unavailable"));
  await state().setBaselinePlan("base");
  expect(storage.fetchCompare).toHaveBeenCalledWith("p", "base");
  expect(state().compareMode).toBe(true);
  expect(state().baselineSimulation).toEqual(forecast);
  await state().setBaselinePlan("broken");
  expect(state().isComparing).toBe(false);
  expect(state().baselinePlanId).toBeNull();
  expect(state().error).toBe("Comparison unavailable");
  await state().setBaselinePlan(null);
  expect(state().compareMode).toBe(false);
  usePlanStore.setState({ plan: null });
  await state().setBaselinePlan("base");
  expect(storage.fetchCompare).toHaveBeenCalledTimes(2);
});
it("ignores a rejected comparison after it is cleared", async () => {
  const pending = deferred<unknown>();
  storage.fetchCompare = vi.fn().mockReturnValue(pending.promise);
  const comparing = state().setBaselinePlan("base");
  state().clearBaseline();
  pending.reject(new Error("Stale error"));
  await comparing;
  expect(state().error).toBeNull();
  expect(state().compareMode).toBe(false);
});
it("does not capture a baseline during recalculation", () => {
  usePlanStore.setState({ isSimulating: true });
  state().saveBaseline();
  expect(state().baselineSimulation).toBeNull();
});
it("deletePlan reports success, drops a pending forecast and comparison of the deleted plan, and clears a stale error", async () => {
  const other = makePlan("other");
  usePlanStore.setState({
    plans: [makePlan(), other],
    error: "Older failure",
    compareMode: true,
    baselinePlanId: "other",
    baselineSimulation: forecast,
  });
  storage.deletePlan = vi.fn().mockResolvedValue(undefined);
  expect(await state().deletePlan("other")).toBe(true);
  expect(state()).toMatchObject({
    error: null,
    compareMode: false,
    baselinePlanId: null,
    baselineSimulation: null,
  });
  expect(state().plan?.id).toBe("p");
  const pending = deferred<SimulationResult>();
  storage.runSimulation = vi.fn().mockReturnValue(pending.promise);
  void state().runSimulation("p");
  expect(await state().deletePlan("p")).toBe(true);
  pending.resolve(forecast);
  await vi.runAllTimersAsync();
  expect(state()).toMatchObject({ plan: null, plans: [], simulation: null, isSimulating: false });
  storage.deletePlan = vi.fn().mockRejectedValue(new Error("Unavailable"));
  expect(await state().deletePlan("gone")).toBe(false);
  expect(state().error).toBe("Unavailable");
});
