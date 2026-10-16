import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GoalsIntakeForm } from "./goals_intake_form";
import {
  accountSlots,
  partnerRetirement,
  socialSecurityIncome,
  withSurplusRule,
} from "./goals_setup";
import { CreatePlanForm } from "@/pages/plan_setup";
import { setStorageAdapter, usePlanStore } from "@/stores/plan_store";
import { useSetupFlow } from "@/stores/setup_flow_store";
import type { CashFlowPriority } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const retirement = {
  id: "m1",
  plan_id: "p1",
  name: "Retirement",
  trigger_type: "age" as const,
  trigger_value: 65,
  trigger_date: null,
  metric: null,
  expense_multiple: null,
  relative_to_id: null,
  offset_years: 0,
  sort_order: 0,
};
const plan = makePlan({
  id: "p1",
  name: "My Plan",
  birth_year: 1990,
  milestones: [retirement],
  priorities_revision: 3,
});
const withPartner = makePlan({ ...plan, spouse: { name: "Sam", birth_year: 1988 } });

const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

let nextId = 0;
const withId =
  (prefix: string) =>
  (...args: unknown[]) => {
    const data = args.find((arg) => arg && typeof arg === "object") as Record<string, unknown>;
    return Promise.resolve({ ...data, id: `${prefix}${++nextId}` });
  };

beforeEach(() => {
  // Ages are counted from this calendar year: the 1990 owner is 36.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 1));
  nextId = 0;
  adapter.createPlan.mockReset().mockResolvedValue(plan);
  adapter.fetchPlan.mockReset().mockResolvedValue(plan);
  adapter.submitPlanIntake.mockReset().mockResolvedValue(plan);
  adapter.runSimulation.mockReset().mockResolvedValue({ metadata: {}, yearly_snapshots: [] });
  adapter.createMilestone.mockReset().mockImplementation(withId("milestone-"));
  adapter.updateMilestone
    .mockReset()
    .mockImplementation((_plan: string, id: string, data: object) =>
      Promise.resolve({ ...data, id }),
    );
  adapter.createIncome.mockReset().mockImplementation(withId("income-"));
  adapter.updateIncome
    .mockReset()
    .mockImplementation((_plan: string, id: string, data: object) =>
      Promise.resolve({ ...data, id }),
    );
  adapter.createExpense.mockReset().mockImplementation(withId("expense-"));
  adapter.updateExpense
    .mockReset()
    .mockImplementation((_plan: string, id: string, data: object) =>
      Promise.resolve({ ...data, id }),
    );
  adapter.createAccount.mockReset().mockImplementation(withId("account-"));
  adapter.updateAccount
    .mockReset()
    .mockImplementation((id: string, data: object) => Promise.resolve({ ...data, id }));
  adapter.listAccounts.mockReset().mockResolvedValue([]);
  adapter.updatePriorities.mockReset().mockResolvedValue({ items: [], revision: 4 });
  setStorageAdapter(adapter);
  usePlanStore.setState({
    plan: null,
    plans: [],
    error: null,
    simulation: null,
    isSimulating: false,
    accountsRevision: 0,
  });
  useSetupFlow.setState({ addIncomeFor: null });
});

afterEach(() => {
  vi.useRealTimers();
});

