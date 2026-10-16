import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PensionFormulaFields, pensionDraft } from "./pension_formula_fields";
import { makeIncome } from "@/test_support/record_builders";

const incomes = [
  makeIncome({ id: "own", name: "Pension", owner: "self" }),
  makeIncome({ id: "salary", name: "Day job", owner: "self", is_earned_income: true }),
  makeIncome({ id: "partner", name: "Partner job", owner: "spouse", is_earned_income: true }),
  makeIncome({
    id: "bonus",
    name: "Bonus",
    owner: "self",
    is_earned_income: true,
    frequency: "once",
  }),
  makeIncome({ id: "ss", name: "Social Security", owner: "self", is_social_security: true }),
];

describe("pensionDraft", () => {
  it("opens a new pension on the entered amount with the formula defaults", () => {
    expect(pensionDraft(null)).toEqual({
      kind: "",
      linkedSalary: "",
      benefitPercent: "1.5",
      priorService: "0",
      averageYears: "3",
      flatAmount: "0",
      cola: "",
    });
  });
});

describe("PensionFormulaFields", () => {
  it("hides the formula inputs until a formula is chosen", () => {
    const onChange = vi.fn();
    render(
      <PensionFormulaFields
        draft={pensionDraft(null)}
        onChange={onChange}
        incomes={incomes}
        owner="self"
      />,
    );
    expect(screen.queryByLabelText("Linked salary")).toBeNull();
    fireEvent.change(screen.getByLabelText("Benefit formula"), {
      target: { value: "final_average" },
    });
    expect(onChange).toHaveBeenCalledWith({ ...pensionDraft(null), kind: "final_average" });
  });

  it("links only the recipient's other recurring salaries", () => {
    const onChange = vi.fn();
    const draft = { ...pensionDraft(null), kind: "final_average" as const };
    render(
      <PensionFormulaFields
        draft={draft}
        onChange={onChange}
        incomes={incomes}
        incomeId="own"
        owner="self"
      />,
    );
    const linked = screen.getByLabelText("Linked salary") as HTMLSelectElement;
    expect(Array.from(linked.options).map((o) => o.text)).toEqual(["Choose salary", "Day job"]);
    expect(screen.getByLabelText("Final average years")).toHaveValue(3);
    fireEvent.change(linked, { target: { value: "salary" } });
    expect(onChange).toHaveBeenCalledWith({ ...draft, linkedSalary: "salary" });
    fireEvent.change(screen.getByLabelText("Pension COLA (%)"), { target: { value: "2" } });
    expect(onChange).toHaveBeenLastCalledWith({ ...draft, cola: "2" });
  });

  it("asks a flat pension only for its amount and COLA", () => {
    render(
      <PensionFormulaFields
        draft={{ ...pensionDraft(null), kind: "flat" }}
        onChange={() => {}}
        incomes={incomes}
        owner="self"
      />,
    );
    expect(screen.getByLabelText(/Flat annual benefit/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Linked salary")).toBeNull();
    expect(screen.queryByLabelText("Final average years")).toBeNull();
    expect(screen.getByLabelText("Pension COLA (%)")).toBeInTheDocument();
  });
});
