import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { BuilderModeContext, PlanHeader, ResidencyTimelineEditor } from "@/pages/plan_setup";
import { setStorageAdapter, usePlanStore } from "@/stores/plan_store";
import type { PlanCreate, PlanData, ResidencyPeriod, TaxRegimeCountry } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const adapter = vi.hoisted(() => ({
  listAccounts: vi.fn(),
  updatePlan: vi.fn(),
  listLocalTaxJurisdictions: vi.fn(),
  listTaxRegimes: vi.fn(),
  runSimulation: vi.fn(),
}));
// A fresh adapter object per test, so the per-adapter registry cache reloads.
let current = makeAdapter(adapter);
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => current),
);

const REGISTRY: TaxRegimeCountry[] = [
  {
    code: "ZZ",
    name: "Testland",
    currency: "SEK",
    filing_unit: "individual",
    regions: [],
    account_kinds: [],
    benefit_rules: [],
    spec_years: [2026],
    approximations: [],
  },
  {
    code: "QZ",
    name: "Fixture country",
    currency: "EUR",
    filing_unit: "individual",
    regions: [
      { code: "N", name: "North" },
      { code: "S", name: "South" },
    ],
    account_kinds: [{ id: "QZ:pension_saver", label: "Pension saver", category: "tax_deferred" }],
    benefit_rules: [
      {
        id: "QZ:basic_pension",
        label: "Basic pension",
        params_schema: {
          type: "object",
          properties: {
            expected_percent: {
              type: "number",
              title: "Expected percent of maximum",
              minimum: 0,
              maximum: 100,
            },
          },
          required: ["expected_percent"],
        },
      },
    ],
    spec_years: [2026],
    approximations: [],
  },
  {
    code: "XX",
    name: "Other (custom rules)",
    currency: "USD",
    filing_unit: "individual",
    regions: [],
    account_kinds: [],
    benefit_rules: [],
    spec_years: [],
    approximations: [],
  },
];

const year = new Date().getFullYear();
let persisted: PlanData;

function basePlan(overrides: Partial<PlanData> = {}): PlanData {
  return makePlan({
    id: "p",
    user_id: "u",
    name: "Plan",
    birth_year: year - 40,
    birth_month: null,
    profile_name: null,
    state_code: "CA",
    local_tax: null,
    life_expectancy: 90,
    ...overrides,
  });
}

let rejectNext: Error | null = null;

beforeEach(() => {
  vi.clearAllMocks();
  rejectNext = null;
  persisted = basePlan();
  usePlanStore.setState({ ...usePlanStore.getInitialState(), plan: persisted });
  current = makeAdapter(adapter);
  setStorageAdapter(current);
  adapter.listAccounts.mockResolvedValue([]);
  adapter.runSimulation.mockReturnValue(new Promise(() => {}));
  adapter.listLocalTaxJurisdictions.mockResolvedValue({ tax_year: 2026, jurisdictions: [] });
  adapter.listTaxRegimes.mockResolvedValue({ countries: REGISTRY });
  adapter.updatePlan.mockImplementation(async (_id: string, data: Partial<PlanCreate>) => {
    if (rejectNext) {
      const error = rejectNext;
      rejectNext = null;
      throw error;
    }
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

it("lists the registry's countries and asks before switching, naming the US settings that stop", async () => {
  await renderHeader();
  const picker = screen.getByLabelText("Tax country");
  await waitFor(() =>
    expect(within(picker).getByRole("option", { name: "Testland" })).toBeInTheDocument(),
  );
  expect(
    within(picker)
      .getAllByRole("option")
      .map((o) => o.textContent),
  ).toEqual(["United States", "Fixture country", "Testland", "Other (custom rules)"]);

  fireEvent.change(picker, { target: { value: "QZ" } });
  const dialog = screen.getByRole("alertdialog", {
    name: "Switch tax country to Fixture country?",
  });
  expect(dialog).toHaveTextContent("Marketplace (ACA) coverage, Medicare and IRMAA");
  expect(dialog).toHaveTextContent("They stay saved.");
  expect(adapter.updatePlan).not.toHaveBeenCalled();

  fireEvent.click(within(dialog).getByRole("button", { name: "Keep United States" }));
  expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(screen.getByLabelText("Tax country")).toHaveValue("US");

  fireEvent.change(screen.getByLabelText("Tax country"), { target: { value: "QZ" } });
  fireEvent.click(screen.getByRole("button", { name: "Switch to Fixture country" }));
  await waitFor(() =>
    expect(adapter.updatePlan).toHaveBeenLastCalledWith("p", {
      tax_country: "QZ",
      tax_region: "N",
      currency: "EUR",
    }),
  );
  expect(screen.getByLabelText("Region")).toHaveValue("N");
});

it("keeps the currency when the switch confirmation's currency box is cleared", async () => {
  await renderHeader();
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("Tax country")).getByRole("option", { name: "Testland" }),
    ).toBeInTheDocument(),
  );
  fireEvent.change(screen.getByLabelText("Tax country"), { target: { value: "ZZ" } });
  fireEvent.click(screen.getByLabelText(/Also show amounts in SEK/));
  fireEvent.click(screen.getByRole("button", { name: "Switch to Testland" }));
  await waitFor(() =>
    expect(adapter.updatePlan).toHaveBeenLastCalledWith("p", { tax_country: "ZZ" }),
  );
});

it("shows loading, then an error with retry, and keeps the plan usable", async () => {
  let fail: (error: Error) => void = () => {};
  adapter.listTaxRegimes.mockReturnValueOnce(
    new Promise((_, reject) => {
      fail = reject;
    }),
  );
  await renderHeader();
  expect(screen.getByText("Loading countries…")).toBeInTheDocument();
  await act(async () => {
    fail(new Error("offline"));
  });
  expect(screen.getByText(/The country list could not load/)).toBeInTheDocument();
  expect(screen.getByLabelText("Tax country")).toHaveValue("US");
  adapter.listTaxRegimes.mockResolvedValueOnce({ countries: REGISTRY });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  });
  await waitFor(() => expect(screen.queryByText(/could not load/)).toBeNull());
  expect(
    within(screen.getByLabelText("Tax country")).getByRole("option", { name: "Fixture country" }),
  ).toBeInTheDocument();
});

