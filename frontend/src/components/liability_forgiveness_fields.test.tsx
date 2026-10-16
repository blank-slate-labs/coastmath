import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import LiabilityForm from "./liability_form";
import {
  forgivenessDraft,
  forgivenessPayload,
  forgivenessProblem,
} from "./liability_forgiveness_fields";
import type { Account, Liability, Milestone, RealAsset } from "@/types/plan";

const fill = (label: string | RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
function setup(initial?: Liability) {
  const submit = vi.fn();
  render(
    <LiabilityForm
      initial={initial}
      onSubmit={submit}
      onCancel={() => {}}
      accounts={[] as Account[]}
      realAssets={[] as RealAsset[]}
      milestones={[{ id: "m", name: "Retirement" } as Milestone]}
    />,
  );
  return submit;
}
const save = () =>
  fireEvent.click(screen.getByRole("button", { name: /^(Save|Update) loan or debt$/ }));
const basics = () => {
  fill("Name", "Loan");
  fill(/Principal balance/, "12000");
  fill(/Interest rate/, "0");
  fill("Remaining term (months)", "12");
};

describe("liability forgiveness", () => {
  it("omits forgiveness unless it is turned on", () => {
    const submit = setup();
    basics();
    save();
    expect(submit.mock.calls[0][0]).not.toHaveProperty("forgiveness");
  });

  it("saves a taxable forgiveness in a year, with no exclusion fields", () => {
    const submit = setup();
    basics();
    fireEvent.click(screen.getByLabelText(/forgiven once/));
    fill("Forgiveness year", "2035");
    fill(/Amount forgiven/, "5000");
    save();
    expect(submit.mock.calls[0][0].forgiveness).toEqual({
      year: 2035,
      milestone_id: null,
      amount: 5000,
      tax_treatment: "taxable",
    });
  });

  it("requires a basis for a declared exclusion and blocks an excluded amount above the forgiven amount", () => {
    const submit = setup();
    basics();
    fireEvent.click(screen.getByLabelText(/forgiven once/));
    fill("Forgiveness year", "2035");
    fill("Tax treatment", "declared_exclusion");
    save();
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Choose the basis");
    fill("Basis for the exclusion", "insolvency");
    fill(/Amount forgiven/, "1000");
    fill(/Excluded amount/, "2000");
    expect(screen.getByRole("alert")).toHaveTextContent("cannot exceed");
    fill(/Excluded amount/, "400");
    save();
    expect(submit.mock.calls[0][0].forgiveness).toEqual({
      year: 2035,
      milestone_id: null,
      amount: 1000,
      tax_treatment: "declared_exclusion",
      exclusion_basis: "insolvency",
      excluded_amount: 400,
    });
  });

  it("clears a saved forgiveness with null", () => {
    const initial = {
      id: "l",
      plan_id: "p",
      name: "Loan",
      principal_balance: 12000,
      interest_rate: 0,
      payment_type: "fixed",
      term_months: 12,
      monthly_payment: 1000,
      extra_payment: 0,
      forgiveness: { year: 2030, tax_treatment: "taxable" },
    } as Liability;
    const submit = setup(initial);
    fireEvent.click(screen.getByLabelText(/forgiven once/));
    save();
    expect(submit.mock.calls[0][0].forgiveness).toBeNull();
  });

  it("round-trips a milestone trigger", () => {
    const draft = forgivenessDraft({ milestone_id: "m", tax_treatment: "taxable" });
    expect(draft.trigger).toBe("milestone");
    expect(forgivenessProblem(draft)).toBeNull();
    expect(forgivenessPayload(draft)).toEqual({
      year: null,
      milestone_id: "m",
      amount: null,
      tax_treatment: "taxable",
    });
    expect(forgivenessProblem({ ...draft, milestoneId: "" })).toMatch(/milestone/);
  });
});
