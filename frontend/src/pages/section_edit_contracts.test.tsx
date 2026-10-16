import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { AccountsSection, BuilderModeContext, ResidencyTimelineEditor } from "./plan_setup";
import HealthcareForm from "@/components/healthcare_form";
import ExpenseForm from "@/components/expense_form";
import IncomeForm from "@/components/income_form";
import EstateSettingsForm from "@/components/estate_settings_form";
import CharityManager from "@/components/charity_manager";
import { setStorageAdapter, usePlanStore } from "@/stores/plan_store";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
const plan = makePlan({ id: "p", birth_year: 1990 });
beforeEach(() => {
  vi.clearAllMocks();
  adapter.listAccounts.mockResolvedValue([]);
  usePlanStore.setState({ ...usePlanStore.getInitialState(), plan });
  setStorageAdapter(adapter);
});

it("keeps incomplete and rapid residency edits local, then saves one latest row", async () => {
  let finish!: () => void;
  const save = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  render(<ResidencyTimelineEditor milestones={[]} periods={[]} onChange={save} />);
  fireEvent.click(screen.getByTestId("residency-add"));
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Save residency changes"));
  expect(screen.getByRole("alert")).toHaveTextContent("Choose a state");
  expect(save).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("State"), { target: { value: "TX" } });
  fireEvent.change(screen.getByLabelText("Start"), { target: { value: "year" } });
  fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "2040" } });
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Save residency changes"));
  expect(save).toHaveBeenCalledExactlyOnceWith([
    expect.objectContaining({ state_code: "TX", start_year: 2040, rank: 0 }),
  ]);
  expect(screen.getByLabelText("State")).toBeDisabled();
  fireEvent.click(screen.getByText("Saving…"));
  expect(save).toHaveBeenCalledTimes(1);
  await act(async () => finish());
  expect(screen.getByText("Residency changes saved.")).toBeInTheDocument();
});

