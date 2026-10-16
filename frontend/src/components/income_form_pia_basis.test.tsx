import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import IncomeForm from "./income_form";
import { estimateSocialSecurity } from "@/api/client";
import type { Income } from "@/types/plan";

vi.mock("@/api/client", () => ({ estimateSocialSecurity: vi.fn() }));

const savedPia: Income = {
  id: "i1",
  plan_id: "p1",
  name: "Social Security",
  annual_amount: 29760,
  start_milestone_id: null,
  end_milestone_id: null,
  growth_rate: null,
  growth_cap: null,
  growth_cap_inflation_linked: false,
  withholding_percent: null,
  start_month: null,
  end_month: null,
  is_active: true,
  is_social_security: true,
  is_earned_income: false,
  is_self_employed: false,
  owner: "self",
  claiming_age: 70,
  tax_category: null,
  ss_benefit_basis: "pia",
  pia_monthly: 2000,
  expected_benefit_percent: 90,
};

describe("IncomeForm PIA basis", () => {
  it("persists current-record controls", async () => {
    const submit = vi.fn();
    render(
      <IncomeForm
        initial={savedPia}
        milestones={[]}
        birthYear={1966}
        onSubmit={submit}
        onCancel={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText("My PIA reflects…"), {
      target: { value: "current_record" },
    });
    fireEvent.change(screen.getByLabelText("Covered years to date"), { target: { value: "20" } });
    await waitFor(() => expect(screen.getByText(/First-year benefit/)).toBeInTheDocument());
    fireEvent.click(screen.getByText("Save income"));
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({ pia_reflects: "current_record", covered_years_to_date: 20 }),
    );
  });
  beforeEach(() => {
    vi.mocked(estimateSocialSecurity).mockReset();
    vi.mocked(estimateSocialSecurity).mockResolvedValue({
      estimated_annual_benefit: 26784,
      claiming_age: 70,
      claiming_factor: 1.24,
      full_retirement_age: 67,
    } as Awaited<ReturnType<typeof estimateSocialSecurity>>);
  });

  it("submits the PIA, expected percent and preview amount", async () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={[]} birthYear={1966} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.click(screen.getByRole("radio", { name: "Social Security" }));
    fireEvent.click(screen.getByRole("radio", { name: "PIA" }));
    expect(screen.queryByLabelText("Annual amount ($)")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Estimate method" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("PIA per month at full retirement age ($)"), {
      target: { value: "2000" },
    });
    fireEvent.change(screen.getByLabelText("Expected benefit paid (%)"), {
      target: { value: "90" },
    });
    await waitFor(() =>
      expect(screen.getByText(/First-year benefit at claiming age 67/)).toBeInTheDocument(),
    );
    expect(estimateSocialSecurity).toHaveBeenLastCalledWith(null, 67, 1966, {
      monthlyPia: 2000,
      expectedBenefitPercentage: 90,
    });
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({
        tax_category: "social_security",
        ss_benefit_basis: "pia",
        pia_monthly: 2000,
        expected_benefit_percent: 90,
        claiming_age: 67,
        annual_amount: 26784,
        amount_frequency: "annual",
      }),
    );
  });

  it("requires a positive PIA and a claiming age", () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.click(screen.getByRole("radio", { name: "Social Security" }));
    fireEvent.click(screen.getByRole("radio", { name: "PIA" }));
    fireEvent.click(screen.getByText("Add income"));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a positive monthly PIA.");
    fireEvent.change(screen.getByLabelText("PIA per month at full retirement age ($)"), {
      target: { value: "1500" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /Claiming age/ }), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByText("Add income"));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a claiming age");
    expect(submit).not.toHaveBeenCalled();
  });

  it("reopens a saved PIA benefit and keeps the category when saving a legacy record", () => {
    const submit = vi.fn();
    render(<IncomeForm initial={savedPia} milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    expect(screen.getByRole("radio", { name: "PIA" })).toBeChecked();
    expect(screen.getByLabelText("PIA per month at full retirement age ($)")).toHaveValue("2,000");
    expect(screen.getByLabelText("Expected benefit paid (%)")).toHaveValue(90);
    fireEvent.click(screen.getByText("Save income"));
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({ tax_category: "social_security", ss_benefit_basis: "pia" }),
    );
  });

  it("switching back to a benefit amount clears the PIA fields", () => {
    const submit = vi.fn();
    render(<IncomeForm initial={savedPia} milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.click(screen.getByRole("radio", { name: "Benefit amount" }));
    fireEvent.click(screen.getByText("Save income"));
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({
        ss_benefit_basis: "amount",
        pia_monthly: null,
        expected_benefit_percent: null,
        annual_amount: 29760,
      }),
    );
  });
});
