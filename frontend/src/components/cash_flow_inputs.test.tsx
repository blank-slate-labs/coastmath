import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LiabilityForm, { calculateMonthlyPayment } from "./liability_form";
import IncomeForm from "./income_form";
import AccountForm from "./account_form";
import SavingsPrioritiesPanel from "./savings_priorities_panel";
import { usePlanStore } from "@/stores/plan_store";
import { formatIncomePerPeriod, hourlyAnnual } from "@/utils/amount_frequency";
import type { Account, Income, Liability, Milestone, RealAsset } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

vi.mock("./amortization_table", () => ({ default: () => <div role="table" /> }));
vi.mock("@/api/client", () => ({ estimateSocialSecurity: vi.fn() }));
const mocks = vi.hoisted(() => ({ save: vi.fn(), accounts: vi.fn(), fetch: vi.fn() }));
// One stable adapter: a new one per render would reload accounts forever.
const adapter = makeAdapter({
  listAccounts: mocks.accounts,
  updatePriorities: mocks.save,
  fetchPlan: mocks.fetch,
});
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

const fill = (label: string | RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe("loan interest method and repeats", () => {
  function setup(initial?: Liability) {
    const submit = vi.fn();
    render(
      <LiabilityForm
        initial={initial}
        onSubmit={submit}
        onCancel={() => {}}
        accounts={[] as Account[]}
        realAssets={[] as RealAsset[]}
        milestones={[{ id: "m", name: "Retirement" } as Milestone]}
      />,
    );
    fill("Name", "Car");
    fill(/Principal balance/, "12000");
    fill(/Interest rate/, "6");
    fill("Remaining term (months)", "12");
    return submit;
  }
  const save = () =>
    fireEvent.click(screen.getByRole("button", { name: /^(Save|Update) loan or debt$/ }));

  it("keeps the default payload unchanged", () => {
    const submit = setup();
    save();
    const sent = submit.mock.calls[0][0];
    for (const key of [
      "interest_method",
      "recurrence_years",
      "recurrence_end_year",
      "recurrence_end_milestone_id",
    ])
      expect(sent).not.toHaveProperty(key);
  });

  it("sends the method and repeat, and the daily payment uses daily compounding", () => {
    const submit = setup();
    fill("Interest method", "daily");
    const daily = calculateMonthlyPayment(12000, 6, 12, "daily")!;
    expect(daily).toBeGreaterThan(calculateMonthlyPayment(12000, 6, 12)!);
    expect(screen.getByText(`Calculated: $${daily.toFixed(2)}/mo`)).toBeVisible();
    fill("Repeat every (years)", "7");
    fill("Last repeat year", "2045");
    fill("Stop repeating at milestone", "m");
    save();
    expect(submit.mock.calls[0][0]).toMatchObject({
      interest_method: "daily",
      monthly_payment: Math.round(daily * 100) / 100,
      recurrence_years: 7,
      recurrence_end_year: 2045,
      recurrence_end_milestone_id: "m",
    });
  });

  it("clears a saved repeat with nulls and rejects a bad interval", () => {
    const initial = {
      id: "l",
      plan_id: "p",
      name: "Car",
      principal_balance: 12000,
      interest_rate: 6,
      term_months: 12,
      monthly_payment: null,
      payment_type: "fixed",
      extra_payment: 0,
      payoff_milestone_id: null,
      offset_account_id: null,
      linked_asset_id: null,
      recurrence_years: 5,
      recurrence_end_year: 2040,
    } as Liability;
    const submit = setup(initial);
    fill("Repeat every (years)", "0");
    save();
    expect(screen.getByLabelText("Repeat every (years)")).toBeInvalid();
    expect(submit).not.toHaveBeenCalled();
    fill("Repeat every (years)", "");
    save();
    expect(submit.mock.calls[0][0]).toMatchObject({
      recurrence_years: null,
      recurrence_end_year: null,
      recurrence_end_milestone_id: null,
    });
  });
});

describe("hourly pay", () => {
  it("computes the annual amount from rate and hours and reopens in hourly", () => {
    const submit = vi.fn();
    const { unmount } = render(
      <IncomeForm milestones={[]} onSubmit={submit} onCancel={() => {}} />,
    );
    fill("Name", "Shifts");
    fill("Amount frequency", "hourly");
    fill(/Hourly rate/, "25.5");
    fill("Hours per week", "30");
    expect(screen.getByTestId("hourly-annual")).toHaveTextContent("$39,780.00 a year");
    fireEvent.click(screen.getByText("Add income"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        amount_frequency: "hourly",
        hourly_rate: 25.5,
        hours_per_week: 30,
        annual_amount: 39780,
      }),
    );
    unmount();
    const initial = {
      id: "i",
      plan_id: "p",
      name: "Shifts",
      annual_amount: 39780,
      amount_frequency: "hourly",
      hourly_rate: 25.5,
      hours_per_week: 30,
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
    } as unknown as Income;
    render(<IncomeForm initial={initial} milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    expect(screen.getByLabelText("Amount frequency")).toHaveValue("hourly");
    expect(screen.getByLabelText(/Hourly rate/)).toHaveValue("25.5");
    // Switching to another unit carries the annual amount and clears the hourly fields.
    fill("Amount frequency", "annual");
    expect(screen.getByLabelText("Annual amount ($)")).toHaveValue("39,780");
    fireEvent.click(screen.getByText("Save income"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        amount_frequency: "annual",
        annual_amount: 39780,
        hourly_rate: null,
        hours_per_week: null,
      }),
    );
  });

  it("requires a rate and weekly hours", () => {
    const submit = vi.fn();
    render(<IncomeForm milestones={[]} onSubmit={submit} onCancel={() => {}} />);
    fill("Name", "Shifts");
    fill("Amount frequency", "hourly");
    fill("Hours per week", "200");
    fireEvent.submit(screen.getByText("Add income").closest("form")!);
    expect(submit).not.toHaveBeenCalled();
  });

  it("formats hourly list rows", () => {
    expect(hourlyAnnual(20, 40)).toBe(41600);
    const format = (value: number) => `$${value}`;
    expect(
      formatIncomePerPeriod(
        { annual_amount: 41600, amount_frequency: "hourly", hourly_rate: 20, hours_per_week: 40 },
        format,
      ),
    ).toBe("$20/hr × 40 hrs/wk");
    expect(
      formatIncomePerPeriod({ annual_amount: 1200, amount_frequency: "monthly" }, format),
    ).toBe("$100/mo");
  });
});

