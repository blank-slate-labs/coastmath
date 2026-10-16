import { useState } from "react";
import type { Account, PlanData, TaxSettings, YearToDateTax } from "@/types/plan";
import {
  ELECTIVE_DEFERRAL_TYPES,
  PAYROLL_TARGET_TYPES,
  TRADITIONAL_RETIREMENT_TYPES,
} from "@/domain/account_types";
import { ownerPossessive } from "@/domain/person_labels";
import { moneyLabel } from "@/utils/format";
import MoneyInput from "./money_input";

const fields = [
  ["gross_income", "Gross ordinary income (including wages and business income)"],
  ["social_security_income", "Social Security benefits"],
  ["capital_gains", "Realized capital gains (negative for losses)"],
  ["qualified_dividends", "Qualified dividends"],
  ["net_investment_income", "Ordinary investment income (included in gross income)"],
  ["deductions", "Pretax payroll and other income adjustments"],
  ["tax_paid", "Total taxes already paid, including payroll tax"],
  ["state_tax_paid", "State income tax already paid (part of total taxes)"],
  ["property_tax", "Property tax paid"],
  ["mortgage_interest", "Deductible mortgage interest paid"],
] as const;

export default function YearToDateTaxForm({
  plan,
  accounts,
  onSave,
}: {
  plan: PlanData;
  accounts: Account[];
  onSave: (settings: TaxSettings) => Promise<void>;
}) {
  const startYear =
    plan.plan_type === "FIXED_DATE" && plan.start_date
      ? Number(plan.start_date.slice(0, 4))
      : new Date().getFullYear();
  const [history, setHistory] = useState<YearToDateTax>(
    plan.tax_settings?.year_to_date ?? { tax_year: startYear },
  );
  const [carry, setCarry] = useState(plan.tax_settings?.capital_loss_carryforward ?? 0);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setStatus("");
    try {
      await onSave({
        mode: "detailed",
        ordinary_income_tax_rate: null,
        capital_gains_tax_rate: null,
        taxable_withholding_rate: 0,
        tax_deferred_withholding_rate: 0,
        settlement_lag_years: 0,
        cash_flow_frequency: "monthly",
        ...plan.tax_settings,
        year_to_date: history,
        capital_loss_carryforward: carry,
      });
      setStatus("Saved");
    } catch {
      setStatus("Could not save. Please try again.");
    } finally {
      setSaving(false);
    }
  }
  return (
    <details id="year-to-date-history" style={{ marginTop: 16 }}>
      <summary>Earlier this tax year</summary>
      <p>Amounts before the projection start date; excluded from starting balances.</p>
      <form
        onSubmit={save}
        style={{
          display: "grid",
          gap: 12,
          gridTemplateColumns: "repeat(auto-fit, minmax(min(240px, 100%), 1fr))",
        }}
      >
        <label>
          Tax year
          <input
            type="number"
            min="1900"
            max="2200"
            required
            value={history.tax_year}
            onChange={(e) => setHistory({ ...history, tax_year: Number(e.target.value) })}
          />
        </label>
        {fields.map(([key, label]) => (
          <label key={key}>
            {moneyLabel(`${label} ($)`)}
            <MoneyInput
              step="0.01"
              min={key === "capital_gains" ? undefined : 0}
              value={history[key] ?? 0}
              onValueChange={(value) => setHistory({ ...history, [key]: Number(value) })}
            />
          </label>
        ))}
        {(["self", "spouse"] as const).map((owner) =>
          (["w2_income_by_owner", "self_employment_income_by_owner"] as const).map((key) => (
            <label key={`${owner}-${key}`}>
              {ownerPossessive(owner)}{" "}
              {key === "w2_income_by_owner" ? "W-2 wages" : "net business income"}{" "}
              {moneyLabel("before start ($)")}
              <MoneyInput
                min="0"
                step="0.01"
                value={history[key]?.[owner] ?? 0}
                onValueChange={(value) =>
                  setHistory({ ...history, [key]: { ...history[key], [owner]: Number(value) } })
                }
              />
            </label>
          )),
        )}
        {accounts
          .filter(
            (a) =>
              ["traditional_ira", "roth_ira", "hsa"].includes(a.account_type) ||
              ELECTIVE_DEFERRAL_TYPES.has(a.account_type),
          )
          .map((a) => (
            <label key={a.id}>
              {a.name}: {moneyLabel("employee contributions already made ($)")}
              <MoneyInput
                min="0"
                step="0.01"
                value={history.contributions_by_account?.[a.id] ?? 0}
                onValueChange={(value) =>
                  setHistory({
                    ...history,
                    contributions_by_account: {
                      ...history.contributions_by_account,
                      [a.id]: Number(value),
                    },
                  })
                }
              />
            </label>
          ))}
        {accounts
          .filter((a) => PAYROLL_TARGET_TYPES.has(a.account_type))
          .map((a) => (
            <label key={`employer-${a.id}`}>
              {a.name}: {moneyLabel("employer contributions already made ($)")}
              <MoneyInput
                min="0"
                step="0.01"
                value={history.employer_contributions_by_account?.[a.id] ?? 0}
                onValueChange={(value) =>
                  setHistory({
                    ...history,
                    employer_contributions_by_account: {
                      ...history.employer_contributions_by_account,
                      [a.id]: Number(value),
                    },
                  })
                }
              />
            </label>
          ))}
        {accounts
          .filter(
            (a) => TRADITIONAL_RETIREMENT_TYPES.has(a.account_type) || a.inherited_year != null,
          )
          .map((a) => (
            <label key={`withdrawn-${a.id}`}>
              {a.name}: {moneyLabel("withdrawals already taken ($)")}
              <MoneyInput
                min="0"
                step="0.01"
                value={history.distributions_by_account?.[a.id] ?? 0}
                onValueChange={(value) =>
                  setHistory({
                    ...history,
                    distributions_by_account: {
                      ...history.distributions_by_account,
                      [a.id]: Number(value),
                    },
                  })
                }
              />
            </label>
          ))}
        <label>
          {moneyLabel("Capital loss carried from prior tax years ($)")}
          <MoneyInput
            min="0"
            step="0.01"
            value={carry}
            onValueChange={(value) => setCarry(Number(value))}
          />
        </label>
        <p>
          Include wages, business income and taxable withdrawals in gross ordinary income. Earlier
          tax payments reduce the remaining bill.
        </p>
        <button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save tax history"}
        </button>
        <span role="status">{status}</span>
      </form>
    </details>
  );
}
