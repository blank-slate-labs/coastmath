import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import type { PlanData, TaxSettings } from "@/types/plan";
import TaxAdjustmentsForm from "./tax_adjustments_form";
import { makePlan } from "@/test_support/plan_builder";
import { makeTaxSettings } from "@/test_support/record_builders";

const settings = makeTaxSettings();

const plan = (tax_settings: TaxSettings | null = settings): PlanData =>
  makePlan({
    id: "p",
    user_id: "u",
    name: "Plan",
    plan_type: "FIXED_DATE",
    start_date: "2027-01-01",
    birth_year: 1966,
    state_code: "AL",
    created_at: "2026-01-01",
    milestones: [
      {
        id: "m1",
        plan_id: "p",
        name: "Retire",
        trigger_type: "age",
        trigger_value: 60,
      } as PlanData["milestones"][number],
    ],
    tax_settings,
  });

function open() {
  fireEvent.click(screen.getByText("Tax adjustments and scheduled changes"));
}

describe("TaxAdjustmentsForm", () => {
  it("saves a deduction, a refundable credit, a milestone schedule and the state rules flag, keeping other settings", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<TaxAdjustmentsForm plan={plan()} onSave={save} />);
    open();
    fireEvent.click(screen.getByRole("checkbox", { name: /Use state deduction rules/ }));

    fireEvent.click(screen.getByRole("button", { name: "Add adjustment" }));
    const first = within(screen.getByRole("group", { name: "Adjustment 1" }));
    fireEvent.change(first.getByLabelText("Name"), { target: { value: "Alimony" } });
    fireEvent.change(first.getByLabelText("Amount per year ($)"), { target: { value: "6000" } });
    fireEvent.change(first.getByLabelText("End (inclusive) type"), {
      target: { value: "milestone" },
    });
    fireEvent.change(first.getByLabelText("End (inclusive) milestone"), {
      target: { value: "m1" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Add adjustment" }));
    const second = within(screen.getByRole("group", { name: "Adjustment 2" }));
    fireEvent.change(second.getByLabelText("Type"), { target: { value: "credit" } });
    expect(second.queryByRole("option", { name: "Federal and state" })).not.toBeInTheDocument();
    fireEvent.click(second.getByRole("checkbox", { name: "Refundable" }));
    fireEvent.change(second.getByLabelText("Amount per year ($)"), { target: { value: "1200" } });
    fireEvent.change(second.getByLabelText("Dollars"), { target: { value: "nominal" } });
    fireEvent.change(second.getByLabelText("Applies"), { target: { value: "once" } });
    fireEvent.change(second.getByLabelText("Year type"), { target: { value: "year" } });
    fireEvent.change(second.getByLabelText("Year year"), { target: { value: "2028" } });

    fireEvent.click(screen.getByRole("button", { name: "Add scheduled change" }));
    const change = within(screen.getByRole("group", { name: "Scheduled change 1" }));
    fireEvent.change(change.getByLabelText("From type"), { target: { value: "milestone" } });
    fireEvent.change(change.getByLabelText("From milestone"), { target: { value: "m1" } });
    fireEvent.change(change.getByLabelText("Tax mode"), { target: { value: "flat" } });
    fireEvent.change(change.getByLabelText("Flat income tax rate (%)"), {
      target: { value: "12" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Save tax adjustments" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved"));
    const saved = save.mock.calls[0][0] as TaxSettings;
    expect(saved.dependent_birth_years).toEqual([2019]);
    expect(saved.state_deduction_rules).toBe(true);
    expect(saved.adjustments).toEqual([
      expect.objectContaining({
        name: "Alimony",
        kind: "deduction",
        deduction_type: "above_the_line",
        scope: "both",
        amount: 6000,
        amount_basis: "today",
        frequency: "annual",
        end_milestone_id: "m1",
        owner: "household",
      }),
      expect.objectContaining({
        kind: "credit",
        scope: "federal",
        refundable: true,
        amount: 1200,
        amount_basis: "nominal",
        frequency: "once",
        start_year: 2028,
      }),
    ]);
    expect(saved.adjustments?.[1]).not.toHaveProperty("end_year");
    expect(saved.scheduled_changes).toEqual([
      { milestone_id: "m1", settings: { mode: "flat", ordinary_income_tax_rate: 0.12 } },
    ]);
  });

  it("blocks incomplete entries without calling save", () => {
    const save = vi.fn();
    render(<TaxAdjustmentsForm plan={plan()} onSave={save} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Add adjustment" }));
    fireEvent.click(screen.getByRole("button", { name: "Save tax adjustments" }));
    expect(screen.getByRole("status")).toHaveTextContent("enter an amount");
    fireEvent.click(screen.getByRole("button", { name: "Remove adjustment" }));
    fireEvent.click(screen.getByRole("button", { name: "Add scheduled change" }));
    fireEvent.click(screen.getByRole("button", { name: "Save tax adjustments" }));
    expect(screen.getByRole("status")).toHaveTextContent("change at least one setting");
    expect(save).not.toHaveBeenCalled();
  });

  it("loads saved rows, keeps unedited schedule settings and keeps the draft after a failed save", async () => {
    const saved: TaxSettings = {
      ...settings,
      state_deduction_rules: true,
      adjustments: [
        {
          id: "s1",
          name: "Surtax",
          kind: "surcharge",
          scope: "state",
          rate: 0.01,
          base: "taxable_income",
          max_amount: 500,
          amount_basis: "today",
          frequency: "annual",
        },
      ],
      scheduled_changes: [{ year: 2030, settings: { state_brackets: [[999999999, 0.03]] } }],
    };
    const save = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(undefined);
    render(<TaxAdjustmentsForm plan={plan(saved)} onSave={save} />);
    open();
    const row = within(screen.getByRole("group", { name: "Adjustment 1" }));
    expect(row.getByLabelText("Rate (%)")).toHaveValue(1);
    expect(row.getByLabelText("Maximum per year ($, optional)")).toHaveValue("500");
    fireEvent.change(row.getByLabelText("Rate (%)"), { target: { value: "1.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save tax adjustments" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Could not save"));
    expect(row.getByLabelText("Rate (%)")).toHaveValue(1.5);
    fireEvent.click(screen.getByRole("button", { name: "Save tax adjustments" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved"));
    const retried = save.mock.calls[1][0] as TaxSettings;
    expect(retried.adjustments?.[0]).toMatchObject({
      id: "s1",
      rate: 0.015,
      max_amount: 500,
      scope: "state",
    });
    expect(retried.scheduled_changes).toEqual([
      { year: 2030, settings: { state_brackets: [[999999999, 0.03]] } },
    ]);
  });

  it("fills required tax settings for a plan without saved settings", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<TaxAdjustmentsForm plan={plan(null)} onSave={save} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Save tax adjustments" }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0]).toMatchObject({
      mode: "detailed",
      settlement_lag_years: 0,
      adjustments: [],
      scheduled_changes: [],
      state_deduction_rules: false,
    });
  });
});