it("retains a failed residency draft through server refresh and supports retry and clear", async () => {
  const save = vi
    .fn()
    .mockRejectedValueOnce(new Error("Save unavailable"))
    .mockResolvedValue(undefined);
  const { rerender } = render(
    <ResidencyTimelineEditor milestones={[]} periods={[]} onChange={save} />,
  );
  fireEvent.click(screen.getByTestId("residency-add"));
  fireEvent.change(screen.getByLabelText("State"), { target: { value: "TX" } });
  fireEvent.click(screen.getByText("Save residency changes"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Save unavailable");
  rerender(
    <ResidencyTimelineEditor
      milestones={[]}
      periods={[{ id: "old", plan_id: "p", state_code: "CA", rank: 0 } as never]}
      onChange={save}
    />,
  );
  expect(screen.getByLabelText("State")).toHaveValue("TX");
  fireEvent.click(screen.getByText("Save residency changes"));
  await screen.findByText("Residency changes saved.");
  fireEvent.click(screen.getByLabelText("Remove residency change"));
  fireEvent.click(screen.getByText("Save residency changes"));
  await waitFor(() => expect(save).toHaveBeenLastCalledWith([]));
});

it("shows account dependencies in the sheet and keeps the blocked account", async () => {
  adapter.listAccounts.mockResolvedValue([
    { id: "a", name: "Brokerage", account_type: "taxable_brokerage", balance: 50000 },
  ]);
  adapter.deleteAccount.mockRejectedValue(
    new Error("Account is referenced by waterfall priorities"),
  );
  render(
    <BuilderModeContext.Provider value="sheet">
      <AccountsSection />
    </BuilderModeContext.Provider>,
  );
  await screen.findByText("Brokerage");
  fireEvent.click(screen.getByText("Delete"));
  // A shared household account says what deleting it does to the other plans.
  const ask = await screen.findByRole("alertdialog", { name: "Delete “Brokerage”?" });
  expect(ask).toHaveTextContent("It is removed from every plan that shares it.");
  fireEvent.click(within(ask).getByRole("button", { name: "Delete" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Income allocation and Drawdown order",
  );
  expect(screen.getByText("Brokerage")).toBeInTheDocument();
  expect(screen.getByText("Delete")).toBeEnabled();
});

it("submits MAGI and annual and monthly premium amounts to the cent", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<HealthcareForm plan={plan} onSave={save} />);
  fireEvent.click(screen.getByLabelText("Model health coverage costs"));
  fireEvent.click(screen.getByLabelText(/Marketplace \(ACA\) coverage/));
  for (const [label, value] of [
    [/Benchmark premium/, "23456.78"],
    [/Your plan's premium/, "21345.67"],
    [/Part D plan premium/, "35.67"],
    [/Medigap or Advantage premium/, "180.55"],
    [/Last year's modified AGI/, "123456"],
    [/Modified AGI two years ago/, "112345.67"],
  ] as const) {
    const input = screen.getByLabelText(label);
    fireEvent.change(input, { target: { value } });
    expect(input).toBeValid();
  }
  fireEvent.click(screen.getByText("Save health coverage"));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      "p",
      expect.objectContaining({
        magi_prior_year: 123456,
        medicare_part_d_plan_premium_monthly: 35.67,
      }),
    ),
  );
});

it.each(["income", "expense"])("submits ordinary %s growth-cap dollars and cents", (kind) => {
  const submit = vi.fn();
  render(
    kind === "income" ? (
      <IncomeForm milestones={[]} onSubmit={submit} onCancel={() => {}} />
    ) : (
      <ExpenseForm milestones={[]} onSubmit={submit} onCancel={() => {}} />
    ),
  );
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "QA" } });
  if (kind === "expense")
    fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "annual" } });
  fireEvent.change(screen.getByLabelText(/(Annual|Monthly) amount/i), {
    target: { value: "7123.45" },
  });
  if (kind === "expense")
    fireEvent.change(screen.getByLabelText("Amount growth"), { target: { value: "custom" } });
  fireEvent.change(screen.getByLabelText(/Growth [Rr]ate/), { target: { value: "3" } });
  const cap = screen.getByLabelText(/Growth cap/);
  fireEvent.change(cap, { target: { value: "12345" } });
  expect(cap).toBeValid();
  fireEvent.change(cap, { target: { value: "12345.67" } });
  expect(cap).toBeValid();
  fireEvent.click(screen.getByText(kind === "income" ? "Add income" : "Add Expense"));
  expect(submit).toHaveBeenCalledWith(
    expect.objectContaining({ growth_cap: 12345.67, annual_amount: 7123.45 }),
  );
});

it("submits a charitable gift amount without rounding", async () => {
  adapter.listCharities.mockResolvedValue([]);
  adapter.createCharity.mockResolvedValue({});
  usePlanStore.setState({ plan: null });
  render(<CharityManager planId="p" milestones={[]} />);
  await screen.findByText("No charitable giving planned yet.");
  fireEvent.click(screen.getByText("+ Add giving"));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "QA" } });
  const amount = screen.getByLabelText(/Annual amount/);
  fireEvent.change(amount, { target: { value: "1234.56" } });
  expect(amount).toBeValid();
  fireEvent.click(screen.getByText("Add giving"));
  await waitFor(() =>
    expect(adapter.createCharity).toHaveBeenCalledWith(
      "p",
      expect.objectContaining({ annual_amount: 1234.56 }),
    ),
  );
});

it("accepts cents for estate settlement costs", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<EstateSettingsForm plan={plan} onSave={save} />);
  const costs = screen.getByLabelText("Settlement costs: fixed ($)");
  fireEvent.change(costs, { target: { value: "12345.67" } });
  expect(costs).toBeValid();
  fireEvent.click(screen.getByText("Save estate settings"));
  await waitFor(() => expect(save).toHaveBeenCalled());
});
