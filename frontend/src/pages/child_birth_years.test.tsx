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
    filing_status: "married_filing_jointly",
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
      ca_dependents_by_year: { 2026: 1 },
      dependent_birth_years: [2019],
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

async function field() {
  await act(async () => {
    render(
      <BuilderModeContext.Provider value="sheet">
        <PlanHeader />
      </BuilderModeContext.Provider>,
    );
  });
  return screen.getByLabelText(/Children's birth years/) as HTMLInputElement;
}

it("shows saved birth years and saves edits without dropping other tax settings", async () => {
  const input = await field();
  expect(input).toHaveValue("2019");
  fireEvent.change(input, { target: { value: "2019, 2023" } });
  fireEvent.blur(input);
  await waitFor(() => expect(adapter.updatePlan).toHaveBeenCalledOnce());
  const sent = adapter.updatePlan.mock.calls[0][1].tax_settings!;
  expect(sent.dependent_birth_years).toEqual([2019, 2023]);
  expect(sent.ca_dependents_by_year).toEqual({ 2026: 1 });
});

it("rejects text that is not a list of years and saves an empty field as none", async () => {
  const input = await field();
  fireEvent.change(input, { target: { value: "2019, soon" } });
  fireEvent.blur(input);
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByText("Enter four-digit years separated by commas.")).toBeInTheDocument();
  expect(adapter.updatePlan).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "" } });
  fireEvent.blur(input);
  await waitFor(() => expect(adapter.updatePlan).toHaveBeenCalledOnce());
  expect(adapter.updatePlan.mock.calls[0][1].tax_settings!.dependent_birth_years).toEqual([]);
});
