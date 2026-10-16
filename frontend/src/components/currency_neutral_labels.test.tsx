import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ExpenseForm from "./expense_form";
import IncomeForm from "./income_form";
import RealAssetForm from "./real_asset_form";
import WithdrawalStrategyForm from "./withdrawal_strategy_form";
import { GoalsIntakeForm } from "./goals_intake_form";
import { DEFAULT_EMPLOYER_MATCH, EmployerMatchFields } from "./employer_match_fields";
import CashReserveControl from "./tax/cash_reserve_control";
import TaxTargetForm from "./tax_target_form";
import TaxAdjustmentsForm from "./tax_adjustments_form";
import { usePlanStore } from "@/stores/plan_store";
import type { CashFlowPriorityCreate, PlanData, TaxSettings } from "@/types/plan";
import { setDisplayCurrency } from "@/utils/format";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

const settings: TaxSettings = {
  mode: "detailed",
  ordinary_income_tax_rate: null,
  capital_gains_tax_rate: null,
  taxable_withholding_rate: 0,
  tax_deferred_withholding_rate: 0,
  settlement_lag_years: 0,
  cash_flow_frequency: "monthly",
};
const plan = (extra: Partial<PlanData> = {}): PlanData =>
  makePlan({
    id: "p",
    user_id: "u",
    name: "Plan",
    plan_type: "FIXED_DATE",
    start_date: "2027-01-01",
    birth_year: 1966,
    created_at: "2026-01-01",
    tax_settings: settings,
    ...extra,
  });

/** Renders in a US-dollar plan, then in a euro plan, and checks the label each time. */
async function inBothCurrencies(show: () => void | Promise<void>, usd: string, eur: string) {
  await show();
  expect(screen.getByLabelText(usd)).toBeInTheDocument();
  cleanup();
  setDisplayCurrency("EUR");
  await show();
  expect(screen.getByLabelText(eur)).toBeInTheDocument();
  expect(screen.queryByLabelText(usd)).not.toBeInTheDocument();
}

afterEach(() => setDisplayCurrency(null));

describe("currency-neutral form labels", () => {
  it("expenses", async () => {
    await inBothCurrencies(
      () => {
        render(<ExpenseForm milestones={[]} onSubmit={vi.fn()} onCancel={() => {}} />);
        fireEvent.change(screen.getByLabelText("Amount growth"), { target: { value: "custom" } });
      },
      "Growth cap ($ per year, optional)",
      "Growth cap (€ per year, optional)",
    );
    expect(screen.getByText(/^Enter the amount in today's money\./)).toBeInTheDocument();
  });

  it("income", async () => {
    await inBothCurrencies(
      () => {
        render(<IncomeForm milestones={[]} onSubmit={vi.fn()} onCancel={() => {}} />);
        fireEvent.click(screen.getByLabelText("Other"));
        fireEvent.change(screen.getByLabelText(/Income tax treatment/), {
          target: { value: "qualified_pension" },
        });
        fireEvent.change(screen.getByLabelText("Benefit formula"), { target: { value: "flat" } });
      },
      "Flat annual benefit (today’s dollars)",
      "Flat annual benefit (today’s money)",
    );
  });

  it("real assets", async () => {
    await inBothCurrencies(
      () => {
        render(<RealAssetForm accounts={[]} onSubmit={vi.fn()} onCancel={() => {}} />);
        fireEvent.change(screen.getByLabelText("Sale tax treatment"), {
          target: { value: "rental" },
        });
      },
      "Annual rent ($, today's dollars)",
      "Annual rent (€, today's money)",
    );
  });

  it("withdrawal strategy", async () => {
    await inBothCurrencies(
      () => {
        render(<WithdrawalStrategyForm planId="p" initial={null} onSave={vi.fn()} />);
        fireEvent.click(screen.getByLabelText("Set spending with a withdrawal strategy"));
        fireEvent.change(screen.getByLabelText("Method"), { target: { value: "fixed_amount" } });
      },
      "Yearly amount (today's dollars)",
      "Yearly amount (today's money)",
    );
    expect(
      screen.getByText("A set amount in today's money, optionally raised with inflation."),
    ).toBeInTheDocument();
  });

  it("goals intake", async () => {
    await inBothCurrencies(
      () => {
        render(<GoalsIntakeForm plan={plan()} onDone={vi.fn()} />);
      },
      "Retirement spending ($/yr, today's dollars)",
      "Retirement spending (€/yr, today's money)",
    );
  });

  it("employer match", async () => {
    const rule = { employer_match: DEFAULT_EMPLOYER_MATCH } as CashFlowPriorityCreate;
    await inBothCurrencies(
      () => {
        render(<EmployerMatchFields rule={rule} edit={vi.fn()} />);
      },
      "Annual employer cap ($, today’s dollars; optional)",
      "Annual employer cap (€, today’s money; optional)",
    );
  });

  it("cash reserve", async () => {
    usePlanStore.setState({ plan: plan({ cash_reserve_settings: null } as Partial<PlanData>) });
    await inBothCurrencies(
      async () => {
        render(<CashReserveControl />);
        fireEvent.click(screen.getByLabelText("Enabled"));
        await screen.findByText(/No checking or savings accounts found/);
      },
      "Reserve amount ($, in today's dollars)",
      "Reserve amount (€, in today's money)",
    );
  });

  it("tax target", async () => {
    const saved = plan({
      tax_settings: { ...settings, tax_target: { kind: "magi", amount: 90000 } },
    });
    await inBothCurrencies(
      () => {
        render(<TaxTargetForm plan={saved} onSave={vi.fn()} />);
      },
      "Amount (today's $)",
      "Amount (today's money)",
    );
    expect(
      screen.getByText(/^Modified AGI in today's money; rises with inflation\./),
    ).toBeInTheDocument();
  });

  it("tax adjustments", async () => {
    await inBothCurrencies(
      () => {
        render(<TaxAdjustmentsForm plan={plan()} onSave={vi.fn()} />);
        fireEvent.click(screen.getByText("Tax adjustments and scheduled changes"));
        fireEvent.click(screen.getByRole("button", { name: "Add adjustment" }));
      },
      "Amount per year ($)",
      "Amount per year (€)",
    );
    expect(
      screen.getByRole("option", { name: "Today's money (rises with inflation)" }),
    ).toBeInTheDocument();
  });
});