const save = () => fireEvent.click(screen.getByRole("button", { name: "Save goals" }));
const change = (label: string | RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe("create form", () => {
  it("opens the goals after an empty plan is created, and Skip lands on the plan without saving", async () => {
    const onCreate = vi.fn();
    render(<CreatePlanForm onCreate={onCreate} />);
    // Birth year and state start blank and are required: nothing is created until both are answered.
    fireEvent.click(screen.getByRole("button", { name: "Create plan" }));
    expect(adapter.createPlan).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/^Birth year: Enter a number\.$/);
    expect(screen.getByLabelText("Birth year")).toHaveAttribute("aria-invalid", "true");
    change("Birth year", "1990");
    // The placeholder is not an answer: an untouched State blocks the plan.
    fireEvent.click(screen.getByRole("button", { name: "Create plan" }));
    expect(adapter.createPlan).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/^State: Choose one\.$/),
    );
    change("State", "__none");
    fireEvent.click(screen.getByRole("button", { name: "Create plan" }));

    expect(await screen.findByRole("heading", { name: "Goals" })).toBeVisible();
    expect(adapter.createPlan).toHaveBeenCalledWith({
      name: "My Plan",
      birth_year: 1990,
      filing_status: "single",
      retirement_milestone_age: 65,
    });
    expect(onCreate).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Retirement age")).toHaveValue(65);

    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(onCreate).toHaveBeenCalledWith();
    expect(adapter.submitPlanIntake).not.toHaveBeenCalled();
    expect(useSetupFlow.getState().addIncomeFor).toBeNull();
  });

  it("asks filing status, state and partner, defaulting a partner's return to joint", async () => {
    render(<CreatePlanForm onCreate={vi.fn()} />);
    const filing = screen.getByLabelText("Filing status");
    fireEvent.click(screen.getByLabelText("Planning with a partner"));
    expect(filing).toHaveValue("married_filing_jointly");
    expect(screen.getByRole("button", { name: "Create plan" })).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Planning with a partner"));
    expect(filing).toHaveValue("single");
    expect(screen.queryByLabelText("Partner birth year")).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Planning with a partner"));
    change("Birth year", "1990");
    change("Partner birth year", "1988");
    change("State", "CA");
    fireEvent.click(screen.getByRole("button", { name: "Create plan" }));
    await screen.findByRole("heading", { name: "Goals" });
    expect(adapter.createPlan).toHaveBeenCalledWith({
      name: "My Plan",
      birth_year: 1990,
      filing_status: "married_filing_jointly",
      state_code: "CA",
      spouse: { name: "Partner", birth_year: 1988 },
      retirement_milestone_age: 65,
    });
  });

  it("keeps a filing status picked by hand when a partner is added", async () => {
    render(<CreatePlanForm onCreate={vi.fn()} />);
    change("Filing status", "married_filing_separately");
    fireEvent.click(screen.getByLabelText("Planning with a partner"));
    expect(screen.getByLabelText("Filing status")).toHaveValue("married_filing_separately");
    change("Partner name", "Sam");
    change("Birth year", "1990");
    change("Partner birth year", "1988");
    change("State", "CA");
    fireEvent.click(screen.getByRole("button", { name: "Create plan" }));
    await screen.findByRole("heading", { name: "Goals" });
    expect(adapter.createPlan).toHaveBeenCalledWith(
      expect.objectContaining({
        filing_status: "married_filing_separately",
        spouse: { name: "Sam", birth_year: 1988 },
      }),
    );
  });
});

