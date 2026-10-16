import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { BuilderModeContext, PlanHeader } from "@/pages/plan_setup";
import { setStorageAdapter, usePlanStore } from "@/stores/plan_store";
import type { PlanCreate, PlanData } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const adapter = makeAdapter();
// The open-source planner: no hosting package. Its own fields are tested in src/business.
vi.mock("@extensions/active", () => ({ default: {} }));
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

const year = new Date().getFullYear();
let persisted: PlanData;
beforeEach(() => {
  vi.clearAllMocks();
  persisted = makePlan({
    id: "p",
    user_id: "u",
    name: "Plan",
    birth_year: year - 40,
    birth_month: null,
    profile_name: "Alex Doe",
    state_code: "",
    local_tax: null,
    life_expectancy: 90,
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

async function renderHeader() {
  await act(async () => {
    render(
      <BuilderModeContext.Provider value="sheet">
        <PlanHeader />
      </BuilderModeContext.Provider>,
    );
  });
}

it("has no full name field without a hosting package", async () => {
  await renderHeader();
  expect(screen.getByText("Advanced tax settings")).toBeInTheDocument();
  expect(screen.queryByLabelText("Full name")).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue("Alex Doe")).not.toBeInTheDocument();
});

it("shows and autosaves the birth month and longevity age", async () => {
  await renderHeader();
  const month = screen.getByLabelText("Birth month");
  const longevity = screen.getByLabelText("Longevity age");
  expect(month).toHaveValue("");
  expect(longevity).toHaveValue(90);

  fireEvent.change(month, { target: { value: "7" } });
  await waitFor(() => expect(adapter.updatePlan).toHaveBeenLastCalledWith("p", { birth_month: 7 }));

  fireEvent.change(longevity, { target: { value: "97" } });
  fireEvent.blur(longevity);
  await waitFor(() =>
    expect(adapter.updatePlan).toHaveBeenLastCalledWith("p", { life_expectancy: 97 }),
  );
  expect(persisted).toMatchObject({ birth_month: 7, life_expectancy: 97 });
});

it("an untouched blur writes nothing", async () => {
  await renderHeader();
  fireEvent.blur(screen.getByLabelText("Longevity age"));
  expect(adapter.updatePlan).not.toHaveBeenCalled();
});

it("blocks a longevity age outside 50 to 120", async () => {
  await renderHeader();
  const longevity = screen.getByLabelText("Longevity age");
  fireEvent.change(longevity, { target: { value: "45" } });
  fireEvent.blur(longevity);
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a whole age from 50 to 120.");
  expect(longevity).toHaveAttribute("aria-describedby", "plan-longevity-error");
  expect(adapter.updatePlan).not.toHaveBeenCalled();
});

it("requires birth year plus longevity to pass the start year, then saves both fixes together", async () => {
  await renderHeader();
  const birth = screen.getByLabelText("Birth year");
  const longevity = screen.getByLabelText("Longevity age");
  fireEvent.change(birth, { target: { value: String(year - 70) } });
  fireEvent.blur(birth);
  await waitFor(() =>
    expect(adapter.updatePlan).toHaveBeenLastCalledWith("p", { birth_year: year - 70 }),
  );

  fireEvent.change(longevity, { target: { value: "65" } });
  fireEvent.blur(longevity);
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Choose a longevity age past the plan's start year.",
  );
  expect(adapter.updatePlan).toHaveBeenCalledOnce();

  fireEvent.change(birth, { target: { value: String(year - 60) } });
  fireEvent.blur(birth);
  await waitFor(() =>
    expect(adapter.updatePlan).toHaveBeenLastCalledWith("p", {
      birth_year: year - 60,
      life_expectancy: 65,
    }),
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("checks a fixed start date against the edited birth month", async () => {
  persisted = makePlan({ ...persisted, plan_type: "FIXED_DATE", start_date: `${year - 40}-03-01` });
  usePlanStore.setState({ plan: persisted });
  await renderHeader();
  fireEvent.change(screen.getByLabelText("Birth month"), { target: { value: "6" } });
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Start date must be on or after your birth year/month.",
  );
  expect(adapter.updatePlan).not.toHaveBeenCalled();
});
