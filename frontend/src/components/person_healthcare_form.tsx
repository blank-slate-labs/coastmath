import type { PersonHealthcareSettings } from "@/types/plan";
import { ownerLabel } from "@/domain/person_labels";
import { moneyLabel } from "@/utils/format";
import MoneyInput from "./money_input";

type Owner = PersonHealthcareSettings["owner"];
type NumericKey =
  | "itemized_annual_amount"
  | "itemized_start_age"
  | "itemized_end_age"
  | "medical_inflation_rate"
  | "medicare_start_age"
  | "medicare_part_a_premium_monthly"
  | "medicare_part_a_quarters"
  | "medicare_part_d_plan_premium_monthly"
  | "medicare_supplement_premium_monthly"
  | "out_of_pocket_annual"
  | "monthly_cost"
  | "duration_months"
  | "start_year"
  | "start_month"
  | "months_before_longevity"
  | "covered_fraction"
  | "inflation_rate"
  | "amount_reference_year";
export interface PersonHealthcareDraft {
  mode: PersonHealthcareSettings["mode"] | "inherit";
  numbers: Record<NumericKey, string>;
  aca: boolean;
  medicare: boolean;
  partB: boolean;
  partD: boolean;
  irmaa: boolean;
  ltc: boolean;
  ltcStart: "calendar" | "longevity";
  original?: PersonHealthcareSettings;
}
const text = (value: number | null | undefined) => (value == null ? "" : String(value));
const percent = (value: number | null | undefined) =>
  value == null ? "" : String(Number((value * 100).toFixed(8)));
export function personHealthcareDraft(value?: PersonHealthcareSettings): PersonHealthcareDraft {
  const ltc = value?.long_term_care;
  return {
    mode: value?.mode ?? "inherit",
    original: value,
    aca: value?.aca_enabled ?? false,
    medicare: value?.medicare_enabled ?? true,
    partB: value?.medicare_part_b ?? true,
    partD: value?.medicare_part_d ?? true,
    irmaa: value?.medicare_apply_irmaa ?? true,
    ltc: ltc != null,
    ltcStart: ltc?.months_before_longevity != null ? "longevity" : "calendar",
    numbers: {
      itemized_annual_amount: text(value?.itemized_annual_amount),
      itemized_start_age: text(value?.itemized_start_age ?? 0),
      itemized_end_age: text(value?.itemized_end_age),
      medical_inflation_rate: percent(value?.medical_inflation_rate),
      medicare_start_age: text(value?.medicare_start_age ?? 65),
      medicare_part_a_premium_monthly: text(value?.medicare_part_a_premium_monthly ?? 0),
      medicare_part_a_quarters: text(value?.medicare_part_a_quarters),
      medicare_part_d_plan_premium_monthly: text(value?.medicare_part_d_plan_premium_monthly ?? 0),
      medicare_supplement_premium_monthly: text(value?.medicare_supplement_premium_monthly ?? 0),
      out_of_pocket_annual: text(value?.out_of_pocket_annual),
      monthly_cost: text(ltc?.monthly_cost),
      duration_months: text(ltc?.duration_months),
      start_year: text(ltc?.start_year),
      start_month: text(ltc?.start_month ?? 1),
      months_before_longevity: text(ltc?.months_before_longevity),
      covered_fraction: percent(ltc?.covered_fraction ?? 0),
      inflation_rate: percent(ltc?.inflation_rate),
      amount_reference_year: text(ltc?.amount_reference_year),
    },
  };
}

