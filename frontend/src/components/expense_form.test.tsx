import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ExpenseForm from "./expense_form";
import type { Expense } from "@/types/plan";
import { makeExpense, makeMilestone } from "@/test_support/record_builders";

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

describe("ExpenseForm", () => {
  it("clears the date error when corrected even if native required-name validation blocks submit", () => {
    const submit = vi.fn();
    const dates = [
      { ...milestones[0], id: "early", name: "Retirement", trigger_value: 47 },
      { ...milestones[0], id: "late", name: "Social Security", trigger_value: 70 },
    ];
    render(
      <ExpenseForm milestones={dates} birthYear={1992} onSubmit={submit} onCancel={() => {}} />,
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Travel" } });
    fireEvent.change(screen.getByRole("combobox", { name: /^Start Milestone/ }), {
      target: { value: "late" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /^End Milestone/ }), {
      target: { value: "early" },
    });
    fireEvent.click(screen.getByText("Add Expense"));
    expect(screen.getByRole("alert")).toHaveTextContent("comes after");
    fireEvent.change(screen.getByRole("combobox", { name: /^Start Milestone/ }), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /^End Milestone/ }), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "" } });
    fireEvent.click(screen.getByText("Add Expense"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toBeInvalid();
    expect(submit).not.toHaveBeenCalled();
  });
  it("sends the qualified education flag only when it is set", () => {
    const handleSubmit = vi.fn();
    render(<ExpenseForm milestones={[]} onSubmit={handleSubmit} onCancel={() => {}} />);
    fireEvent.change(screen.getAllByRole("textbox")[0], { target: { value: "Tuition" } });
    fireEvent.click(screen.getByText("Add Expense"));
    expect(handleSubmit.mock.calls[0][0]).not.toHaveProperty("qualified_education");
    fireEvent.click(screen.getByLabelText(/Qualified education expense/));
    fireEvent.click(screen.getByText("Add Expense"));
    expect(handleSubmit.mock.calls[1][0]).toMatchObject({ qualified_education: true });
  });

  it("renders MonthPicker for start and end months", () => {
    render(<ExpenseForm milestones={milestones} onSubmit={() => {}} onCancel={() => {}} />);

    expect(screen.getByText("Start Month")).toBeInTheDocument();
    expect(screen.getByText("End Month")).toBeInTheDocument();
  });

  it("includes start_month and end_month in submitted data", () => {
    const handleSubmit = vi.fn();
    render(<ExpenseForm milestones={[]} onSubmit={handleSubmit} onCancel={() => {}} />);

    // Fill required name
    const textInputs = screen.getAllByRole("textbox");
    fireEvent.change(textInputs[0], { target: { value: "Rent" } });

    const startMonthSelect = screen.getByRole("combobox", { name: "Start Month" });
    const endMonthSelect = screen.getByRole("combobox", { name: "End Month" });

    fireEvent.change(startMonthSelect, { target: { value: "3" } });
    fireEvent.change(endMonthSelect, { target: { value: "8" } });

    fireEvent.click(screen.getByText("Add Expense"));

    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        start_month: 3,
        end_month: 8,
      }),
    );
  });

  it("sends null months when none selected", () => {
    const handleSubmit = vi.fn();
    render(<ExpenseForm milestones={[]} onSubmit={handleSubmit} onCancel={() => {}} />);

    const textInputs = screen.getAllByRole("textbox");
    fireEvent.change(textInputs[0], { target: { value: "Groceries" } });
    fireEvent.click(screen.getByText("Add Expense"));

    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        start_month: null,
        end_month: null,
      }),
    );
  });

  it("submits an explicit after-tax treatment for a tied payroll expense", () => {
    const handleSubmit = vi.fn();
    const income = {
      id: "salary",
      plan_id: "p1",
      name: "Salary",
      annual_amount: 100000,
      is_active: true,
      growth_rate: null,
      growth_cap: null,
      growth_cap_inflation_linked: false,
      withholding_percent: null,
      start_milestone_id: null,
      end_milestone_id: null,
      start_month: null,
      end_month: null,
      tax_category: "employment" as const,
      is_social_security: false,
      is_earned_income: true,
      is_self_employed: false,
      owner: "self" as const,
    };
    render(
      <ExpenseForm
        milestones={[]}
        incomeStreams={[income]}
        onSubmit={handleSubmit}
        onCancel={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Health premium" } });
    fireEvent.click(screen.getByLabelText("Payroll Deduction"));
    fireEvent.change(screen.getByRole("combobox", { name: /Deduct from income/ }), {
      target: { value: "salary" },
    });
    fireEvent.click(screen.getByLabelText("After-tax"));
    fireEvent.click(screen.getByText("Add Expense"));

    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        is_payroll_deduction: true,
        tied_income_id: "salary",
        payroll_tax_treatment: "after_tax",
      }),
    );
  });

  it("stores only wage-base elections that differ from the treatment defaults", () => {
    const handleSubmit = vi.fn();
    const income = {
      id: "salary",
      plan_id: "p1",
      name: "Salary",
      annual_amount: 100000,
      is_active: true,
      growth_rate: null,
      growth_cap: null,
      growth_cap_inflation_linked: false,
      withholding_percent: null,
      start_milestone_id: null,
      end_milestone_id: null,
      start_month: null,
      end_month: null,
      tax_category: "employment" as const,
      is_social_security: false,
      is_earned_income: true,
      is_self_employed: false,
      owner: "self" as const,
    };
    render(
      <ExpenseForm
        milestones={[]}
        incomeStreams={[income]}
        onSubmit={handleSubmit}
        onCancel={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Medical premium" } });
    fireEvent.click(screen.getByLabelText("Payroll Deduction"));
    fireEvent.change(screen.getByRole("combobox", { name: /Deduct from income/ }), {
      target: { value: "salary" },
    });
    expect(screen.getByLabelText("Federal income tax")).toBeChecked();
    expect(screen.getByLabelText("Social Security and Medicare")).not.toBeChecked();
    fireEvent.click(screen.getByLabelText("Social Security and Medicare"));
    fireEvent.click(screen.getByLabelText("State income tax"));
    fireEvent.click(screen.getByLabelText("State income tax"));
    fireEvent.click(screen.getByText("Add Expense"));
    expect(handleSubmit.mock.calls[0][0].payroll_tax_elections).toEqual({ fica: true });
  });

  it("leaves default elections out of a new payroll expense", () => {
    const handleSubmit = vi.fn();
    const income = {
      id: "salary",
      plan_id: "p1",
      name: "Salary",
      annual_amount: 100000,
      is_active: true,
      growth_rate: null,
      growth_cap: null,
      growth_cap_inflation_linked: false,
      withholding_percent: null,
      start_milestone_id: null,
      end_milestone_id: null,
      start_month: null,
      end_month: null,
      tax_category: "employment" as const,
      is_social_security: false,
      is_earned_income: true,
      is_self_employed: false,
      owner: "self" as const,
    };
    render(
      <ExpenseForm
        milestones={[]}
        incomeStreams={[income]}
        onSubmit={handleSubmit}
        onCancel={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "401(k)" } });
    fireEvent.click(screen.getByLabelText("Payroll Deduction"));
    fireEvent.change(screen.getByRole("combobox", { name: /Deduct from income/ }), {
      target: { value: "salary" },
    });
    fireEvent.click(screen.getByLabelText("After-tax"));
    expect(screen.getByLabelText("Federal income tax")).not.toBeChecked();
    fireEvent.click(screen.getByText("Add Expense"));
    expect(handleSubmit.mock.calls[0][0]).not.toHaveProperty("payroll_tax_elections");
  });

  it("explains saved month-only overrides instead of promising half-year expenses", () => {
    render(
      <ExpenseForm
        initial={makeExpense({
          id: "e1",
          plan_id: "p1",
          name: "Rent",
          annual_amount: 24000,
          start_milestone_id: null,
          end_milestone_id: null,
          inflation_linked: true,
          is_payroll_deduction: false,
          tied_income_id: null,
          specific_funding_source_id: null,
          start_month: 1,
          end_month: 6,
          category: null,
        })}
        milestones={[]}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );

    expect(screen.getByText(/Requires a Start Milestone/)).toBeInTheDocument();
    expect(screen.getByText(/Requires an End Milestone/)).toBeInTheDocument();
    expect(screen.queryByText(/\$12,000/)).not.toBeInTheDocument();
  });

  it("defaults category to essential for new expenses", () => {
    const handleSubmit = vi.fn();
    render(<ExpenseForm milestones={[]} onSubmit={handleSubmit} onCancel={() => {}} />);

    const essentialRadio = screen.getByLabelText("Essential") as HTMLInputElement;
    const discretionaryRadio = screen.getByLabelText("Discretionary") as HTMLInputElement;

    expect(essentialRadio.checked).toBe(true);
    expect(discretionaryRadio.checked).toBe(false);

    // Submit and verify category value
    const textInputs = screen.getAllByRole("textbox");
    fireEvent.change(textInputs[0], { target: { value: "Rent" } });
    fireEvent.click(screen.getByText("Add Expense"));

    expect(handleSubmit).toHaveBeenCalledWith(expect.objectContaining({ category: "essential" }));
  });

  it("reflects initial category when editing", () => {
    render(
      <ExpenseForm
        initial={makeExpense({
          id: "e1",
          plan_id: "p1",
          name: "Travel",
          annual_amount: 5000,
          start_milestone_id: null,
          end_milestone_id: null,
          inflation_linked: true,
          is_payroll_deduction: false,
          tied_income_id: null,
          specific_funding_source_id: null,
          start_month: null,
          end_month: null,
          category: "discretionary",
        })}
        milestones={[]}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );

    const essentialRadio = screen.getByLabelText("Essential") as HTMLInputElement;
    const discretionaryRadio = screen.getByLabelText("Discretionary") as HTMLInputElement;

    expect(essentialRadio.checked).toBe(false);
    expect(discretionaryRadio.checked).toBe(true);
  });

  it("submits selected category when toggled", () => {
    const handleSubmit = vi.fn();
    render(<ExpenseForm milestones={[]} onSubmit={handleSubmit} onCancel={() => {}} />);

    // Toggle to discretionary
    fireEvent.click(screen.getByLabelText("Discretionary"));

    const textInputs = screen.getAllByRole("textbox");
    fireEvent.change(textInputs[0], { target: { value: "Dining" } });
    fireEvent.click(screen.getByText("Add Expense"));

    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ category: "discretionary" }),
    );
  });

  it("does not show ProRateDisplay when months are null", () => {
    const { container } = render(
      <ExpenseForm milestones={[]} onSubmit={() => {}} onCancel={() => {}} />,
    );

    // No pro-rate text should appear
    expect(container.textContent).not.toMatch(/annual/);
  });

  it("submits custom growth, cap, recurrence and a specific funding source", () => {
    const handleSubmit = vi.fn();
    const accounts = [
      {
        id: "a1",
        user_id: "u",
        name: "Brokerage",
        account_type: "taxable_brokerage",
        balance: 1000,
        owner: "self",
        cost_basis: null,
        expected_return: null,
        created_at: "",
        updated_at: "",
      },
    ] as never;
    render(
      <ExpenseForm
        milestones={[]}
        accounts={accounts}
        onSubmit={handleSubmit}
        onCancel={() => {}}
      />,
    );
    fireEvent.change(screen.getAllByRole("textbox")[0], { target: { value: "Car" } });
    fireEvent.change(screen.getByLabelText("Amount growth"), { target: { value: "custom" } });
    fireEvent.change(screen.getByLabelText(/Growth rate/), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText(/Growth cap/), { target: { value: "40000" } });
    fireEvent.click(screen.getByLabelText(/Cap rises with inflation/));
    fireEvent.click(screen.getByLabelText(/Repeats every few years/));
    fireEvent.change(screen.getByLabelText(/Repeat every/), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText(/Change per occurrence/), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText(/Fund from a specific account/), {
      target: { value: "a1" },
    });
    fireEvent.click(screen.getByText("Add Expense"));
    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        inflation_linked: false,
        growth_rate: 5,
        growth_cap: 40000,
        growth_cap_inflation_linked: true,
        recurrence_years: 7,
        recurrence_growth_rate: 10,
        specific_funding_source_id: "a1",
      }),
    );
  });

  it("submits an ordered list of funding accounts and allows reordering", () => {
    const handleSubmit = vi.fn();
    const accounts = [
      {
        id: "a1",
        user_id: "u",
        name: "Checking",
        account_type: "checking",
        balance: 6000,
        owner: "self",
        cost_basis: null,
        expected_return: null,
        created_at: "",
        updated_at: "",
      },
      {
        id: "a2",
        user_id: "u",
        name: "Savings",
        account_type: "savings",
        balance: 10000,
        owner: "self",
        cost_basis: null,
        expected_return: null,
        created_at: "",
        updated_at: "",
      },
    ] as never;
    render(
      <ExpenseForm
        milestones={[]}
        accounts={accounts}
        onSubmit={handleSubmit}
        onCancel={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Living" } });
    const funding = screen.getByLabelText("Fund from a specific account");
    fireEvent.change(funding, { target: { value: "a1" } });
    fireEvent.change(funding, { target: { value: "a2" } });
    fireEvent.click(screen.getByRole("button", { name: "Move Savings up" }));
    fireEvent.click(screen.getByText("Add Expense"));
    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        specific_funding_source_id: "a2",
        specific_funding_source_ids: ["a2", "a1"],
      }),
    );
  });

  it("keeps saved growth and recurrence when editing and blocks payroll plus specific funding", () => {
    const handleSubmit = vi.fn();
    const initial = makeExpense({
      id: "e1",
      plan_id: "p1",
      name: "Roof",
      annual_amount: 20000,
      start_milestone_id: null,
      end_milestone_id: null,
      inflation_linked: false,
      growth_rate: 2.5,
      growth_cap: null,
      growth_cap_inflation_linked: false,
      recurrence_years: 15,
      recurrence_growth_rate: 5,
      is_payroll_deduction: false,
      tied_income_id: null,
      specific_funding_source_id: "a1",
      start_month: null,
      end_month: null,
      category: "essential",
    });
    render(
      <ExpenseForm initial={initial} milestones={[]} onSubmit={handleSubmit} onCancel={() => {}} />,
    );
    expect(screen.getByLabelText("Amount growth")).toHaveValue("custom");
    expect(screen.getByLabelText(/Repeat every/)).toHaveValue(15);
    fireEvent.click(screen.getByText("Update Expense"));
    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        growth_rate: 2.5,
        recurrence_years: 15,
        recurrence_growth_rate: 5,
        specific_funding_source_id: "a1",
        inflation_linked: false,
      }),
    );
    fireEvent.click(screen.getByLabelText("Payroll Deduction"));
    fireEvent.click(screen.getByText("Update Expense"));
    expect(screen.getByRole("alert")).toHaveTextContent("payroll deduction");
    expect(handleSubmit).toHaveBeenCalledTimes(1);
  });

  it("sends fixed nominal amounts as not inflation-linked with no growth", () => {
    const handleSubmit = vi.fn();
    render(<ExpenseForm milestones={[]} onSubmit={handleSubmit} onCancel={() => {}} />);
    fireEvent.change(screen.getAllByRole("textbox")[0], { target: { value: "Mortgage" } });
    fireEvent.change(screen.getByLabelText("Amount growth"), { target: { value: "fixed" } });
    fireEvent.click(screen.getByText("Add Expense"));
    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        inflation_linked: false,
        growth_rate: null,
        recurrence_years: null,
      }),
    );
  });
});

