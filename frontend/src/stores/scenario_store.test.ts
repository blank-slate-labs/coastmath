import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import type { PlanSummary } from "@/types/plan";
import type { PlanInheritance } from "@/types/scenario";
import { setStorageAdapter, usePlanStore } from "./plan_store";
import { useSaveStore } from "./save_store";
import { changeCount, useInheritanceSync, useScenarioStore } from "./scenario_store";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const main = makePlan({ id: "p", name: "Primary", client_id: "c" });
const scenario = makePlan({ id: "s", name: "Retire at 55", client_id: "c", parent_plan_id: "p" });
const inheritance = (count: number): PlanInheritance => ({
  plan_id: "s",
  parent_plan_id: "p",
  parent_name: "Primary",
  status: "ok",
  synced_at: null,
  skipped: [],
  plan_fields: [],
  items: Array.from({ length: count }, (_, i) => ({
    kind: "income",
    row_id: `r${i}`,
    parent_row_id: null,
    name: `Item ${i}`,
    state: "scenario_only",
    fields: [],
  })),
});

const adapter = makeAdapter({ runSimulation: vi.fn().mockResolvedValue(null) });

beforeEach(() => {
  vi.clearAllMocks();
  setStorageAdapter(adapter);
  usePlanStore.setState({
    ...usePlanStore.getInitialState(),
    plan: main,
    activePlanId: "p",
    plans: [main as PlanSummary],
  });
  useScenarioStore.setState({ byPlan: {} });
  useSaveStore.setState({ pending: 0, failed: [], lastSavedAt: null, lastSavedKey: null });
});

it("creates a scenario, refreshes the plan list and opens it", async () => {
  adapter.createScenario.mockResolvedValue(scenario);
  adapter.fetchPlans.mockResolvedValue([main, scenario]);
  adapter.fetchPlan.mockResolvedValue(scenario);
  expect(await usePlanStore.getState().createScenario("p", "Retire at 55")).toBe(true);
  expect(adapter.createScenario).toHaveBeenCalledWith("p", "Retire at 55");
  expect(usePlanStore.getState().plans.map((p) => p.id)).toEqual(["p", "s"]);
  expect(usePlanStore.getState().plan).toEqual(scenario);
});

it("keeps the open plan and reports the error when creating a scenario fails", async () => {
  adapter.createScenario.mockRejectedValue(new Error("Create it from the Main plan."));
  expect(await usePlanStore.getState().createScenario("s")).toBe(false);
  expect(usePlanStore.getState()).toMatchObject({
    plan: main,
    error: "Create it from the Main plan.",
  });
});

it("makes a scenario independent in the open plan and the plan list", async () => {
  const detached = { ...scenario, parent_plan_id: undefined };
  adapter.detachScenario.mockResolvedValue(detached);
  usePlanStore.setState({ plan: scenario, plans: [main, scenario] });
  expect(await usePlanStore.getState().detachScenario("s")).toBe(true);
  expect(usePlanStore.getState().plan?.parent_plan_id).toBeUndefined();
  expect(usePlanStore.getState().plans.find((p) => p.id === "s")?.parent_plan_id).toBeUndefined();
});

it("lists a deleted Main plan’s scenarios as independent plans", async () => {
  adapter.deletePlan.mockResolvedValue(undefined);
  usePlanStore.setState({ plans: [main, scenario] });
  expect(await usePlanStore.getState().deletePlan("p")).toBe(true);
  expect(usePlanStore.getState().plans).toEqual([{ ...scenario, parent_plan_id: null }]);
});

it("keeps only the latest inheritance read and counts every difference", async () => {
  let resolveFirst: (value: PlanInheritance) => void = () => {};
  adapter.fetchInheritance
    .mockReturnValueOnce(
      new Promise((resolve) => {
        resolveFirst = resolve;
      }),
    )
    .mockResolvedValueOnce(inheritance(2));
  const store = useScenarioStore.getState();
  const first = store.load(adapter, "s");
  await store.load(adapter, "s");
  resolveFirst(inheritance(5));
  await first;
  const entry = useScenarioStore.getState().byPlan.s;
  expect(entry).toMatchObject({ loading: false, failed: false });
  expect(changeCount(entry.data!)).toBe(2);
  expect(
    changeCount({
      ...inheritance(1),
      plan_fields: [{ field: "life_expectancy", value: 90, parent_value: 95 }],
    }),
  ).toBe(2);
});

// The API client confirms a save before the awaiting store action resumes.
const confirmSave = (key: string) => {
  const save = useSaveStore.getState();
  save.finish(key, true, save.begin(key));
};

it("rereads the open scenario after a save but not after its own deletion", async () => {
  adapter.fetchInheritance.mockResolvedValue(inheritance(0));
  usePlanStore.setState({ plan: scenario, activePlanId: "s", plans: [main, scenario] });
  renderHook(() => useInheritanceSync(adapter));
  await waitFor(() => expect(adapter.fetchInheritance).toHaveBeenCalledTimes(1));

  act(() => confirmSave("put /plans/s/incomes/r0"));
  await waitFor(() => expect(adapter.fetchInheritance).toHaveBeenCalledTimes(2));

  // In the browser React commits the confirmed DELETE while the plan store still has the
  // deleted plan open; act() makes that ordering deterministic.
  let finishDelete: () => void = () => {};
  adapter.deletePlan.mockImplementation(
    (id: string) =>
      new Promise<void>((resolve) => {
        finishDelete = () => {
          confirmSave(`delete /plans/${id}`);
          resolve();
        };
      }),
  );
  let deleted: Promise<boolean> = Promise.resolve(false);
  act(() => {
    deleted = usePlanStore.getState().deletePlan("s");
  });
  act(() => finishDelete());
  expect(usePlanStore.getState().plan?.id).toBe("s");
  await act(async () => {
    expect(await deleted).toBe(true);
  });
  expect(usePlanStore.getState().plan).toBeNull();
  expect(adapter.fetchInheritance).toHaveBeenCalledTimes(2);
});