it("keeps a withdrawn saved country selectable and says nothing of it carries over", async () => {
  persisted = basePlan({ tax_country: "CA", currency: "CAD", state_code: null });
  usePlanStore.setState({ plan: persisted });
  adapter.listTaxRegimes.mockResolvedValue({ countries: REGISTRY.filter((c) => c.code === "XX") });
  await renderHeader();
  const picker = screen.getByLabelText("Tax country");
  await waitFor(() =>
    expect(
      within(picker).getByRole("option", { name: "Other (custom rules)" }),
    ).toBeInTheDocument(),
  );
  expect(
    within(picker)
      .getAllByRole("option")
      .map((o) => o.textContent),
  ).toEqual(["United States", "Other (custom rules)", "Canada"]);
  fireEvent.change(picker, { target: { value: "US" } });
  const dialog = screen.getByRole("alertdialog", { name: "Switch tax country to United States?" });
  expect(dialog).toHaveTextContent(
    "Canada is no longer supported; its benefits and contribution room are removed.",
  );
  fireEvent.click(screen.getByRole("button", { name: "Switch to United States" }));
  await waitFor(() =>
    expect(adapter.updatePlan).toHaveBeenLastCalledWith(
      "p",
      expect.objectContaining({ tax_country: "US" }),
    ),
  );
});

it("keeps the draft country when the save is rejected", async () => {
  await renderHeader();
  await waitFor(() =>
    expect(
      within(screen.getByLabelText("Tax country")).getByRole("option", { name: "Fixture country" }),
    ).toBeInTheDocument(),
  );
  rejectNext = Object.assign(new Error("rejected"), {
    response: {
      status: 422,
      data: {
        error: {
          code: "VALIDATION_ERROR",
          message: "Validation failed",
          details: [
            { field: "healthcare_settings", reason: "Marketplace coverage needs a US year" },
          ],
        },
      },
    },
  });
  fireEvent.change(screen.getByLabelText("Tax country"), { target: { value: "QZ" } });
  fireEvent.click(screen.getByRole("button", { name: "Switch to Fixture country" }));
  await waitFor(() => expect(adapter.updatePlan).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(usePlanStore.getState().error).toBeTruthy());
  expect(persisted.tax_country).toBeUndefined();
  // The picker keeps the user's choice; the saved plan still shows its US settings to fix.
  expect(screen.getByLabelText("Tax country")).toHaveValue("QZ");
  expect(screen.getByPlaceholderText("2019, 2022")).toBeInTheDocument();
});

