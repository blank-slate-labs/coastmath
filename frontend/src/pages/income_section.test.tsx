import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BuilderModeContext, IncomeSection } from "./plan_setup";
import { usePlanStore } from "@/stores/plan_store";
import { useSetupFlow } from "@/stores/setup_flow_store";
import type { Income } from "@/types/plan";
import { makePlan } from "@/test_support/plan_builder";

const income: Income = {
  id: "income",
  plan_id: "plan",
  name: "Consulting",
  annual_amount: 12000,
  owner: "self",
  growth_rate: 0,
  growth_cap: null,
  growth_cap_inflation_linked: false,
  withholding_percent: null,
  start_milestone_id: null,
  end_milestone_id: null,
  start_month: null,
  end_month: null,
  is_social_security: false,
  is_earned_income: true,
  is_self_employed: true,
  is_active: true,
  claiming_age: null,
};

const updateIncome = vi.fn().mockResolvedValue(undefined);

beforeEach(() => {
  updateIncome.mockClear();
  usePlanStore.setState({
    plan: makePlan({ id: "plan", birth_year: 1990, income_streams: [income] }),
    simulation: null,
    updateIncome,
  });
});

describe("income edits preserve separately saved fields", () => {
  it("sends only the changed amount from a stale form and supports explicit null clears", async () => {
    render(
      <BuilderModeContext.Provider value="sheet">
        <IncomeSection />
      </BuilderModeContext.Provider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const form = within(screen.getByRole("dialog", { name: "Edit Income" }));
    expect(form.getByText(/Enter net business profit/)).toBeInTheDocument();
    // Simulate a newer saved name reaching the store while this form is open.
    act(() =>
      usePlanStore.setState((s) => ({
        plan: { ...s.plan!, income_streams: [{ ...income, name: "Renamed consulting" }] },
      })),
    );
    fireEvent.change(form.getByLabelText("Annual amount ($)"), { target: { value: "24000" } });
    fireEvent.click(form.getByRole("button", { name: "Save income" }));
    expect(updateIncome).toHaveBeenLastCalledWith("plan", "income", { annual_amount: 24000 });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText(/Growth rate/), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save income" }));
    expect(updateIncome).toHaveBeenLastCalledWith("plan", "income", { growth_rate: null });
  });

  it("does not write an unchanged stale form", () => {
    render(
      <BuilderModeContext.Provider value="sheet">
        <IncomeSection />
      </BuilderModeContext.Provider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Save income" }));
    expect(updateIncome).not.toHaveBeenCalled();
  });
});

describe("include in projection", () => {
  it("excludes an income without deleting it and marks it in the list", async () => {
    render(
      <BuilderModeContext.Provider value="sheet">
        <IncomeSection />
      </BuilderModeContext.Provider>,
    );
    expect(screen.queryByText("Excluded")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const form = within(screen.getByRole("dialog", { name: "Edit Income" }));
    const include = form.getByRole("checkbox", { name: "Include in projection" });
    expect(include).toBeChecked();
    fireEvent.click(include);
    fireEvent.click(form.getByRole("button", { name: "Save income" }));
    expect(updateIncome).toHaveBeenLastCalledWith("plan", "income", { is_active: false });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    act(() =>
      usePlanStore.setState((s) => ({
        plan: { ...s.plan!, income_streams: [{ ...income, is_active: false }] },
      })),
    );
    expect(screen.getByText("Excluded")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const reopened = within(screen.getByRole("dialog", { name: "Edit Income" }));
    expect(reopened.getByRole("checkbox", { name: "Include in projection" })).not.toBeChecked();
    expect(reopened.getByRole("checkbox", { name: "Include in projection" })).toBeVisible();
  });
});

describe("new-plan setup hand-off", () => {
  it("opens Add income once for the plan setup asked about", () => {
    act(() => useSetupFlow.getState().requestAddIncome("other-plan"));
    const { unmount } = render(
      <BuilderModeContext.Provider value="sheet">
        <IncomeSection />
      </BuilderModeContext.Provider>,
    );
    expect(screen.queryByRole("dialog", { name: "Add Income" })).not.toBeInTheDocument();
    unmount();

    act(() => useSetupFlow.getState().requestAddIncome("plan"));
    const second = render(
      <BuilderModeContext.Provider value="sheet">
        <IncomeSection />
      </BuilderModeContext.Provider>,
    );
    expect(screen.getByRole("dialog", { name: "Add Income" })).toBeInTheDocument();
    expect(useSetupFlow.getState().addIncomeFor).toBeNull();
    second.unmount();

    render(
      <BuilderModeContext.Provider value="sheet">
        <IncomeSection />
      </BuilderModeContext.Provider>,
    );
    expect(screen.queryByRole("dialog", { name: "Add Income" })).not.toBeInTheDocument();
  });
});

describe("income amount units", () => {
  it("shows rows in their saved unit and sends only a changed unit", async () => {
    usePlanStore.setState((s) => ({
      plan: makePlan({
        ...s.plan!,
        income_streams: [
          { ...income, amount_frequency: "monthly" },
          { ...income, id: "legacy", name: "Legacy", annual_amount: 31200 },
        ],
      }),
    }));
    render(
      <BuilderModeContext.Provider value="sheet">
        <IncomeSection />
      </BuilderModeContext.Provider>,
    );
    expect(screen.getByText(/^\$1\.0K\/mo \(0% growth\)/)).toBeInTheDocument();
    expect(screen.getByText(/^\$31\.2K\/yr \(0% growth\)/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
    const form = within(screen.getByRole("dialog", { name: "Edit Income" }));
    expect(form.getByLabelText("Monthly amount ($)")).toHaveValue("1,000");
    fireEvent.change(form.getByLabelText("Amount frequency"), { target: { value: "biweekly" } });
    fireEvent.click(form.getByRole("button", { name: "Save income" }));
    expect(updateIncome).toHaveBeenLastCalledWith("plan", "income", {
      amount_frequency: "biweekly",
    });
  });
});

describe("income event fields preserve separately saved settings", () => {
  it("does not overwrite newly saved event settings from a legacy stale form", () => {
    render(
      <BuilderModeContext.Provider value="sheet">
        <IncomeSection />
      </BuilderModeContext.Provider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    act(() =>
      usePlanStore.setState((s) => ({
        plan: {
          ...s.plan!,
          income_streams: [
            {
              ...income,
              frequency: "once",
              recurrence_years: 3,
              tax_category: "qualified_pension",
              is_earned_income: false,
              is_self_employed: false,
              pension_formula: {
                kind: "flat",
                flat_annual_amount: 25000,
                benefit_percent_per_year: 0,
              },
            },
          ],
        },
      })),
    );
    fireEvent.change(screen.getByLabelText("Annual amount ($)"), { target: { value: "24000" } });
    fireEvent.click(screen.getByRole("button", { name: "Save income" }));
    expect(updateIncome).toHaveBeenLastCalledWith("plan", "income", { annual_amount: 24000 });
  });

  it("sends an explicit recurrence clear without resending unchanged event defaults", () => {
    usePlanStore.setState((s) => ({
      plan: {
        ...s.plan!,
        income_streams: [{ ...income, frequency: "recurring", recurrence_years: 3 }],
      },
    }));
    render(
      <BuilderModeContext.Provider value="sheet">
        <IncomeSection />
      </BuilderModeContext.Provider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Repeat every (years)"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save income" }));
    expect(updateIncome).toHaveBeenLastCalledWith("plan", "income", { recurrence_years: null });
  });

  it("compares pension formulas by their active fields and defaults rather than object identity", () => {
    const pension: Income = {
      ...income,
      name: "Pension",
      annual_amount: 12000,
      is_earned_income: false,
      is_self_employed: false,
      tax_category: "qualified_pension",
      pension_formula: {
        kind: "career_average",
        linked_income_id: "salary",
        benefit_percent_per_year: 2,
      },
    };
    usePlanStore.setState((s) => ({
      plan: { ...s.plan!, income_streams: [pension, { ...income, id: "salary", name: "Salary" }] },
    }));
    render(
      <BuilderModeContext.Provider value="sheet">
        <IncomeSection />
      </BuilderModeContext.Provider>,
    );
    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Save income" }));
    expect(updateIncome).not.toHaveBeenCalled();
  });
});

describe("growth schedule edits", () => {
  const scheduled: Income = {
    ...income,
    growth_schedule: [
      { start_year: 2027, end_year: 2028, kind: "percent", value: 3, dollars: null },
      { start_year: 2029, end_year: null, kind: "set_amount", value: 120000, dollars: "nominal" },
    ],
  };

  beforeEach(() => {
    usePlanStore.setState((s) => ({ plan: { ...s.plan!, income_streams: [scheduled] } }));
  });

  it("does not write an unchanged schedule and sends only the edited schedule", async () => {
    render(
      <BuilderModeContext.Provider value="sheet">
        <IncomeSection />
      </BuilderModeContext.Provider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Save income" }));
    expect(updateIncome).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const segment = within(screen.getByRole("group", { name: "Growth segment 1" }));
    fireEvent.change(segment.getByLabelText("Change (% per year)"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Save income" }));
    expect(updateIncome).toHaveBeenLastCalledWith("plan", "income", {
      growth_schedule: [
        { ...scheduled.growth_schedule![0], value: 4 },
        scheduled.growth_schedule![1],
      ],
    });
  });

  it("clears the schedule with an explicit null", () => {
    render(
      <BuilderModeContext.Provider value="sheet">
        <IncomeSection />
      </BuilderModeContext.Provider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove growth segment 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove growth segment 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Save income" }));
    expect(updateIncome).toHaveBeenLastCalledWith("plan", "income", { growth_schedule: null });
  });
});

it("marks a partner's income row with the Partner label, never the owner value", () => {
  usePlanStore.setState({
    plan: makePlan({
      id: "plan",
      birth_year: 1990,
      spouse: { name: "Sam", birth_year: 1991 },
      income_streams: [{ ...income, owner: "spouse" }],
    }),
  });
  const { container } = render(
    <BuilderModeContext.Provider value="sheet">
      <IncomeSection />
    </BuilderModeContext.Provider>,
  );
  expect(container).toHaveTextContent("· Partner");
  expect(container.textContent).not.toMatch(/spouse/i);
});
