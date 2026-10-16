import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { BuilderModeContext, PlanHeader } from "@/pages/plan_setup";
import { setStorageAdapter, usePlanStore } from "@/stores/plan_store";
import type { PlanCreate, PlanData } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

let persisted: PlanData;
beforeEach(() => {
  vi.clearAllMocks();
  persisted = makePlan({
    id: "p",
    user_id: "u",
    name: "Plan",
    birth_year: 1985,
    state_code: "",
    local_tax: null,
    life_expectancy: 90,
    tax_settings: {
      mode: "detailed",
      ordinary_income_tax_rate: null,
      capital_gains_tax_rate: null,
      taxable_withholding_rate: 0,
      tax_deferred_withholding_rate: 0,
      settlement_lag_years: 0,
    },
  });
  usePlanStore.setState({ ...usePlanStore.getInitialState(), plan: persisted });
  setStorageAdapter(adapter);
  adapter.listAccounts.mockResolvedValue([]);
  adapter.listLocalTaxJurisdictions.mockResolvedValue({ tax_year: 2026, jurisdictions: [] });
  adapter.updatePlan.mockImplementation(async (_id: string, data: Partial<PlanCreate>) => {
    persisted = { ...persisted, ...data } as PlanData;
    return persisted;
  });
});

it("renders one filing status schedule however many times the plan saves", async () => {
  await act(async () => {
    render(
      <BuilderModeContext.Provider value="sheet">
        <PlanHeader />
      </BuilderModeContext.Provider>,
    );
  });
  const filingStatus = screen.getByLabelText("Filing status");
  for (const status of ["married_filing_jointly", "single", "head_of_household"]) {
    fireEvent.change(filingStatus, { target: { value: status } });
    await waitFor(() => expect(usePlanStore.getState().plan?.filing_status).toBe(status));
  }
  expect(screen.getAllByText("Filing status changes")).toHaveLength(1);
});