describe("goals", () => {
  it("submits only the answered goals, then opens Add income for the salary", async () => {
    const onDone = vi.fn();
    render(<GoalsIntakeForm plan={plan} onDone={onDone} />);
    change("Retirement age", "60");
    change(/Retirement spending/, "80000");
    change(/^Travel \(/, "15000");
    change("Travel until age", "80");
    save();

    await waitFor(() => expect(onDone).toHaveBeenCalledWith("income"));
    expect(adapter.submitPlanIntake).toHaveBeenCalledWith("p1", {
      retirement_age: 60,
      retirement_spending: 80000,
      travel_budget: 15000,
      travel_until_age: 80,
    });
    expect(useSetupFlow.getState().addIncomeFor).toBe("p1");
    expect(adapter.fetchPlan).toHaveBeenCalledWith("p1");
  });

  it("keeps the answers when the save fails", async () => {
    adapter.submitPlanIntake.mockRejectedValueOnce(new Error("Enter a retirement age."));
    const onDone = vi.fn();
    render(<GoalsIntakeForm plan={plan} onDone={onDone} />);
    change(/Charitable giving/, "5000");
    save();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Not saved: Goals. Save again to retry.Enter a retirement age.",
    );
    expect(screen.getByLabelText(/Charitable giving/)).toHaveValue("5,000");
    expect(onDone).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Skip" })).toBeEnabled();
  });

  it("finishes without a request when every answer is blank", async () => {
    const onDone = vi.fn();
    render(<GoalsIntakeForm plan={{ ...plan, milestones: [] }} onDone={onDone} />);
    expect(screen.getByLabelText("Retirement age")).toHaveValue(null);
    save();
    await waitFor(() => expect(onDone).toHaveBeenCalledWith("income"));
    expect(adapter.submitPlanIntake).not.toHaveBeenCalled();
    expect(adapter.fetchPlan).not.toHaveBeenCalled();
  });

  it("asks what to leave heirs in today's dollars and shows a saved amount", async () => {
    const onDone = vi.fn();
    const { unmount } = render(
      <GoalsIntakeForm plan={{ ...plan, milestones: [] }} onDone={onDone} />,
    );
    change(/Leave to heirs/, "1000000");
    save();
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(adapter.submitPlanIntake).toHaveBeenCalledWith("p1", { legacy_target: 1000000 });
    unmount();

    render(
      <GoalsIntakeForm
        plan={makePlan({ ...plan, estate_settings: { legacy_target: 250000 } })}
        onDone={onDone}
      />,
    );
    expect(screen.getByLabelText("Leave to heirs ($, today's dollars)")).toHaveValue("250,000");
  });

  it("refuses a retirement age already reached, without writing", async () => {
    const onDone = vi.fn();
    render(<GoalsIntakeForm plan={plan} onDone={onDone} />);
    change("Retirement age", "36");
    save();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Choose an age after your current age, or mark that you've already stopped working.",
    );
    expect(adapter.submitPlanIntake).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
  });

  it("retires at independence by updating the seeded Retirement milestone before the goals", async () => {
    const onDone = vi.fn();
    render(<GoalsIntakeForm plan={plan} onDone={onDone} />);
    fireEvent.click(screen.getByLabelText("When I can afford to"));
    expect(screen.queryByLabelText("Retirement age")).not.toBeInTheDocument();
    change(/Retirement spending/, "70000");
    save();

    await waitFor(() => expect(onDone).toHaveBeenCalledWith("income"));
    expect(adapter.updateMilestone).toHaveBeenCalledWith("p1", "m1", {
      trigger_type: "expense_multiple",
      expense_multiple: 25,
      metric: "liquid_net_worth",
      trigger_value: null,
      trigger_date: null,
      relative_to_id: null,
      offset_years: 0,
    });
    expect(adapter.submitPlanIntake).toHaveBeenCalledWith("p1", { retirement_spending: 70000 });
    expect(adapter.updateMilestone.mock.invocationCallOrder[0]).toBeLessThan(
      adapter.submitPlanIntake.mock.invocationCallOrder[0],
    );
  });

  it("creates the independence Retirement milestone when the plan has none", async () => {
    render(<GoalsIntakeForm plan={{ ...plan, milestones: [] }} onDone={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("When I can afford to"));
    save();
    await waitFor(() =>
      expect(adapter.createMilestone).toHaveBeenCalledWith(
        "p1",
        expect.objectContaining({
          name: "Retirement",
          trigger_type: "expense_multiple",
          expense_multiple: 25,
          metric: "liquid_net_worth",
        }),
      ),
    );
    expect(adapter.submitPlanIntake).not.toHaveBeenCalled();
  });

  it("for someone already retired, retires now and records benefits instead of asking for a salary", async () => {
    const onDone = vi.fn();
    render(<GoalsIntakeForm plan={plan} onDone={onDone} />);
    fireEvent.click(screen.getByLabelText("I've already stopped working"));
    change("Social Security received ($/mo)", "2000");
    change("Pension or other retirement income ($/yr)", "12000");
    save();

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(onDone).toHaveBeenCalledWith(undefined);
    expect(useSetupFlow.getState().addIncomeFor).toBeNull();
    expect(adapter.submitPlanIntake).toHaveBeenCalledWith("p1", { retirement_age: 36 });
    expect(adapter.createIncome).toHaveBeenNthCalledWith(
      1,
      "p1",
      expect.objectContaining({
        name: "Social Security",
        annual_amount: 24000,
        amount_frequency: "monthly",
        owner: "self",
        is_social_security: true,
        claiming_age: 62,
        tax_category: "social_security",
      }),
    );
    expect(adapter.createIncome).toHaveBeenNthCalledWith(
      2,
      "p1",
      expect.objectContaining({
        name: "Pension",
        annual_amount: 12000,
        amount_frequency: "annual",
        owner: "self",
        is_social_security: false,
        is_earned_income: false,
        tax_category: "qualified_pension",
      }),
    );
  });

  it("asks the partner's retirement only with a partner, saved as Add milestone saves it", async () => {
    const { unmount } = render(<GoalsIntakeForm plan={plan} onDone={vi.fn()} />);
    expect(screen.queryByLabelText("Partner retirement age")).not.toBeInTheDocument();
    unmount();

    const onDone = vi.fn();
    render(<GoalsIntakeForm plan={withPartner} onDone={onDone} />);
    change("Partner retirement age", "62");
    save();
    await waitFor(() => expect(onDone).toHaveBeenCalledWith("income"));
    // The partner (born 1988) reaches 62 when the owner (born 1990) is 60.
    expect(adapter.createMilestone).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({
        name: "Partner retirement",
        trigger_type: "age",
        trigger_value: 60,
      }),
    );
  });

  it("records a retired partner's benefits under the partner", async () => {
    render(<GoalsIntakeForm plan={withPartner} onDone={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("My partner has already stopped working"));
    expect(screen.queryByLabelText("Partner retirement age")).not.toBeInTheDocument();
    change("Partner Social Security received ($/mo)", "1500");
    save();
    await waitFor(() =>
      expect(adapter.createIncome).toHaveBeenCalledWith(
        "p1",
        expect.objectContaining({
          name: "Partner Social Security",
          annual_amount: 18000,
          owner: "spouse",
          claiming_age: 62,
        }),
      ),
    );
    // The partner is 38 now: the milestone fires at the owner's 36.
    expect(adapter.createMilestone).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ name: "Partner retirement", trigger_value: 36 }),
    );
  });

  it("adds today's spending as living expenses that end at Retirement when retirement spending is given", async () => {
    const { unmount } = render(<GoalsIntakeForm plan={plan} onDone={vi.fn()} />);
    change("Monthly spending today ($/mo)", "5000");
    save();
    await waitFor(() =>
      expect(adapter.createExpense).toHaveBeenCalledWith("p1", {
        name: "Living expenses",
        annual_amount: 60000,
        amount_frequency: "monthly",
        category: "essential",
        inflation_linked: true,
        is_payroll_deduction: false,
        recurrence_growth_rate: 0,
        growth_cap_inflation_linked: false,
        end_milestone_id: null,
      }),
    );
    unmount();

    adapter.submitPlanIntake.mockResolvedValueOnce({
      ...plan,
      milestones: [{ ...retirement, id: "m-saved" }],
    });
    render(<GoalsIntakeForm plan={plan} onDone={vi.fn()} />);
    change("Monthly spending today ($/mo)", "5000");
    change(/Retirement spending/, "48000");
    save();
    await waitFor(() =>
      expect(adapter.createExpense).toHaveBeenLastCalledWith(
        "p1",
        expect.objectContaining({ end_milestone_id: "m-saved" }),
      ),
    );
  });
});

