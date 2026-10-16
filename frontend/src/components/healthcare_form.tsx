import { useState } from "react";
import { useFormDraftStatus } from "@/utils/form_draft_status";

import PersonHealthcareForm, {
  personHealthcareDraft,
  readPersonHealthcare,
} from "./person_healthcare_form";
import type {
  FilingStatus,
  HealthcareSettings,
  HealthcareStateGroup,
  Milestone,
  PlanData,
} from "@/types/plan";
import { moneyLabel } from "@/utils/format";
import MoneyInput from "./money_input";

interface HealthcareFormProps {
  plan: PlanData;
  onSave: (planId: string, settings: HealthcareSettings) => void | Promise<void>;
}

export const defaultHealthcareSettings: HealthcareSettings = {
  enabled: false,
  medical_inflation_rate: null,
  aca_enabled: false,
  aca_start_milestone_id: null,
  aca_end_milestone_id: null,
  aca_benchmark_premium_annual: 0,
  aca_plan_premium_annual: 0,
  aca_advance_credit_fraction: 1,
  aca_cover_spouse: true,
  aca_dependents: 0,
  aca_apply_age_curve: true,
  aca_state_group: "contiguous",
  medicare_enabled: true,
  medicare_part_b: true,
  medicare_part_d: true,
  medicare_part_d_plan_premium_monthly: 0,
  medicare_supplement_premium_monthly: 0,
  medicare_apply_irmaa: true,
  magi_prior_year: null,
  magi_two_years_prior: null,
};

const helpStyle: React.CSSProperties = {
  display: "block",
  fontSize: 12,
  color: "var(--text-secondary)",
  textTransform: "none",
  letterSpacing: "normal",
  fontWeight: 400,
  marginTop: 4,
};
const rowStyle: React.CSSProperties = { display: "flex", alignItems: "center", gap: 8 };
const groupStyle: React.CSSProperties = {
  display: "grid",
  gap: 8,
  paddingLeft: 12,
  borderLeft: "2px solid var(--surface-border)",
};
const inputStyle: React.CSSProperties = { display: "block", width: "100%" };

function numberOrNull(value: string): number | null {
  return value.trim() === "" ? null : Number(value);
}

/**
 * Health coverage assumptions: ACA marketplace premiums and credits before
 * Medicare, then Medicare Part B/D with IRMAA. Saved as one plan setting.
 */
