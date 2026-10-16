import { useState } from "react";
import type { PlanData, TaxSettings, TaxTarget, TaxTargetKind } from "@/types/plan";
import { moneyLabel } from "@/utils/format";
import MoneyInput from "@/components/money_input";
import {
  STALE_RATE_NOTE,
  fillableBracketRates,
  includesRate,
  planBracketRates,
} from "@/domain/federal_bracket_rates";
import { DEFAULT_TAX_SETTINGS } from "@/domain/tax_settings_defaults";

const kinds: { value: TaxTargetKind | "none"; label: string; help: string }[] = [
  {
    value: "none",
    label: "No tax target",
    help: "Withdrawals follow the drawdown order; conversion and harvest rules use their own limits.",
  },
  {
    value: "federal_bracket",
    label: "Stay within a federal bracket",
    help: "Taxable income, including capital gains and qualified dividends, stays within the top of the chosen bracket.",
  },
  {
    value: "taxable_income",
    label: "Keep taxable income at or below",
    help: "Taxable income, including capital gains and qualified dividends, in today's dollars; rises with inflation.",
  },
  {
    value: "magi",
    label: "Keep MAGI at or below",
    help: "Modified AGI in today's dollars; rises with inflation. In marketplace-coverage years this is the premium tax credit MAGI.",
  },
  {
    value: "irmaa_tier",
    label: "Stay below a Medicare IRMAA tier",
    help: "Income in a year sets Medicare premiums two years later, so each year uses the IRMAA ranges projected for then. Applies once someone reaches 65 by that premium year.",
  },
  {
    value: "aca_fpl_percent",
    label: "Stay under a share of the poverty line (ACA years)",
    help: "Premium tax credit MAGI stays at or below this percentage of the federal poverty line. Applies only in years with marketplace coverage.",
  },
];

const ratePercent = (rate: number) => `${Number((rate * 100).toFixed(2))}%`;
const text = (value: number | null | undefined) => (value == null ? "" : String(value));
const parsed = (value: string) => (value.trim() === "" ? null : Number(value));

