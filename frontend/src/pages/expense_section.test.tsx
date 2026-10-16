import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { BuilderModeContext, ExpenseSection } from "./plan_setup";
import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import { makeExpense } from "@/test_support/record_builders";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const mocks = vi.hoisted(() => ({
  listExpenses: vi.fn(),
  listAccounts: vi.fn().mockResolvedValue([]),
}));
const adapter = makeAdapter({ listExpenses: mocks.listExpenses, listAccounts: mocks.listAccounts });
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
const expense = makeExpense({
  id: "expense",
  plan_id: "plan",
  name: "Cedar rent",
  annual_amount: 18000,
  inflation_linked: true,
  growth_rate: null,
  growth_cap: null,
  growth_cap_inflation_linked: false,
  recurrence_years: null,
  recurrence_growth_rate: 0,
  is_payroll_deduction: false,
  tied_income_id: null,
  specific_funding_source_id: null,
  start_milestone_id: null,
  end_milestone_id: null,
  start_month: null,
  end_month: null,
  category: "essential",
});
const updateExpense = vi.fn();
const key = "put /plans/plan/expenses/expense";
beforeEach(() => {
  vi.clearAllMocks();
  updateExpense.mockResolvedValue(true);
  mocks.listExpenses.mockResolvedValue([{ ...expense, annual_amount: 21000 }]);
  useSaveStore.setState({ pending: 0, failed: [], failures: {}, latest: {} });
  usePlanStore.setState({
    plan: makePlan({ id: "plan", name: "Cedar", birth_year: 1990, expenses: [expense] }),
    simulation: null,
    updateExpense,
    runSimulation: vi.fn().mockResolvedValue(undefined),
  });
});
async function open() {
  render(
    <BuilderModeContext.Provider value="sheet">
      <ExpenseSection />
    </BuilderModeContext.Provider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  await act(async () => {});
}
async function reject() {
  updateExpense.mockImplementationOnce(async () => {
    useSaveStore.setState({
      failed: [key],
      failures: {
        [key]: {
          rejected: true,
          message:
            "Save expense “Cedar rent” in “Cedar” was not saved. This expense changed after you opened it. Review latest saved values.",
        },
      },
    });
    return false;
  });
  fireEvent.change(screen.getByLabelText("Annual amount ($)"), { target: { value: "19000" } });
  fireEvent.click(screen.getByRole("button", { name: "Update Expense" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Cedar rent"));
}
it("sends opening values only for edited fields and awaits success before closing", async () => {
  await open();
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Revised" } });
  fireEvent.click(screen.getByRole("button", { name: "Update Expense" }));
  expect(updateExpense).toHaveBeenCalledWith("plan", "expense", {
    name: "Revised",
    expected_values: { name: "Cedar rent" },
  });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});
it("retains a failed draft, reviews its latest edits, and retries against the reviewed baseline", async () => {
  await open();
  await reject();
  expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("19,000");
  // Edits made after rejection must appear in review and be the ones saved.
  fireEvent.change(screen.getByLabelText("Annual amount ($)"), { target: { value: "19500" } });
  fireEvent.click(screen.getByRole("button", { name: "Review latest saved values" }));
  await screen.findByText("Saved: 21000");
  expect(screen.getByRole("region", { name: "Review expense changes" })).toHaveFocus();
  expect(screen.getByText("Your draft: 19500")).toBeInTheDocument();
  expect(screen.getByLabelText("Annual amount ($)")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Save my reviewed changes" }));
  expect(updateExpense).toHaveBeenLastCalledWith("plan", "expense", {
    annual_amount: 19500,
    expected_values: { annual_amount: 21000 },
  });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});
it("can keep the saved version without a write, then close and reopen it", async () => {
  await open();
  await reject();
  fireEvent.click(screen.getByRole("button", { name: "Review latest saved values" }));
  await screen.findByText("Saved: 21000");
  fireEvent.click(screen.getByRole("button", { name: "Use saved version" }));
  expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("21,000");
  expect(useSaveStore.getState().failed).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("21,000");
  expect(updateExpense).toHaveBeenCalledTimes(1);
});
it("retains the draft when checking saved values fails", async () => {
  await open();
  await reject();
  mocks.listExpenses.mockRejectedValueOnce(new Error("network unavailable"));
  fireEvent.click(screen.getByRole("button", { name: "Review latest saved values" }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("Could not check saved values"),
  );
  expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("19,000");
  expect(screen.getByRole("button", { name: "Review latest saved values" })).toBeEnabled();
});

it("shows rows in their saved unit and sends a unit change with its opening value", async () => {
  usePlanStore.setState((s) => ({
    plan: makePlan({
      ...s.plan!,
      expenses: [
        { ...expense, amount_frequency: "monthly" },
        { ...expense, id: "legacy", name: "Legacy", annual_amount: 6000 },
        {
          ...expense,
          id: "roof",
          name: "Roof",
          annual_amount: 12000,
          amount_frequency: "monthly",
          recurrence_years: 10,
        },
      ],
    }),
  }));
  render(
    <BuilderModeContext.Provider value="sheet">
      <ExpenseSection />
    </BuilderModeContext.Provider>,
  );
  expect(screen.getByText(/^\$1\.5K\/mo \(inflation-linked\)/)).toBeInTheDocument();
  expect(screen.getByText(/^\$6\.0K\/yr \(inflation-linked\)/)).toBeInTheDocument();
  // A repeating charge stays a yearly amount every few years.
  expect(screen.getByText(/^\$12\.0K every 10 yrs/)).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
  await act(async () => {});
  expect(screen.getByLabelText("Monthly amount ($)")).toHaveValue("1,500");
  fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "weekly" } });
  fireEvent.click(screen.getByRole("button", { name: "Update Expense" }));
  await waitFor(() =>
    expect(updateExpense).toHaveBeenLastCalledWith("plan", "expense", {
      amount_frequency: "weekly",
      expected_values: { amount_frequency: "monthly" },
    }),
  );
});
it("labels a partial split in the list and sends a changed percent with its category and opening values", async () => {
  const split = { ...expense, discretionary_percent: 40 };
  usePlanStore.setState({ plan: { ...usePlanStore.getState().plan!, expenses: [split] } });
  await open();
  expect(screen.getByText("40% flexible")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Discretionary share (%)"), { target: { value: "60" } });
  fireEvent.click(screen.getByRole("button", { name: "Update Expense" }));
  expect(updateExpense).toHaveBeenCalledWith("plan", "expense", {
    category: "discretionary",
    discretionary_percent: 60,
    expected_values: { category: "essential", discretionary_percent: 40 },
  });
});
