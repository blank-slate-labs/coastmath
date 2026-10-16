import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import IncomeForm from "./income_form";
vi.mock("@/api/client", () => ({ estimateSocialSecurity: vi.fn() }));

describe("income events", () => {
  it("submits a full one-time wage bonus in the annual entry unit", () => {
    const save = vi.fn();
    render(<IncomeForm milestones={[]} onSubmit={save} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Repeats"), { target: { value: "once" } });
    fireEvent.change(screen.getByLabelText("Annual amount ($)"), { target: { value: "15000" } });
    fireEvent.click(screen.getByText("Add income"));
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        frequency: "once",
        annual_amount: 15000,
        tax_category: "employment",
      }),
    );
    expect(screen.getByLabelText("Amount frequency")).toBeDisabled();
  });
});

it("saves a flat pension formula without a redundant stream amount", () => {
  const save = vi.fn();
  render(<IncomeForm milestones={[]} onSubmit={save} onCancel={() => {}} />);
  fireEvent.click(screen.getByLabelText("Other"));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Pension" } });
  fireEvent.change(screen.getByLabelText(/Income tax treatment/), {
    target: { value: "qualified_pension" },
  });
  fireEvent.change(screen.getByLabelText("Benefit formula"), { target: { value: "flat" } });
  fireEvent.change(screen.getByLabelText("Flat annual benefit (today’s dollars)"), {
    target: { value: "25000" },
  });
  fireEvent.click(screen.getByText("Add income"));
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({
      annual_amount: 0,
      tax_category: "qualified_pension",
      pension_formula: expect.objectContaining({
        kind: "flat",
        flat_annual_amount: 25000,
        cola_percent: null,
      }),
    }),
  );
});

it("offers recurring earned income as pension salary and excludes one-time awards", () => {
  const incomes = [
    {
      id: "salary",
      name: "Recurring salary",
      owner: "self",
      is_earned_income: true,
      frequency: "recurring",
    },
    { id: "legacy", name: "Existing salary", owner: "self", is_earned_income: true },
    {
      id: "award",
      name: "One-time award",
      owner: "self",
      is_earned_income: true,
      frequency: "once",
    },
  ] as import("../types/plan").Income[];
  render(<IncomeForm milestones={[]} incomes={incomes} onSubmit={vi.fn()} onCancel={() => {}} />);
  fireEvent.click(screen.getByLabelText("Other"));
  fireEvent.change(screen.getByLabelText(/Income tax treatment/), {
    target: { value: "qualified_pension" },
  });
  fireEvent.change(screen.getByLabelText("Benefit formula"), {
    target: { value: "career_average" },
  });
  const choices = Array.from(
    (screen.getByLabelText("Linked salary") as HTMLSelectElement).options,
  ).map((option) => option.value);
  expect(choices).toEqual(["", "salary", "legacy"]);
});
