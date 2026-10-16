import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { PlanData, TaxSettings } from "@/types/plan";
import TaxLawOverridesForm, { readBrackets, TOP_BRACKET_BOUND } from "./tax_law_overrides_form";
import { makePlan } from "@/test_support/plan_builder";
import type { PlanOverrides } from "@/test_support/plan_builder";
import { makeTaxSettings } from "@/test_support/record_builders";

const settings = makeTaxSettings();

const plan = (
  tax_settings: TaxSettings | null = settings,
  spouse: PlanOverrides["spouse"] = null,
): PlanData =>
  makePlan({
    id: "p",
    user_id: "u",
    name: "Plan",
    birth_year: 1966,
    created_at: "2026-01-01",
    spouse,
    tax_settings,
  });

const open = () => fireEvent.click(screen.getByText("Tax law assumptions"));

describe("TaxLawOverridesForm", () => {
  it("reads brackets with an open top bracket and rejects decreasing bounds", () => {
    expect(
      readBrackets([
        { upper: "50000", rate: "10" },
        { upper: "", rate: "30" },
      ]),
    ).toEqual([
      [50000, 0.1],
      [TOP_BRACKET_BOUND, 0.3],
    ]);
    expect(() =>
      readBrackets([
        { upper: "50000", rate: "10" },
        { upper: "40000", rate: "20" },
      ]),
    ).toThrow(/upper bound above/);
    expect(() =>
      readBrackets([
        { upper: "", rate: "10" },
        { upper: "", rate: "20" },
      ]),
    ).toThrow(/Bracket 1/);
  });

  it("saves custom brackets, a deduction, unindexed amounts and an RMD age while keeping other settings", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<TaxLawOverridesForm plan={plan()} onSave={save} />);
    open();
    fireEvent.click(screen.getByLabelText(/Use custom federal income tax brackets/));
    fireEvent.change(screen.getByLabelText("Bracket 1 up to ($)"), { target: { value: "60000" } });
    fireEvent.change(screen.getByLabelText("Bracket 1 rate (%)"), { target: { value: "12" } });
    fireEvent.click(screen.getByText("Add bracket"));
    fireEvent.change(screen.getByLabelText("Bracket 2 rate (%)"), { target: { value: "25" } });
    fireEvent.change(screen.getByLabelText(/Federal standard deduction/), {
      target: { value: "20000" },
    });
    fireEvent.click(screen.getByLabelText(/Grow custom federal amounts/));
    fireEvent.change(screen.getByLabelText(/Primary person RMD start age/), {
      target: { value: "77" },
    });
    expect(screen.queryByLabelText(/Partner RMD start age/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save tax law assumptions" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved"));
    expect(save).toHaveBeenCalledWith({
      ...settings,
      federal_brackets: [
        [60000, 0.12],
        [TOP_BRACKET_BOUND, 0.25],
      ],
      federal_standard_deduction: 20000,
      federal_overrides_indexed: false,
      rmd_start_ages: { self: 77 },
    });
  });

  it("clears overrides back to current law and keeps entries after a failed save", async () => {
    const saved = {
      ...settings,
      federal_brackets: [
        [50000, 0.1],
        [TOP_BRACKET_BOUND, 0.2],
      ] as Array<[number, number]>,
      federal_standard_deduction: 5000,
      rmd_start_ages: { self: 75, spouse: 78 },
    };
    const save = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(undefined);
    render(<TaxLawOverridesForm plan={plan(saved, { name: "Sam" })} onSave={save} />);
    open();
    expect(screen.getByLabelText("Bracket 2 up to ($)")).toHaveValue("");
    expect(screen.getByLabelText(/Partner RMD start age/)).toHaveValue(78);
    fireEvent.click(screen.getByLabelText(/Use custom federal income tax brackets/));
    fireEvent.change(screen.getByLabelText(/Federal standard deduction/), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText(/Primary person RMD start age/), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save tax law assumptions" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Could not save"));
    expect(screen.getByLabelText(/Partner RMD start age/)).toHaveValue(78);
    fireEvent.click(screen.getByRole("button", { name: "Save tax law assumptions" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved"));
    expect(save.mock.calls[1][0]).toEqual({ ...settings, rmd_start_ages: { spouse: 78 } });
  });

  it("rejects an RMD age outside 70 to 80 without saving", () => {
    const save = vi.fn();
    render(<TaxLawOverridesForm plan={plan()} onSave={save} />);
    open();
    fireEvent.change(screen.getByLabelText(/Primary person RMD start age/), {
      target: { value: "85" },
    });
    // Submit directly: the browser's min/max check would otherwise block it first.
    fireEvent.submit(
      screen.getByRole("button", { name: "Save tax law assumptions" }).closest("form")!,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Primary person RMD start age must be a whole number from 70 to 80",
    );
    expect(save).not.toHaveBeenCalled();
  });
});
