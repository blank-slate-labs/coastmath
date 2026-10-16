import type { ExSpouseRecord } from "@/types/plan";
import { moneyLabel } from "@/utils/format";
import MoneyInput from "./money_input";

/** Editable former-spouse record; numbers stay text until the form is saved. */
export interface ExSpouseDraft {
  enabled: boolean;
  pia: string;
  birthYear: string;
  birthMonth: string;
  marriageYears: string;
  tenYears: boolean;
  divorceYear: string;
  divorceMonth: string;
  claimAge: string;
  deathYear: string;
  currentMarriageYear: string;
  survivorClaimAge: string;
}

const text = (value: number | null | undefined) => (value == null ? "" : String(value));

export function exSpouseDraft(record: ExSpouseRecord | null | undefined): ExSpouseDraft {
  return {
    enabled: record != null,
    pia: text(record?.pia_monthly),
    birthYear: text(record?.birth_year),
    birthMonth: text(record?.birth_month ?? 1),
    marriageYears: text(record?.marriage_years),
    tenYears: record?.marriage_lasted_10_years ?? false,
    divorceYear: text(record?.divorce_year),
    divorceMonth: text(record?.divorce_month),
    claimAge: text(record?.claim_age),
    deathYear: text(record?.death_year),
    currentMarriageYear: text(record?.current_marriage_year),
    survivorClaimAge: text(record?.survivor_claim_age),
  };
}

function optional(value: string): number | null {
  return value.trim() === "" ? null : Number(value);
}

/** Validated record for saving: null when the section is off. */
export function exSpouseFromDraft(draft: ExSpouseDraft): {
  record: ExSpouseRecord | null;
  error: string | null;
} {
  if (!draft.enabled) return { record: null, error: null };
  const fail = (error: string) => ({ record: null, error });
  const pia = Number(draft.pia);
  if (draft.pia.trim() === "" || !Number.isFinite(pia) || pia <= 0)
    return fail("Enter the former spouse's positive monthly PIA.");
  const birthYear = Number(draft.birthYear);
  const birthMonth = Number(draft.birthMonth || "1");
  if (!Number.isInteger(birthYear) || birthYear < 1900 || birthYear > 2100)
    return fail("Enter the former spouse's birth year.");
  if (!Number.isInteger(birthMonth) || birthMonth < 1 || birthMonth > 12)
    return fail("Former spouse's birth month must be 1 to 12.");
  const marriageYears = optional(draft.marriageYears);
  if (
    marriageYears !== null &&
    (!Number.isFinite(marriageYears) || marriageYears < 0 || marriageYears > 100)
  ) {
    return fail("Marriage length must be between 0 and 100 years.");
  }
  if (marriageYears === null && !draft.tenYears)
    return fail("Enter the marriage length or confirm it lasted at least 10 years.");
  const divorceYear = Number(draft.divorceYear);
  if (
    draft.divorceYear.trim() === "" ||
    !Number.isInteger(divorceYear) ||
    divorceYear < birthYear ||
    divorceYear > 2200
  ) {
    return fail("Enter the divorce year.");
  }
  const divorceMonth = optional(draft.divorceMonth);
  if (
    divorceMonth !== null &&
    (!Number.isInteger(divorceMonth) || divorceMonth < 1 || divorceMonth > 12)
  ) {
    return fail("Divorce month must be 1 to 12.");
  }
  const claimAge = optional(draft.claimAge);
  if (claimAge !== null && (!Number.isFinite(claimAge) || claimAge < 62 || claimAge > 70)) {
    return fail("The former spouse's claiming age must be 62 to 70.");
  }
  const deathYear = optional(draft.deathYear);
  if (
    deathYear !== null &&
    (!Number.isInteger(deathYear) || deathYear < divorceYear || deathYear > 2200)
  ) {
    return fail("The former spouse's death year must be on or after the divorce year.");
  }
  const currentMarriageYear = optional(draft.currentMarriageYear);
  if (
    currentMarriageYear !== null &&
    (!Number.isInteger(currentMarriageYear) ||
      currentMarriageYear < 1900 ||
      currentMarriageYear > 2200)
  ) {
    return fail("Enter a valid year for the current marriage.");
  }
  const survivorClaimAge = optional(draft.survivorClaimAge);
  if (
    survivorClaimAge !== null &&
    (!Number.isFinite(survivorClaimAge) || survivorClaimAge < 60 || survivorClaimAge > 70)
  ) {
    return fail("Survivor benefits can start from age 60 to 70.");
  }
  return {
    error: null,
    record: {
      pia_monthly: pia,
      birth_year: birthYear,
      birth_month: birthMonth,
      marriage_years: marriageYears,
      marriage_lasted_10_years: draft.tenYears,
      divorce_year: divorceYear,
      divorce_month: divorceMonth,
      claim_age: claimAge,
      death_year: deathYear,
      current_marriage_year: currentMarriageYear,
      survivor_claim_age: survivorClaimAge,
    },
  };
}

