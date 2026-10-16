import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import LiabilityForm from "./liability_form";
import type { Account, Liability, Milestone, RealAsset } from "@/types/plan";
vi.mock("./amortization_table", () => ({
  default: (props: { principalBalance: number; interestRate: number }) => (
    <div role="table">
      Saved balance {props.principalBalance}, annual percent {props.interestRate}
    </div>
  ),
}));
const fill = (label: string | RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
function setup(initial?: Liability, planId?: string) {
  const submit = vi.fn(),
    cancel = vi.fn();
  render(
    <LiabilityForm
      initial={initial}
      planId={planId}
      onSubmit={submit}
      onCancel={cancel}
      accounts={[{ id: "a", name: "Offset cash" } as Account]}
      realAssets={[{ id: "r", name: "Home" } as RealAsset]}
      milestones={[{ id: "m", name: "Retirement" } as Milestone]}
    />,
  );
  return { submit, cancel };
}
const save = () =>
  fireEvent.click(screen.getByRole("button", { name: /^(Save|Update) loan or debt$/ }));
function basics() {
  fill("Name", "Loan");
  fill(/Principal balance/, "12000");
  fill(/Interest rate/, "0");
}
it("calculates a zero-rate loan and preserves exact linked references", () => {
  const { submit, cancel } = setup();
  basics();
  fill("Remaining term (months)", "12");
  expect(screen.getByText("Calculated: $1000.00/mo")).toBeVisible();
  fill("Offset account", "a");
  fill("Linked real asset", "r");
  fill("Payoff milestone", "m");
  fill(/Extra payment/, "120");
  save();
  expect(submit).toHaveBeenCalledExactlyOnceWith({
    name: "Loan",
    principal_balance: 12000,
    interest_rate: 0,
    payment_type: "fixed",
    term_months: 12,
    monthly_payment: 1000,
    extra_payment: 120,
    offset_account_id: "a",
    linked_asset_id: "r",
    payoff_milestone_id: "m",
  });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(cancel).toHaveBeenCalledOnce();
});
it("uses the independently calculated 30-year mortgage payment and permits an explicit override", () => {
  const { submit } = setup();
  basics();
  fill(/Principal balance/, "300000");
  fill(/Interest rate/, "6.5");
  fill("Remaining term (months)", "360");
  expect(screen.getByText("Calculated: $1896.20/mo")).toBeVisible();
  save();
  expect(submit.mock.calls[0][0].monthly_payment).toBe(1896.2);
  fill(/^Monthly payment \(\$\)/, "2000");
  save();
  expect(submit.mock.calls[1][0].monthly_payment).toBe(2000);
});
it.each(["custom", "percent_of_balance"] as const)(
  "submits %s payment without a stale fixed term",
  (type) => {
    const { submit } = setup();
    basics();
    fill("Remaining term (months)", "36");
    fill("Payment type", type);
    expect(screen.queryByLabelText("Remaining term (months)")).not.toBeInTheDocument();
    save();
    expect(submit.mock.calls[0][0]).toMatchObject({
      payment_type: type,
      term_months: null,
      monthly_payment: null,
      extra_payment: 0,
      offset_account_id: null,
    });
    fill(/Monthly payment/, type === "custom" ? "500" : "0.02");
    save();
    expect(submit.mock.calls[1][0].monthly_payment).toBe(type === "custom" ? 500 : 0.02);
  },
);
it("submits missing optional fixed-payment values as null and enforces native validation", () => {
  const { submit } = setup();
  save();
  expect(submit).not.toHaveBeenCalled();
  basics();
  save();
  expect(submit.mock.calls[0][0]).toMatchObject({ term_months: null, monthly_payment: null });
  fill("Remaining term (months)", "0");
  expect(screen.getByLabelText("Remaining term (months)")).toBeInvalid();
  expect(screen.queryByText(/Calculated:/)).not.toBeInTheDocument();
  save();
  expect(submit).toHaveBeenCalledTimes(1);
  fill("Remaining term (months)", "12");
  fill(/Principal balance/, "0");
  save();
  expect(submit).toHaveBeenCalledTimes(1);
  fill(/Principal balance/, "12000");
  fill(/Interest rate/, "101");
  save();
  expect(submit).toHaveBeenCalledTimes(1);
});
it("opens the saved amortization schedule without feeding it unsaved draft values", () => {
  const initial = {
    id: "l",
    plan_id: "p",
    name: "Saved loan",
    principal_balance: 12000,
    interest_rate: 5,
    payment_type: "fixed",
    term_months: 24,
    monthly_payment: 526.46,
    extra_payment: 20,
    offset_account_id: "a",
    linked_asset_id: "r",
    payoff_milestone_id: "m",
  } as Liability;
  const { submit } = setup(initial, "p");
  fill(/Principal balance/, "13000");
  fireEvent.click(screen.getByRole("button", { name: "Show amortization schedule" }));
  expect(screen.getByRole("table")).toHaveTextContent("Saved balance 12000, annual percent 5");
  expect(screen.getByText(/Uses saved values/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Hide amortization schedule" }));
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  save();
  expect(submit.mock.calls[0][0]).toMatchObject({
    principal_balance: 13000,
    monthly_payment: 526.46,
    offset_account_id: "a",
  });
});
it("warns, without blocking, when payments do not cover the monthly interest", () => {
  const { submit } = setup();
  basics();
  fill(/Principal balance/, "10000");
  fill(/Interest rate/, "5");
  fill("Payment type", "custom");
  fill(/^Monthly payment \(\$\)/, "1");
  expect(screen.getByText(/below the \$42 monthly interest/)).toBeVisible();
  fill(/^Monthly payment \(\$\)/, "50");
  expect(screen.queryByText(/monthly interest/)).not.toBeInTheDocument();
  fill(/^Monthly payment \(\$\)/, "1");
  save();
  expect(submit).toHaveBeenCalledOnce();
});
it("keeps less common terms under More options, opened when one is saved", () => {
  setup();
  expect(screen.getByText("More options").closest("details")).not.toHaveAttribute("open");
});
