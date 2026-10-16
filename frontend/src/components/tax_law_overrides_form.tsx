import { useState } from "react";
import type { PlanData, TaxSettings } from "@/types/plan";
import { moneyLabel } from "@/utils/format";
import MoneyInput from "@/components/money_input";
import { PARTNER_LABEL, PRIMARY_PERSON_LABEL } from "@/domain/person_labels";
import { TOP_BRACKET_BOUND } from "@/domain/federal_bracket_rates";
import { DEFAULT_TAX_SETTINGS } from "@/domain/tax_settings_defaults";

export { TOP_BRACKET_BOUND };
const MIN_RMD_AGE = 70;
const MAX_RMD_AGE = 80;

interface BracketRow {
  upper: string;
  rate: string;
}

const text = (value: number | null | undefined) => (value == null ? "" : String(value));
const percentText = (rate: number) => String(Number((rate * 100).toFixed(6)));

function rowsFrom(brackets: Array<[number, number]> | null | undefined): BracketRow[] {
  if (!brackets?.length) return [{ upper: "", rate: "" }];
  return brackets.map(([upper, rate]) => ({
    upper: upper >= TOP_BRACKET_BOUND ? "" : String(upper),
    rate: percentText(rate),
  }));
}

/** Validated (upper bound, rate) pairs; a blank last bound is the open top bracket. */
export function readBrackets(rows: BracketRow[]): Array<[number, number]> {
  const result: Array<[number, number]> = [];
  let previous = 0;
  rows.forEach((row, index) => {
    const last = index === rows.length - 1;
    const rate = Number(row.rate);
    if (row.rate.trim() === "" || !Number.isFinite(rate) || rate < 0 || rate > 100) {
      throw new Error(`Bracket ${index + 1}: enter a rate between 0 and 100%.`);
    }
    let upper = TOP_BRACKET_BOUND;
    if (row.upper.trim() !== "" || !last) {
      upper = Number(row.upper);
      if (row.upper.trim() === "" || !Number.isFinite(upper) || upper <= previous) {
        throw new Error(
          `Bracket ${index + 1}: enter an upper bound above ${previous.toLocaleString()}${last ? ", or leave the last one blank" : ""}.`,
        );
      }
    }
    result.push([upper, rate / 100]);
    previous = upper;
  });
  return result;
}

