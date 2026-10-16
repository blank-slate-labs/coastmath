import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { localTaxDraft, localTaxSelection, withoutCatalogLocality } from "./local_tax_fields";
import { BuilderModeContext, PlanHeader, ResidencyTimelineEditor } from "@/pages/plan_setup";
import { setStorageAdapter, usePlanStore } from "@/stores/plan_store";
import type { LocalTaxJurisdiction, PlanCreate, PlanData, ResidencyPeriod } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const jurisdiction = (id: string, name: string, state_code: string): LocalTaxJurisdiction => ({
  id,
  name,
  state_code,
  components: [{ label: `${name} tax`, base: "state_taxable_income", kind: "tax" }],
  limitations: [],
});
const catalog = {
  tax_year: 2026,
  jurisdictions: [
    jurisdiction("ny_new_york_city", "New York City", "NY"),
    jurisdiction("ny_yonkers", "Yonkers", "NY"),
    jurisdiction("pa_philadelphia", "Philadelphia", "PA"),
    jurisdiction("pa_pittsburgh", "Pittsburgh", "PA"),
  ],
};

const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

describe("local tax drafts", () => {
  it("converts decimal rates to percent text and back, omitting zero rates", () => {
    const draft = localTaxDraft({
      jurisdiction: "custom",
      earned_income_rate: 0.03876,
      state_tax_surcharge_rate: 0.1675,
    });
    expect(draft).toEqual({
      jurisdiction: "custom",
      earned_income_rate: "3.876",
      taxable_income_rate: "",
      state_tax_surcharge_rate: "16.75",
    });
    expect(localTaxSelection({ ...draft, taxable_income_rate: "0" })).toEqual({
      selection: {
        jurisdiction: "custom",
        earned_income_rate: 0.03876,
        state_tax_surcharge_rate: 0.1675,
      },
    });
  });

  it("sends a catalog locality alone and none as null", () => {
    expect(localTaxSelection(localTaxDraft({ jurisdiction: "ny_new_york_city" }))).toEqual({
      selection: { jurisdiction: "ny_new_york_city" },
    });
    expect(localTaxSelection(localTaxDraft(null))).toEqual({ selection: null });
  });

  it("rejects custom rates that are all blank or zero, or outside the server bounds", () => {
    const custom = localTaxDraft({ jurisdiction: "custom" });
    expect(localTaxSelection(custom)).toEqual({ error: "Enter at least one local tax rate." });
    expect(localTaxSelection({ ...custom, earned_income_rate: "0" })).toEqual({
      error: "Enter at least one local tax rate.",
    });
    expect(localTaxSelection({ ...custom, earned_income_rate: "12" })).toEqual({
      error: "Earned income rate: enter 0 to 10%.",
    });
    expect(localTaxSelection({ ...custom, state_tax_surcharge_rate: "40" })).toEqual({
      selection: { jurisdiction: "custom", state_tax_surcharge_rate: 0.4 },
    });
  });

  it("clears a catalog locality on a state change and keeps custom rates", () => {
    expect(withoutCatalogLocality(localTaxDraft({ jurisdiction: "ny_yonkers" })).jurisdiction).toBe(
      "",
    );
    const custom = localTaxDraft({ jurisdiction: "custom", earned_income_rate: 0.01 });
    expect(withoutCatalogLocality(custom)).toBe(custom);
  });
});

