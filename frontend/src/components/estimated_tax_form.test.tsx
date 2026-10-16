import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { PlanData, TaxSettings } from "@/types/plan";
import EstimatedTaxForm from "./estimated_tax_form";
import { makePlan } from "@/test_support/plan_builder";

const settings: TaxSettings = {
  mode: "detailed",
  ordinary_income_tax_rate: null,
  capital_gains_tax_rate: null,
  taxable_withholding_rate: 0,
  tax_deferred_withholding_rate: 0,
  settlement_lag_years: 0,
  cash_flow_frequency: "monthly",
  dependent_birth_years: [2019],
  year_to_date: { tax_year: 2027, tax_paid: 3000 },
};

const plan = (tax_settings: TaxSettings | null = settings): PlanData =>
  makePlan({
    id: "p",
    user_id: "u",
    name: "Plan",
    plan_type: "FIXED_DATE",
    start_date: "2027-01-01",
    birth_year: 1966,
    created_at: "2026-01-01",
    tax_settings,
  });

describe("EstimatedTaxForm", () => {
  it("defaults to off and hides the prior-year fields", () => {
    render(<EstimatedTaxForm plan={plan()} onSave={vi.fn()} />);
    fireEvent.click(screen.getByText("Estimated tax payments"));
    expect(screen.getByLabelText("Estimated payments")).toHaveValue("off");
    expect(screen.queryByLabelText(/total federal tax/)).not.toBeInTheDocument();
  });

  it("saves the strategy and prior-year amounts while keeping other tax settings", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<EstimatedTaxForm plan={plan()} onSave={save} />);
    fireEvent.click(screen.getByText("Estimated tax payments"));
    fireEvent.change(screen.getByLabelText("Estimated payments"), {
      target: { value: "safe_harbor" },
    });
    expect(screen.getByText(/smaller of 90% of this year's federal tax/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/2026 total federal tax/), {
      target: { value: "12000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save estimated payments" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved"));
    expect(save).toHaveBeenCalledWith({
      ...settings,
      estimated_payments: {
        strategy: "safe_harbor",
        prior_year_total_tax: 12000,
        prior_year_agi: null,
      },
    });
  });

  it("loads a saved strategy and keeps entries after a failed save", async () => {
    const saved = {
      ...settings,
      estimated_payments: {
        strategy: "settle_at_filing" as const,
        prior_year_total_tax: 8000,
        prior_year_agi: 160000,
      },
    };
    render(
      <EstimatedTaxForm
        plan={plan(saved)}
        onSave={vi.fn().mockRejectedValue(new Error("offline"))}
      />,
    );
    fireEvent.click(screen.getByText("Estimated tax payments"));
    expect(screen.getByLabelText("Estimated payments")).toHaveValue("settle_at_filing");
    expect(screen.getByLabelText(/2026 adjusted gross income/)).toHaveValue("160,000");
    fireEvent.change(screen.getByLabelText(/2026 total federal tax/), {
      target: { value: "9000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save estimated payments" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Could not save"));
    expect(screen.getByLabelText(/2026 total federal tax/)).toHaveValue("9,000");
  });

  it("fills required tax settings for a plan without saved settings", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<EstimatedTaxForm plan={plan(null)} onSave={save} />);
    fireEvent.click(screen.getByText("Estimated tax payments"));
    fireEvent.change(screen.getByLabelText("Estimated payments"), {
      target: { value: "settle_at_filing" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save estimated payments" }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0]).toMatchObject({
      mode: "detailed",
      settlement_lag_years: 0,
      estimated_payments: {
        strategy: "settle_at_filing",
        prior_year_total_tax: null,
        prior_year_agi: null,
      },
    });
  });
});
