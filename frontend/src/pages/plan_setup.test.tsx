/** Store integration for residency saves. Render regressions live in LiveEditQa.test.tsx. */

import { describe, it, expect, vi, beforeEach } from "vitest";
import type { Mock } from "vitest";

import { setStorageAdapter } from "@/stores/plan_store";
import { usePlanStore } from "@/stores/plan_store";
import type { PlanData, ResidencyPeriodCreate } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

function buildPlan(overrides: Partial<PlanData> = {}): PlanData {
  return makePlan({
    id: "plan-1",
    user_id: "user-1",
    name: "Test",
    birth_year: 1990,
    state_code: "CA",
    created_at: new Date().toISOString(),
    ...overrides,
  });
}

describe("PlanSetup residency timeline → plan_store", () => {
  let updatePlanMock: Mock;
  let runSimulationMock: Mock;

  beforeEach(() => {
    updatePlanMock = vi.fn();
    runSimulationMock = vi.fn().mockResolvedValue({
      metadata: {
        plan_id: "plan-1",
        start_year: 2026,
        end_year: 2060,
        success: true,
        failure_year: null,
        net_legacy: null,
        rmd_start_age: null,
      },
      yearly_snapshots: [],
    });

    const fakeAdapter = makeAdapter({
      updatePlan: updatePlanMock,
      runSimulation: runSimulationMock,
    });
    setStorageAdapter(fakeAdapter);

    usePlanStore.setState({
      plan: buildPlan(),
      plans: [buildPlan()],
      simulation: null,
      isSimulating: false,
      error: null,
      currencyMode: "nominal",
    });
  });

  it("updateResidencyPeriods sends rows in PUT body with assigned ranks", async () => {
    updatePlanMock.mockResolvedValue(
      buildPlan({
        residency_periods: [
          {
            id: "rp-1",
            plan_id: "plan-1",
            state_code: "CA",
            start_milestone_id: null,
            end_milestone_id: null,
            start_year: null,
            end_year: 2029,
            rank: 0,
          },
          {
            id: "rp-2",
            plan_id: "plan-1",
            state_code: "NV",
            start_milestone_id: null,
            end_milestone_id: null,
            start_year: 2030,
            end_year: null,
            rank: 1,
          },
        ],
      }),
    );

    const rows: ResidencyPeriodCreate[] = [
      { state_code: "CA", end_year: 2029, rank: 0 },
      { state_code: "NV", start_year: 2030, rank: 1 },
    ];

    await usePlanStore.getState().updateResidencyPeriods("plan-1", rows);

    expect(updatePlanMock).toHaveBeenCalledWith("plan-1", {
      residency_periods: rows,
    });

    const stored = usePlanStore.getState().plan?.residency_periods ?? [];
    expect(stored).toHaveLength(2);
    expect(stored.map((p) => p.state_code)).toEqual(["CA", "NV"]);
    expect(stored[0].rank).toBe(0);
    expect(stored[1].rank).toBe(1);
  });

  it("updateResidencyPeriods with empty array clears residency_periods", async () => {
    usePlanStore.setState({
      plan: buildPlan({
        residency_periods: [
          {
            id: "rp-existing",
            plan_id: "plan-1",
            state_code: "TX",
            start_milestone_id: null,
            end_milestone_id: null,
            start_year: null,
            end_year: null,
            rank: 0,
          },
        ],
      }),
    });
    updatePlanMock.mockResolvedValue(buildPlan({ residency_periods: [] }));

    await usePlanStore.getState().updateResidencyPeriods("plan-1", []);

    expect(updatePlanMock).toHaveBeenCalledWith("plan-1", {
      residency_periods: [],
    });
    expect(usePlanStore.getState().plan?.residency_periods).toEqual([]);
  });

  it("updateResidencyPeriods surfaces adapter errors to store.error", async () => {
    updatePlanMock.mockRejectedValue(new Error("boom"));

    await expect(
      usePlanStore.getState().updateResidencyPeriods("plan-1", [{ state_code: "CA", rank: 0 }]),
    ).rejects.toThrow("boom");

    expect(usePlanStore.getState().error).toBe("boom");
  });
});