export default function TaxLawOverridesForm({
  plan,
  onSave,
}: {
  plan: PlanData;
  onSave: (settings: TaxSettings) => Promise<void>;
}) {
  const saved = plan.tax_settings;
  const [custom, setCustom] = useState(!!saved?.federal_brackets?.length);
  const [rows, setRows] = useState<BracketRow[]>(rowsFrom(saved?.federal_brackets));
  const [deduction, setDeduction] = useState(text(saved?.federal_standard_deduction));
  const [indexed, setIndexed] = useState(saved?.federal_overrides_indexed ?? true);
  const [selfAge, setSelfAge] = useState(text(saved?.rmd_start_ages?.self));
  const [spouseAge, setSpouseAge] = useState(text(saved?.rmd_start_ages?.spouse));
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const hasPartner = plan.spouse != null;

  function rmdAge(raw: string, who: string): number | undefined {
    if (raw.trim() === "") return undefined;
    const age = Number(raw);
    if (!Number.isInteger(age) || age < MIN_RMD_AGE || age > MAX_RMD_AGE) {
      throw new Error(
        `${who} RMD start age must be a whole number from ${MIN_RMD_AGE} to ${MAX_RMD_AGE}.`,
      );
    }
    return age;
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setStatus("");
    setError(null);
    let next: TaxSettings;
    try {
      const amount = deduction.trim() === "" ? null : Number(deduction);
      if (amount != null && (!Number.isFinite(amount) || amount < 0))
        throw new Error("Standard deduction must be zero or more.");
      const ages: Partial<Record<"self" | "spouse", number>> = {};
      const own = rmdAge(selfAge, PRIMARY_PERSON_LABEL);
      if (own != null) ages.self = own;
      const partner = hasPartner ? rmdAge(spouseAge, PARTNER_LABEL) : undefined;
      if (partner != null) ages.spouse = partner;
      next = { ...DEFAULT_TAX_SETTINGS, ...saved };
      delete next.federal_brackets;
      delete next.federal_standard_deduction;
      delete next.federal_overrides_indexed;
      delete next.rmd_start_ages;
      if (custom) next.federal_brackets = readBrackets(rows);
      if (amount != null) next.federal_standard_deduction = amount;
      if (!indexed && (custom || amount != null)) next.federal_overrides_indexed = false;
      if (Object.keys(ages).length) next.rmd_start_ages = ages;
    } catch (err) {
      setError((err as Error).message);
      return;
    }
    setSaving(true);
    try {
      await onSave(next);
      setStatus("Saved");
    } catch {
      setStatus("Could not save. Your entries are kept; please try again.");
    } finally {
      setSaving(false);
    }
  }

  const updateRow = (index: number, change: Partial<BracketRow>) =>
    setRows(rows.map((row, i) => (i === index ? { ...row, ...change } : row)));

  return (
    <details id="tax-law-overrides" style={{ marginTop: 16 }}>
      <summary>Tax law assumptions</summary>
      <p>Model a possible change in law. Blank fields follow current law.</p>
      <form
        onSubmit={save}
        style={{
          display: "grid",
          gap: 12,
          gridTemplateColumns: "repeat(auto-fit, minmax(min(240px, 100%), 1fr))",
        }}
      >
        <label style={{ gridColumn: "1 / -1" }}>
          <input type="checkbox" checked={custom} onChange={(e) => setCustom(e.target.checked)} />{" "}
          Use custom federal income tax brackets
          <span style={{ display: "block", fontSize: 12 }}>
            Replaces the ordinary-income brackets for every filing status. Capital gains rates,
            NIIT, AMT and credits follow current law.
          </span>
        </label>
        {custom && (
          <fieldset
            style={{
              gridColumn: "1 / -1",
              border: "none",
              padding: 0,
              margin: 0,
              display: "grid",
              gap: 8,
            }}
          >
            <legend style={{ fontSize: 13 }}>Federal brackets on taxable income</legend>
            {rows.map((row, index) => (
              <div
                key={index}
                style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "end" }}
              >
                <label>
                  {moneyLabel(`Bracket ${index + 1} up to ($)`)}
                  <MoneyInput
                    min="0"
                    step="1"
                    value={row.upper}
                    placeholder={index === rows.length - 1 ? "No limit" : undefined}
                    onValueChange={(value) => updateRow(index, { upper: value })}
                  />
                </label>
                <label>
                  {`Bracket ${index + 1} rate (%)`}
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                    value={row.rate}
                    onChange={(e) => updateRow(index, { rate: e.target.value })}
                  />
                </label>
                {rows.length > 1 && (
                  <button
                    type="button"
                    aria-label={`Remove bracket ${index + 1}`}
                    onClick={() => setRows(rows.filter((_, i) => i !== index))}
                  >
                    Remove
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              style={{ justifySelf: "start" }}
              onClick={() => setRows([...rows, { upper: "", rate: "" }])}
            >
              Add bracket
            </button>
          </fieldset>
        )}
        <label>
          {moneyLabel("Federal standard deduction ($, optional)")}
          <MoneyInput
            min="0"
            step="1"
            value={deduction}
            placeholder="Current law"
            onValueChange={setDeduction}
          />
          <span style={{ display: "block", fontSize: 12 }}>
            Replaces the basic amount; the extra amount at 65 and the senior deduction still apply.
          </span>
        </label>
        <label>
          <input type="checkbox" checked={indexed} onChange={(e) => setIndexed(e.target.checked)} />{" "}
          Grow custom federal amounts with inflation
          <span style={{ display: "block", fontSize: 12 }}>
            Amounts are in today's dollars. Unchecked, they stay fixed in every year.
          </span>
        </label>
        <label>
          {PRIMARY_PERSON_LABEL} RMD start age (optional)
          <input
            type="number"
            min={MIN_RMD_AGE}
            max={MAX_RMD_AGE}
            step="1"
            value={selfAge}
            placeholder="Current law"
            onChange={(e) => setSelfAge(e.target.value)}
          />
        </label>
        {hasPartner && (
          <label>
            {PARTNER_LABEL} RMD start age (optional)
            <input
              type="number"
              min={MIN_RMD_AGE}
              max={MAX_RMD_AGE}
              step="1"
              value={spouseAge}
              placeholder="Current law"
              onChange={(e) => setSpouseAge(e.target.value)}
            />
          </label>
        )}
        <p style={{ gridColumn: "1 / -1", margin: 0, fontSize: 13 }}>
          An RMD start age replaces the SECURE 2.0 age (72, 73 or 75 by birth year) for that
          person's own accounts. Inherited accounts follow current rules.
        </p>
        {error && (
          <p role="alert" style={{ gridColumn: "1 / -1", margin: 0 }}>
            {error}
          </p>
        )}
        <button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save tax law assumptions"}
        </button>
        <span role="status">{status}</span>
      </form>
    </details>
  );
}