describe("liquid net worth override", () => {
  const account = {
    id: "a",
    user_id: "u",
    name: "Art",
    account_type: "other",
    balance: 5000,
    owner: "self",
  } as Account;
  it("sends the override only when chosen or already saved", () => {
    const submit = vi.fn();
    const { unmount } = render(
      <AccountForm initial={account} onSubmit={submit} onCancel={() => {}} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Update Account" }));
    expect(submit.mock.calls[0][0]).not.toHaveProperty("include_in_liquid");
    fill("Liquid net worth", "exclude");
    fireEvent.click(screen.getByRole("button", { name: "Update Account" }));
    expect(submit.mock.calls[1][0]).toMatchObject({ include_in_liquid: false });
    unmount();
    render(
      <AccountForm
        initial={{ ...account, include_in_liquid: true }}
        onSubmit={submit}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByLabelText("Liquid net worth")).toHaveValue("include");
    fill("Liquid net worth", "");
    fireEvent.click(screen.getByRole("button", { name: "Update Account" }));
    expect(submit.mock.calls[2][0]).toMatchObject({ include_in_liquid: null });
  });
});

describe("monthly transfers", () => {
  beforeEach(() => {
    sessionStorage.clear();
    mocks.fetch.mockReset().mockRejectedValue(new Error("offline"));
    usePlanStore.setState({ plan: null, simulation: null, isSimulating: false });
  });
  it("saves the transfer timing", async () => {
    mocks.accounts.mockResolvedValue([
      { id: "cash", name: "Cash", account_type: "savings" },
      { id: "brk", name: "Brokerage", account_type: "taxable_brokerage" },
    ]);
    mocks.save.mockReset().mockResolvedValue({ items: [], revision: 1 });
    const transfer = {
      id: "t",
      plan_id: "p",
      priority_rank: 1,
      priority_type: "transfer",
      source_account_id: "cash",
      target_account_id: "brk",
      max_annual_amount: 1200,
    };
    render(<SavingsPrioritiesPanel plan={makePlan({ id: "p", priorities: [transfer] })} />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add allocation" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByText(/^1\. Brokerage/, { selector: "summary" }));
    expect(screen.getByLabelText("Transfer timing")).toHaveValue("annual");
    fill("Transfer timing", "monthly");
    expect(screen.getByText(/Moves 1\/12 of the annual maximum/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Save allocation" }));
    await waitFor(() =>
      expect(mocks.save).toHaveBeenCalledWith(
        "p",
        [expect.objectContaining({ priority_type: "transfer", transfer_frequency: "monthly" })],
        0,
      ),
    );
  });
});