describe("plan locality", () => {
  let persisted: PlanData;
  beforeEach(() => {
    vi.clearAllMocks();
    persisted = makePlan({
      id: "p",
      user_id: "u",
      name: "Plan",
      birth_year: 1980,
      state_code: "NY",
      local_tax: null,
      life_expectancy: 90,
    });
    usePlanStore.setState({ ...usePlanStore.getInitialState(), plan: persisted });
    setStorageAdapter(adapter);
    adapter.listAccounts.mockResolvedValue([]);
    adapter.listLocalTaxJurisdictions.mockResolvedValue(catalog);
    // Mirrors the server: a state change without a selection clears one from another state.
    adapter.updatePlan.mockImplementation(async (_id: string, data: Partial<PlanCreate>) => {
      const local =
        "local_tax" in data
          ? data.local_tax
          : "state_code" in data && persisted.local_tax?.jurisdiction !== "custom"
            ? null
            : persisted.local_tax;
      persisted = { ...persisted, ...data, local_tax: local } as PlanData;
      return persisted;
    });
  });
  async function header() {
    await act(async () => {
      render(
        <BuilderModeContext.Provider value="sheet">
          <PlanHeader />
        </BuilderModeContext.Provider>,
      );
    });
    return screen.getByLabelText("Local income tax") as HTMLSelectElement;
  }
  const optionNames = (select: HTMLSelectElement) =>
    Array.from(select.options).map((option) => option.text);

  it("lists only the plan state's localities and saves a selection or none", async () => {
    const select = await header();
    expect(optionNames(select)).toEqual(["None", "New York City", "Yonkers", "Custom rates"]);
    fireEvent.change(select, { target: { value: "ny_new_york_city" } });
    await waitFor(() =>
      expect(adapter.updatePlan).toHaveBeenCalledWith("p", {
        local_tax: { jurisdiction: "ny_new_york_city" },
      }),
    );
    fireEvent.change(select, { target: { value: "" } });
    await waitFor(() =>
      expect(adapter.updatePlan).toHaveBeenLastCalledWith("p", { local_tax: null }),
    );
  });

  it("shows the saved locality and clears it with a state change", async () => {
    persisted = { ...persisted, local_tax: { jurisdiction: "ny_yonkers" } };
    usePlanStore.setState({ plan: persisted });
    const select = await header();
    expect(select).toHaveValue("ny_yonkers");
    fireEvent.change(screen.getByLabelText("State"), { target: { value: "PA" } });
    expect(screen.getByLabelText("Local income tax")).toHaveValue("");
    expect(optionNames(screen.getByLabelText("Local income tax") as HTMLSelectElement)).toEqual([
      "None",
      "Philadelphia",
      "Pittsburgh",
      "Custom rates",
    ]);
    await waitFor(() => expect(persisted.state_code).toBe("PA"));
    expect(adapter.updatePlan).toHaveBeenCalledExactlyOnceWith("p", { state_code: "PA" });
    expect(persisted.local_tax).toBeNull();
  });

  it("saves custom rates once one is entered and keeps an incomplete draft unsaved", async () => {
    const select = await header();
    fireEvent.change(select, { target: { value: "custom" } });
    expect(adapter.updatePlan).not.toHaveBeenCalled();
    const earned = screen.getByLabelText("Earned income rate (%)");
    fireEvent.blur(earned);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter at least one local tax rate.");
    expect(adapter.updatePlan).not.toHaveBeenCalled();
    fireEvent.change(earned, { target: { value: "1.5" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.blur(earned);
    await waitFor(() =>
      expect(adapter.updatePlan).toHaveBeenCalledExactlyOnceWith("p", {
        local_tax: { jurisdiction: "custom", earned_income_rate: 0.015 },
      }),
    );
    expect(screen.getByLabelText("Earned income rate (%)")).toHaveValue(1.5);
  });

  it("hides the picker without a state", async () => {
    persisted = { ...persisted, state_code: null };
    usePlanStore.setState({ plan: persisted });
    await act(async () => {
      render(
        <BuilderModeContext.Provider value="sheet">
          <PlanHeader />
        </BuilderModeContext.Provider>,
      );
    });
    expect(screen.queryByLabelText("Local income tax")).not.toBeInTheDocument();
  });
});

describe("residency period localities", () => {
  const period = (patch: Partial<ResidencyPeriod>): ResidencyPeriod => ({
    id: "r",
    plan_id: "p",
    state_code: "PA",
    start_milestone_id: null,
    end_milestone_id: null,
    start_year: null,
    end_year: 2030,
    rank: 0,
    ...patch,
  });

  it("resends each saved locality when another field changes", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(
      <ResidencyTimelineEditor
        milestones={[]}
        jurisdictions={catalog.jurisdictions}
        onChange={save}
        periods={[
          period({ local_tax: { jurisdiction: "pa_philadelphia" } }),
          period({
            id: "s",
            state_code: "OH",
            start_year: 2031,
            end_year: null,
            rank: 1,
            local_tax: { jurisdiction: "custom", earned_income_rate: 0.025 },
          }),
        ]}
      />,
    );
    expect(screen.getAllByLabelText("Local income tax")[0]).toHaveValue("pa_philadelphia");
    fireEvent.change(screen.getAllByRole("spinbutton")[0], { target: { value: "2031" } });
    fireEvent.click(screen.getByText("Save residency changes"));
    await screen.findByText("Residency changes saved.");
    expect(save).toHaveBeenCalledExactlyOnceWith([
      expect.objectContaining({
        state_code: "PA",
        end_year: 2031,
        rank: 0,
        local_tax: { jurisdiction: "pa_philadelphia" },
      }),
      expect.objectContaining({
        state_code: "OH",
        start_year: 2031,
        rank: 1,
        local_tax: { jurisdiction: "custom", earned_income_rate: 0.025 },
      }),
    ]);
  });

  it("clears a row's catalog locality with its state and blocks custom rows without a rate", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(
      <ResidencyTimelineEditor
        milestones={[]}
        jurisdictions={catalog.jurisdictions}
        onChange={save}
        periods={[period({ local_tax: { jurisdiction: "pa_pittsburgh" } })]}
      />,
    );
    const row = screen
      .getByLabelText("Remove residency change")
      .closest("div[style]")!.parentElement!;
    fireEvent.change(within(row).getByLabelText("State"), { target: { value: "NY" } });
    const local = within(row).getByLabelText("Local income tax");
    expect(local).toHaveValue("");
    fireEvent.change(local, { target: { value: "custom" } });
    fireEvent.click(screen.getByText("Save residency changes"));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter at least one local tax rate.");
    expect(save).not.toHaveBeenCalled();
    fireEvent.change(within(row).getByLabelText("State tax surcharge (%)"), {
      target: { value: "16.75" },
    });
    fireEvent.click(screen.getByText("Save residency changes"));
    await screen.findByText("Residency changes saved.");
    expect(save).toHaveBeenCalledExactlyOnceWith([
      expect.objectContaining({
        state_code: "NY",
        local_tax: { jurisdiction: "custom", state_tax_surcharge_rate: 0.1675 },
      }),
    ]);
  });

  it("sends an explicit null for rows without a locality", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<ResidencyTimelineEditor milestones={[]} periods={[]} onChange={save} />);
    fireEvent.click(screen.getByTestId("residency-add"));
    expect(screen.queryByLabelText("Local income tax")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("State"), { target: { value: "TX" } });
    expect(screen.getByLabelText("Local income tax")).toHaveValue("");
    fireEvent.click(screen.getByText("Save residency changes"));
    await screen.findByText("Residency changes saved.");
    expect(save).toHaveBeenCalledWith([
      expect.objectContaining({ state_code: "TX", local_tax: null }),
    ]);
  });
});