export default function TaxTargetForm({
  plan,
  onSave,
}: {
  plan: PlanData;
  onSave: (settings: TaxSettings) => Promise<void>;
}) {
  const saved = plan.tax_settings?.tax_target ?? null;
  // A bracket without a top (the built-in top one, a custom one left open) has nothing to fill,
  // so it is not offered for a new target.
  const offeredRates = fillableBracketRates(plan.tax_settings);
  const savedRate = saved?.bracket_rate ?? null;
  // The server accepts every rate of the plan's brackets, open top brackets included;
  // a saved one keeps its option even when it is not offered for a new target.
  const bracketRates =
    savedRate != null &&
    includesRate(planBracketRates(plan.tax_settings), savedRate) &&
    !includesRate(offeredRates, savedRate)
      ? [...offeredRates, savedRate]
      : offeredRates;
  // A rate saved before the plan's brackets changed stays visible until replaced.
  const staleRate =
    savedRate != null && !includesRate(planBracketRates(plan.tax_settings), savedRate)
      ? savedRate
      : null;
  const [kind, setKind] = useState<TaxTargetKind | "none">(saved?.kind ?? "none");
  const [bracketRate, setBracketRate] = useState(
    String(savedRate ?? (includesRate(bracketRates, 0.12) ? 0.12 : (bracketRates[0] ?? 0.12))),
  );
  const [amount, setAmount] = useState(text(saved?.amount));
  const [tier, setTier] = useState(String(saved?.irmaa_tier ?? 1));
  const [fplPercent, setFplPercent] = useState(text(saved?.aca_fpl_percent ?? 400));
  const [avoidNiit, setAvoidNiit] = useState(saved?.avoid_niit ?? false);
  const [avoidIrmaa, setAvoidIrmaa] = useState(saved?.avoid_irmaa ?? false);
  const [acaCap, setAcaCap] = useState(saved?.aca_cap_fpl_percent != null);
  const [acaCapPercent, setAcaCapPercent] = useState(text(saved?.aca_cap_fpl_percent ?? 400));
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const selected = kinds.find((option) => option.value === kind) ?? kinds[0];

  function target(): TaxTarget | null {
    if (kind === "none") return null;
    return {
      kind,
      bracket_rate: kind === "federal_bracket" ? Number(bracketRate) : null,
      amount: kind === "taxable_income" || kind === "magi" ? parsed(amount) : null,
      irmaa_tier: kind === "irmaa_tier" ? Number(tier) : null,
      aca_fpl_percent: kind === "aca_fpl_percent" ? parsed(fplPercent) : null,
      avoid_niit: avoidNiit,
      avoid_irmaa: avoidIrmaa,
      aca_cap_fpl_percent: acaCap ? parsed(acaCapPercent) : null,
    };
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const next = target();
    if (
      next &&
      (next.kind === "taxable_income" || next.kind === "magi") &&
      (next.amount == null || next.amount < 0)
    ) {
      setStatus(moneyLabel("Enter the amount in today's dollars."));
      return;
    }
    setSaving(true);
    setStatus("");
    try {
      const settings: TaxSettings = {
        ...DEFAULT_TAX_SETTINGS,
        ...plan.tax_settings,
        tax_target: next,
      };
      // Blending needs a target; clearing the target turns it off.
      if (!next) settings.blend_drawdown_to_tax_target = false;
      await onSave(settings);
      setStatus("Saved");
    } catch {
      setStatus("Could not save. Your entries are kept; please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <details id="tax-target" style={{ marginTop: 16 }}>
      <summary>Tax target</summary>
      <p>
        How much taxable income each year should carry. Withdrawal blending (under Drawdown order)
        and conversion or harvest rules set to use the plan tax target fill the room below it.
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
          Target
          <select
            value={kind}
            aria-describedby="tax-target-help"
            onChange={(e) => setKind(e.target.value as TaxTargetKind | "none")}
          >
            {kinds.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        {kind === "federal_bracket" && (
          <label>
            Bracket
            <select value={bracketRate} onChange={(e) => setBracketRate(e.target.value)}>
              {bracketRates.map((rate) => (
                <option key={rate} value={rate}>
                  {ratePercent(rate)}
                </option>
              ))}
              {staleRate != null && (
                <option value={staleRate}>
                  {ratePercent(staleRate)} {STALE_RATE_NOTE}
                </option>
              )}
            </select>
          </label>
        )}
        {(kind === "taxable_income" || kind === "magi") && (
          <label>
            {moneyLabel("Amount (today's $)")}
            <MoneyInput min="0" step="1" required value={amount} onValueChange={setAmount} />
          </label>
        )}
        {kind === "irmaa_tier" && (
          <label>
            Stay below
            <select value={tier} onChange={(e) => setTier(e.target.value)}>
              <option value="1">Any surcharge (tier 1)</option>
              {[2, 3, 4, 5].map((value) => (
                <option key={value} value={value}>
                  Surcharge tier {value}
                </option>
              ))}
            </select>
          </label>
        )}
        {kind === "aca_fpl_percent" && (
          <label>
            Percent of the poverty line
            <input
              type="number"
              min="1"
              max="1000"
              step="1"
              required
              value={fplPercent}
              onChange={(e) => setFplPercent(e.target.value)}
            />
          </label>
        )}
        <p id="tax-target-help" style={{ gridColumn: "1 / -1", margin: 0, fontSize: 13 }}>
          {moneyLabel(selected.help)}
        </p>
        {kind !== "none" && (
          <fieldset style={{ gridColumn: "1 / -1", display: "grid", gap: 8 }}>
            <legend>Also stay under</legend>
            <label>
              <input
                type="checkbox"
                checked={avoidNiit}
                onChange={(e) => setAvoidNiit(e.target.checked)}
              />{" "}
              The 3.8% net investment income tax threshold
            </label>
            <label>
              <input
                type="checkbox"
                checked={avoidIrmaa}
                onChange={(e) => setAvoidIrmaa(e.target.checked)}
              />{" "}
              The first Medicare IRMAA tier (two-year lookback)
            </label>
            <label>
              <input
                type="checkbox"
                checked={acaCap}
                onChange={(e) => setAcaCap(e.target.checked)}
              />{" "}
              A share of the poverty line in ACA years
            </label>
            {acaCap && (
              <label>
                Poverty-line cap (%)
                <input
                  type="number"
                  min="1"
                  max="1000"
                  step="1"
                  value={acaCapPercent}
                  onChange={(e) => setAcaCapPercent(e.target.value)}
                />
              </label>
            )}
          </fieldset>
        )}
        <button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save tax target"}
        </button>
        <span role="status">{status}</span>
      </form>
    </details>
  );
}

/** The opt-in drawdown pass that fills the tax target, shown with the withdrawal order. */
export function BlendDrawdownToggle({
  plan,
  onSave,
}: {
  plan: PlanData;
  onSave: (settings: TaxSettings) => Promise<void>;
}) {
  const hasTarget = plan.tax_settings?.tax_target != null;
  const [checked, setChecked] = useState(plan.tax_settings?.blend_drawdown_to_tax_target ?? false);
  const [status, setStatus] = useState("");
  async function change(next: boolean) {
    setChecked(next);
    setStatus("");
    try {
      await onSave({
        ...DEFAULT_TAX_SETTINGS,
        ...plan.tax_settings,
        blend_drawdown_to_tax_target: next,
      });
    } catch {
      setChecked(!next);
      setStatus("Could not save. Please try again.");
    }
  }
  return (
    <div style={{ margin: "8px 0 12px" }}>
      <label>
        <input
          type="checkbox"
          checked={checked && hasTarget}
          disabled={!hasTarget}
          onChange={(e) => void change(e.target.checked)}
        />{" "}
        Fill the tax target first
      </label>
      <p style={{ margin: "4px 0 0", fontSize: 13 }}>
        {hasTarget
          ? "When spending needs withdrawals, first take tax-deferred money and taxable-account gains, in this order, up to the tax target; the rest follows the order. Cash, Roth, HSA, locked accounts and withdrawals that would be penalized are skipped in that first pass."
          : "Set a tax target under Plan details to fill low brackets from tax-deferred accounts before following this order."}
      </p>
      {status && <p role="alert">{status}</p>}
    </div>
  );
}