describe("opening balances and leftover income", () => {
  it("posts each entered balance in order, joint and per person with a partner", async () => {
    const onDone = vi.fn();
    render(<GoalsIntakeForm plan={withPartner} onDone={onDone} />);
    const balances = screen.getByText("Account balances").closest("details")!;
    fireEvent.change(within(balances).getByLabelText("Brokerage"), { target: { value: "50000" } });
    fireEvent.change(within(balances).getByLabelText("401(k)"), { target: { value: "120000" } });
    fireEvent.change(within(balances).getByLabelText("Partner's Roth IRA"), {
      target: { value: "0" },
    });
    save();

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(adapter.createAccount.mock.calls).toEqual([
      [
        { name: "Brokerage", account_type: "taxable_brokerage", balance: 50000, owner: "joint" },
        "p1",
      ],
      [{ name: "401(k)", account_type: "traditional_401k", balance: 120000, owner: "self" }, "p1"],
      [{ name: "Partner's Roth IRA", account_type: "roth_ira", balance: 0, owner: "spouse" }, "p1"],
    ]);
    expect(usePlanStore.getState().accountsRevision).toBe(1);
  });

  it("keeps the drafts on a partial failure, names what failed, and resends only that", async () => {
    adapter.createAccount
      .mockImplementationOnce(withId("account-"))
      .mockRejectedValueOnce(new Error("Create account “Roth IRA” was not saved."));
    const onDone = vi.fn();
    render(<GoalsIntakeForm plan={plan} onDone={onDone} />);
    change("Cash", "10000");
    change("Roth IRA", "30000");
    change("HSA", "4000");
    save();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Not saved: Roth IRA. Save again to retry.");
    expect(alert).toHaveTextContent("Create account “Roth IRA” was not saved.");
    expect(screen.getByLabelText("Roth IRA")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Roth IRA")).toHaveValue("30,000");
    expect(adapter.createAccount).toHaveBeenCalledTimes(3);
    expect(onDone).not.toHaveBeenCalled();

    change("Cash", "12000");
    save();
    await waitFor(() => expect(onDone).toHaveBeenCalledWith("income"));
    expect(adapter.createAccount).toHaveBeenCalledTimes(4);
    expect(adapter.createAccount).toHaveBeenLastCalledWith(
      { name: "Roth IRA", account_type: "roth_ira", balance: 30000, owner: "self" },
      "p1",
    );
    expect(adapter.updateAccount).toHaveBeenCalledWith("account-1", { balance: 12000 }, "p1");
  });

  it("adds a leftover-income rule to the latest rules with their revision", async () => {
    const existing = {
      id: "r1",
      plan_id: "p1",
      priority_rank: 1,
      priority_type: "contribution",
      target_account_id: "acct-cash",
      allocation_mode: "amount",
      allocation_value: 5000,
    } as unknown as CashFlowPriority;
    adapter.fetchPlan.mockResolvedValue({
      ...plan,
      priorities: [existing],
      priorities_revision: 7,
    });
    const onDone = vi.fn();
    render(<GoalsIntakeForm plan={plan} onDone={onDone} />);
    change("Brokerage", "25000");
    change("Leftover income goes to", "brokerage");
    save();

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(adapter.updatePriorities).toHaveBeenCalledWith(
      "p1",
      [
        {
          priority_rank: 1,
          priority_type: "contribution",
          target_account_id: "acct-cash",
          allocation_mode: "amount",
          allocation_value: 5000,
        },
        {
          priority_rank: 2,
          priority_type: "contribution",
          target_account_id: "account-1",
          allocation_mode: "remaining",
          allocation_value: null,
        },
      ],
      7,
    );
    expect(adapter.createAccount.mock.invocationCallOrder[0]).toBeLessThan(
      adapter.updatePriorities.mock.invocationCallOrder[0],
    );
  });

  it("uses an existing account, or a blank one, as the leftover destination", async () => {
    adapter.listAccounts.mockResolvedValueOnce([
      { id: "acct-savings", name: "Savings", account_type: "savings", owner: "self", balance: 100 },
    ]);
    const { unmount } = render(<GoalsIntakeForm plan={plan} onDone={vi.fn()} />);
    change("Leftover income goes to", "cash");
    save();
    await waitFor(() =>
      expect(adapter.updatePriorities).toHaveBeenCalledWith(
        "p1",
        [expect.objectContaining({ target_account_id: "acct-savings" })],
        3,
      ),
    );
    expect(adapter.createAccount).not.toHaveBeenCalled();
    unmount();

    render(<GoalsIntakeForm plan={plan} onDone={vi.fn()} />);
    change("Leftover income goes to", "brokerage");
    save();
    await waitFor(() =>
      expect(adapter.createAccount).toHaveBeenCalledWith(
        { name: "Brokerage", account_type: "taxable_brokerage", balance: 0, owner: "self" },
        "p1",
      ),
    );
  });

  it("surfaces an allocation conflict for review and never retries it", async () => {
    adapter.updatePriorities.mockRejectedValueOnce(
      Object.assign(new Error("conflicts with saved data"), { status: 409 }),
    );
    const onDone = vi.fn();
    render(<GoalsIntakeForm plan={plan} onDone={onDone} />);
    change("Brokerage", "25000");
    change("Leftover income goes to", "brokerage");
    save();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Leftover income was not saved: income allocation changed since this plan opened. Set it under Income allocation.",
    );
    expect(screen.getByLabelText("Leftover income goes to")).toHaveValue("");
    expect(onDone).not.toHaveBeenCalled();

    save();
    await waitFor(() => expect(onDone).toHaveBeenCalledWith("income"));
    expect(adapter.updatePriorities).toHaveBeenCalledTimes(1);
    expect(adapter.createAccount).toHaveBeenCalledTimes(1);
  });

  it("does not stand in a blank destination when its balance failed", async () => {
    adapter.createAccount.mockRejectedValueOnce(
      new Error("Create account “Brokerage” was not saved."),
    );
    render(<GoalsIntakeForm plan={plan} onDone={vi.fn()} />);
    change("Brokerage", "25000");
    change("Leftover income goes to", "brokerage");
    save();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Not saved: Brokerage, Leftover income.",
    );
    expect(adapter.createAccount).toHaveBeenCalledTimes(1);
    expect(adapter.updatePriorities).not.toHaveBeenCalled();
  });
});

