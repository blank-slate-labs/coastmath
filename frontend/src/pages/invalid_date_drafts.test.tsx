import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { BuilderModeContext, PlanHeader } from "./plan_setup";
import IncomeForm from "@/components/income_form";
import ExpenseForm from "@/components/expense_form";
import { usePlanStore } from "@/stores/plan_store";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";
import { makeMilestone } from "@/test_support/record_builders";

const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
const updatePlan = vi.fn();
beforeEach(() => {
  vi.clearAllMocks();
  usePlanStore.setState({
    plan: makePlan({
      id: "plan",
      name: "Dates",
      plan_type: "FIXED_DATE",
      start_date: "2026-01-01",
      birth_year: 1990,
    }),
    accountsRevision: 0,
    updatePlan,
  });
});

it("retains the last forecast and invalid date draft, then saves a corrected date", async () => {
  await act(async () => {
    render(
      <BuilderModeContext.Provider value="sheet">
        <PlanHeader />
      </BuilderModeContext.Provider>,
    );
  });
  const input = screen.getByLabelText("Start date");
  fireEvent.change(input, { target: { value: "1980-01-01" } });
  fireEvent.blur(input);
  expect(screen.getByRole("alert")).toHaveTextContent("Start date must be on or after");
  expect(input).toHaveValue("1980-01-01");
  expect(updatePlan).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "2027-01-01" } });
  fireEvent.blur(input);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(updatePlan).toHaveBeenCalledWith(
    "plan",
    expect.objectContaining({ start_date: "2027-01-01" }),
  );
});

it.each(["Income", "Expense"])(
  "rejects reversed same-year %s months and allows correction",
  (entity) => {
    const submit = vi.fn();
    const milestones = [
      makeMilestone({
        id: "m",
        plan_id: "plan",
        name: "Sabbatical",
        trigger_type: "date" as const,
        trigger_date: "2027-07-01",
        trigger_value: null,
        sort_order: 0,
      }),
    ];
    const Component = entity === "Income" ? IncomeForm : ExpenseForm;
    render(
      <Component milestones={milestones} birthYear={1990} onSubmit={submit} onCancel={() => {}} />,
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Temporary" } });
    if (screen.queryByLabelText("Amount frequency"))
      fireEvent.change(screen.getByLabelText("Amount frequency"), { target: { value: "annual" } });
    fireEvent.change(screen.getByLabelText(/(Annual|Monthly) amount/i), {
      target: { value: "24000" },
    });
    for (const name of ["Start Milestone", "End Milestone"])
      fireEvent.change(screen.getByRole("combobox", { name: new RegExp(`^${name}$`, "i") }), {
        target: { value: "m" },
      });
    fireEvent.change(screen.getByRole("combobox", { name: /^Start month$/i }), {
      target: { value: "12" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /^End month$/i }), {
      target: { value: "1" },
    });
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`^Add ${entity}$`, "i") }));
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Start month must not be after end month");
    fireEvent.change(screen.getByRole("combobox", { name: /^Start month$/i }), {
      target: { value: "7" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /^End month$/i }), {
      target: { value: "12" },
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.getByText(/Starts in Jul in the year the Start Milestone is reached/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Ends after Dec in the year the End Milestone is reached/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`^Add ${entity}$`, "i") }));
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({ start_month: 7, end_month: 12, annual_amount: 24000 }),
    );
  },
);
