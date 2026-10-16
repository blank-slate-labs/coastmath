import { useState } from "react";
import type { EstimatedTaxStrategy, PlanData, TaxSettings } from "@/types/plan";
import { moneyLabel } from "@/utils/format";
import MoneyInput from "./money_input";
import { DEFAULT_TAX_SETTINGS } from "@/domain/tax_settings_defaults";

const strategies: { value: EstimatedTaxStrategy; label: string; help: string }[] = [
  {
    value: "off",
    label: "Not modeled",
    help: "No estimated payments or underpayment penalty. Each year's tax is settled in that year.",
  },
  {
    value: "settle_at_filing",
    label: "Pay the balance when filing (estimate the penalty)",
    help: "No quarterly payments. If withholding falls short of the safe harbor, the IRS underpayment penalty is estimated and paid with that year's tax.",
  },
  {
    value: "safe_harbor",
    label: "Pay safe-harbor estimates",
    help: "Four equal payments bring withholding up to the required annual payment: the smaller of 90% of this year's federal tax or 100% of last year's (110% above $150,000 AGI). No penalty.",
  },
  {
    value: "pay_in_full",
    label: "Pay projected federal tax in estimates",
    help: "Four equal payments cover the projected federal tax not withheld. No penalty, and no federal balance at filing.",
  },
];

const amount = (value: number | null | undefined) => (value == null ? "" : String(value));
const parsed = (text: string) => (text.trim() === "" ? null : Number(text));

export default function EstimatedTaxForm({
  plan,
  onSave,
}: {
  plan: PlanData;
  onSave: (settings: TaxSettings) => Promise<void>;
}) {
  const saved = plan.tax_settings?.estimated_payments;
  const [strategy, setStrategy] = useState<EstimatedTaxStrategy>(saved?.strategy ?? "off");
  const [priorTax, setPriorTax] = useState(amount(saved?.prior_year_total_tax));
  const [priorAgi, setPriorAgi] = useState(amount(saved?.prior_year_agi));
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const startYear =
    plan.plan_type === "FIXED_DATE" && plan.start_date
      ? Number(plan.start_date.slice(0, 4))
      : new Date().getFullYear();
  const selected = strategies.find((option) => option.value === strategy) ?? strategies[0];
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setStatus("");
    try {
      await onSave({
        ...DEFAULT_TAX_SETTINGS,
        ...plan.tax_settings,
        estimated_payments: {
          strategy,
          prior_year_total_tax: parsed(priorTax),
          prior_year_agi: parsed(priorAgi),
        },
      });
      setStatus("Saved");
    } catch {
      setStatus("Could not save. Your entries are kept; please try again.");
    } finally {
      setSaving(false);
    }
  }
  return (
    <details id="estimated-tax-payments" style={{ marginTop: 16 }}>
      <summary>Estimated tax payments</summary>
      <p>
        Federal quarterly estimates and the IRS underpayment penalty. State estimates aren't
        modeled.
      </p>
      <form
        onSubmit={save}
        style={{
          display: "grid",
          gap: 12,
          gridTemplateColumns: "repeat(auto-fit, minmax(min(240px, 100%), 1fr))",
        }}
      >
        <label>
          Estimated payments
          <select
            value={strategy}
            aria-describedby="estimated-tax-help"
            onChange={(e) => setStrategy(e.target.value as EstimatedTaxStrategy)}
          >
            {strategies.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <p id="estimated-tax-help" style={{ gridColumn: "1 / -1", margin: 0, fontSize: 13 }}>
          {selected.help}
        </p>
        {strategy !== "off" && (
          <>
            <label>
              {startYear - 1} {moneyLabel("total federal tax ($, optional)")}
              <MoneyInput
                min="0"
                step="0.01"
                value={priorTax}
                placeholder="Unknown"
                onValueChange={setPriorTax}
              />
            </label>
            <label>
              {startYear - 1} {moneyLabel("adjusted gross income ($, optional)")}
              <MoneyInput
                min="0"
                step="0.01"
                value={priorAgi}
                placeholder="Unknown"
                onValueChange={setPriorAgi}
              />
            </label>
            <p style={{ gridColumn: "1 / -1", margin: 0, fontSize: 13 }}>
              Used for {startYear} only; later years use the previous projected year. Without last
              year's tax, only the 90% rule applies. Without its AGI, the 110% rule is assumed.
            </p>
          </>
        )}
        <button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save estimated payments"}
        </button>
        <span role="status">{status}</span>
      </form>
    </details>
  );
}
