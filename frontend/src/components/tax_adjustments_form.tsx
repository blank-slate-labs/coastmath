import { useState } from "react";
import type {
  PlanData,
  ScheduledTaxChange,
  ScheduledTaxSettings,
  TaxAdjustment,
  TaxAdjustmentKind,
  TaxAdjustmentScope,
  TaxSettings,
  TaxSurchargeBase,
} from "@/types/plan";
import { PARTNER_LABEL, PRIMARY_PERSON_LABEL } from "@/domain/person_labels";
import { dollarsOr, moneyLabel } from "@/utils/format";
import MoneyInput from "@/components/money_input";
import { DEFAULT_TAX_SETTINGS } from "@/domain/tax_settings_defaults";

type When = { kind: "plan" | "year" | "milestone"; year: string; milestone: string };

interface AdjustmentDraft {
  id: string;
  name: string;
  kind: TaxAdjustmentKind;
  deductionType: "above_the_line" | "itemized";
  scope: TaxAdjustmentScope;
  refundable: boolean;
  amount: string;
  ratePercent: string;
  base: TaxSurchargeBase;
  cap: string;
  basis: "today" | "nominal";
  owner: "household" | "self" | "spouse";
  frequency: "once" | "annual" | "every_n_years";
  interval: string;
  start: When;
  end: When;
}

interface ChangeDraft {
  when: When;
  mode: "" | "detailed" | "flat";
  ordinaryPercent: string;
  gainsPercent: string;
  stateRules: "" | "on" | "off";
  /** Settings this form does not edit (adjustments, state brackets) are kept as saved. */
  kept: ScheduledTaxSettings;
}

const bases: { value: TaxSurchargeBase; label: string }[] = [
  { value: "ordinary_taxable_income", label: "Ordinary taxable income" },
  { value: "taxable_income", label: "All taxable income" },
  { value: "capital_gains", label: "Taxable capital gains and qualified dividends" },
  { value: "income_tax", label: "Income tax before credits" },
];

let nextId = 0;
const newId = () => `adj-${Date.now().toString(36)}-${(nextId += 1)}`;
const text = (value: number | null | undefined) => (value == null ? "" : String(value));
const percent = (rate: number | null | undefined) =>
  rate == null ? "" : String(Math.round(rate * 1e6) / 1e4);
const whenOf = (year?: number, milestone?: string, fallback: When["kind"] = "plan"): When => ({
  kind: year != null ? "year" : milestone ? "milestone" : fallback,
  year: text(year),
  milestone: milestone ?? "",
});

function toDraft(row: TaxAdjustment): AdjustmentDraft {
  return {
    id: row.id,
    name: row.name ?? "",
    kind: row.kind,
    deductionType: row.deduction_type ?? "above_the_line",
    scope: row.scope,
    refundable: row.refundable ?? false,
    amount: text(row.amount),
    ratePercent: percent(row.rate),
    base: row.base ?? "taxable_income",
    cap: text(row.max_amount),
    basis: row.amount_basis,
    owner: row.owner ?? "household",
    frequency: row.frequency,
    interval: text(row.interval_years ?? 2),
    start: whenOf(row.start_year, row.start_milestone_id),
    end: whenOf(row.end_year, row.end_milestone_id),
  };
}

function toChangeDraft(row: ScheduledTaxChange): ChangeDraft {
  const { mode, ordinary_income_tax_rate, capital_gains_tax_rate, state_deduction_rules, ...kept } =
    row.settings;
  return {
    when: whenOf(row.year, row.milestone_id, "year"),
    mode: mode ?? "",
    ordinaryPercent: percent(ordinary_income_tax_rate),
    gainsPercent: percent(capital_gains_tax_rate),
    stateRules: state_deduction_rules == null ? "" : state_deduction_rules ? "on" : "off",
    kept,
  };
}

function blankAdjustment(): AdjustmentDraft {
  return toDraft({
    id: newId(),
    kind: "deduction",
    deduction_type: "above_the_line",
    scope: "both",
    amount_basis: "today",
    frequency: "annual",
  });
}

const numberOrError = (value: string, label: string, errors: string[]): number | undefined => {
  if (value.trim() === "") return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    errors.push(`${label} must be a number of zero or more.`);
    return undefined;
  }
  return parsed;
};

function yearWindow(
  prefix: "start" | "end",
  when: When,
  label: string,
  errors: string[],
): Partial<TaxAdjustment> {
  if (when.kind === "year") {
    const year = Number(when.year);
    if (!Number.isInteger(year) || year < 1900 || year > 2300)
      errors.push(`${label}: enter a year.`);
    return { [`${prefix}_year`]: year };
  }
  if (when.kind === "milestone") {
    if (!when.milestone) errors.push(`${label}: choose a milestone.`);
    return { [`${prefix}_milestone_id`]: when.milestone };
  }
  return {};
}