describe("setup payloads", () => {
  it("lists shared accounts once and retirement accounts per person", () => {
    expect(accountSlots(false).map((slot) => `${slot.name}:${slot.owner}`)).toEqual([
      "Cash:self",
      "Brokerage:self",
      "401(k):self",
      "Traditional IRA:self",
      "Roth IRA:self",
      "HSA:self",
    ]);
    expect(accountSlots(true).map((slot) => `${slot.name}:${slot.owner}`)).toEqual([
      "Cash:joint",
      "Brokerage:joint",
      "401(k):self",
      "Partner's 401(k):spouse",
      "Traditional IRA:self",
      "Partner's Traditional IRA:spouse",
      "Roth IRA:self",
      "Partner's Roth IRA:spouse",
      "HSA:self",
      "Partner's HSA:spouse",
    ]);
  });

  it("keeps the claiming age within 62–70 and shifts the partner's age by the birth-year gap", () => {
    expect(socialSecurityIncome(1, "self", 58).claiming_age).toBe(62);
    expect(socialSecurityIncome(1, "self", 66).claiming_age).toBe(66);
    expect(socialSecurityIncome(1, "self", 75).claiming_age).toBe(70);
    expect(partnerRetirement(65, 1990, 1985).trigger_value).toBe(60);
  });

  it("adds no rule when leftover income already goes to the account", () => {
    const rule = {
      id: "r",
      plan_id: "p",
      priority_rank: 1,
      priority_type: null,
      target_account_id: "a",
    } as unknown as CashFlowPriority;
    expect(withSurplusRule([rule], "a")).toBeNull();
    expect(withSurplusRule([rule], "b")).toHaveLength(2);
  });
});

it("is not stuck saving when the plan reload fails", async () => {
  adapter.fetchPlan.mockRejectedValueOnce(new Error("offline"));
  const onDone = vi.fn();
  render(<GoalsIntakeForm plan={plan} onDone={onDone} />);
  change(/Retirement spending/, "60000");
  await act(async () => {
    save();
  });
  await waitFor(() => expect(onDone).toHaveBeenCalledWith("income"));
});
