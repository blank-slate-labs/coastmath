import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { it, expect, vi } from "vitest";
import HealthcareForm from "./healthcare_form";
import { makePlan } from "@/test_support/plan_builder";

const plan = makePlan({
  id: "p1",
  milestones: [
    {
      id: "m1",
      plan_id: "p1",
      name: "Retire",
      trigger_type: "age",
      trigger_value: 60,
      trigger_date: null,
      metric: null,
      expense_multiple: null,
      relative_to_id: null,
      offset_years: 0,
      sort_order: 0,
    },
  ],
  spouse: {
    id: "s",
    plan_id: "p1",
    name: "Sam",
    birth_year: 1968,
    life_expectancy: 90,
    income_streams: [],
    retirement_milestone_id: null,
  },
  healthcare_settings: null,
});

it("saves ACA and Medicare inputs in engine units", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<HealthcareForm plan={plan} onSave={save} />);
  fireEvent.click(screen.getByLabelText("Model health coverage costs"));
  fireEvent.change(screen.getByLabelText(/Medical cost inflation/), { target: { value: "4.5" } });
  fireEvent.click(screen.getByLabelText(/Marketplace \(ACA\) coverage/));
  fireEvent.change(screen.getByLabelText("Covered from milestone"), { target: { value: "m1" } });
  fireEvent.change(screen.getByLabelText(/Benchmark premium/), { target: { value: "24000" } });
  fireEvent.change(screen.getByLabelText(/Your plan's premium/), { target: { value: "22000" } });
  fireEvent.change(screen.getByLabelText(/Advance premium tax credit/), {
    target: { value: "50" },
  });
  fireEvent.change(screen.getByLabelText(/Other household members/), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText(/Poverty guideline region/), {
    target: { value: "alaska" },
  });
  fireEvent.change(screen.getByLabelText(/Part D plan premium/), { target: { value: "35" } });
  fireEvent.change(screen.getByLabelText(/Medigap or Advantage premium/), {
    target: { value: "180" },
  });
  fireEvent.change(screen.getByLabelText(/Last year's modified AGI/), {
    target: { value: "90000" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save health coverage" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved"));
  expect(save).toHaveBeenCalledWith(
    "p1",
    expect.objectContaining({
      enabled: true,
      medical_inflation_rate: 0.045,
      aca_enabled: true,
      aca_start_milestone_id: "m1",
      aca_end_milestone_id: null,
      aca_benchmark_premium_annual: 24000,
      aca_plan_premium_annual: 22000,
      aca_advance_credit_fraction: 0.5,
      aca_cover_spouse: true,
      aca_dependents: 1,
      aca_apply_age_curve: true,
      aca_state_group: "alaska",
      medicare_enabled: true,
      medicare_part_b: true,
      medicare_part_d: true,
      medicare_part_d_plan_premium_monthly: 35,
      medicare_supplement_premium_monthly: 180,
      medicare_apply_irmaa: true,
      magi_prior_year: 90000,
      magi_two_years_prior: null,
    }),
  );
});

it("requires both marketplace premiums and reports failed saves", async () => {
  const save = vi.fn().mockRejectedValue(new Error("offline"));
  render(<HealthcareForm plan={plan} onSave={save} />);
  fireEvent.click(screen.getByLabelText("Model health coverage costs"));
  fireEvent.click(screen.getByLabelText(/Marketplace \(ACA\) coverage/));
  fireEvent.change(screen.getByLabelText(/Your plan's premium/), { target: { value: "22000" } });
  fireEvent.click(screen.getByRole("button", { name: "Save health coverage" }));
  expect(screen.getByRole("alert")).toHaveTextContent("benchmark");
  expect(save).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText(/Benchmark premium/), { target: { value: "24000" } });
  fireEvent.click(screen.getByRole("button", { name: "Save health coverage" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not save"));
  expect(screen.getByLabelText(/Benchmark premium/)).toHaveValue("24,000");
});