function fromDraft(draft: AdjustmentDraft, errors: string[]): TaxAdjustment {
  const label = draft.name || "Adjustment";
  const row: TaxAdjustment = {
    id: draft.id,
    name: draft.name.trim(),
    kind: draft.kind,
    scope:
      draft.kind === "deduction" ? draft.scope : draft.scope === "both" ? "federal" : draft.scope,
    amount_basis: draft.basis,
    owner: draft.owner,
    frequency: draft.frequency,
  };
  if (draft.kind === "deduction") row.deduction_type = draft.deductionType;
  if (draft.kind === "credit" && draft.refundable) row.refundable = true;
  if (draft.kind === "surcharge") {
    const rate = numberOrError(draft.ratePercent, `${label} rate`, errors);
    if (rate == null || rate <= 0 || rate > 100)
      errors.push(`${label}: enter a rate above 0% and at most 100%.`);
    else row.rate = rate / 100;
    row.base = draft.base;
    const cap = numberOrError(draft.cap, `${label} cap`, errors);
    if (cap != null) row.max_amount = cap;
  } else {
    const amount = numberOrError(draft.amount, `${label} amount`, errors);
    if (amount == null) errors.push(`${label}: enter an amount.`);
    else row.amount = amount;
  }
  if (draft.frequency === "every_n_years") {
    const interval = Number(draft.interval);
    if (!Number.isInteger(interval) || interval < 2 || interval > 50)
      errors.push(`${label}: repeat every 2 to 50 years.`);
    row.interval_years = interval;
  }
  Object.assign(row, yearWindow("start", draft.start, `${label} start`, errors));
  if (draft.frequency !== "once")
    Object.assign(row, yearWindow("end", draft.end, `${label} end`, errors));
  if (row.start_year != null && row.end_year != null && row.end_year < row.start_year) {
    errors.push(`${label}: the end year must be on or after the start year.`);
  }
  return row;
}

function fromChangeDraft(draft: ChangeDraft, index: number, errors: string[]): ScheduledTaxChange {
  const label = `Scheduled change ${index + 1}`;
  const settings: ScheduledTaxSettings = { ...draft.kept };
  if (draft.mode) settings.mode = draft.mode;
  const ordinary = numberOrError(draft.ordinaryPercent, `${label} income tax rate`, errors);
  if (ordinary != null) settings.ordinary_income_tax_rate = ordinary / 100;
  const gains = numberOrError(draft.gainsPercent, `${label} capital gains rate`, errors);
  if (gains != null) settings.capital_gains_tax_rate = gains / 100;
  if ([ordinary, gains].some((value) => value != null && value > 100))
    errors.push(`${label}: rates are at most 100%.`);
  if (draft.stateRules) settings.state_deduction_rules = draft.stateRules === "on";
  if (Object.keys(settings).length === 0) errors.push(`${label}: change at least one setting.`);
  const when = yearWindow("start", draft.when, label, errors);
  return {
    ...(when.start_year != null
      ? { year: when.start_year }
      : { milestone_id: when.start_milestone_id }),
    settings,
  };
}