it("annualizes monthly entry without opening Advanced and keeps switching units lossless", () => {
  const submit = vi.fn();
  render(<ExpenseForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Rent" } });
  fireEvent.change(screen.getByLabelText("Monthly amount ($)"), { target: { value: "2000" } });
  expect(
    screen.getByText("Advanced: growth, funding and timing").closest("details"),
  ).not.toHaveAttribute("open");
  fireEvent.click(screen.getByText("Add Expense"));
  expect(submit).toHaveBeenLastCalledWith(
    expect.objectContaining({
      annual_amount: 24000,
      inflation_linked: true,
      start_milestone_id: null,
      end_milestone_id: null,
    }),
  );
  fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "annual" } });
  expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("24,000");
  fireEvent.change(screen.getByLabelText("Annual amount ($)"), { target: { value: "7123.45" } });
  fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "monthly" } });
  fireEvent.click(screen.getByText("Add Expense"));
  expect(submit.mock.calls.at(-1)![0].annual_amount).toBeCloseTo(7123.45, 8);
});

describe("ExpenseForm saved amount unit", () => {
  const saved = (amount_frequency?: Expense["amount_frequency"]): Expense => ({
    id: "e1",
    plan_id: "p1",
    name: "Groceries",
    annual_amount: 5200,
    start_milestone_id: null,
    end_milestone_id: null,
    inflation_linked: true,
    growth_rate: null,
    growth_cap: null,
    growth_cap_inflation_linked: false,
    recurrence_years: null,
    recurrence_growth_rate: 0,
    is_payroll_deduction: false,
    payroll_tax_treatment: "pre_tax",
    tied_income_id: null,
    specific_funding_source_id: null,
    specific_funding_source_ids: null,
    start_month: null,
    end_month: null,
    category: "essential",
    ...(amount_frequency === undefined ? {} : { amount_frequency }),
  });

  it("defaults a new expense to monthly and submits the unit", () => {
    const submit = vi.fn();
    render(<ExpenseForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    expect(screen.getByLabelText("Amount frequency")).toHaveValue("monthly");
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Rent" } });
    fireEvent.change(screen.getByLabelText("Monthly amount ($)"), { target: { value: "2000" } });
    expect(screen.getByText(/^\$2,000\/month · increases with inflation/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Add Expense"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ annual_amount: 24000, amount_frequency: "monthly" }),
    );
  });

  it("reopens in the saved unit, keeps the amount through toggles and names it in the preview", () => {
    const submit = vi.fn();
    render(
      <ExpenseForm
        initial={saved("weekly")}
        milestones={[]}
        onSubmit={submit}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByLabelText("Amount frequency")).toHaveValue("weekly");
    expect(screen.getByLabelText("Weekly amount ($)")).toHaveValue("100");
    expect(screen.getByText(/^\$100\/week ·/)).toBeInTheDocument();
    for (const unit of ["monthly", "biweekly", "annual", "quarterly", "weekly"]) {
      fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: unit } });
    }
    fireEvent.click(screen.getByText("Update Expense"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ annual_amount: 5200, amount_frequency: "weekly" }),
    );
    fireEvent.change(screen.getByLabelText("Amount frequency"), {
      target: { value: "semimonthly" },
    });
    fireEvent.change(screen.getByLabelText("Semimonthly amount ($)"), { target: { value: "250" } });
    expect(screen.getByText(/^\$250 twice a month ·/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "biweekly" } });
    expect(screen.getByLabelText("Biweekly amount ($)")).toHaveValue("230.77");
    expect(screen.getByText(/^\$230\.77 every 2 weeks ·/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Update Expense"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ annual_amount: 6000, amount_frequency: "biweekly" }),
    );
  });

  it.each([null, undefined])(
    "opens a legacy %s expense as annual and leaves its unit unset unless one is chosen",
    (legacy) => {
      const submit = vi.fn();
      render(
        <ExpenseForm
          initial={saved(legacy)}
          milestones={[]}
          onSubmit={submit}
          onCancel={() => {}}
        />,
      );
      expect(screen.getByLabelText("Amount frequency")).toHaveValue("annual");
      expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("5,200");
      fireEvent.click(screen.getByText("Update Expense"));
      expect(submit.mock.calls.at(-1)![0]).not.toHaveProperty("amount_frequency");
      fireEvent.change(screen.getByLabelText("Amount frequency"), {
        target: { value: "quarterly" },
      });
      expect(screen.getByLabelText("Quarterly amount ($)")).toHaveValue("1,300");
      fireEvent.click(screen.getByText("Update Expense"));
      expect(submit).toHaveBeenLastCalledWith(
        expect.objectContaining({ annual_amount: 5200, amount_frequency: "quarterly" }),
      );
    },
  );
});