export function readPersonHealthcare(
  draft: PersonHealthcareDraft,
  owner: Owner,
  planStartYear?: number,
): PersonHealthcareSettings | undefined {
  if (draft.mode === "inherit") return undefined;
  if (
    draft.original &&
    JSON.stringify(draft) === JSON.stringify(personHealthcareDraft(draft.original))
  )
    return draft.original;
  const number = (
    key: NumericKey,
    label: string,
    min = 0,
    max = Infinity,
    required = false,
    whole = false,
  ): number | null => {
    const raw = draft.numbers[key];
    if (raw.trim() === "" && !required) return null;
    const value = Number(raw);
    if (
      raw.trim() === "" ||
      !Number.isFinite(value) ||
      value < min ||
      value > max ||
      (whole && !Number.isInteger(value))
    )
      throw new Error(
        `${ownerLabel(owner)} ${label} must be ${whole ? "a whole number " : ""}between ${min} and ${Number.isFinite(max) ? max : "a finite positive amount"}.`,
      );
    return value;
  };
  const settings: PersonHealthcareSettings = {
    ...draft.original,
    owner,
    mode: draft.mode,
    itemized_annual_amount:
      draft.mode === "itemized"
        ? number("itemized_annual_amount", "itemized annual cost", 0, Infinity, true)
        : null,
    out_of_pocket_annual:
      draft.mode === "coverage" ? number("out_of_pocket_annual", "out-of-pocket budget") : null,
    medical_inflation_rate: null,
  };
  const medical = number("medical_inflation_rate", "medical inflation", -50, 50);
  settings.medical_inflation_rate = medical == null ? null : medical / 100;
  if (draft.mode === "itemized") {
    settings.itemized_start_age = number("itemized_start_age", "start age", 0, 120, true, true)!;
    settings.itemized_end_age = number(
      "itemized_end_age",
      "end age",
      settings.itemized_start_age,
      130,
      false,
      true,
    );
  }
  if (draft.mode === "coverage")
    Object.assign(settings, {
      aca_enabled: draft.aca,
      medicare_enabled: draft.medicare,
      medicare_start_age: number("medicare_start_age", "Medicare start age", 65, 120, true, true),
      medicare_part_b: draft.partB,
      medicare_part_d: draft.partD,
      medicare_apply_irmaa: draft.irmaa,
      medicare_part_a_premium_monthly: number(
        "medicare_part_a_premium_monthly",
        "Part A monthly premium",
        0,
        Infinity,
        true,
      ),
      medicare_part_a_quarters: number(
        "medicare_part_a_quarters",
        "Medicare-covered quarters",
        0,
        200,
        false,
        true,
      ),
      medicare_part_d_plan_premium_monthly: number(
        "medicare_part_d_plan_premium_monthly",
        "Part D monthly premium",
        0,
        Infinity,
        true,
      ),
      medicare_supplement_premium_monthly: number(
        "medicare_supplement_premium_monthly",
        "supplement monthly premium",
        0,
        Infinity,
        true,
      ),
    });
  settings.long_term_care = null;
  if (draft.ltc) {
    const rate = number("inflation_rate", "LTC inflation", -50, 50);
    const reference = number(
      "amount_reference_year",
      "LTC amount reference year",
      1900,
      2300,
      false,
      true,
    );
    if (reference != null && planStartYear != null && reference !== planStartYear && rate == null)
      throw new Error(
        "Enter LTC inflation when the amount reference year differs from the plan start year.",
      );
    settings.long_term_care = {
      ...draft.original?.long_term_care,
      monthly_cost: number("monthly_cost", "LTC monthly cost", 0, Infinity, true)!,
      duration_months: number("duration_months", "LTC duration", 1, 600, true, true)!,
      start_year:
        draft.ltcStart === "calendar"
          ? number("start_year", "LTC start year", 1900, 2300, true, true)
          : null,
      start_month:
        draft.ltcStart === "calendar"
          ? number("start_month", "LTC start month", 1, 12, true, true)!
          : 1,
      months_before_longevity:
        draft.ltcStart === "longevity"
          ? number("months_before_longevity", "months before longevity", 1, 600, true, true)
          : null,
      covered_fraction: number("covered_fraction", "LTC covered share", 0, 100, true)! / 100,
      inflation_rate: rate == null ? null : rate / 100,
      amount_reference_year: reference,
    };
  }
  return settings;
}

