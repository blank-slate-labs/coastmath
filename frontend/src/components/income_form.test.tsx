import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import IncomeForm from "./income_form";
import { estimateSocialSecurity } from "@/api/client";
import type { Income } from "@/types/plan";
import { makeIncome, makeMilestone } from "@/test_support/record_builders";

vi.mock("@/api/client", () => ({ estimateSocialSecurity: vi.fn() }));

/** A new income needs an amount before it saves. */
const enterAmount = (value = "50000") =>
  fireEvent.change(screen.getByLabelText("Annual amount ($)"), { target: { value } });

const milestones = [
  makeMilestone({
    id: "m1",
    plan_id: "p1",
    name: "Retirement",
    trigger_type: "age" as const,
    trigger_value: 65,
    trigger_date: null,
    sort_order: 0,
  }),
];

describe("IncomeForm", () => {
  it("converts monthly income once and keeps growth caps and timing in their original units", () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={milestones} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Pension" } });
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "monthly" } });
    fireEvent.change(screen.getByLabelText("Monthly amount ($)"), { target: { value: "1234.56" } });
    fireEvent.change(screen.getByLabelText("Growth cap ($ per year, optional)"), {
      target: { value: "20000" },
    });
    fireEvent.change(screen.getByLabelText("Start milestone"), { target: { value: "m1" } });
    fireEvent.change(screen.getByLabelText("Start month"), { target: { value: "7" } });
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        annual_amount: 14814.72,
        growth_cap: 20000,
        start_milestone_id: "m1",
        start_month: 7,
      }),
    );
    expect(screen.getByText(/Starts in Jul.*Start Milestone is reached/)).toBeInTheDocument();
    expect(
      screen.getByText("Months apply to boundary years only, not a seasonal schedule."),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "annual" } });
    expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("14,814.72");
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "monthly" } });
    expect(screen.getByLabelText("Monthly amount ($)")).toHaveValue("1,234.56");
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ annual_amount: 14814.72 }));
  });

  it("preserves an exact saved annual amount through repeated unit toggles and unrelated edits", () => {
    const submit = vi.fn();
    const initial = makeIncome({
      id: "i1",
      plan_id: "p1",
      name: "Salary",
      annual_amount: 100000.01,
      start_milestone_id: null,
      end_milestone_id: null,
      growth_rate: null,
      withholding_percent: null,
      start_month: null,
      end_month: null,
      is_active: true,
      is_social_security: false,
      is_earned_income: true,
      is_self_employed: false,
    });
    render(<IncomeForm initial={initial} milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    for (let i = 0; i < 4; i += 1) {
      fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "monthly" } });
      expect(screen.getByLabelText("Monthly amount ($)")).toHaveValue("8,333.33");
      fireEvent.click(screen.getByText("Save income"));
      expect(submit).toHaveBeenLastCalledWith(
        expect.objectContaining({ annual_amount: 100000.01 }),
      );
      fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "annual" } });
      expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("100,000.01");
    }
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Renamed salary" } });
    fireEvent.click(screen.getByText("Save income"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ name: "Renamed salary", annual_amount: 100000.01 }),
    );
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "monthly" } });
    fireEvent.change(screen.getByLabelText("Monthly amount ($)"), { target: { value: "8500.25" } });
    fireEvent.click(screen.getByText("Save income"));
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ annual_amount: 102003 }));
  });

  // A money field takes digits only, so 1e308 is typed out; it overflows once annualized.
  it.each(["", "1" + "0".repeat(308)])(
    "rejects invalid monthly amount %j without changing the wire payload",
    (value) => {
      const submit = vi.fn();
      render(<IncomeForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
      fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Salary" } });
      fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "monthly" } });
      fireEvent.change(screen.getByLabelText("Monthly amount ($)"), { target: { value } });
      fireEvent.submit(screen.getByText("Add income").closest("form")!);
      expect(submit).not.toHaveBeenCalled();
      expect(screen.getByRole("alert")).toHaveTextContent("Enter a finite income amount.");
    },
  );

  it("asks for 0 or more, as expenses do, even on a saved negative income", () => {
    const submit = vi.fn();
    const initial = makeIncome({
      id: "i1",
      plan_id: "p1",
      name: "Adjustment",
      annual_amount: -1000.01,
      start_milestone_id: null,
      end_milestone_id: null,
      growth_rate: null,
      withholding_percent: null,
      start_month: null,
      end_month: null,
      is_active: true,
      is_social_security: false,
      is_earned_income: true,
      is_self_employed: false,
    });
    render(<IncomeForm initial={initial} milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "monthly" } });
    expect(screen.getByLabelText("Monthly amount ($)")).toHaveValue("-83.33");
    fireEvent.click(screen.getByText("Save income"));
    expect(submit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Monthly amount ($)"), { target: { value: "83.33" } });
    fireEvent.click(screen.getByText("Save income"));
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ annual_amount: 999.96 }));
  });

  it("refuses a $0 salary or other income with an inline error until an amount is entered", () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Enter an amount.");
    fireEvent.click(screen.getByRole("radio", { name: "Other" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Gift" } });
    fireEvent.change(screen.getByRole("combobox", { name: /Income tax treatment/ }), {
      target: { value: "nontaxable" },
    });
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Enter an amount.");
    enterAmount("5000");
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ annual_amount: 5000 }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("allows $0 for Social Security and for an income already saved at $0", () => {
    const submit = vi.fn();
    const { unmount } = render(
      <IncomeForm milestones={[]} usCoverage="non_us" onSubmit={submit} onCancel={() => {}} />,
    );
    fireEvent.click(screen.getByRole("radio", { name: "US Social Security" }));
    expect(screen.queryByText(/For PIA, enter your monthly benefit/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ is_social_security: true, annual_amount: 0 }),
    );
    unmount();

    const saved = makeIncome({ id: "i0", name: "Side work", is_earned_income: true });
    render(<IncomeForm initial={saved} milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Side gig" } });
    fireEvent.click(screen.getByText("Save income"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ name: "Side gig", annual_amount: 0 }),
    );
  });

  it("annualizes monthly income through display toggles", () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Side work" } });
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "monthly" } });
    fireEvent.change(screen.getByLabelText("Monthly amount ($)"), { target: { value: "100.25" } });
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ annual_amount: 1203 }));
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "annual" } });
    expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("1,203");
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "monthly" } });
    expect(screen.getByLabelText("Monthly amount ($)")).toHaveValue("100.25");
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ annual_amount: 1203 }));
  });

  it.each(["monthly", "annual"] as const)(
    "shows an asynchronous Social Security estimate in the currently selected %s unit",
    async (frequency) => {
      const submit = vi.fn();
      let resolve!: (value: Awaited<ReturnType<typeof estimateSocialSecurity>>) => void;
      vi.mocked(estimateSocialSecurity).mockReturnValueOnce(
        new Promise((done) => {
          resolve = done;
        }),
      );
      render(<IncomeForm milestones={[]} birthYear={1960} onSubmit={submit} onCancel={() => {}} />);
      fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Social Security" } });
      fireEvent.click(screen.getByRole("radio", { name: "Social Security" }));
      fireEvent.change(screen.getByLabelText("Amount frequency"), {
        target: { value: frequency === "monthly" ? "annual" : "monthly" },
      });
      fireEvent.change(screen.getByLabelText("Current annual income (for estimate)"), {
        target: { value: "75000" },
      });
      fireEvent.click(screen.getByText("Estimate from income"));
      fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: frequency } });
      await act(async () => {
        resolve({ estimated_annual_benefit: 28800.01 } as Awaited<
          ReturnType<typeof estimateSocialSecurity>
        >);
      });
      expect(
        screen.getByLabelText(frequency === "monthly" ? "Monthly amount ($)" : "Annual amount ($)"),
      ).toHaveValue(frequency === "monthly" ? "2,400" : "28,800.01");
      fireEvent.click(screen.getByText("Add income"));
      expect(submit).toHaveBeenLastCalledWith(
        expect.objectContaining({ annual_amount: 28800.01, is_social_security: true }),
      );
    },
  );

  it("requires explicit unearned tax treatment and recovers with a qualified pension", () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Pension" } });
    fireEvent.click(screen.getByRole("radio", { name: "Other" }));
    enterAmount();
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Choose the income tax treatment");
    fireEvent.change(screen.getByRole("combobox", { name: /Income tax treatment/ }), {
      target: { value: "qualified_pension" },
    });
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        name: "Pension",
        tax_category: "qualified_pension",
        is_earned_income: false,
      }),
    );
  });
  it("preserves seeded SS growth on unrelated edits and lets a saved claiming age return to null", () => {
    const submit = vi.fn();
    const initial = makeIncome({
      id: "ss",
      plan_id: "p",
      name: "Social Security",
      annual_amount: 28000,
      start_milestone_id: "m1",
      end_milestone_id: null,
      growth_rate: 2,
      growth_cap: 50000,
      growth_cap_inflation_linked: true,
      withholding_percent: null,
      start_month: null,
      end_month: null,
      is_active: true,
      is_social_security: true,
      is_earned_income: false,
      is_self_employed: false,
      claiming_age: 70,
    });
    render(
      <IncomeForm
        initial={initial}
        milestones={milestones}
        onSubmit={submit}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByLabelText(/Growth rate/)).toHaveValue(2);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Renamed benefit" } });
    fireEvent.change(screen.getByRole("combobox", { name: /Claiming age/ }), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByText("Save income"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        name: "Renamed benefit",
        claiming_age: null,
        growth_rate: 2,
        growth_cap: 50000,
        growth_cap_inflation_linked: true,
        start_milestone_id: "m1",
      }),
    );
    fireEvent.change(screen.getByLabelText(/Growth rate/), { target: { value: "" } });
    fireEvent.click(screen.getByText("Save income"));
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ growth_rate: null }));
  });
  it("hides Income recipient on a single-person plan and saves the income as yours", () => {
    const submit = vi.fn();
    render(<IncomeForm hasPartner={false} milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    expect(screen.queryByRole("combobox", { name: "Income recipient" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Add a partner under/)).not.toBeInTheDocument();
    enterAmount();
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ owner: "self" }));
  });
  it("shows Income recipient unchanged when the plan has a partner", () => {
    render(<IncomeForm hasPartner milestones={[]} onSubmit={() => {}} onCancel={() => {}} />);
    expect(screen.getByRole("combobox", { name: "Income recipient" })).toHaveValue("self");
    expect(screen.getByRole("option", { name: "Primary person" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Partner" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /^(You|Spouse)$/ })).not.toBeInTheDocument();
  });
  it("keeps the recipient select for a saved partner income after the partner is removed", () => {
    const initial = makeIncome({
      id: "i1",
      plan_id: "p1",
      name: "Salary",
      annual_amount: 1000,
      owner: "spouse" as const,
      start_milestone_id: null,
      end_milestone_id: null,
      growth_rate: null,
      withholding_percent: null,
      start_month: null,
      end_month: null,
      is_active: true,
      is_social_security: false,
      is_earned_income: true,
      is_self_employed: false,
    });
    render(
      <IncomeForm
        initial={initial}
        hasPartner={false}
        milestones={[]}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByRole("combobox", { name: /Income recipient/ })).toHaveValue("spouse");
    expect(
      screen.getByRole("option", { name: "Partner (partner profile missing)" }),
    ).toBeInTheDocument();
  });
  it("renders MonthPicker for start and end months", () => {
    render(<IncomeForm milestones={milestones} onSubmit={() => {}} onCancel={() => {}} />);

    expect(screen.getByText("Start month")).toBeInTheDocument();
    expect(screen.getByText("End month")).toBeInTheDocument();
    // Should have comboboxes (select elements) for month pickers
    const selects = screen.getAllByRole("combobox");
    // At least 2 for month pickers (plus milestone selects)
    expect(selects.length).toBeGreaterThanOrEqual(4);
  });

  it("includes start_month and end_month in submitted data", () => {
    const handleSubmit = vi.fn();
    render(<IncomeForm milestones={milestones} onSubmit={handleSubmit} onCancel={() => {}} />);

    // Fill required name field
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Salary" },
    });

    // Set start month to July (7)
    const startMonthSelect = screen.getByRole("combobox", { name: "Start month" });
    const endMonthSelect = screen.getByRole("combobox", { name: "End month" });

    fireEvent.change(startMonthSelect, { target: { value: "7" } });
    fireEvent.change(endMonthSelect, { target: { value: "12" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Income recipient" }), {
      target: { value: "spouse" },
    });

    enterAmount();
    fireEvent.click(screen.getByText("Add income"));

    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        start_month: 7,
        end_month: 12,
        owner: "spouse",
      }),
    );
  });

  it("sends null months when none selected", () => {
    const handleSubmit = vi.fn();
    render(<IncomeForm milestones={[]} onSubmit={handleSubmit} onCancel={() => {}} />);

    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Salary" },
    });
    enterAmount();
    fireEvent.click(screen.getByText("Add income"));

    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        start_month: null,
        end_month: null,
      }),
    );
  });

  it("explains saved month-only overrides instead of promising half-year income", () => {
    render(
      <IncomeForm
        initial={makeIncome({
          id: "i1",
          plan_id: "p1",
          name: "Salary",
          annual_amount: 100000,
          start_milestone_id: null,
          end_milestone_id: null,
          growth_rate: null,
          withholding_percent: null,
          start_month: 7,
          end_month: 12,
          is_active: true,
          is_social_security: false,
          is_earned_income: true,
          is_self_employed: false,
        })}
        milestones={[]}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );

    expect(screen.getByText(/Requires a Start Milestone/)).toBeInTheDocument();
    expect(screen.getByText(/Requires an End Milestone/)).toBeInTheDocument();
    expect(screen.queryByText(/\$50,000/)).not.toBeInTheDocument();
  });

  it("submits growth cap, withholding and employment flags in percent/dollar units", () => {
    const handleSubmit = vi.fn();
    render(<IncomeForm milestones={[]} onSubmit={handleSubmit} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Consulting" } });
    fireEvent.change(screen.getByLabelText(/Growth rate/), { target: { value: "4.5" } });
    fireEvent.change(screen.getByLabelText(/Growth cap/), { target: { value: "200000" } });
    fireEvent.click(screen.getByLabelText(/Cap rises with inflation/));
    fireEvent.click(screen.getByLabelText(/Self-employed/));
    fireEvent.change(screen.getByLabelText(/Tax withholding/), { target: { value: "22.5" } });
    enterAmount();
    fireEvent.click(screen.getByText("Add income"));
    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        growth_rate: 4.5,
        growth_cap: 200000,
        growth_cap_inflation_linked: true,
        withholding_percent: 22.5,
        is_earned_income: true,
        is_self_employed: true,
        is_social_security: false,
      }),
    );
  });

  it("preserves growth assumptions when changing income type and clears employment flags for Social Security", () => {
    const handleSubmit = vi.fn();
    const initial = makeIncome({
      id: "i1",
      plan_id: "p1",
      name: "Salary",
      annual_amount: 100000,
      start_milestone_id: null,
      end_milestone_id: null,
      growth_rate: 3,
      growth_cap: 150000,
      growth_cap_inflation_linked: true,
      withholding_percent: 18,
      start_month: null,
      end_month: null,
      is_active: true,
      is_social_security: false,
      is_earned_income: true,
      is_self_employed: true,
      owner: "spouse" as const,
    });
    render(
      <IncomeForm initial={initial} milestones={[]} onSubmit={handleSubmit} onCancel={() => {}} />,
    );
    expect(screen.getByLabelText(/Growth cap/)).toHaveValue("150,000");
    expect(screen.getByLabelText(/Tax withholding/)).toHaveValue(18);
    expect(screen.getByLabelText(/Self-employed/)).toBeChecked();
    fireEvent.click(screen.getByText("Save income"));
    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        growth_cap: 150000,
        growth_cap_inflation_linked: true,
        withholding_percent: 18,
        is_self_employed: true,
        owner: "spouse",
      }),
    );
    fireEvent.click(screen.getByRole("radio", { name: "Social Security" }));
    fireEvent.click(screen.getByText("Save income"));
    expect(handleSubmit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        is_social_security: true,
        growth_rate: 3,
        growth_cap: 150000,
        growth_cap_inflation_linked: true,
        is_earned_income: false,
        is_self_employed: false,
        withholding_percent: 18,
      }),
    );
  });

  it("rejects a start month after the end month without submitting", () => {
    const handleSubmit = vi.fn();
    render(<IncomeForm milestones={[]} onSubmit={handleSubmit} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Salary" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Start month" }), {
      target: { value: "9" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "End month" }), {
      target: { value: "3" },
    });
    enterAmount();
    fireEvent.click(screen.getByText("Add income"));
    expect(screen.getByRole("alert")).toHaveTextContent("Start month");
    expect(handleSubmit).not.toHaveBeenCalled();
  });

  it("submits the Social Security claiming age and shows when benefits begin", () => {
    const handleSubmit = vi.fn();
    render(
      <IncomeForm
        milestones={milestones}
        birthYear={1992}
        onSubmit={handleSubmit}
        onCancel={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Social Security" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Social Security" },
    });
    const claiming = screen.getByRole("combobox", { name: /Claiming age/ });
    expect(claiming).toHaveValue("67");
    fireEvent.change(claiming, { target: { value: "70" } });
    expect(screen.getByText(/Benefits begin the year you turn 70 \(2062\)/)).toBeInTheDocument();
    fireEvent.submit(screen.getByRole("button", { name: "Add income" }).closest("form")!);
    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        is_social_security: true,
        claiming_age: 70,
        start_milestone_id: null,
      }),
    );
  });

  it("exposes the PIA estimate option and validates its required input", () => {
    render(<IncomeForm milestones={[]} onSubmit={() => {}} onCancel={() => {}} />);
    fireEvent.click(screen.getByRole("radio", { name: "Social Security" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Estimate method" }), {
      target: { value: "pia" },
    });

    expect(screen.getByLabelText("Monthly PIA at FRA")).toBeInTheDocument();
    expect(screen.getByLabelText("Expected benefit (%)")).toHaveValue(100);
    fireEvent.click(screen.getByText("Estimate from PIA"));
    expect(screen.getByText("Enter a positive monthly PIA")).toBeInTheDocument();
  });

  it("reopens with the saved claiming age and defers to an explicit start milestone", () => {
    const initial = makeIncome({
      id: "i1",
      plan_id: "p1",
      name: "Social Security",
      annual_amount: 28800,
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
      owner: "self" as const,
      claiming_age: 70,
    });
    render(
      <IncomeForm
        initial={initial}
        milestones={milestones}
        birthYear={1992}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByRole("combobox", { name: /Claiming age/ })).toHaveValue("70");
    expect(screen.getByRole("option", { name: "Not set" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Start milestone" }), {
      target: { value: "m1" },
    });
    expect(
      screen.getByText(/Benefits follow the "Retirement" milestone \(2057\)/),
    ).toBeInTheDocument();
  });

  it("updates month guidance for claiming age, explicit milestones and their removal", () => {
    render(<IncomeForm milestones={milestones} onSubmit={() => {}} onCancel={() => {}} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Start month" }), {
      target: { value: "7" },
    });
    expect(screen.getByText(/Requires a Start Milestone/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Social Security" }));
    expect(screen.getByText(/Starts in Jul.*claiming age 67/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Start milestone" }), {
      target: { value: "m1" },
    });
    expect(screen.getByText(/Starts in Jul.*Start Milestone is reached/)).toBeInTheDocument();
    expect(screen.queryByText(/Starts in Jul.*claiming age/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Start milestone" }), {
      target: { value: "" },
    });
    expect(screen.getByText(/Starts in Jul.*claiming age 67/)).toBeInTheDocument();
  });

  it("warns about a window bounded by a projection-dependent milestone", () => {
    const fi = makeMilestone({
      id: "fi",
      plan_id: "p1",
      name: "FI",
      trigger_type: "expense_multiple" as const,
      trigger_value: null,
      trigger_date: null,
      expense_multiple: 25,
      sort_order: 1,
    });
    render(
      <IncomeForm
        milestones={[...milestones, fi]}
        birthYear={1992}
        outcomes={[
          { id: "m1", name: "Retirement", trigger_type: "age", year: 2057 },
          { id: "fi", name: "FI", trigger_type: "expense_multiple", year: 2035 },
        ]}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Start milestone" }), {
      target: { value: "m1" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "End milestone" }), {
      target: { value: "fi" },
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      /"Retirement" fires in 2057, after "FI" in 2035, so this never runs/,
    );
  });

  it("defaults a new salary's name and end to the Retirement milestone, and swaps both for Social Security", () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={milestones} onSubmit={submit} onCancel={() => {}} />);
    expect(screen.getByRole("radio", { name: "Salary" })).toBeChecked();
    expect(screen.getByLabelText("Name")).toHaveValue("Salary");
    expect(screen.getByRole("combobox", { name: "End milestone" })).toHaveValue("m1");
    fireEvent.click(screen.getByRole("radio", { name: "Social Security" }));
    expect(screen.getByLabelText("Name")).toHaveValue("Social Security");
    expect(screen.getByRole("combobox", { name: "End milestone" })).toHaveValue("");
    fireEvent.click(screen.getByRole("radio", { name: "Salary" }));
    expect(screen.getByLabelText("Name")).toHaveValue("Salary");
    expect(screen.getByRole("combobox", { name: "End milestone" })).toHaveValue("m1");
  });

  it("defaults the end to Retirement by name with any trigger and follows the recipient", () => {
    const plan = [
      makeMilestone({
        id: "fi",
        plan_id: "p1",
        name: "Retirement",
        trigger_type: "expense_multiple" as const,
        trigger_value: null,
        trigger_date: null,
        sort_order: 0,
      }),
      makeMilestone({
        id: "pr",
        plan_id: "p1",
        name: "Partner retirement",
        trigger_type: "date" as const,
        trigger_value: null,
        trigger_date: "2040-01-01",
        sort_order: 1,
      }),
    ];
    render(<IncomeForm milestones={plan} onSubmit={() => {}} onCancel={() => {}} />);
    const end = screen.getByRole("combobox", { name: "End milestone" });
    expect(end).toHaveValue("fi");
    fireEvent.change(screen.getByLabelText("Income recipient"), { target: { value: "spouse" } });
    expect(end).toHaveValue("pr");
    fireEvent.change(screen.getByLabelText("Income recipient"), { target: { value: "self" } });
    expect(end).toHaveValue("fi");
    fireEvent.change(end, { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Income recipient"), { target: { value: "spouse" } });
    expect(end).toHaveValue("");
  });

  it("says a blank rate follows wage growth only for earned income", () => {
    render(<IncomeForm milestones={milestones} onSubmit={() => {}} onCancel={() => {}} />);
    expect(
      screen.getByText(/A blank rate follows the Wage growth assumption\./),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Other" }));
    expect(screen.getByText(/A blank rate keeps a fixed nominal amount\./)).toBeInTheDocument();
    expect(screen.queryByText(/Wage growth assumption/)).not.toBeInTheDocument();
  });

  it("includes a new income in the projection by default", () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={milestones} onSubmit={submit} onCancel={() => {}} />);
    enterAmount();
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ is_active: true }));
  });

  it("ends a partner's salary at Retirement when there is no partner retirement", () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={milestones} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Income recipient"), { target: { value: "spouse" } });
    const end = () => screen.getByRole("combobox", { name: "End milestone" }) as HTMLSelectElement;
    expect(end()).toHaveValue("m1");
    expect(end().selectedOptions[0]).toHaveTextContent("Retirement");
    // Type selection applies the same default.
    fireEvent.click(screen.getByRole("radio", { name: "Social Security" }));
    expect(end()).toHaveValue("");
    fireEvent.click(screen.getByRole("radio", { name: "Salary" }));
    expect(end()).toHaveValue("m1");
    enterAmount();
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ owner: "spouse", end_milestone_id: "m1" }),
    );
  });

  it("Other clears the default name and retirement end and asks for its tax treatment up front", () => {
    const submit = vi.fn();
    const { container } = render(
      <IncomeForm milestones={milestones} onSubmit={submit} onCancel={() => {}} />,
    );
    expect(
      screen.queryByRole("combobox", { name: /Income tax treatment/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Earned income \(wages/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Other" }));
    expect(screen.getByLabelText("Name")).toHaveValue("");
    expect(screen.getByRole("combobox", { name: "End milestone" })).toHaveValue("");
    const treatment = screen.getByRole("combobox", { name: /Income tax treatment/ });
    expect(treatment.closest("details")).toBeNull();
    expect(screen.getByLabelText(/Earned income \(wages/)).not.toBeChecked();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Rental" } });
    fireEvent.change(treatment, { target: { value: "investment" } });
    enterAmount();
    fireEvent.submit(container.querySelector("form")!);
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        name: "Rental",
        is_earned_income: false,
        is_social_security: false,
        tax_category: "investment",
        end_milestone_id: null,
      }),
    );
  });

  it("keeps a typed name when the type changes", () => {
    render(<IncomeForm milestones={milestones} onSubmit={() => {}} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Acme payroll" } });
    fireEvent.click(screen.getByRole("radio", { name: "Other" }));
    expect(screen.getByLabelText("Name")).toHaveValue("Acme payroll");
  });

  it.each([
    [{ is_social_security: true, is_earned_income: false }, "Social Security"],
    [{ is_social_security: false, is_earned_income: true }, "Salary"],
    [
      {
        is_social_security: false,
        is_earned_income: false,
        tax_category: "qualified_pension" as const,
      },
      "Other",
    ],
  ])("opens a saved income on its type (%o)", (flags, label) => {
    const initial = makeIncome({
      id: "i1",
      plan_id: "p1",
      name: "Saved",
      annual_amount: 1000,
      start_milestone_id: null,
      end_milestone_id: null,
      growth_rate: null,
      withholding_percent: null,
      start_month: null,
      end_month: null,
      is_active: true,
      is_self_employed: false,
      ...flags,
    });
    render(
      <IncomeForm
        initial={initial}
        milestones={milestones}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByRole("radio", { name: label })).toBeChecked();
    expect(screen.getByLabelText("Name")).toHaveValue("Saved");
  });

  it("keeps month selects collapsed by default and opens them for a saved month", () => {
    const { unmount } = render(
      <IncomeForm milestones={milestones} onSubmit={() => {}} onCancel={() => {}} />,
    );
    const months = () =>
      screen
        .getByRole("combobox", { name: "Start month" })
        .closest("details.income-months") as HTMLDetailsElement;
    expect(months().open).toBe(false);
    expect(screen.queryByText(/Months apply only with a milestone/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Social Security" }));
    expect(months().open).toBe(false);
    unmount();
    render(
      <IncomeForm
        initial={makeIncome({
          id: "i1",
          plan_id: "p1",
          name: "Salary",
          annual_amount: 1000,
          start_milestone_id: "m1",
          end_milestone_id: null,
          growth_rate: null,
          withholding_percent: null,
          start_month: 7,
          end_month: null,
          is_active: true,
          is_social_security: false,
          is_earned_income: true,
          is_self_employed: false,
        })}
        milestones={milestones}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(months().open).toBe(true);
  });

  it("stores a biweekly paycheck as 26 times the amount", () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "biweekly" } });
    fireEvent.change(screen.getByLabelText("Biweekly amount ($)"), {
      target: { value: "2000.50" },
    });
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ annual_amount: 52013 }));
  });

  it("shows a saved annual amount per biweekly paycheck in cents without changing it", () => {
    const initial = makeIncome({
      id: "i1",
      plan_id: "p1",
      name: "Salary",
      annual_amount: 100000,
      start_milestone_id: null,
      end_milestone_id: null,
      growth_rate: null,
      withholding_percent: null,
      start_month: null,
      end_month: null,
      is_active: true,
      is_social_security: false,
      is_earned_income: true,
      is_self_employed: false,
    });
    const save = vi.fn();
    render(<IncomeForm initial={initial} milestones={[]} onSubmit={save} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "biweekly" } });
    expect(screen.getByLabelText("Biweekly amount ($)")).toHaveValue("3,846.15");
    fireEvent.click(screen.getByText("Save income"));
    expect(save).toHaveBeenLastCalledWith(expect.objectContaining({ annual_amount: 100000 }));
  });

  it("puts wage timing behind its summary with Now and End of plan defaults", () => {
    const { container } = render(
      <IncomeForm milestones={milestones} planType="NOW" onSubmit={() => {}} onCancel={() => {}} />,
    );
    const timing = container.querySelector("details.income-timing") as HTMLDetailsElement;
    expect(timing.open).toBe(false);
    expect(timing.querySelector("summary")).toHaveTextContent("Starts now; ends at Retirement");
    expect(screen.getByRole("option", { name: "Now" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "End of plan" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "End milestone" }), {
      target: { value: "" },
    });
    expect(timing.querySelector("summary")).toHaveTextContent(
      "Starts now; continues to end of plan",
    );
    expect(screen.queryByText("When you receive this income")).not.toBeInTheDocument();
  });

  it("keeps Plan start for fixed-date wages and the Social Security timing controls", () => {
    render(
      <IncomeForm
        milestones={milestones}
        planType="FIXED_DATE"
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByRole("option", { name: "Plan start" })).toBeInTheDocument();
    expect(
      screen.getByText(/Starts when this plan begins; ends at Retirement/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Social Security" }));
    expect(screen.getByText("When you receive this income")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Through plan end" })).toBeInTheDocument();
    expect(screen.getByText(/continues through plan end/)).toBeInTheDocument();
  });

  it("keeps a saved income's name and end milestone", () => {
    const initial = makeIncome({
      id: "i1",
      plan_id: "p1",
      name: "Consulting",
      annual_amount: 5000,
      start_milestone_id: null,
      end_milestone_id: null,
      growth_rate: null,
      withholding_percent: null,
      start_month: null,
      end_month: null,
      is_active: true,
      is_social_security: false,
      is_earned_income: true,
      is_self_employed: false,
    });
    render(
      <IncomeForm
        initial={initial}
        milestones={milestones}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByLabelText("Name")).toHaveValue("Consulting");
    expect(screen.getByRole("combobox", { name: "End milestone" })).toHaveValue("");
  });

  it("estimates Social Security from the recipient's planned earnings and follows the claiming age", async () => {
    const salary = makeIncome({
      id: "s1",
      plan_id: "p1",
      owner: "self" as const,
      name: "Salary",
      annual_amount: 90000,
      start_milestone_id: null,
      end_milestone_id: "m1",
      growth_rate: null,
      withholding_percent: null,
      start_month: null,
      end_month: null,
      is_active: true,
      is_social_security: false,
      is_earned_income: true,
      is_self_employed: false,
    });
    const estimate = vi.mocked(estimateSocialSecurity);
    estimate.mockReset();
    estimate.mockResolvedValueOnce({ estimated_annual_benefit: 30000 } as Awaited<
      ReturnType<typeof estimateSocialSecurity>
    >);
    estimate.mockResolvedValueOnce({ estimated_annual_benefit: 37200 } as Awaited<
      ReturnType<typeof estimateSocialSecurity>
    >);
    render(
      <IncomeForm
        milestones={milestones}
        incomes={[salary]}
        birthYear={1990}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("radio", { name: "Social Security" }));
    });
    expect(estimate).toHaveBeenLastCalledWith(90000, 67, 1990, undefined);
    expect(screen.getByLabelText("Current annual income (for estimate)")).toHaveValue("90,000");
    expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("30,000.00");
    await act(async () => {
      fireEvent.change(screen.getByRole("combobox", { name: /^Claiming age/ }), {
        target: { value: "70" },
      });
    });
    expect(estimate).toHaveBeenLastCalledWith(90000, 70, 1990, undefined);
    expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("37,200.00");
    // A typed amount stops the automatic estimate.
    fireEvent.change(screen.getByLabelText("Annual amount ($)"), { target: { value: "25000" } });
    await act(async () => {
      fireEvent.change(screen.getByRole("combobox", { name: /^Claiming age/ }), {
        target: { value: "62" },
      });
    });
    expect(estimate).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("25,000");
  });
});