describe("ExpenseForm discretionary share", () => {
  const saved = (overrides: Partial<Expense> = {}): Expense => ({
    id: "e1",
    plan_id: "p1",
    name: "Groceries",
    annual_amount: 9000,
    amount_frequency: "annual",
    start_milestone_id: null,
    end_milestone_id: null,
    inflation_linked: true,
    growth_rate: null,
    growth_cap: null,
    growth_cap_inflation_linked: false,
    recurrence_years: null,
    recurrence_growth_rate: 0,
    is_payroll_deduction: false,
    payroll_tax_treatment: "pre_tax",
    tied_income_id: null,
    specific_funding_source_id: null,
    specific_funding_source_ids: null,
    start_month: null,
    end_month: null,
    category: "essential",
    ...overrides,
  });
  const radio = (label: string) => screen.getByLabelText(label) as HTMLInputElement;

  it("keeps presets category-only so new expenses send no percent", () => {
    const submit = vi.fn();
    render(<ExpenseForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    expect(radio("Essential").checked).toBe(true);
    expect(
      screen.getByText("Always paid in full; flexible spending never cuts it."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Discretionary share (%)")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Travel" } });
    fireEvent.click(radio("Discretionary"));
    expect(
      screen.getByText("Flexible spending can cut all of it after weak market years."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText("Add Expense"));
    const payload = submit.mock.calls.at(-1)![0];
    expect(payload.category).toBe("discretionary");
    expect(payload).not.toHaveProperty("discretionary_percent");
  });

  it("submits a custom percent with the category it implies", () => {
    const submit = vi.fn();
    render(<ExpenseForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Groceries" } });
    fireEvent.click(radio("Custom"));
    const percent = screen.getByLabelText("Discretionary share (%)");
    const slider = screen.getByLabelText("Discretionary share slider");
    expect(percent).toHaveValue(50);
    fireEvent.change(percent, { target: { value: "30" } });
    expect(slider).toHaveValue("30");
    expect(
      screen.getByText(/can cut 30% of it after weak market years; the other 70% is always paid/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText("Add Expense"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ discretionary_percent: 30, category: "essential" }),
    );
    fireEvent.change(slider, { target: { value: "65" } });
    expect(percent).toHaveValue(65);
    fireEvent.click(screen.getByText("Add Expense"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ discretionary_percent: 65, category: "discretionary" }),
    );
    fireEvent.change(percent, { target: { value: "12.5" } });
    expect(slider).toHaveValue("13");
    fireEvent.click(screen.getByText("Add Expense"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ discretionary_percent: 12.5, category: "essential" }),
    );
  });

  it("starts a new expense from a spending category without saving the category", () => {
    const submit = vi.fn();
    render(
      <ExpenseForm
        milestones={[]}
        existingNames={["Travel", "Housing"]}
        onSubmit={submit}
        onCancel={() => {}}
      />,
    );
    const spending = screen.getByLabelText("Spending category");
    fireEvent.change(spending, { target: { value: "travel" } });
    expect(screen.getByLabelText("Name")).toHaveValue("Travel 2");
    expect(radio("Discretionary").checked).toBe(true);
    // An untouched name follows the category; the share follows every choice.
    fireEvent.change(spending, { target: { value: "college" } });
    expect(screen.getByLabelText("Name")).toHaveValue("College");
    expect(radio("Essential").checked).toBe(true);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Europe trip" } });
    fireEvent.change(spending, { target: { value: "travel" } });
    expect(screen.getByLabelText("Name")).toHaveValue("Europe trip");
    expect(radio("Discretionary").checked).toBe(true);
    fireEvent.click(screen.getByText("Add Expense"));
    const payload = submit.mock.calls.at(-1)![0];
    expect(payload).toMatchObject({ name: "Europe trip", category: "discretionary" });
    expect(Object.values(payload)).not.toContain("travel");
  });

  it("offers spending categories only for a new expense", () => {
    render(
      <ExpenseForm
        initial={makeExpense({ id: "e1", plan_id: "p1", name: "Rent" })}
        milestones={[]}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.queryByLabelText("Spending category")).not.toBeInTheDocument();
  });

  it.each(["", "101", "-5", "abc"])(
    "rejects a custom percent of %j without submitting",
    (value) => {
      const submit = vi.fn();
      render(<ExpenseForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
      fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Groceries" } });
      fireEvent.click(radio("Custom"));
      const percent = screen.getByLabelText("Discretionary share (%)");
      fireEvent.change(percent, { target: { value } });
      fireEvent.click(screen.getByText("Add Expense"));
      // The browser's min/max check blocks out-of-range numbers; the form rejects the rest.
      if (value === "101" || value === "-5") expect(percent).toBeInvalid();
      else
        expect(screen.getByRole("alert")).toHaveTextContent(
          "Discretionary share must be a percent between 0 and 100.",
        );
      expect(submit).not.toHaveBeenCalled();
    },
  );

  it("reopens a saved split as Custom and a saved 0% or 100% as its preset", () => {
    const { unmount } = render(
      <ExpenseForm
        initial={saved({ discretionary_percent: 40 })}
        milestones={[]}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(radio("Custom").checked).toBe(true);
    expect(screen.getByLabelText("Discretionary share (%)")).toHaveValue(40);
    unmount();
    const submit = vi.fn();
    render(
      <ExpenseForm
        initial={saved({ discretionary_percent: 100, category: "discretionary" })}
        milestones={[]}
        onSubmit={submit}
        onCancel={() => {}}
      />,
    );
    expect(radio("Discretionary").checked).toBe(true);
    fireEvent.click(screen.getByText("Update Expense"));
    // An untouched saved 100% is submitted unchanged rather than cleared.
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ discretionary_percent: 100, category: "discretionary" }),
    );
  });

  it("clears a saved split when a preset is chosen", () => {
    const submit = vi.fn();
    render(
      <ExpenseForm
        initial={saved({ discretionary_percent: 40 })}
        milestones={[]}
        onSubmit={submit}
        onCancel={() => {}}
      />,
    );
    fireEvent.click(radio("Discretionary"));
    fireEvent.click(screen.getByText("Update Expense"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ discretionary_percent: null, category: "discretionary" }),
    );
  });

  it("leaves an older record's payload without the field", () => {
    const submit = vi.fn();
    render(<ExpenseForm initial={saved()} milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.click(screen.getByText("Update Expense"));
    expect(submit.mock.calls.at(-1)![0]).not.toHaveProperty("discretionary_percent");
  });
});