it("hides US-only settings in an all-non-US plan and notes them in a plan that moves", async () => {
  persisted = basePlan({ tax_country: "ZZ", currency: "SEK", state_code: null });
  usePlanStore.setState({ plan: persisted });
  const { unmount } = render(
    <BuilderModeContext.Provider value="sheet">
      <PlanHeader />
    </BuilderModeContext.Provider>,
  );
  await waitFor(() => expect(screen.getByLabelText("Tax country")).toHaveValue("ZZ"));
  expect(screen.queryByLabelText("State")).toBeNull();
  expect(screen.queryByPlaceholderText("2019, 2022")).toBeNull();
  expect(screen.queryByText(/apply only in the years you live in the US/)).toBeNull();
  expect(screen.getByLabelText("Currency")).toHaveValue("SEK");
  unmount();

  const usPeriod = {
    id: "r",
    plan_id: "p",
    state_code: "TX",
    country: "US",
    region: null,
    start_milestone_id: null,
    end_milestone_id: null,
    start_year: year + 5,
    end_year: null,
    rank: 0,
  } as ResidencyPeriod;
  usePlanStore.setState({ plan: { ...persisted, residency_periods: [usPeriod] } });
  render(
    <BuilderModeContext.Provider value="sheet">
      <PlanHeader />
    </BuilderModeContext.Provider>,
  );
  await waitFor(() => expect(screen.getByPlaceholderText("2019, 2022")).toBeInTheDocument());
  expect(screen.getAllByText(/apply only in the years you live in the US/).length).toBeGreaterThan(
    0,
  );
  // Only the US period has a state; the plan's own starting state applies only to US plans.
  expect(screen.getAllByLabelText("State")).toHaveLength(1);
  expect(screen.getByLabelText("State")).toHaveValue("TX");
});

it("offers the benefits editor and the custom rules editor for the plan's countries", async () => {
  persisted = basePlan({
    tax_country: "QZ",
    tax_region: "N",
    currency: "EUR",
    state_code: null,
    residency_periods: [
      {
        id: "r",
        plan_id: "p",
        state_code: null,
        country: "XX",
        region: null,
        start_milestone_id: null,
        end_milestone_id: null,
        start_year: year + 3,
        end_year: null,
        rank: 0,
      } as ResidencyPeriod,
    ],
  });
  usePlanStore.setState({ plan: persisted });
  await renderHeader();
  await waitFor(() => expect(screen.getByTestId("intl-benefits-editor")).toBeInTheDocument());
  expect(screen.getByTestId("custom-regime-editor")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "+ Add benefit" }));
  fireEvent.change(screen.getByLabelText("Start age"), { target: { value: "65" } });
  fireEvent.change(screen.getByLabelText("Expected percent of maximum"), {
    target: { value: "80" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save benefits" }));
  await waitFor(() =>
    expect(adapter.updatePlan).toHaveBeenLastCalledWith("p", {
      intl_settings: {
        benefits: [
          {
            rule: "QZ:basic_pension",
            owner: "self",
            start_age: 65,
            start_milestone_id: null,
            params: { expected_percent: 80 },
          },
        ],
      },
    }),
  );
});

it("residency changes take a country and region; US changes keep their state", async () => {
  const onChange = vi.fn().mockResolvedValue(undefined);
  render(
    <ResidencyTimelineEditor
      milestones={[]}
      periods={[]}
      onChange={onChange}
      planCountry="US"
      countries={REGISTRY}
    />,
  );
  fireEvent.click(screen.getByTestId("residency-add"));
  fireEvent.click(screen.getByTestId("residency-add"));
  const [first, second] = screen.getAllByLabelText("Country");
  fireEvent.change(first, { target: { value: "QZ" } });
  expect(screen.getByLabelText("Region")).toHaveValue("N");
  fireEvent.change(screen.getByLabelText("Region"), { target: { value: "S" } });
  expect(screen.getAllByLabelText("State")).toHaveLength(1);
  fireEvent.change(second, { target: { value: "" } });
  fireEvent.change(screen.getByLabelText("State"), { target: { value: "NY" } });
  fireEvent.click(screen.getByRole("button", { name: "Save residency changes" }));
  await waitFor(() => expect(onChange).toHaveBeenCalled());
  expect(onChange.mock.calls[0][0]).toEqual([
    {
      state_code: null,
      country: "QZ",
      region: "S",
      start_milestone_id: null,
      end_milestone_id: null,
      start_year: null,
      end_year: null,
      rank: 0,
      local_tax: null,
    },
    {
      state_code: "NY",
      start_milestone_id: null,
      end_milestone_id: null,
      start_year: null,
      end_year: null,
      rank: 1,
      local_tax: null,
    },
  ]);
});