describe("IncomeForm saved amount unit", () => {
  const saved = (amount_frequency?: Income["amount_frequency"]): Income => ({
    id: "i1",
    plan_id: "p1",
    name: "Salary",
    annual_amount: 100000.01,
    start_milestone_id: null,
    end_milestone_id: null,
    growth_rate: null,
    growth_cap: null,
    growth_cap_inflation_linked: false,
    withholding_percent: null,
    start_month: null,
    end_month: null,
    is_active: true,
    is_social_security: false,
    is_earned_income: true,
    is_self_employed: false,
    ...(amount_frequency === undefined ? {} : { amount_frequency }),
  });

  it.each([
    ["weekly", "Weekly amount ($)", "1,923.08"],
    ["biweekly", "Biweekly amount ($)", "3,846.15"],
    ["semimonthly", "Semimonthly amount ($)", "4,166.67"],
    ["monthly", "Monthly amount ($)", "8,333.33"],
    ["quarterly", "Quarterly amount ($)", "25,000"],
    ["annual", "Annual amount ($)", "100,000.01"],
  ] as const)("reopens a %s income in its unit and saves it unchanged", (unit, label, shown) => {
    const submit = vi.fn();
    render(
      <IncomeForm initial={saved(unit)} milestones={[]} onSubmit={submit} onCancel={() => {}} />,
    );
    expect(screen.getByLabelText("Amount frequency")).toHaveValue(unit);
    expect(screen.getByLabelText(label)).toHaveValue(shown);
    // Toggle through every unit and back without editing: the saved amount must not drift.
    for (const other of ["weekly", "annual", "semimonthly", "quarterly", unit]) {
      fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: other } });
    }
    fireEvent.click(screen.getByText("Save income"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ annual_amount: 100000.01, amount_frequency: unit }),
    );
  });

  it.each([null, undefined])(
    "opens a legacy %s income as annual and leaves its unit unset unless one is chosen",
    (legacy) => {
      const submit = vi.fn();
      render(
        <IncomeForm
          initial={saved(legacy)}
          milestones={[]}
          onSubmit={submit}
          onCancel={() => {}}
        />,
      );
      expect(screen.getByLabelText("Amount frequency")).toHaveValue("annual");
      expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("100,000.01");
      fireEvent.click(screen.getByText("Save income"));
      expect(submit.mock.calls.at(-1)![0]).not.toHaveProperty("amount_frequency");
      fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "monthly" } });
      fireEvent.click(screen.getByText("Save income"));
      expect(submit).toHaveBeenLastCalledWith(
        expect.objectContaining({ annual_amount: 100000.01, amount_frequency: "monthly" }),
      );
    },
  );

  it("submits the unit of a new income, defaulting to annual", () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    expect(screen.getByLabelText("Amount frequency")).toHaveValue("annual");
    fireEvent.change(screen.getByLabelText("Annual amount ($)"), { target: { value: "52000" } });
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ annual_amount: 52000, amount_frequency: "annual" }),
    );
    fireEvent.change(screen.getByLabelText("Amount frequency"), {
      target: { value: "semimonthly" },
    });
    fireEvent.change(screen.getByLabelText("Semimonthly amount ($)"), {
      target: { value: "2500.50" },
    });
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ annual_amount: 60012, amount_frequency: "semimonthly" }),
    );
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "weekly" } });
    expect(screen.getByLabelText("Weekly amount ($)")).toHaveValue("1,154.08");
    fireEvent.click(screen.getByText("Add income"));
    // The unit shown at save is the one saved; the typed semimonthly value still sets the amount.
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ annual_amount: 60012, amount_frequency: "weekly" }),
    );
  });
});
