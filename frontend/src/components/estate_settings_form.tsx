import { moneyLabel } from "@/utils/format";
import { useState } from "react";
import { useFormDraftStatus } from "@/utils/form_draft_status";
import { useSaveStore } from "@/stores/save_store";
import { usCoverage } from "@/domain/intl_plan";
import MoneyInput from "./money_input";

import type {
  EstateSettings,
  FilingStatusAfterDeath,
  PlanCreate,
  PlanData,
  SpouseUpdate,
} from "@/types/plan";

interface EstateSettingsFormProps {
  plan: PlanData;
  onSave: (planId: string, data: Partial<PlanCreate>) => void | Promise<void>;
}

export const defaultEstateSettings: EstateSettings = {
  step_up_basis_on_death: true,
  filing_status_after_death: "single",
  federal_estate_exemption: 15_000_000,
  custom_federal_exemption_enabled: false,
  portability_election: true,
  state_estate_tax_enabled: false,
  state_estate_exemption: 0,
  state_estate_tax_rate: 0,
  settlement_cost_fixed: 0,
  settlement_cost_rate: 0,
  heir_income_tax_rate: 0,
};

const filingOptions: { value: FilingStatusAfterDeath; label: string }[] = [
  { value: "single", label: "Single" },
  { value: "head_of_household", label: "Head of household" },
  { value: "married_filing_jointly", label: "Married filing jointly (remarried)" },
  { value: "married_filing_separately", label: "Married filing separately" },
];

const helpStyle: React.CSSProperties = {
  fontSize: 12,
  color: "var(--text-secondary)",
  textTransform: "none",
  letterSpacing: "normal",
  fontWeight: 400,
  display: "block",
  marginTop: 4,
};
const rowStyle: React.CSSProperties = { display: "flex", alignItems: "center", gap: 8 };
const currentYear = new Date().getFullYear();

/**
 * Edits the partner profile and the estate assumptions the engine actually
 * uses: step-up, survivor filing status, federal exemption override,
 * portability and a flat-rate state estate tax. Saves as one PUT so the
 * partner's life expectancy and the estate rules stay consistent.
 */
