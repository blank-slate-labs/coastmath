import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock the API client before importing the store
vi.mock("@/api/client", () => ({
  fetchPlans: vi.fn(),
  fetchPlan: vi.fn(),
  createPlan: vi.fn(),
  updatePlan: vi.fn(),
  deletePlan: vi.fn(),
  createMilestone: vi.fn(),
  updateMilestone: vi.fn(),
  deleteMilestone: vi.fn(),
  createIncome: vi.fn(),
  updateIncome: vi.fn(),
  deleteIncome: vi.fn(),
  createExpense: vi.fn(),
  updateExpense: vi.fn(),
  deleteExpense: vi.fn(),
  updatePriorities: vi.fn(),
  updateDrawdownOrder: vi.fn(),
  runSimulation: vi.fn(),
}));

import { setStorageAdapter, usePlanStore } from "./plan_store";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";
import type { MilestoneCreate, RealAssetCreate } from "@/types/plan";

describe("plan_store", () => {
  beforeEach(() => {
    // Reset store to initial state between tests
    usePlanStore.setState({
      plan: null,
      plans: [],
      simulation: null,
      isSimulating: false,
      error: null,
      currencyMode: "nominal",
    });
  });

  it("has null plan and empty plans array in initial state", () => {
    const state = usePlanStore.getState();
    expect(state.plan).toBeNull();
    expect(state.plans).toEqual([]);
  });

  it("has null simulation in initial state", () => {
    const state = usePlanStore.getState();
    expect(state.simulation).toBeNull();
    expect(state.isSimulating).toBe(false);
  });

  it("has nominal as default currency mode", () => {
    const state = usePlanStore.getState();
    expect(state.currencyMode).toBe("nominal");
  });

  it("has all expected action functions", () => {
    const state = usePlanStore.getState();

    const expectedActions: (keyof typeof state)[] = [
      "setCurrencyMode",
      "loadPlans",
      "loadPlan",
      "createPlan",
      "updatePlan",
      "deletePlan",
      "addMilestone",
      "updateMilestone",
      "deleteMilestone",
      "addIncome",
      "updateIncome",
      "deleteIncome",
      "addExpense",
      "updateExpense",
      "deleteExpense",
      "updatePriorities",
      "updateDrawdownOrder",
      "runSimulation",
    ];

    for (const action of expectedActions) {
      expect(typeof state[action]).toBe("function");
    }
  });

  it("setCurrencyMode updates the mode and remembers the display preference", () => {
    usePlanStore.getState().setCurrencyMode("inflation_adjusted");
    expect(localStorage.getItem("coastmath:currency_mode")).toBe("inflation_adjusted");
    expect(usePlanStore.getState().currencyMode).toBe("inflation_adjusted");
  });

  it.each([
    [null, "inflation_adjusted"],
    ["nominal", "nominal"],
    ["inflation_adjusted", "inflation_adjusted"],
  ])(
    "starts in today's dollars unless future dollars were chosen (saved %s)",
    async (saved, expected) => {
      localStorage.clear();
      if (saved) localStorage.setItem("coastmath:currency_mode", saved);
      vi.resetModules();
      const { usePlanStore: fresh } = await import("./plan_store");
      expect(fresh.getState().currencyMode).toBe(expected);
    },
  );
});

describe("archiveActivePlans", () => {
  it("drops archived plans from the active list before the refreshed list arrives", async () => {
    let finishList!: () => void;
    const archivePlan = vi.fn().mockResolvedValue(undefined);
    setStorageAdapter(makeAdapter({ archivePlan }));
    const loadPlans = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finishList = resolve;
        }),
    );
    const plan = makePlan({ id: "old", name: "Old" });
    usePlanStore.setState({
      plan,
      plans: [plan],
      activePlanId: "old",
      loadPlans,
      loadArchivedPlans: vi.fn().mockResolvedValue(undefined),
    });
    const done = usePlanStore.getState().archiveActivePlans();
    await vi.waitFor(() => expect(loadPlans).toHaveBeenCalled());
    // Nothing is left to reopen while the list reloads: the access policy may refuse an archived plan.
    expect(usePlanStore.getState()).toMatchObject({ plan: null, plans: [], activePlanId: null });
    finishList();
    expect(await done).toBe(true);
  });
});

describe("row add and update actions", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    usePlanStore.setState({ error: null, runSimulation: vi.fn().mockResolvedValue(undefined) });
  });
  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it("addRealAsset resolves true and appends the server's row to the open plan", async () => {
    const createRealAsset = vi.fn().mockResolvedValue({ id: "new", name: "Cabin" });
    setStorageAdapter(makeAdapter({ createRealAsset }));
    usePlanStore.setState({
      plan: makePlan({ id: "p", real_assets: [{ id: "home", name: "Home" }] }),
    });

    expect(
      await usePlanStore.getState().addRealAsset("p", { name: "Cabin" } as RealAssetCreate),
    ).toBe(true);
    expect(createRealAsset).toHaveBeenCalledWith("p", { name: "Cabin" });
    expect(usePlanStore.getState().plan?.real_assets.map((a) => a.id)).toEqual(["home", "new"]);
    expect(usePlanStore.getState().isSimulating).toBe(true);
  });

  it("updateLiability resolves true and replaces only the matching row", async () => {
    const updateLiability = vi.fn().mockResolvedValue({ id: "car", name: "Car loan (refinanced)" });
    setStorageAdapter(makeAdapter({ updateLiability }));
    usePlanStore.setState({
      plan: makePlan({
        id: "p",
        liabilities: [
          { id: "car", name: "Car loan" },
          { id: "home", name: "Mortgage" },
        ],
      }),
    });

    expect(
      await usePlanStore.getState().updateLiability("p", "car", { name: "Car loan (refinanced)" }),
    ).toBe(true);
    expect(updateLiability).toHaveBeenCalledWith("p", "car", { name: "Car loan (refinanced)" });
    expect(usePlanStore.getState().plan?.liabilities.map((l) => l.name)).toEqual([
      "Car loan (refinanced)",
      "Mortgage",
    ]);
  });

  it("updateMilestone resolves false, reports the error and leaves the plan unchanged on failure", async () => {
    setStorageAdapter(
      makeAdapter({
        updateMilestone: vi.fn().mockRejectedValue(new Error("Save milestone was not saved.")),
      }),
    );
    const plan = makePlan({ id: "p", milestones: [{ id: "m", name: "Retire" }] });
    usePlanStore.setState({ plan });

    expect(await usePlanStore.getState().updateMilestone("p", "m", { name: "Later" })).toBe(false);
    expect(usePlanStore.getState().error).toBe("Save milestone was not saved.");
    expect(usePlanStore.getState().plan).toBe(plan);
  });

  it("does not put a row into a different plan that opened while the save ran", async () => {
    setStorageAdapter(
      makeAdapter({ createMilestone: vi.fn().mockResolvedValue({ id: "m", name: "Retire" }) }),
    );
    const other = makePlan({ id: "other" });
    usePlanStore.setState({ plan: other });

    expect(
      await usePlanStore.getState().addMilestone("p", { name: "Retire" } as MilestoneCreate),
    ).toBe(true);
    expect(usePlanStore.getState().plan).toBe(other);
  });
});
