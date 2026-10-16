import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { PlanData } from "@/types/plan";
import YearToDateTaxForm from "./year_to_date_tax_form";
import { makePlan } from "@/test_support/plan_builder";

const plan: PlanData = makePlan({
  id: "p",
  user_id: "u",
  name: "Plan",
  plan_type: "FIXED_DATE",
  start_date: "2026-07-01",
  birth_year: 1966,
  created_at: "2026-01-01",
  tax_settings: {
    mode: "flat",
    ordinary_income_tax_rate: 0.2,
    capital_gains_tax_rate: 0.15,
    taxable_withholding_rate: 0.1,
    tax_deferred_withholding_rate: 0.2,
    settlement_lag_years: 1,
    cash_flow_frequency: "monthly",
  },
});

describe("YearToDateTaxForm", () => {
  it("saves opening history and deferrals while preserving the configured tax model", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(
      <YearToDateTaxForm
        plan={plan}
        accounts={[
          {
            id: "r",
            user_id: "u",
            name: "Roth",
            account_type: "roth_401k",
            balance: 10000,
            owner: "self",
          },
        ]}
        onSave={save}
      />,
    );
    fireEvent.click(screen.getByText("Earlier this tax year"));
    fireEvent.change(screen.getByLabelText(/Gross ordinary income/), {
      target: { value: "60000" },
    });
    fireEvent.change(screen.getByLabelText(/Primary person's W-2 wages/), {
      target: { value: "60000" },
    });
    expect(screen.getByLabelText(/Partner's W-2 wages/)).toBeInTheDocument();
    expect(screen.queryByText(/Spouse's|Your W-2/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Roth: employee/), { target: { value: "10000" } });
    fireEvent.click(screen.getByRole("button", { name: "Save tax history" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved"));
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        ...plan.tax_settings,
        capital_loss_carryforward: 0,
        year_to_date: {
          tax_year: 2026,
          gross_income: 60000,
          w2_income_by_owner: { self: 60000 },
          contributions_by_account: { r: 10000 },
        },
      }),
    );
  });

  it("retains entered history and reports a failed save", async () => {
    render(
      <YearToDateTaxForm
        plan={plan}
        accounts={[]}
        onSave={vi.fn().mockRejectedValue(new Error("offline"))}
      />,
    );
    fireEvent.click(screen.getByText("Earlier this tax year"));
    fireEvent.change(screen.getByLabelText(/Gross ordinary income/), {
      target: { value: "60000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save tax history" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Could not save"));
    expect(screen.getByLabelText(/Gross ordinary income/)).toHaveValue("60,000");
  });

  it("records withdrawals already taken from accounts with required distributions", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(
      <YearToDateTaxForm
        plan={plan}
        accounts={[
          {
            id: "ira",
            user_id: "u",
            name: "IRA",
            account_type: "traditional_ira",
            balance: 500000,
            owner: "self",
          },
          {
            id: "heir",
            user_id: "u",
            name: "Inherited Roth",
            account_type: "roth_ira",
            balance: 80000,
            owner: "self",
            inherited_year: 2022,
          },
          {
            id: "roth",
            user_id: "u",
            name: "Own Roth",
            account_type: "roth_ira",
            balance: 90000,
            owner: "self",
          },
        ]}
        onSave={save}
      />,
    );
    fireEvent.click(screen.getByText("Earlier this tax year"));
    expect(screen.queryByLabelText(/Own Roth: withdrawals/)).toBeNull();
    fireEvent.change(screen.getByLabelText(/IRA: withdrawals already taken/), {
      target: { value: "20000" },
    });
    fireEvent.change(screen.getByLabelText(/Inherited Roth: withdrawals already taken/), {
      target: { value: "5000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save tax history" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved"));
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        year_to_date: { tax_year: 2026, distributions_by_account: { ira: 20000, heir: 5000 } },
      }),
    );
  });
});