export default function EstateSettingsForm({ plan, onSave }: EstateSettingsFormProps) {
  const initial = { ...defaultEstateSettings, ...(plan.estate_settings ?? {}) };
  // US estate tax applies only to a death in a US year. A plan with no US year
  // hides its exemption settings; their saved values are kept unchanged.
  const coverage = usCoverage(plan);
  const [hasPartner, setHasPartner] = useState(plan.spouse != null);
  const [partnerName, setPartnerName] = useState(plan.spouse?.name ?? "");
  const [partnerBirthMonth, setPartnerBirthMonth] = useState(
    String(plan.spouse?.birth_month ?? ""),
  );
  const [partnerBirthYear, setPartnerBirthYear] = useState(
    plan.spouse?.birth_year != null ? String(plan.spouse.birth_year) : "",
  );
  const [partnerLifeExpectancy, setPartnerLifeExpectancy] = useState(
    plan.spouse?.life_expectancy != null ? String(plan.spouse.life_expectancy) : "",
  );
  const [stepUp, setStepUp] = useState(initial.step_up_basis_on_death);
  const [filingAfterDeath, setFilingAfterDeath] = useState<FilingStatusAfterDeath>(
    initial.filing_status_after_death,
  );
  const [customExemption, setCustomExemption] = useState(initial.custom_federal_exemption_enabled);
  const [federalExemption, setFederalExemption] = useState(
    String(initial.federal_estate_exemption),
  );
  const [portability, setPortability] = useState(initial.portability_election);
  const [stateEnabled, setStateEnabled] = useState(initial.state_estate_tax_enabled);
  const [stateExemption, setStateExemption] = useState(String(initial.state_estate_exemption));
  const [stateRate, setStateRate] = useState(
    String(Number((initial.state_estate_tax_rate * 100).toFixed(4))),
  );
  const [settlementFixed, setSettlementFixed] = useState(
    String(initial.settlement_cost_fixed ?? 0),
  );
  const [settlementRate, setSettlementRate] = useState(
    String(Number(((initial.settlement_cost_rate ?? 0) * 100).toFixed(4))),
  );
  const [heirRate, setHeirRate] = useState(
    String(Number(((initial.heir_income_tax_rate ?? 0) * 100).toFixed(4))),
  );
  const [jointStepUp, setJointStepUp] = useState(initial.joint_account_step_up ?? false);
  const [heirGainsRate, setHeirGainsRate] = useState(
    String(Number(((initial.heir_capital_gains_rate ?? 0) * 100).toFixed(4))),
  );
  const [sellingCost, setSellingCost] = useState(String(initial.estate_selling_cost_percent ?? 0));
  const [bequest, setBequest] = useState(String(initial.charitable_bequest_percent ?? 0));
  const [legacyTarget, setLegacyTarget] = useState(
    initial.legacy_target != null ? String(initial.legacy_target) : "",
  );
  const [horizon, setHorizon] = useState(initial.household_lifecycle ?? "legacy_primary_endpoint");
  const [survivorPolicy, setSurvivorPolicy] = useState(
    initial.survivor_social_security_policy ?? "off",
  );
  const [eligibilityConfirmed, setEligibilityConfirmed] = useState(
    initial.survivor_social_security_eligibility_confirmed ?? false,
  );
  const [eligibilitySource, setEligibilitySource] = useState(
    initial.survivor_social_security_eligibility_source ?? "",
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const { dirty, saved, clearSaved, markSaved } = useFormDraftStatus(
    JSON.stringify([
      hasPartner,
      partnerName,
      partnerBirthYear,
      partnerLifeExpectancy,
      stepUp,
      filingAfterDeath,
      customExemption,
      federalExemption,
      portability,
      stateEnabled,
      stateExemption,
      stateRate,
      settlementFixed,
      settlementRate,
      heirRate,
      partnerBirthMonth,
      horizon,
      survivorPolicy,
      eligibilityConfirmed,
      eligibilitySource,
      legacyTarget,
      jointStepUp,
      heirGainsRate,
      sellingCost,
      bequest,
    ]),
  );

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    clearSaved();

    const settlementFixedValue = Number(settlementFixed || 0);
    const settlementRatePct = Number(settlementRate || 0);
    const heirRatePct = Number(heirRate || 0);
    if (!Number.isFinite(settlementFixedValue) || settlementFixedValue < 0) {
      setError("Settlement costs must be zero or a positive dollar amount.");
      return;
    }
    if (!Number.isFinite(settlementRatePct) || settlementRatePct < 0 || settlementRatePct > 50) {
      setError("Settlement cost rate must be between 0 and 50 percent of the estate.");
      return;
    }
    if (!Number.isFinite(heirRatePct) || heirRatePct < 0 || heirRatePct > 100) {
      setError("Heir income tax rate must be between 0 and 100 percent.");
      return;
    }
    const heirGainsPct = Number(heirGainsRate || 0);
    const sellingCostPct = Number(sellingCost || 0);
    const bequestPct = Number(bequest || 0);
    if (!Number.isFinite(heirGainsPct) || heirGainsPct < 0 || heirGainsPct > 100) {
      setError("Heirs' capital gains rate must be between 0 and 100 percent.");
      return;
    }
    if (!Number.isFinite(sellingCostPct) || sellingCostPct < 0 || sellingCostPct > 100) {
      setError("Selling costs must be between 0 and 100 percent of real asset value.");
      return;
    }
    if (!Number.isFinite(bequestPct) || bequestPct < 0 || bequestPct > 100) {
      setError("Charitable bequest must be between 0 and 100 percent of the estate.");
      return;
    }
    const legacyValue = legacyTarget.trim() === "" ? null : Number(legacyTarget);
    if (
      legacyValue !== null &&
      (!Number.isFinite(legacyValue) || legacyValue < 0 || legacyValue > 1e12)
    ) {
      setError("Leave to heirs must be zero or a positive dollar amount.");
      return;
    }

    let spouse: SpouseUpdate | null = null;
    if (hasPartner) {
      const birthYear = partnerBirthYear.trim() === "" ? null : Number(partnerBirthYear);
      const lifeExpectancy =
        partnerLifeExpectancy.trim() === "" ? null : Number(partnerLifeExpectancy);
      if (
        birthYear === null ||
        !Number.isInteger(birthYear) ||
        birthYear < 1900 ||
        birthYear > currentYear
      ) {
        setError(`Partner birth year must be a whole year between 1900 and ${currentYear}.`);
        return;
      }
      if (
        lifeExpectancy === null ||
        !Number.isInteger(lifeExpectancy) ||
        lifeExpectancy < 50 ||
        lifeExpectancy > 120
      ) {
        setError("Partner life expectancy must be a whole age between 50 and 120.");
        return;
      }
      spouse = {
        name: partnerName.trim() || null,
        birth_year: birthYear,
        life_expectancy: lifeExpectancy,
      };
      if (partnerBirthMonth || plan.spouse?.birth_month != null) {
        spouse.birth_month = partnerBirthMonth ? Number(partnerBirthMonth) : null;
      }
    }

    const exemption = Number(federalExemption);
    if (
      customExemption &&
      (federalExemption.trim() === "" || !Number.isFinite(exemption) || exemption < 0)
    ) {
      setError("Custom federal exemption must be zero or a positive dollar amount.");
      return;
    }
    const stateExemptionValue = Number(stateExemption);
    const stateRatePct = Number(stateRate);
    if (stateEnabled) {
      if (
        stateExemption.trim() === "" ||
        !Number.isFinite(stateExemptionValue) ||
        stateExemptionValue < 0
      ) {
        setError("State exemption must be zero or a positive dollar amount.");
        return;
      }
      if (
        stateRate.trim() === "" ||
        !Number.isFinite(stateRatePct) ||
        stateRatePct < 0 ||
        stateRatePct > 100
      ) {
        setError("State estate tax rate must be between 0 and 100 percent.");
        return;
      }
    }

    if (
      horizon === "last_survivor_calendar_year_end" &&
      !["single", "head_of_household"].includes(filingAfterDeath)
    ) {
      setError("Household lifecycle requires Single or Head of household after the first death.");
      return;
    }
    if (
      survivorPolicy !== "off" &&
      (horizon !== "last_survivor_calendar_year_end" ||
        !hasPartner ||
        !partnerBirthMonth ||
        plan.birth_month == null ||
        !eligibilityConfirmed ||
        !eligibilitySource.trim())
    ) {
      setError(
        "Survivor benefits require a household horizon, both birth months, confirmed eligibility and an eligibility note.",
      );
      return;
    }
    const estate_settings: EstateSettings = {
      ...initial,
      step_up_basis_on_death: stepUp,
      filing_status_after_death: filingAfterDeath,
      federal_estate_exemption: customExemption ? exemption : initial.federal_estate_exemption,
      custom_federal_exemption_enabled: customExemption,
      portability_election: portability,
      state_estate_tax_enabled: stateEnabled,
      state_estate_exemption: stateEnabled ? stateExemptionValue : initial.state_estate_exemption,
      state_estate_tax_rate: stateEnabled ? stateRatePct / 100 : initial.state_estate_tax_rate,
      settlement_cost_fixed: settlementFixedValue,
      settlement_cost_rate: settlementRatePct / 100,
      heir_income_tax_rate: heirRatePct / 100,
    };

    if (initial.household_lifecycle !== undefined || horizon !== "legacy_primary_endpoint")
      estate_settings.household_lifecycle = horizon;
    if (initial.survivor_social_security_policy !== undefined || survivorPolicy !== "off")
      estate_settings.survivor_social_security_policy = survivorPolicy;
    if (
      initial.survivor_social_security_eligibility_confirmed !== undefined ||
      eligibilityConfirmed
    )
      estate_settings.survivor_social_security_eligibility_confirmed = eligibilityConfirmed;
    if (
      initial.survivor_social_security_eligibility_source !== undefined ||
      eligibilitySource !== ""
    )
      estate_settings.survivor_social_security_eligibility_source =
        eligibilitySource.trim() || null;
    if (initial.legacy_target !== undefined || legacyValue !== null)
      estate_settings.legacy_target = legacyValue;
    // Opt-in legacy detail: saved only once set, so older documents stay unchanged.
    if (initial.joint_account_step_up !== undefined || jointStepUp)
      estate_settings.joint_account_step_up = jointStepUp;
    if (initial.heir_capital_gains_rate !== undefined || heirGainsPct > 0)
      estate_settings.heir_capital_gains_rate = heirGainsPct / 100;
    if (initial.estate_selling_cost_percent !== undefined || sellingCostPct > 0)
      estate_settings.estate_selling_cost_percent = sellingCostPct;
    if (initial.charitable_bequest_percent !== undefined || bequestPct > 0)
      estate_settings.charitable_bequest_percent = bequestPct;
    setSaving(true);
    Promise.resolve()
      .then(() => onSave(plan.id, { estate_settings, spouse }))
      .then(markSaved)
      // The server's reason, e.g. the partner's incomes and accounts to reassign before removing them.
      .catch(() =>
        setError(
          useSaveStore.getState().failures[`put /plans/${plan.id}`]?.message ??
            "Could not save estate settings. Your edits are retained; try again.",
        ),
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
        <label style={rowStyle}>
          <input
            type="checkbox"
            checked={hasPartner}
            onChange={(e) => setHasPartner(e.target.checked)}
          />
          Plan includes a partner
        </label>
        {hasPartner && (
          <div
            style={{
              display: "grid",
              gap: 8,
              paddingLeft: 12,
              borderLeft: "2px solid var(--surface-border)",
            }}
          >
            <label>
              Partner name (optional)
              <input
                value={partnerName}
                onChange={(e) => setPartnerName(e.target.value)}
                style={{ display: "block", width: "100%" }}
              />
            </label>
            <label>
              Partner birth year
              <input
                type="number"
                min={1900}
                max={currentYear}
                step={1}
                value={partnerBirthYear}
                onChange={(e) => setPartnerBirthYear(e.target.value)}
                style={{ display: "block", width: "100%" }}
              />
            </label>
            <label>
              Partner birth month
              <select
                value={partnerBirthMonth}
                onChange={(e) => setPartnerBirthMonth(e.target.value)}
              >
                <option value="">Not specified (January assumed)</option>
                {Array.from({ length: 12 }, (_, i) => (
                  <option key={i + 1} value={i + 1}>
                    {new Date(2000, i, 1).toLocaleString("en-US", { month: "long" })}
                  </option>
                ))}
              </select>
              <span style={helpStyle}>
                Used for Medicare enrollment and the modeled death month at life expectancy.
              </span>
            </label>
            <label>
              Partner life expectancy (age)
              <input
                type="number"
                min={50}
                max={120}
                step={1}
                value={partnerLifeExpectancy}
                onChange={(e) => setPartnerLifeExpectancy(e.target.value)}
                style={{ display: "block", width: "100%" }}
              />
              <span style={helpStyle}>Survivor Social Security also needs the policy below.</span>
            </label>
          </div>
        )}
        {(hasPartner || horizon !== "legacy_primary_endpoint") && (
          <label>
            Plan ends
            <select
              value={horizon}
              onChange={(e) => setHorizon(e.target.value as typeof horizon)}
              style={{ display: "block", width: "100%" }}
            >
              <option value="legacy_primary_endpoint">At your longevity age</option>
              <option value="last_survivor_calendar_year_end">
                At the last survivor's longevity age
              </option>
            </select>
          </label>
        )}

        {(hasPartner || survivorPolicy !== "off") && (
          <div style={{ display: "grid", gap: 8 }}>
            <label>
              Survivor Social Security policy
              <select
                value={survivorPolicy}
                onChange={(e) => setSurvivorPolicy(e.target.value as typeof survivorPolicy)}
                style={{ display: "block", width: "100%" }}
              >
                <option value="off">Off — no survivor benefit adjustment</option>
                <option value="claimed_benefit_at_survivor_fra">
                  Claimed benefit top-up at survivor full retirement age
                </option>
              </select>
            </label>
            <span style={helpStyle}>
              Adds only the excess of the deceased's claimed benefit over the survivor's own. Early
              deceased claims are not modeled.
            </span>
            {survivorPolicy !== "off" && (
              <>
                <label style={rowStyle}>
                  <input
                    type="checkbox"
                    checked={eligibilityConfirmed}
                    onChange={(e) => setEligibilityConfirmed(e.target.checked)}
                  />
                  Survivor eligibility is confirmed, including remarriage rules
                </label>
                <label>
                  Survivor eligibility note
                  <textarea
                    maxLength={2000}
                    value={eligibilitySource}
                    onChange={(e) => setEligibilitySource(e.target.value)}
                    style={{ display: "block", width: "100%" }}
                  />
                </label>
                <span style={helpStyle}>
                  Requires both birth months and Social Security income streams.
                </span>
              </>
            )}
          </div>
        )}
        {/* Estate and inheritance inputs: collapsed, so the section opens on the partner. */}
        <details className="form-advanced">
          <summary>Estate settings</summary>
          <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
            <label style={rowStyle}>
              <input
                type="checkbox"
                checked={stepUp}
                onChange={(e) => setStepUp(e.target.checked)}
              />
              Step up cost basis on partner-owned taxable accounts at their death
            </label>
            {stepUp ? (
              <label style={rowStyle}>
                <input
                  type="checkbox"
                  checked={jointStepUp}
                  onChange={(e) => setJointStepUp(e.target.checked)}
                />
                Also step up joint taxable accounts at the first death
              </label>
            ) : (
              <label>
                Heirs' capital gains rate on inherited taxable gains (%)
                <input
                  type="number"
                  min={0}
                  max={100}
                  step={0.5}
                  value={heirGainsRate}
                  onChange={(e) => setHeirGainsRate(e.target.value)}
                  style={{ display: "block", width: "100%" }}
                />
                <span style={helpStyle}>
                  Applied to unrealized gains in taxable accounts at death.
                </span>
              </label>
            )}
            {stepUp && jointStepUp && (
              <span style={helpStyle}>
                The deceased partner's half steps up; in a community property state (AZ, CA, ID, LA,
                NV, NM, TX, WA, WI) the whole account does.
              </span>
            )}

            <label>
              Filing status after partner's death
              <select
                value={filingAfterDeath}
                onChange={(e) => setFilingAfterDeath(e.target.value as FilingStatusAfterDeath)}
                style={{ display: "block", width: "100%" }}
              >
                {filingOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <span style={helpStyle}>
                The two-year qualifying surviving spouse status is not modeled.
              </span>
            </label>

            {coverage !== "non_us" && (
              <>
                {coverage === "mixed" && (
                  <p
                    className="us-only-note"
                    style={{ margin: 0, fontSize: 12, color: "var(--text-secondary)" }}
                  >
                    US estate tax, including the exemptions below, applies only to a death in a year
                    you live in the US. A death in another country&apos;s year uses that
                    country&apos;s estate rules, if it has any.
                  </p>
                )}
                <label style={rowStyle}>
                  <input
                    type="checkbox"
                    checked={customExemption}
                    onChange={(e) => setCustomExemption(e.target.checked)}
                  />
                  Override the federal estate exemption
                </label>
                {customExemption ? (
                  <label>
                    {moneyLabel("Federal exemption at death ($, nominal)")}
                    <MoneyInput
                      min={0}
                      step={0.01}
                      value={federalExemption}
                      onValueChange={setFederalExemption}
                      style={{ display: "block", width: "100%" }}
                    />
                    <span style={helpStyle}>
                      Applied in the year of death, not inflation-indexed.
                    </span>
                  </label>
                ) : (
                  <span style={helpStyle}>Default: $15M in 2026, indexed by plan inflation.</span>
                )}

                <label style={rowStyle}>
                  <input
                    type="checkbox"
                    checked={portability}
                    onChange={(e) => setPortability(e.target.checked)}
                  />
                  Elect portability of a deceased partner's unused exemption
                </label>
                <span style={helpStyle}>
                  If your partner dies first, their unused exemption (fixed at that year's amount)
                  is added to yours.
                </span>

                <label style={rowStyle}>
                  <input
                    type="checkbox"
                    checked={stateEnabled}
                    onChange={(e) => setStateEnabled(e.target.checked)}
                  />
                  Apply a state estate tax
                </label>
                {stateEnabled && (
                  <div
                    style={{
                      display: "grid",
                      gap: 8,
                      paddingLeft: 12,
                      borderLeft: "2px solid var(--surface-border)",
                    }}
                  >
                    <label>
                      {moneyLabel("State exemption ($)")}
                      <MoneyInput
                        min={0}
                        step={0.01}
                        value={stateExemption}
                        onValueChange={setStateExemption}
                        style={{ display: "block", width: "100%" }}
                      />
                    </label>
                    <label>
                      State rate on the excess (%)
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step={0.1}
                        value={stateRate}
                        onChange={(e) => setStateRate(e.target.value)}
                        style={{ display: "block", width: "100%" }}
                      />
                      <span style={helpStyle}>
                        One flat rate; brackets and inheritance taxes are not modeled.
                      </span>
                    </label>
                  </div>
                )}
              </>
            )}

            <label>
              {moneyLabel("Settlement costs: fixed ($)")}
              <MoneyInput
                min={0}
                step={0.01}
                value={settlementFixed}
                onValueChange={setSettlementFixed}
                style={{ display: "block", width: "100%" }}
              />
            </label>
            <label>
              Settlement costs: percent of gross estate (%)
              <input
                type="number"
                min={0}
                max={50}
                step={0.1}
                value={settlementRate}
                onChange={(e) => setSettlementRate(e.target.value)}
                style={{ display: "block", width: "100%" }}
              />
              <span style={helpStyle}>
                Probate, administration and liquidation costs; deducted before estate tax.
              </span>
            </label>
            <label>
              Selling costs on real assets (%)
              <input
                type="number"
                min={0}
                max={100}
                step={0.5}
                value={sellingCost}
                onChange={(e) => setSellingCost(e.target.value)}
                style={{ display: "block", width: "100%" }}
              />
              <span style={helpStyle}>
                Commissions and fees to sell property at death; reduces what heirs receive, not the
                taxable estate.
              </span>
            </label>
            <label>
              Charitable bequest (% of estate)
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={bequest}
                onChange={(e) => setBequest(e.target.value)}
                style={{ display: "block", width: "100%" }}
              />
              <span style={helpStyle}>
                Share of the estate after settlement costs left to charity; deducted before estate
                tax.
              </span>
            </label>
            <label>
              {moneyLabel("Leave to heirs (today's $)")}
              <MoneyInput
                min={0}
                step={1000}
                value={legacyTarget}
                onValueChange={setLegacyTarget}
                style={{ display: "block", width: "100%" }}
              />
              <span style={helpStyle}>
                Monte Carlo's default final target; the projection ignores it.
              </span>
            </label>
            <label>
              Heirs' income tax rate on inherited pre-tax accounts (%)
              <input
                type="number"
                min={0}
                max={100}
                step={0.5}
                value={heirRate}
                onChange={(e) => setHeirRate(e.target.value)}
                style={{ display: "block", width: "100%" }}
              />
              <span style={helpStyle}>Not applied when a surviving partner inherits.</span>
            </label>
          </div>
        </details>
        {error && (
          <div role="alert" style={{ color: "var(--color-danger)", fontSize: 13 }}>
            {error}
          </div>
        )}
        <button type="submit">{saving ? "Saving…" : "Save estate settings"}</button>
      </fieldset>
      {dirty && <p role="status">Unsaved estate changes. Save before closing.</p>}
      {saved && (
        <p role="status" style={{ margin: 0, fontSize: 13 }}>
          Estate settings saved.
        </p>
      )}
    </form>
  );
}