const moneyKeys = new Set<NumericKey>([
  "itemized_annual_amount",
  "medicare_part_a_premium_monthly",
  "medicare_part_d_plan_premium_monthly",
  "medicare_supplement_premium_monthly",
  "out_of_pocket_annual",
  "monthly_cost",
]);
const group: React.CSSProperties = {
  display: "grid",
  gap: 10,
  border: "1px solid var(--surface-border)",
  borderRadius: 8,
  padding: 12,
  minWidth: 0,
};
const help: React.CSSProperties = { margin: 0, color: "var(--text-secondary)", fontSize: 12 };
export default function PersonHealthcareForm({
  owner,
  value,
  onChange,
}: {
  owner: Owner;
  value: PersonHealthcareDraft;
  onChange: (value: PersonHealthcareDraft) => void;
}) {
  const who = ownerLabel(owner);
  const input = (key: NumericKey, label: string, min = 0, max?: number, step: number = 0.01) => {
    const set = (raw: string) => onChange({ ...value, numbers: { ...value.numbers, [key]: raw } });
    const field = {
      "aria-label": `${who} ${moneyLabel(label)}`,
      min,
      max,
      step,
      style: { width: "100%", display: "block" },
    };
    return (
      <label>
        {moneyLabel(label)}
        {moneyKeys.has(key) ? (
          <MoneyInput {...field} value={value.numbers[key]} onValueChange={set} />
        ) : (
          <input
            {...field}
            type="number"
            value={value.numbers[key]}
            onChange={(e) => set(e.target.value)}
          />
        )}
      </label>
    );
  };
  const toggle = (key: "aca" | "medicare" | "partB" | "partD" | "irmaa" | "ltc", label: string) => (
    <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <input
        type="checkbox"
        aria-label={`${who} ${label}`}
        checked={value[key]}
        onChange={(e) => onChange({ ...value, [key]: e.target.checked })}
      />
      {label}
    </label>
  );
  return (
    <fieldset style={group}>
      <legend>{who} healthcare</legend>
      <label>
        Medical cost method
        <select
          aria-label={`${who} medical cost method`}
          value={value.mode}
          onChange={(e) =>
            onChange({ ...value, mode: e.target.value as PersonHealthcareDraft["mode"] })
          }
          style={{ display: "block", width: "100%" }}
        >
          <option value="inherit">Use shared settings</option>
          <option value="off">Off</option>
          <option value="itemized">Itemized medical budget</option>
          <option value="coverage">Coverage premiums + optional budget</option>
        </select>
      </label>
      {value.mode !== "inherit" && <p style={help}>Overrides shared settings for this person.</p>}
      {value.mode !== "inherit" && (
        <>
          {value.mode === "itemized" && (
            <>
              {input("itemized_annual_amount", "Itemized medical cost ($ per year)")}
              {input("itemized_start_age", "Medical budget starts at age", 0, 120, 1)}
              {input("itemized_end_age", "Medical budget ends at age (optional)", 0, 130, 1)}
            </>
          )}
          {value.mode !== "off" &&
            input(
              "medical_inflation_rate",
              "Medical inflation (% per year, optional)",
              -50,
              50,
              0.1,
            )}
          {value.mode === "coverage" && (
            <>
              {toggle("aca", "Include marketplace coverage")}
              <p style={help}>
                Marketplace coverage uses the shared policy premiums and income settings above.
              </p>
              {toggle("medicare", "Include Medicare coverage")}
              {value.medicare && (
                <>
                  {input("medicare_start_age", "Medicare starts at age", 65, 120, 1)}
                  {toggle("partB", "Include Part B")}
                  {toggle("partD", "Include Part D")}
                  {toggle("irmaa", "Apply IRMAA surcharges")}
                  {input(
                    "medicare_part_a_quarters",
                    "Medicare-covered quarters for Part A (optional)",
                    0,
                    200,
                    1,
                  )}
                  <p style={help}>
                    Fewer than 40 quarters (yours or a qualifying spouse's) adds the published Part
                    A premium: reduced at 30–39, full below 30. Blank adds none. A premium entered
                    below is added on top.
                  </p>
                  {input("medicare_part_a_premium_monthly", "Other Part A premium ($ per month)")}
                  {input("medicare_part_d_plan_premium_monthly", "Part D premium ($ per month)")}
                  {input("medicare_supplement_premium_monthly", "Supplement premium ($ per month)")}
                </>
              )}
              {input("out_of_pocket_annual", "Out-of-pocket budget ($ per year, optional)")}
              <p style={help}>Blank means unknown; 0 means no cost.</p>
            </>
          )}
          {toggle("ltc", "Include a long-term-care budget")}
          {value.ltc && (
            <div style={{ display: "grid", gap: 10 }}>
              <p style={help}>Covered share reduces costs; eligibility is not modeled.</p>
              {input("monthly_cost", "LTC cost ($ per month)")}
              {input("duration_months", "LTC duration (months)", 1, 600, 1)}
              <label>
                LTC timing
                <select
                  aria-label={`${who} LTC timing`}
                  value={value.ltcStart}
                  onChange={(e) =>
                    onChange({ ...value, ltcStart: e.target.value as "calendar" | "longevity" })
                  }
                >
                  <option value="calendar">Calendar start</option>
                  <option value="longevity">Before modeled longevity</option>
                </select>
              </label>
              {value.ltcStart === "calendar" ? (
                <>
                  {input("start_year", "LTC start year", 1900, 2300, 1)}
                  {input("start_month", "LTC start month", 1, 12, 1)}
                </>
              ) : (
                input("months_before_longevity", "LTC months before longevity", 1, 600, 1)
              )}
              {input("covered_fraction", "LTC covered share (%)", 0, 100, 0.1)}
              {input("inflation_rate", "LTC inflation (% per year, optional)", -50, 50, 0.1)}
              {input(
                "amount_reference_year",
                "LTC amount reference year (optional)",
                1900,
                2300,
                1,
              )}
            </div>
          )}
        </>
      )}
    </fieldset>
  );
}