export default function HealthcareForm({ plan, onSave }: HealthcareFormProps) {
  const initial: HealthcareSettings = {
    ...defaultHealthcareSettings,
    ...(plan.healthcare_settings ?? {}),
  };
  const milestones: Milestone[] = plan.milestones;
  const [enabled, setEnabled] = useState(initial.enabled);
  const [medicalInflation, setMedicalInflation] = useState(
    initial.medical_inflation_rate != null
      ? String(Number((initial.medical_inflation_rate * 100).toFixed(4)))
      : "",
  );
  const [acaEnabled, setAcaEnabled] = useState(initial.aca_enabled);
  const [acaStart, setAcaStart] = useState(initial.aca_start_milestone_id ?? "");
  const [acaEnd, setAcaEnd] = useState(initial.aca_end_milestone_id ?? "");
  const [benchmark, setBenchmark] = useState(
    initial.aca_benchmark_premium_annual ? String(initial.aca_benchmark_premium_annual) : "",
  );
  const [planPremium, setPlanPremium] = useState(
    initial.aca_plan_premium_annual ? String(initial.aca_plan_premium_annual) : "",
  );
  const [acaAdvanceCreditPercent, setAcaAdvanceCreditPercent] = useState(
    String((initial.aca_advance_credit_fraction ?? 1) * 100),
  );
  const [coverSpouse, setCoverSpouse] = useState(initial.aca_cover_spouse);
  const [dependents, setDependents] = useState(String(initial.aca_dependents));
  const [ageCurve, setAgeCurve] = useState(initial.aca_apply_age_curve);
  const [stateGroup, setStateGroup] = useState<HealthcareStateGroup>(initial.aca_state_group);
  const [medicareEnabled, setMedicareEnabled] = useState(initial.medicare_enabled);
  const [partB, setPartB] = useState(initial.medicare_part_b);
  const [partD, setPartD] = useState(initial.medicare_part_d);
  const [partDPremium, setPartDPremium] = useState(
    String(initial.medicare_part_d_plan_premium_monthly),
  );
  const [supplement, setSupplement] = useState(String(initial.medicare_supplement_premium_monthly));
  const [applyIrmaa, setApplyIrmaa] = useState(initial.medicare_apply_irmaa);
  const [magiPrior, setMagiPrior] = useState(
    initial.magi_prior_year != null ? String(initial.magi_prior_year) : "",
  );
  const [magiTwoPrior, setMagiTwoPrior] = useState(
    initial.magi_two_years_prior != null ? String(initial.magi_two_years_prior) : "",
  );
  const [personDrafts, setPersonDrafts] = useState(() => ({
    self: personHealthcareDraft(initial.persons?.find((p) => p.owner === "self")),
    spouse: personHealthcareDraft(initial.persons?.find((p) => p.owner === "spouse")),
  }));
  const [priorFiling, setPriorFiling] = useState<FilingStatus | "">(
    initial.magi_prior_year_filing_status ?? "",
  );
  const [twoPriorFiling, setTwoPriorFiling] = useState<FilingStatus | "">(
    initial.magi_two_years_prior_filing_status ?? "",
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const advancedSaved =
    initial.magi_prior_year != null ||
    initial.magi_two_years_prior != null ||
    !!initial.magi_prior_year_filing_status ||
    !!initial.magi_two_years_prior_filing_status ||
    !!initial.persons?.length;
  const { dirty, saved, clearSaved, markSaved } = useFormDraftStatus(
    JSON.stringify([
      enabled,
      medicalInflation,
      acaEnabled,
      acaStart,
      acaEnd,
      benchmark,
      planPremium,
      acaAdvanceCreditPercent,
      coverSpouse,
      dependents,
      ageCurve,
      stateGroup,
      medicareEnabled,
      partB,
      partD,
      partDPremium,
      supplement,
      applyIrmaa,
      magiPrior,
      magiTwoPrior,
      personDrafts,
      priorFiling,
      twoPriorFiling,
    ]),
  );

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    clearSaved();
    const inflation = numberOrNull(medicalInflation);
    if (inflation !== null && (!Number.isFinite(inflation) || inflation < -50 || inflation > 50)) {
      setError(
        "Medical inflation must be a percent between -50 and 50, or blank to use plan inflation.",
      );
      return;
    }
    const bench = Number(benchmark);
    const gross = Number(planPremium);
    const advanceCreditPercent =
      acaAdvanceCreditPercent.trim() === "" ? 100 : Number(acaAdvanceCreditPercent);
    if (
      !Number.isFinite(advanceCreditPercent) ||
      advanceCreditPercent < 0 ||
      advanceCreditPercent > 100
    ) {
      setError("Advance ACA credit must be a percentage from 0 to 100.");
      return;
    }
    if (
      enabled &&
      acaEnabled &&
      (benchmark.trim() === "" ||
        planPremium.trim() === "" ||
        !Number.isFinite(bench) ||
        !Number.isFinite(gross) ||
        bench <= 0 ||
        gross <= 0)
    ) {
      setError("Enter both the benchmark and your plan's annual premium.");
      return;
    }
    const deps = Number(dependents);
    if (!Number.isInteger(deps) || deps < 0 || deps > 20) {
      setError("Dependents must be a whole number from 0 to 20.");
      return;
    }
    const partDValue = Number(partDPremium || 0);
    const suppValue = Number(supplement || 0);
    if (
      !Number.isFinite(partDValue) ||
      partDValue < 0 ||
      !Number.isFinite(suppValue) ||
      suppValue < 0
    ) {
      setError("Medicare premiums must be zero or positive monthly amounts.");
      return;
    }
    const prior = numberOrNull(magiPrior);
    const twoPrior = numberOrNull(magiTwoPrior);
    if (
      (prior !== null && (!Number.isFinite(prior) || prior < 0)) ||
      (twoPrior !== null && (!Number.isFinite(twoPrior) || twoPrior < 0))
    ) {
      setError("Prior-year income must be zero or positive.");
      return;
    }
    let persons;
    try {
      persons = (["self", "spouse"] as const).flatMap((owner) => {
        const value = readPersonHealthcare(
          personDrafts[owner],
          owner,
          plan.plan_type === "FIXED_DATE" && plan.start_date
            ? Number(plan.start_date.slice(0, 4))
            : new Date().getFullYear(),
        );
        return value ? [value] : [];
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Check the person healthcare budgets.");
      return;
    }
    if (
      enabled &&
      persons.some((p) => p.mode === "coverage" && p.aca_enabled) &&
      (bench <= 0 || gross <= 0 || !Number.isFinite(bench) || !Number.isFinite(gross))
    ) {
      setError("Person marketplace coverage needs both shared annual premiums above.");
      return;
    }
    const settings: HealthcareSettings = {
      ...initial,
      enabled,
      medical_inflation_rate: inflation === null ? null : inflation / 100,
      aca_enabled: acaEnabled,
      aca_start_milestone_id: acaStart || null,
      aca_end_milestone_id: acaEnd || null,
      aca_benchmark_premium_annual: benchmark.trim() === "" ? 0 : bench,
      aca_plan_premium_annual: planPremium.trim() === "" ? 0 : gross,
      aca_advance_credit_fraction: advanceCreditPercent / 100,
      aca_cover_spouse: coverSpouse,
      aca_dependents: deps,
      aca_apply_age_curve: ageCurve,
      aca_state_group: stateGroup,
      medicare_enabled: medicareEnabled,
      medicare_part_b: partB,
      medicare_part_d: partD,
      medicare_part_d_plan_premium_monthly: partDValue,
      medicare_supplement_premium_monthly: suppValue,
      medicare_apply_irmaa: applyIrmaa,
      magi_prior_year: prior,
      magi_two_years_prior: twoPrior,
    };
    if (initial.persons !== undefined || persons.length > 0) settings.persons = persons;
    if (initial.magi_prior_year_filing_status !== undefined || priorFiling !== "")
      settings.magi_prior_year_filing_status = priorFiling || null;
    if (initial.magi_two_years_prior_filing_status !== undefined || twoPriorFiling !== "")
      settings.magi_two_years_prior_filing_status = twoPriorFiling || null;
    setSaving(true);
    Promise.resolve()
      .then(() => onSave(plan.id, settings))
      .then(markSaved)
      .catch(() =>
        setError("Could not save health coverage settings. Your edits are retained; try again."),
      )
      .finally(() => setSaving(false));
  }

  return (
    <form
      data-unsaved-changes={dirty || undefined}
      data-save-pending={saving || undefined}
      onSubmit={handleSubmit}
      style={{ display: "grid", gap: 10 }}
    >
      <fieldset
        disabled={saving}
        style={{ border: 0, padding: 0, minWidth: 0, display: "grid", gap: 10 }}
      >
        <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
          Remove duplicate premium expenses.
        </p>
        <label style={rowStyle}>
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Model health coverage costs
        </label>
        {enabled && (
          <>
            <label>
              Medical cost inflation (% per year, optional)
              <input
                type="number"
                step="0.1"
                min={-50}
                max={50}
                value={medicalInflation}
                onChange={(e) => setMedicalInflation(e.target.value)}
                placeholder="Plan inflation"
                style={inputStyle}
              />
              <span style={helpStyle}>
                Premiums grow at this rate; income thresholds follow plan inflation.
              </span>
            </label>

            <label style={rowStyle}>
              <input
                type="checkbox"
                checked={acaEnabled}
                onChange={(e) => setAcaEnabled(e.target.checked)}
              />
              Marketplace (ACA) coverage before Medicare
            </label>
            {acaEnabled && (
              <div style={groupStyle}>
                <label>
                  Covered from milestone
                  <select
                    value={acaStart}
                    onChange={(e) => setAcaStart(e.target.value)}
                    style={inputStyle}
                  >
                    <option value="">— From the start of the plan —</option>
                    {milestones.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Covered until milestone
                  <select
                    value={acaEnd}
                    onChange={(e) => setAcaEnd(e.target.value)}
                    style={inputStyle}
                  >
                    <option value="">— Until Medicare at 65 —</option>
                    {milestones.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                  <span style={helpStyle}>
                    Each adult leaves marketplace coverage at 65 regardless of this milestone.
                  </span>
                </label>
                <label>
                  {moneyLabel("Benchmark premium ($ per year, today's ages)")}
                  <MoneyInput
                    min={0}
                    step={0.01}
                    value={benchmark}
                    onValueChange={setBenchmark}
                    style={inputStyle}
                  />
                  <span style={helpStyle}>
                    Second-lowest-cost silver premium for the covered adults, before credit.
                  </span>
                </label>
                <label>
                  {moneyLabel("Your plan's premium ($ per year, today's ages)")}
                  <MoneyInput
                    min={0}
                    step={0.01}
                    value={planPremium}
                    onValueChange={setPlanPremium}
                    style={inputStyle}
                  />
                </label>
                <label>
                  Advance premium tax credit (% of estimate)
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={0.1}
                    value={acaAdvanceCreditPercent}
                    onChange={(e) => setAcaAdvanceCreditPercent(e.target.value)}
                    style={inputStyle}
                  />
                  <span style={helpStyle}>
                    Share of the estimated credit applied during the year; the rest reconciles at
                    tax time.
                  </span>
                </label>
                {plan.spouse && (
                  <label style={rowStyle}>
                    <input
                      type="checkbox"
                      checked={coverSpouse}
                      onChange={(e) => setCoverSpouse(e.target.checked)}
                    />
                    Partner is covered on the same policy
                  </label>
                )}
                <label>
                  Other household members (dependents)
                  <input
                    type="number"
                    min={0}
                    max={20}
                    step={1}
                    value={dependents}
                    onChange={(e) => setDependents(e.target.value)}
                    style={inputStyle}
                  />
                  <span style={helpStyle}>
                    Counted for the poverty-line household size only; children's premiums are not
                    added.
                  </span>
                </label>
                <label style={rowStyle}>
                  <input
                    type="checkbox"
                    checked={ageCurve}
                    onChange={(e) => setAgeCurve(e.target.checked)}
                  />
                  Age-rate premiums as you get older (federal 3:1 curve)
                </label>
                <label>
                  Poverty guideline region
                  <select
                    value={stateGroup}
                    onChange={(e) => setStateGroup(e.target.value as HealthcareStateGroup)}
                    style={inputStyle}
                  >
                    <option value="contiguous">48 states and DC</option>
                    <option value="alaska">Alaska</option>
                    <option value="hawaii">Hawaii</option>
                  </select>
                </label>
                <span style={helpStyle}>
                  2026 rules: credit = benchmark minus 2.10%–9.96% of income, none above 400% of the
                  poverty line or below 100% (Medicaid not modeled). Computed annually from
                  projected income.
                </span>
              </div>
            )}

            <label style={rowStyle}>
              <input
                type="checkbox"
                checked={medicareEnabled}
                onChange={(e) => setMedicareEnabled(e.target.checked)}
              />
              Medicare premiums from age 65
            </label>
            {medicareEnabled && (
              <div style={groupStyle}>
                <label style={rowStyle}>
                  <input
                    type="checkbox"
                    checked={partB}
                    onChange={(e) => setPartB(e.target.checked)}
                  />
                  Part B (2026 standard $202.90 per month)
                </label>
                <label style={rowStyle}>
                  <input
                    type="checkbox"
                    checked={partD}
                    onChange={(e) => setPartD(e.target.checked)}
                  />
                  Part D drug coverage
                </label>
                {partD && (
                  <label>
                    {moneyLabel("Part D plan premium ($ per month, per person)")}
                    <MoneyInput
                      min={0}
                      step={0.01}
                      value={partDPremium}
                      onValueChange={setPartDPremium}
                      style={inputStyle}
                    />
                  </label>
                )}
                <label>
                  {moneyLabel("Medigap or Advantage premium ($ per month, per person)")}
                  <MoneyInput
                    min={0}
                    step={0.01}
                    value={supplement}
                    onValueChange={setSupplement}
                    style={inputStyle}
                  />
                </label>
                <label style={rowStyle}>
                  <input
                    type="checkbox"
                    checked={applyIrmaa}
                    onChange={(e) => setApplyIrmaa(e.target.checked)}
                  />
                  Apply income-related surcharges (IRMAA)
                </label>
              </div>
            )}
            {/* The IRMAA lookback and per-person overrides refine the defaults; a saved one opens the group. */}
            <details className="form-advanced" open={advancedSaved || undefined}>
              <summary>Advanced</summary>
              <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
                {medicareEnabled && applyIrmaa && (
                  <fieldset style={groupStyle}>
                    <legend>IRMAA lookback</legend>
                    <label>
                      {moneyLabel("Last year's modified AGI ($, optional)")}
                      <MoneyInput
                        min={0}
                        step={0.01}
                        value={magiPrior}
                        onValueChange={setMagiPrior}
                        style={inputStyle}
                      />
                    </label>
                    <label>
                      {moneyLabel("Modified AGI two years ago ($, optional)")}
                      <MoneyInput
                        min={0}
                        step={0.01}
                        value={magiTwoPrior}
                        onValueChange={setMagiTwoPrior}
                        style={inputStyle}
                      />
                      <span style={helpStyle}>
                        2026 thresholds: $109,000 single / $218,000 joint.
                      </span>
                    </label>
                    <p style={helpStyle}>
                      Use the filing status on the lookback return, even if your household status
                      changed since.
                    </p>
                    {(
                      [
                        ["Last year's filing status", priorFiling, setPriorFiling],
                        ["Filing status two years ago", twoPriorFiling, setTwoPriorFiling],
                      ] as const
                    ).map(([label, value, setter]) => (
                      <label key={label}>
                        {label}
                        <select
                          value={value}
                          onChange={(e) => setter(e.target.value as FilingStatus | "")}
                          style={inputStyle}
                        >
                          <option value="">Unknown / projection fallback</option>
                          {[
                            "single",
                            "head_of_household",
                            "married_filing_jointly",
                            "married_filing_separately",
                          ].map((status) => (
                            <option key={status} value={status}>
                              {status.replace(/_/g, " ")}
                            </option>
                          ))}
                        </select>
                      </label>
                    ))}
                  </fieldset>
                )}
                <PersonHealthcareForm
                  owner="self"
                  value={personDrafts.self}
                  onChange={(value) => setPersonDrafts((current) => ({ ...current, self: value }))}
                />
                {(plan.spouse || initial.persons?.some((p) => p.owner === "spouse")) && (
                  <PersonHealthcareForm
                    owner="spouse"
                    value={personDrafts.spouse}
                    onChange={(value) =>
                      setPersonDrafts((current) => ({ ...current, spouse: value }))
                    }
                  />
                )}
              </div>
            </details>
          </>
        )}
        {error && (
          <div role="alert" style={{ color: "var(--color-danger)", fontSize: 13 }}>
            {error}
          </div>
        )}
        <button type="submit">{saving ? "Saving…" : "Save health coverage"}</button>
      </fieldset>
      {dirty && <p role="status">Unsaved health coverage changes. Save before closing.</p>}
      {saved && (
        <p role="status" style={{ margin: 0, fontSize: 13 }}>
          Health coverage settings saved.
        </p>
      )}
    </form>
  );
}