function WhenFields({
  legend,
  when,
  onChange,
  milestones,
  allowPlan,
}: {
  legend: string;
  when: When;
  onChange: (next: When) => void;
  milestones: PlanData["milestones"];
  allowPlan: string | null;
}) {
  return (
    <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
      <legend>{legend}</legend>
      <select
        aria-label={`${legend} type`}
        value={when.kind}
        onChange={(e) => onChange({ ...when, kind: e.target.value as When["kind"] })}
      >
        {allowPlan && <option value="plan">{allowPlan}</option>}
        <option value="year">Year</option>
        <option value="milestone">Milestone</option>
      </select>
      {when.kind === "year" && (
        <input
          aria-label={`${legend} year`}
          inputMode="numeric"
          value={when.year}
          onChange={(e) => onChange({ ...when, year: e.target.value })}
        />
      )}
      {when.kind === "milestone" && (
        <select
          aria-label={`${legend} milestone`}
          value={when.milestone}
          onChange={(e) => onChange({ ...when, milestone: e.target.value })}
        >
          <option value="">Choose…</option>
          {milestones.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      )}
    </fieldset>
  );
}

export default function TaxAdjustmentsForm({
  plan,
  onSave,
}: {
  plan: PlanData;
  onSave: (settings: TaxSettings) => Promise<void>;
}) {
  const saved = plan.tax_settings;
  const [rows, setRows] = useState<AdjustmentDraft[]>(() =>
    (saved?.adjustments ?? []).map(toDraft),
  );
  const [changes, setChanges] = useState<ChangeDraft[]>(() =>
    (saved?.scheduled_changes ?? []).map(toChangeDraft),
  );
  const [stateRules, setStateRules] = useState(saved?.state_deduction_rules ?? false);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const milestones = plan.milestones ?? [];
  const hasSpouse = plan.spouse != null;

  const update = (index: number, patch: Partial<AdjustmentDraft>) =>
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  const updateChange = (index: number, patch: Partial<ChangeDraft>) =>
    setChanges((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const errors: string[] = [];
    const adjustments = rows.map((row) => fromDraft(row, errors));
    const scheduled = changes.map((row, index) => fromChangeDraft(row, index, errors));
    if (errors.length) {
      setStatus(errors[0]);
      return;
    }
    setSaving(true);
    setStatus("");
    try {
      await onSave({
        ...DEFAULT_TAX_SETTINGS,
        ...plan.tax_settings,
        adjustments,
        scheduled_changes: scheduled,
        state_deduction_rules: stateRules,
      });
      setStatus("Saved");
    } catch {
      setStatus("Could not save. Your entries are kept; please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <details id="tax-adjustments" style={{ marginTop: 16 }}>
      <summary>Tax adjustments and scheduled changes</summary>
      <p>
        Deductions, credits and surcharges you enter for specific years, and tax settings that
        change from a year or milestone. Amounts are per tax year and are not prorated in a partial
        year.
      </p>
      <form onSubmit={save} style={{ display: "grid", gap: 12 }}>
        <label>
          <input
            type="checkbox"
            checked={stateRules}
            onChange={(e) => setStateRules(e.target.checked)}
          />{" "}
          Use state deduction rules where supported
          <span style={{ display: "block", fontSize: 12 }}>
            State itemized-or-standard choice, exemption phaseouts and any federal income tax
            deduction, for states with supported rules. Other states keep the standard deduction
            estimate.
          </span>
        </label>

        {rows.map((row, index) => (
          <fieldset
            key={row.id}
            aria-label={`Adjustment ${index + 1}`}
            style={{
              display: "grid",
              gap: 8,
              gridTemplateColumns: "repeat(auto-fit, minmax(min(200px, 100%), 1fr))",
            }}
          >
            <legend>Adjustment {index + 1}</legend>
            <label>
              Name
              <input
                value={row.name}
                maxLength={120}
                onChange={(e) => update(index, { name: e.target.value })}
              />
            </label>
            <label>
              Type
              <select
                value={row.kind}
                onChange={(e) => update(index, { kind: e.target.value as TaxAdjustmentKind })}
              >
                <option value="deduction">Deduction</option>
                <option value="credit">Credit</option>
                <option value="surcharge">Surcharge</option>
              </select>
            </label>
            {row.kind === "deduction" && (
              <label>
                Deduction
                <select
                  value={row.deductionType}
                  onChange={(e) =>
                    update(index, {
                      deductionType: e.target.value as AdjustmentDraft["deductionType"],
                    })
                  }
                >
                  <option value="above_the_line">Above the line (lowers AGI)</option>
                  <option value="itemized">Itemized (only when itemizing)</option>
                </select>
              </label>
            )}
            <label>
              Return
              <select
                value={row.kind !== "deduction" && row.scope === "both" ? "federal" : row.scope}
                onChange={(e) => update(index, { scope: e.target.value as TaxAdjustmentScope })}
              >
                <option value="federal">Federal</option>
                <option value="state">State</option>
                {row.kind === "deduction" && <option value="both">Federal and state</option>}
              </select>
            </label>
            {row.kind === "credit" && (
              <label>
                <input
                  type="checkbox"
                  checked={row.refundable}
                  onChange={(e) => update(index, { refundable: e.target.checked })}
                />{" "}
                Refundable
              </label>
            )}
            {row.kind === "surcharge" ? (
              <>
                <label>
                  Rate (%)
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                    value={row.ratePercent}
                    onChange={(e) => update(index, { ratePercent: e.target.value })}
                  />
                </label>
                <label>
                  Applied to
                  <select
                    value={row.base}
                    onChange={(e) => update(index, { base: e.target.value as TaxSurchargeBase })}
                  >
                    {bases.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  {moneyLabel("Maximum per year ($, optional)")}
                  <MoneyInput
                    min="0"
                    step="0.01"
                    value={row.cap}
                    onValueChange={(value) => update(index, { cap: value })}
                  />
                </label>
              </>
            ) : (
              <label>
                {moneyLabel("Amount per year ($)")}
                <MoneyInput
                  min="0"
                  step="0.01"
                  value={row.amount}
                  onValueChange={(value) => update(index, { amount: value })}
                />
              </label>
            )}
            <label>
              {dollarsOr("Dollars", "Amount basis")}
              <select
                value={row.basis}
                onChange={(e) =>
                  update(index, { basis: e.target.value as AdjustmentDraft["basis"] })
                }
              >
                <option value="today">
                  {moneyLabel("Today's dollars (rises with inflation)")}
                </option>
                <option value="nominal">
                  {dollarsOr(
                    "Future dollars (as entered)",
                    "Future (nominal) amounts (as entered)",
                  )}
                </option>
              </select>
            </label>
            <label>
              Applies
              <select
                value={row.frequency}
                onChange={(e) =>
                  update(index, { frequency: e.target.value as AdjustmentDraft["frequency"] })
                }
              >
                <option value="once">Once</option>
                <option value="annual">Every year</option>
                <option value="every_n_years">Every few years</option>
              </select>
            </label>
            {row.frequency === "every_n_years" && (
              <label>
                Every (years)
                <input
                  type="number"
                  min="2"
                  max="50"
                  value={row.interval}
                  onChange={(e) => update(index, { interval: e.target.value })}
                />
              </label>
            )}
            <WhenFields
              legend={row.frequency === "once" ? "Year" : "Start"}
              when={row.start}
              milestones={milestones}
              allowPlan="Plan start"
              onChange={(start) => update(index, { start })}
            />
            {row.frequency !== "once" && (
              <WhenFields
                legend="End (inclusive)"
                when={row.end}
                milestones={milestones}
                allowPlan="No end"
                onChange={(end) => update(index, { end })}
              />
            )}
            <label>
              Whose
              <select
                value={row.owner}
                onChange={(e) =>
                  update(index, { owner: e.target.value as AdjustmentDraft["owner"] })
                }
              >
                <option value="household">Household</option>
                <option value="self">{PRIMARY_PERSON_LABEL} (ends after their death)</option>
                {(hasSpouse || row.owner === "spouse") && (
                  <option value="spouse">{PARTNER_LABEL} (ends after their death)</option>
                )}
              </select>
            </label>
            <button
              type="button"
              onClick={() => setRows((current) => current.filter((_, i) => i !== index))}
            >
              Remove adjustment
            </button>
          </fieldset>
        ))}
        <button type="button" onClick={() => setRows((current) => [...current, blankAdjustment()])}>
          Add adjustment
        </button>

        {changes.map((change, index) => (
          <fieldset
            key={index}
            aria-label={`Scheduled change ${index + 1}`}
            style={{
              display: "grid",
              gap: 8,
              gridTemplateColumns: "repeat(auto-fit, minmax(min(200px, 100%), 1fr))",
            }}
          >
            <legend>Scheduled change {index + 1}</legend>
            <WhenFields
              legend="From"
              when={change.when}
              milestones={milestones}
              allowPlan={null}
              onChange={(when) => updateChange(index, { when })}
            />
            <label>
              Tax mode
              <select
                value={change.mode}
                onChange={(e) =>
                  updateChange(index, { mode: e.target.value as ChangeDraft["mode"] })
                }
              >
                <option value="">No change</option>
                <option value="detailed">Detailed</option>
                <option value="flat">Flat rate</option>
              </select>
            </label>
            <label>
              Flat income tax rate (%)
              <input
                type="number"
                min="0"
                max="100"
                step="0.01"
                value={change.ordinaryPercent}
                placeholder="No change"
                onChange={(e) => updateChange(index, { ordinaryPercent: e.target.value })}
              />
            </label>
            <label>
              Flat capital gains rate (%)
              <input
                type="number"
                min="0"
                max="100"
                step="0.01"
                value={change.gainsPercent}
                placeholder="No change"
                onChange={(e) => updateChange(index, { gainsPercent: e.target.value })}
              />
            </label>
            <label>
              State deduction rules
              <select
                value={change.stateRules}
                onChange={(e) =>
                  updateChange(index, { stateRules: e.target.value as ChangeDraft["stateRules"] })
                }
              >
                <option value="">No change</option>
                <option value="on">Use where supported</option>
                <option value="off">Don't use</option>
              </select>
            </label>
            {Object.keys(change.kept).length > 0 && (
              <p style={{ margin: 0, fontSize: 12 }}>
                Also changes settings saved elsewhere (kept).
              </p>
            )}
            <button
              type="button"
              onClick={() => setChanges((current) => current.filter((_, i) => i !== index))}
            >
              Remove change
            </button>
          </fieldset>
        ))}
        <button
          type="button"
          onClick={() =>
            setChanges((current) => [
              ...current,
              {
                when: { kind: "year", year: "", milestone: "" },
                mode: "",
                ordinaryPercent: "",
                gainsPercent: "",
                stateRules: "",
                kept: {},
              },
            ])
          }
        >
          Add scheduled change
        </button>
        <p style={{ margin: 0, fontSize: 13 }}>
          A change lasts until a later change replaces the same setting. Changes from the same year
          apply in list order; a milestone that is never reached never applies.
        </p>
        <button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save tax adjustments"}
        </button>
        <span role="status">{status}</span>
      </form>
    </details>
  );
}