interface ExSpouseFieldsProps {
  draft: ExSpouseDraft;
  onChange: (draft: ExSpouseDraft) => void;
}

/** Former-spouse section of a PIA-basis Social Security benefit. */
export function ExSpouseFields({ draft, onChange }: ExSpouseFieldsProps) {
  const set = (patch: Partial<ExSpouseDraft>) => onChange({ ...draft, ...patch });
  const number = (
    label: string,
    key: keyof ExSpouseDraft,
    props: React.InputHTMLAttributes<HTMLInputElement> = {},
  ) => (
    <label>
      {label}
      <input
        type="number"
        step="any"
        value={draft[key] as string}
        onChange={(e) => set({ [key]: e.target.value })}
        {...props}
      />
    </label>
  );
  return (
    <fieldset className="ex-spouse" style={{ gridColumn: "1 / -1" }}>
      <legend>Former spouse</legend>
      <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <input
          type="checkbox"
          checked={draft.enabled}
          onChange={(e) => set({ enabled: e.target.checked })}
        />
        Include a former spouse's record (divorced or surviving divorced spouse benefits)
      </label>
      {draft.enabled && (
        <div className="form-field-group" style={{ marginTop: 8 }}>
          <label>
            {moneyLabel("Former spouse's PIA per month ($)")}
            <MoneyInput
              min={0}
              placeholder="e.g. 3000"
              value={draft.pia}
              onValueChange={(pia) => set({ pia })}
            />
          </label>
          {number("Former spouse's birth year", "birthYear", { step: 1 })}
          {number("Former spouse's birth month", "birthMonth", { min: 1, max: 12, step: 1 })}
          {number("Marriage length (years)", "marriageYears", { min: 0, max: 100 })}
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <input
              type="checkbox"
              checked={draft.tenYears}
              onChange={(e) => set({ tenYears: e.target.checked })}
            />
            The marriage lasted at least 10 years
          </label>
          {number("Divorce year", "divorceYear", { step: 1 })}
          {number("Divorce month (optional)", "divorceMonth", {
            min: 1,
            max: 12,
            step: 1,
            placeholder: "December",
          })}
          {number("Former spouse's claiming age (optional)", "claimAge", {
            min: 62,
            max: 70,
            placeholder: "Not claimed",
          })}
          {number("Former spouse's death year (optional)", "deathYear", {
            step: 1,
            placeholder: "Living",
          })}
          {number("Your current marriage began (year, optional)", "currentMarriageYear", {
            step: 1,
            placeholder: "Unknown",
          })}
          {number("Start survivor benefits at age (optional)", "survivorClaimAge", {
            min: 60,
            max: 70,
            placeholder: "With your own claim",
          })}
          <p
            style={{
              gridColumn: "1 / -1",
              margin: 0,
              fontSize: 12,
              color: "var(--text-secondary)",
            }}
          >
            After a marriage of 10 years or more, you can receive the excess of half your former
            spouse's PIA over your own PIA while you are unmarried and both of you are 62 or older.
            Unless your former spouse has claimed, you must have been divorced for 2 years. After
            their death, a survivor benefit can start at 60, and a remarriage at 60 or later does
            not end it. Only the largest spousal, divorced spouse or survivor amount is paid. Your
            filing status schedule marks when you are married.
          </p>
        </div>
      )}
    </fieldset>
  );
}
