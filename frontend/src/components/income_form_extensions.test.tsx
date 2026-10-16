import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import IncomeForm from "./income_form";
import { estimateSocialSecurity } from "@/api/client";
import type { ExSpouseRecord, Income } from "@/types/plan";

vi.mock("@/api/client", () => ({ estimateSocialSecurity: vi.fn() }));

const record: ExSpouseRecord = {
  pia_monthly: 3000,
  birth_year: 1958,
  birth_month: 1,
  marriage_years: 12,
  marriage_lasted_10_years: false,
  divorce_year: 2000,
  divorce_month: null,
  claim_age: 67,
  death_year: null,
  current_marriage_year: null,
  survivor_claim_age: null,
};

const savedPia: Income = {
  id: "i1",
  plan_id: "p1",
  name: "Social Security",
  annual_amount: 12000,
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
  claiming_age: 67,
  tax_category: "social_security",
  ss_benefit_basis: "pia",
  pia_monthly: 1000,
  expected_benefit_percent: 100,
  ex_spouse: record,
};

beforeEach(() => {
  vi.mocked(estimateSocialSecurity).mockReset();
  vi.mocked(estimateSocialSecurity).mockResolvedValue({
    estimated_annual_benefit: 12000,
    claiming_age: 67,
    claiming_factor: 1,
    full_retirement_age: 67,
  } as Awaited<ReturnType<typeof estimateSocialSecurity>>);
});

describe("IncomeForm growth schedule", () => {
  it("submits ordered segments with their dollar units", () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Annual amount ($)"), { target: { value: "100000" } });
    fireEvent.click(screen.getByRole("button", { name: "Add growth segment" }));
    let row = within(screen.getByRole("group", { name: "Growth segment 1" }));
    fireEvent.change(row.getByLabelText("Start year"), { target: { value: "2027" } });
    fireEvent.change(row.getByLabelText("End year"), { target: { value: "2029" } });
    fireEvent.change(row.getByLabelText("Change (% per year)"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Add growth segment" }));
    row = within(screen.getByRole("group", { name: "Growth segment 2" }));
    expect(row.getByLabelText("Start year")).toHaveValue(2030);
    fireEvent.change(row.getByLabelText("Change type"), { target: { value: "set_amount" } });
    fireEvent.change(row.getByLabelText("Annual amount ($)"), { target: { value: "120000" } });
    fireEvent.change(row.getByLabelText("Dollars"), { target: { value: "nominal" } });
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({
        growth_schedule: [
          { start_year: 2027, end_year: 2029, kind: "percent", value: 3, dollars: null },
          {
            start_year: 2030,
            end_year: null,
            kind: "set_amount",
            value: 120000,
            dollars: "nominal",
          },
        ],
        ex_spouse: null,
      }),
    );
  });

  it("lets an income start at $0 when a segment sets its amount later", () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Add growth segment" }));
    const row = within(screen.getByRole("group", { name: "Growth segment 1" }));
    fireEvent.change(row.getByLabelText("Start year"), { target: { value: "2030" } });
    fireEvent.change(row.getByLabelText("Change type"), { target: { value: "set_amount" } });
    fireEvent.change(row.getByLabelText("Annual amount ($)"), { target: { value: "60000" } });
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ annual_amount: 0 }));
  });

  it("rejects overlapping segments and keeps the draft", () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Annual amount ($)"), { target: { value: "100000" } });
    fireEvent.click(screen.getByRole("button", { name: "Add growth segment" }));
    fireEvent.change(
      within(screen.getByRole("group", { name: "Growth segment 1" })).getByLabelText(
        "Change (% per year)",
      ),
      { target: { value: "3" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Add growth segment" }));
    const second = within(screen.getByRole("group", { name: "Growth segment 2" }));
    fireEvent.change(second.getByLabelText("Change (% per year)"), { target: { value: "2" } });
    fireEvent.click(screen.getByText("Add income"));
    expect(screen.getByRole("alert")).toHaveTextContent("must not overlap");
    expect(submit).not.toHaveBeenCalled();
    expect(second.getByLabelText("Change (% per year)")).toHaveValue(2);
  });

  it("is not offered for Social Security", () => {
    render(
      <IncomeForm initial={savedPia} milestones={[]} onSubmit={vi.fn()} onCancel={() => {}} />,
    );
    expect(screen.queryByRole("button", { name: "Add growth segment" })).not.toBeInTheDocument();
  });
});

describe("IncomeForm former spouse", () => {
  it("shows only for PIA-basis benefits and submits the record", () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={[]} birthYear={1960} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.click(screen.getByRole("radio", { name: "Social Security" }));
    expect(screen.queryByText("Former spouse")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "PIA" }));
    fireEvent.change(screen.getByLabelText("PIA per month at full retirement age ($)"), {
      target: { value: "1000" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /Include a former spouse's record/ }));
    fireEvent.change(screen.getByLabelText("Former spouse's PIA per month ($)"), {
      target: { value: "3000" },
    });
    fireEvent.change(screen.getByLabelText("Former spouse's birth year"), {
      target: { value: "1958" },
    });
    fireEvent.change(screen.getByLabelText("Divorce year"), { target: { value: "2000" } });
    fireEvent.click(screen.getByText("Add income"));
    expect(screen.getByRole("alert")).toHaveTextContent("marriage length");
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox", { name: /lasted at least 10 years/ }));
    fireEvent.change(screen.getByLabelText("Former spouse's claiming age (optional)"), {
      target: { value: "67" },
    });
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({
        ss_benefit_basis: "pia",
        growth_schedule: null,
        ex_spouse: { ...record, marriage_years: null, marriage_lasted_10_years: true },
      }),
    );
  });

  it("reopens a saved record unchanged and clears it when the basis changes", () => {
    const submit = vi.fn();
    render(<IncomeForm initial={savedPia} milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    expect(screen.getByLabelText("Former spouse's PIA per month ($)")).toHaveValue("3,000");
    fireEvent.click(screen.getByText("Save income"));
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ ex_spouse: record }));
    fireEvent.click(screen.getByRole("radio", { name: "Benefit amount" }));
    fireEvent.click(screen.getByText("Save income"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ ss_benefit_basis: "amount", ex_spouse: null }),
    );
  });
});
