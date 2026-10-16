import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { AccountsSection, BuilderModeContext, ExpenseSection } from "./plan_setup";
import { usePlanStore } from "@/stores/plan_store";
import type { Account, Expense } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
// The app's own discard dialog, answered by each test.
const confirmDiscard = vi.hoisted(() => vi.fn<(message?: string) => Promise<boolean>>());
vi.mock("@/components/confirm_dialog", () => ({
  confirmDiscard,
  confirmDelete: () => Promise.resolve(true),
}));
const expense = {
  id: "expense",
  plan_id: "plan",
  name: "Travel",
  annual_amount: 1200,
  inflation_linked: false,
  growth_rate: null,
  growth_cap: null,
  growth_cap_inflation_linked: false,
  recurrence_years: null,
  recurrence_growth_rate: 0,
  is_payroll_deduction: false,
  specific_funding_source_id: null,
  start_milestone_id: null,
  end_milestone_id: null,
  category: "discretionary",
  start_month: null,
  end_month: null,
} as Expense;
const account = {
  id: "account",
  name: "Cash",
  account_type: "checking",
  balance: 1234.56,
  owner: "self",
  cost_basis: null,
} as Account;
const updateExpense = vi.fn().mockResolvedValue(undefined);
const saveAccount = vi.fn().mockResolvedValue(undefined);
beforeEach(() => {
  vi.clearAllMocks();
  adapter.listAccounts.mockResolvedValue([account]);
  usePlanStore.setState({
    plan: makePlan({ id: "plan", birth_year: 1990, expenses: [expense] }),
    simulation: null,
    accountsRevision: 0,
    updateExpense,
    saveAccount,
  });
});
function show(Component: typeof ExpenseSection) {
  return render(
    <BuilderModeContext.Provider value="sheet">
      <Component />
    </BuilderModeContext.Provider>,
  );
}
it("preserves an independently renamed expense when a stale form changes its amount", async () => {
  await act(async () => {
    show(ExpenseSection);
  });
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  act(() =>
    usePlanStore.setState((s) => ({
      plan: { ...s.plan!, expenses: [{ ...expense, name: "Renamed travel" }] },
    })),
  );
  fireEvent.change(screen.getByLabelText("Annual amount ($)"), { target: { value: "2400" } });
  fireEvent.click(screen.getByRole("button", { name: "Update Expense" }));
  expect(updateExpense).toHaveBeenCalledWith("plan", "expense", {
    annual_amount: 2400,
    expected_values: { annual_amount: 1200 },
  });
});
it("does not write an unchanged expense", async () => {
  await act(async () => {
    show(ExpenseSection);
  });
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.click(screen.getByRole("button", { name: "Update Expense" }));
  expect(updateExpense).not.toHaveBeenCalled();
});
it("preserves an independently renamed account when a stale form changes its balance", async () => {
  show(AccountsSection);
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  adapter.listAccounts.mockResolvedValue([{ ...account, name: "Renamed cash" }]);
  act(() => usePlanStore.setState({ accountsRevision: 1 }));
  await screen.findByText("Renamed cash");
  const form = within(screen.getByRole("dialog", { name: "Edit Account" }));
  fireEvent.change(form.getByLabelText("Balance ($)"), { target: { value: "2345.67" } });
  fireEvent.click(form.getByRole("button", { name: "Update Account" }));
  await waitFor(() => expect(saveAccount).toHaveBeenCalledWith("account", { balance: 2345.67 }));
});
it("does not write an unchanged account", async () => {
  show(AccountsSection);
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  fireEvent.click(screen.getByRole("button", { name: "Update Account" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(saveAccount).not.toHaveBeenCalled();
});
it("sends an explicit null when clearing brokerage basis", async () => {
  adapter.listAccounts.mockResolvedValue([
    { ...account, account_type: "taxable_brokerage", cost_basis: 500 },
  ]);
  show(AccountsSection);
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByLabelText(/Cost basis/), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Update Account" }));
  await waitFor(() => expect(saveAccount).toHaveBeenCalledWith("account", { cost_basis: null }));
});
it("clears an expense funding source without resending the stale name", async () => {
  usePlanStore.setState((s) => ({
    plan: { ...s.plan!, expenses: [{ ...expense, specific_funding_source_id: "account" }] },
  }));
  await act(async () => {
    show(ExpenseSection);
  });
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.click(screen.getByRole("button", { name: /^Remove / }));
  fireEvent.click(screen.getByRole("button", { name: "Update Expense" }));
  expect(updateExpense).toHaveBeenCalledWith("plan", "expense", {
    specific_funding_source_id: null,
    expected_values: { specific_funding_source_id: "account" },
  });
});
it("retains an expense draft while saving and after failure, then closes after retry", async () => {
  let complete!: (saved: boolean) => void;
  updateExpense
    .mockImplementationOnce(
      () =>
        new Promise<boolean>((resolve) => {
          complete = resolve;
        }),
    )
    .mockResolvedValueOnce(true);
  await act(async () => {
    show(ExpenseSection);
  });
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByLabelText("Annual amount ($)"), { target: { value: "2400" } });
  fireEvent.click(screen.getByRole("button", { name: "Update Expense" }));
  expect(screen.getByRole("button", { name: "Update Expense" })).toBeDisabled();
  await act(async () => {
    usePlanStore.setState({ error: "Expense save unavailable" });
    complete(false);
  });
  expect(screen.getByRole("alert")).toHaveTextContent("Expense save unavailable");
  expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("2,400");
  fireEvent.click(screen.getByRole("button", { name: "Update Expense" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(updateExpense).toHaveBeenCalledTimes(2);
});

it("discarding a failed expense draft clears its error before opening another edit", async () => {
  const confirm = confirmDiscard.mockReset().mockResolvedValue(true);
  updateExpense.mockResolvedValueOnce(false);
  await act(async () => {
    show(ExpenseSection);
  });
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByLabelText("Annual amount ($)"), { target: { value: "2400" } });
  fireEvent.click(screen.getByRole("button", { name: "Update Expense" }));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(confirm).toHaveBeenCalledOnce();
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("1,200");
});
