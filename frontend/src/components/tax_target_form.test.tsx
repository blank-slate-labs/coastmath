import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { PlanData, TaxSettings } from "@/types/plan";
import TaxTargetForm, { BlendDrawdownToggle } from "./tax_target_form";
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
    created_at: "2026-01-01",
    tax_settings,
  });

describe("TaxTargetForm", () => {
  it("saves a bracket target with ceilings while keeping other tax settings", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<TaxTargetForm plan={plan()} onSave={save} />);
    fireEvent.click(screen.getByText("Tax target"));
    expect(screen.getByLabelText("Target")).toHaveValue("none");
    fireEvent.change(screen.getByLabelText("Target"), { target: { value: "federal_bracket" } });
    fireEvent.change(screen.getByLabelText("Bracket"), { target: { value: "0.22" } });
    fireEvent.click(screen.getByLabelText(/net investment income tax/));
    fireEvent.click(screen.getByLabelText(/share of the poverty line in ACA years/));
    fireEvent.change(screen.getByLabelText("Poverty-line cap (%)"), { target: { value: "300" } });
    fireEvent.click(screen.getByRole("button", { name: "Save tax target" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved"));
    expect(save).toHaveBeenCalledWith({
      ...settings,
      tax_target: {
        kind: "federal_bracket",
        bracket_rate: 0.22,
        amount: null,
        irmaa_tier: null,
        aca_fpl_percent: null,
        avoid_niit: true,
        avoid_irmaa: false,
        aca_cap_fpl_percent: 300,
      },
    });
  });

  it("offers the plan's custom bracket rates and keeps a stale saved rate visible", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    // The open 30% top bracket has nothing to fill, so it is not offered.
    const custom: TaxSettings = {
      ...settings,
      federal_brackets: [
        [50000, 0.1],
        [150000, 0.2],
        [999999999, 0.3],
      ],
      tax_target: { kind: "federal_bracket", bracket_rate: 0.12 },
    };
    render(<TaxTargetForm plan={plan(custom)} onSave={save} />);
    fireEvent.click(screen.getByText("Tax target"));
    const bracket = screen.getByLabelText("Bracket");
    expect(bracket).toHaveValue("0.12");
    expect([...bracket.querySelectorAll("option")].map((o) => o.textContent)).toEqual([
      "10%",
      "20%",
      "12% (not in this plan's brackets)",
    ]);
    fireEvent.change(bracket, { target: { value: "0.2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save tax target" }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].tax_target).toMatchObject({
      kind: "federal_bracket",
      bracket_rate: 0.2,
    });
  });

  it("keeps a saved built-in 37% target as a valid choice, not a stale one", () => {
    const top: TaxSettings = {
      ...settings,
      tax_target: { kind: "federal_bracket", bracket_rate: 0.37 },
    };
    render(<TaxTargetForm plan={plan(top)} onSave={vi.fn()} />);
    fireEvent.click(screen.getByText("Tax target"));
    const bracket = screen.getByLabelText("Bracket");
    expect(bracket).toHaveValue("0.37");
    expect([...bracket.querySelectorAll("option")].map((o) => o.textContent)).toEqual([
      "10%",
      "12%",
      "22%",
      "24%",
      "32%",
      "35%",
      "37%",
    ]);
  });

  it("clearing the target also turns blending off", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const saved = {
      ...settings,
      tax_target: { kind: "magi" as const, amount: 90000 },
      blend_drawdown_to_tax_target: true,
    };
    render(<TaxTargetForm plan={plan(saved)} onSave={save} />);
    fireEvent.click(screen.getByText("Tax target"));
    expect(screen.getByLabelText("Amount (today's $)")).toHaveValue("90,000");
    fireEvent.change(screen.getByLabelText("Target"), { target: { value: "none" } });
    fireEvent.click(screen.getByRole("button", { name: "Save tax target" }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0]).toMatchObject({
      tax_target: null,
      blend_drawdown_to_tax_target: false,
    });
  });
});

describe("BlendDrawdownToggle", () => {
  it("is disabled until a target exists", () => {
    render(<BlendDrawdownToggle plan={plan()} onSave={vi.fn()} />);
    expect(screen.getByRole("checkbox", { name: /Fill the tax target first/ })).toBeDisabled();
  });

  it("saves the flag with the rest of the tax settings", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const saved = {
      ...settings,
      tax_target: { kind: "federal_bracket" as const, bracket_rate: 0.12 },
    };
    render(<BlendDrawdownToggle plan={plan(saved)} onSave={save} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /Fill the tax target first/ }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({ ...saved, blend_drawdown_to_tax_target: true }),
    );
  });
});
