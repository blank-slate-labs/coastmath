import { moneyLabel } from "@/utils/format";
import type { Milestone, SsBenefitBasis } from "@/types/plan";
import MoneyInput from "@/components/money_input";
import { ExSpouseFields, type ExSpouseDraft } from "@/components/ex_spouse_fields";
import { choiceLabelStyle } from "@/components/form_styles";
import type { SocialSecurityEstimate } from "./use_social_security_estimate";

export type PiaReflects = "current_record" | "continued_work";

interface SocialSecurityBenefitFieldsProps {
  basis: SsBenefitBasis;
  onBasisChange: (basis: SsBenefitBasis) => void;
  piaReflects: PiaReflects;
  onPiaReflectsChange: (reflects: PiaReflects) => void;
  coveredYears: number;
  onCoveredYearsChange: (years: number) => void;
  /** Monthly PIA at full retirement age, as typed. */
  pia: string;
  onPiaChange: (pia: string) => void;
  /** Expected percentage of the benefit paid, as typed. */
  expectedPercent: string;
  onExpectedPercentChange: (percent: string) => void;
  /** First-year benefit of a PIA basis, once the server has sized it. */
  preview: number | null;
  exSpouse: ExSpouseDraft;
  onExSpouseChange: (draft: ExSpouseDraft) => void;
  claimingAge: number | null;
  onClaimingAgeChange: (age: number | null) => void;
  /** Calendar year the recipient reaches the claiming age. */
  claimYear: number | null;
  startMilestoneId: string;
  startMilestone?: Milestone;
  /** Year the start milestone resolves to, when known without a projection. */
  startYear: number | null;
  /** The benefit-amount estimate controls. */
  estimate: SocialSecurityEstimate;
}

/** Benefit basis, PIA inputs and preview, claiming age and the amount estimate of a Social Security income. */
export function SocialSecurityBenefitFields({
  basis,
  onBasisChange,
  piaReflects,
  onPiaReflectsChange,
  coveredYears,
  onCoveredYearsChange,
  pia,
  onPiaChange,
  expectedPercent,
  onExpectedPercentChange,
  preview,
  exSpouse,
  onExSpouseChange,
  claimingAge,
  onClaimingAgeChange,
  claimYear,
  startMilestoneId,
  startMilestone,
  startYear,
  estimate,
}: SocialSecurityBenefitFieldsProps) {
  const isPiaBasis = basis === "pia";
  return (
    <>
      <fieldset style={{ gridColumn: "1 / -1", border: "none", padding: 0, margin: 0 }}>
        <legend style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 6 }}>
          Benefit basis
        </legend>
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
          <label style={choiceLabelStyle}>
            <input
              type="radio"
              name="ss-basis"
              value="amount"
              checked={basis === "amount"}
              onChange={() => onBasisChange("amount")}
            />
            Benefit amount
          </label>
          <label style={choiceLabelStyle}>
            <input
              type="radio"
              name="ss-basis"
              value="pia"
              checked={basis === "pia"}
              onChange={() => onBasisChange("pia")}
            />
            PIA
          </label>
        </div>
      </fieldset>
      {isPiaBasis && (
        <>
          <label>
            My PIA reflects…
            <select
              value={piaReflects}
              onChange={(e) => onPiaReflectsChange(e.target.value as PiaReflects)}
            >
              <option value="continued_work">Assumes I keep working</option>
              <option value="current_record">Current record</option>
            </select>
          </label>
          {piaReflects === "current_record" && (
            <label>
              Covered years to date
              <input
                type="number"
                min="1"
                max="35"
                step="1"
                value={coveredYears}
                onChange={(e) => onCoveredYearsChange(Number(e.target.value))}
              />
            </label>
          )}

          <label>
            {moneyLabel("PIA per month at full retirement age ($)")}
            <MoneyInput
              min="0"
              step="0.01"
              value={pia}
              onValueChange={onPiaChange}
              placeholder="e.g. 2000"
            />
          </label>
          <label>
            Expected benefit paid (%)
            <input
              type="number"
              min="0"
              max="100"
              step="0.1"
              value={expectedPercent}
              onChange={(e) => onExpectedPercentChange(e.target.value)}
            />
          </label>
          <div
            role="status"
            style={{ gridColumn: "1 / -1", color: "var(--text-secondary)", fontSize: 12 }}
          >
            {preview != null
              ? `First-year benefit at claiming age ${claimingAge}: ${preview.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 })} a year in today's dollars. `
              : ""}
            The projection adjusts your PIA for the claim date, applies the expected percentage and
            COLA, and adds spousal and survivor benefits when both partners use PIA.
          </div>
          <ExSpouseFields draft={exSpouse} onChange={onExSpouseChange} />
        </>
      )}
      <label>
        Claiming age
        <select
          value={claimingAge ?? ""}
          onChange={(e) =>
            onClaimingAgeChange(e.target.value === "" ? null : Number(e.target.value))
          }
        >
          <option value="">Not set</option>
          {[62, 63, 64, 65, 66, 67, 68, 69, 70].map((age) => (
            <option key={age} value={age}>
              {age}
            </option>
          ))}
        </select>
        <span style={{ display: "block", fontSize: 12, color: "var(--text-secondary)" }}>
          {startMilestoneId
            ? `Benefits follow the "${startMilestone?.name ?? "start"}" milestone${startYear != null ? ` (${startYear})` : ""}; ${isPiaBasis ? "the benefit is sized for that start date" : "the claiming age only sizes the estimate below"}.`
            : claimingAge != null
              ? `Benefits begin the year you turn ${claimingAge}${claimYear != null ? ` (${claimYear})` : ""}. Choose a Start milestone below to override this.`
              : "Without a claiming age, benefits begin at plan start or the Start milestone."}
        </span>
      </label>

      {!isPiaBasis && (
        <>
          <div
            style={{
              gridColumn: "1 / -1",
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
              gap: 8,
              alignItems: "end",
            }}
          >
            <label style={{ flex: 1 }}>
              Estimate method
              <select
                aria-label="Estimate method"
                value={estimate.mode}
                onChange={(e) => estimate.setMode(e.target.value as "income" | "pia")}
              >
                <option value="income">From current annual income</option>
                <option value="pia">From monthly PIA</option>
              </select>
            </label>
            {estimate.mode === "pia" ? (
              <>
                <label style={{ flex: 1 }}>
                  Monthly PIA at FRA
                  <MoneyInput
                    min="0"
                    step="0.01"
                    value={estimate.monthlyPia}
                    onValueChange={estimate.setMonthlyPia}
                    placeholder="e.g. 2000"
                  />
                </label>
                <label style={{ flex: 1 }}>
                  Expected benefit (%)
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="0.1"
                    value={estimate.expectedPercent}
                    onChange={(e) => estimate.setExpectedPercent(e.target.value)}
                  />
                </label>
              </>
            ) : (
              <label style={{ flex: 1 }}>
                Current annual income (for estimate)
                <MoneyInput
                  value={estimate.income}
                  onValueChange={estimate.setIncome}
                  placeholder="e.g. 75000"
                />
              </label>
            )}
            <button type="button" onClick={estimate.estimate} disabled={estimate.estimating}>
              {estimate.estimating
                ? "Estimating…"
                : estimate.mode === "pia"
                  ? "Estimate from PIA"
                  : "Estimate from income"}
            </button>
          </div>
          {estimate.error && (
            <div style={{ gridColumn: "1 / -1", color: "var(--red-600, #c00)", fontSize: 13 }}>
              {estimate.error}
            </div>
          )}
        </>
      )}
    </>
  );
}
