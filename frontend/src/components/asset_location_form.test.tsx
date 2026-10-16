import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { PlanData, TaxSettings } from "@/types/plan";
import AssetLocationForm, { bucketOrder, mergeOrder } from "./asset_location_form";
import { makePlan } from "@/test_support/plan_builder";

const settings: TaxSettings = {
  mode: "detailed",
  ordinary_income_tax_rate: null,
  capital_gains_tax_rate: null,
  taxable_withholding_rate: 0,
  tax_deferred_withholding_rate: 0,
  settlement_lag_years: 0,
  cash_flow_frequency: "monthly",
  capital_loss_carryforward: 1000,
};

const plan = (tax_settings: TaxSettings | null = settings): PlanData =>
  makePlan({
    id: "p",
    user_id: "u",
    name: "Plan",
    birth_year: 1970,
    created_at: "2026-01-01",
    tax_settings,
  });

describe("AssetLocationForm", () => {
  it("hands the sheet's Save a household order that keeps other tax settings", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const pending = vi.fn();
    render(<AssetLocationForm plan={plan()} onSave={save} onPending={pending} />);
    fireEvent.click(screen.getByText(/Bond location/));
    expect(screen.queryByRole("button", { name: /Save/ })).toBeNull();
    fireEvent.change(screen.getByLabelText("Apply the bond allocation"), {
      target: { value: "household" },
    });
    fireEvent.click(screen.getByLabelText("Move Taxable brokerage and other up"));
    const { check, save: run } = pending.mock.lastCall![0];
    expect(check()).toBe(true);
    await expect(run()).resolves.toBe(true);
    expect(save).toHaveBeenCalledWith({
      ...settings,
      asset_location: {
        bond_allocation_mode: "household",
        bond_location_order: ["tax_deferred", "taxable", "tax_free"],
        excluded_account_ids: [],
      },
    });
  });

  it("sends no setting when per-account mode was never saved, and keeps the choice on failure", async () => {
    const save = vi.fn().mockRejectedValue(new Error("offline"));
    const pending = vi.fn();
    render(<AssetLocationForm plan={plan()} onSave={save} onPending={pending} />);
    fireEvent.change(screen.getByLabelText("Apply the bond allocation"), {
      target: { value: "per_account" },
    });
    await expect(pending.mock.lastCall![0].save()).resolves.toBe(false);
    expect(save.mock.calls[0][0].asset_location).toBeNull();
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Could not save the bond location"),
    );
  });

  it("keeps account ids and exclusions saved through the API", () => {
    expect(bucketOrder(["acct-1", "taxable"])).toEqual(["taxable", "tax_deferred", "tax_free"]);
    expect(
      mergeOrder(["acct-1", "taxable", "tax_free"], ["tax_free", "taxable", "tax_deferred"]),
    ).toEqual(["acct-1", "tax_free", "taxable", "tax_deferred"]);
  });
});
