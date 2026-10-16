import FilingStatusSchedule from "../components/filing_status_schedule";
import { useEffect, useRef, useState } from "react";

import YearToDateTaxForm from "@/components/year_to_date_tax_form";
import CoverageForm from "@/components/coverage_form";
import EstimatedTaxForm from "@/components/estimated_tax_form";
import TaxTargetForm from "@/components/tax_target_form";
import TaxAdjustmentsForm from "@/components/tax_adjustments_form";
import TaxLawOverridesForm from "@/components/tax_law_overrides_form";
import {
  CUSTOM_LOCAL_TAX,
  LocalTaxFields,
  localTaxDraft,
  localTaxSelection,
  useLocalTaxJurisdictions,
  withoutCatalogLocality,
  type LocalTaxDraft,
} from "@/components/local_tax_fields";
import { ResidencyTimelineEditor } from "@/components/residency_timeline_editor";
import SaveErrorNotice from "@/components/save_error_notice";
import { useUnloadWarning } from "@/components/use_failed_save_guard";
import { extensions } from "@/extensions";
import { useStorage } from "@/storage/context";
import PlanCountryFields, { type CountryChange } from "@/components/intl/plan_country_fields";
import IntlBenefitsEditor from "@/components/intl/intl_benefits_editor";
import IntlRoomEditor from "@/components/intl/intl_room_editor";
import CustomRegimeEditor from "@/components/intl/custom_regime_editor";
import UsOnlyNote from "@/components/intl/us_only_note";
import { useTaxRegimes } from "@/components/intl/use_tax_regimes";
import {
  CUSTOM_COUNTRY,
  US_COUNTRY,
  benefitRulesFor,
  planCountries,
  planTaxCountry,
  roomKindsFor,
  usCoverage,
} from "@/domain/intl_plan";
import { usePlanStore } from "@/stores/plan_store";
import { MONTH_NAMES } from "@/domain/us_states";
import {
  CollapsibleSection,
  EARLIEST_BIRTH_YEAR,
  filingStatuses,
  formGridStyle,
  usStates,
} from "@/pages/plan_setup_shared";
import type { FilingStatus, PlanCreate, PlanType, TaxSettings } from "@/types/plan";
import { usePlanAccounts } from "@/utils/use_plan_accounts";

const TAX_SETTINGS_DEFAULTS: TaxSettings = {
  mode: "detailed",
  ordinary_income_tax_rate: null,
  capital_gains_tax_rate: null,
  taxable_withholding_rate: 0,
  tax_deferred_withholding_rate: 0,
  settlement_lag_years: 0,
  cash_flow_frequency: "monthly",
};

/** Parse "2019, 2022" into birth years, or return an error message. */
function parseBirthYears(text: string): number[] | string {
  const parts = text.split(/[\s,]+/).filter(Boolean);
  const years = parts.map(Number);
  if (years.some((year) => !Number.isInteger(year) || year < 1900 || year > 2300)) {
    return "Enter four-digit years separated by commas.";
  }
  if (years.length > 20) return "Enter at most 20 children.";
  return years;
}

// Saved together, so an edit blocked by one rule saves with the fix to another field.
const TIMELINE_FIELDS = [
  "plan_type",
  "start_date",
  "birth_year",
  "birth_month",
  "life_expectancy",
] as const;

function birthDateOf(year: number | string, month: number | string | null) {
  return `${year}-${String(month || 1).padStart(2, "0")}-01`;
}

function startYearOf(planType: PlanType, startDate: string | null) {
  return planType === "FIXED_DATE" && startDate
    ? Number(startDate.slice(0, 4))
    : new Date().getFullYear();
}

/** A whole year from 120 years ago (the server's floor is 1900) through this year. */
function birthYearError(birthYear: string): string | null {
  const year = Number(birthYear);
  const earliest = Math.max(1900, EARLIEST_BIRTH_YEAR);
  const latest = new Date().getFullYear();
  if (birthYear.trim() === "" || !Number.isInteger(year) || year < earliest || year > latest)
    return `Enter a year from ${earliest} to ${latest}.`;
  return null;
}

/** Longevity must be a whole age the server accepts and outlast the start year, as on iOS. */
function longevityError(longevity: string, birthYear: number, startYear: number): string | null {
  const age = Number(longevity);
  if (longevity.trim() === "" || !Number.isInteger(age) || age < 50 || age > 120)
    return "Enter a whole age from 50 to 120.";
  if (Number.isInteger(birthYear) && birthYear >= 1900 && birthYear + age <= startYear)
    return "Choose a longevity age past the plan's start year.";
  return null;
}

export function PlanHeader() {
  const plan = usePlanStore((s) => s.plan);
  const { adapter } = useStorage();
  const { accounts } = usePlanAccounts(adapter, plan?.id);
  const updatePlan = usePlanStore((s) => s.updatePlan);
  const updateResidencyPeriods = usePlanStore((s) => s.updateResidencyPeriods);
  const jurisdictions = useLocalTaxJurisdictions(adapter);
  const regimes = useTaxRegimes(adapter);

  const [name, setName] = useState("");
  const [planType, setPlanType] = useState<PlanType>("NOW");
  // Free-text plan fields an extension adds, keyed by field.
  const [textDrafts, setTextDrafts] = useState<Record<string, string>>({});
  const [birthYear, setBirthYear] = useState("");
  const [birthMonth, setBirthMonth] = useState("");
  const [lifeExpectancy, setLifeExpectancy] = useState("");
  const [filingStatus, setFilingStatus] = useState<FilingStatus>("single");
  const [mfsApart, setMfsApart] = useState(false);
  const [medicalDeductions, setMedicalDeductions] = useState(false);
  const [stateEducationDeduction, setStateEducationDeduction] = useState(false);
  const [childYears, setChildYears] = useState("");
  const [childYearsError, setChildYearsError] = useState<string | null>(null);
  const [startDate, setStartDate] = useState("");
  const [stateCode, setStateCode] = useState<string>("");
  const [localTax, setLocalTax] = useState<LocalTaxDraft>(() => localTaxDraft(plan?.local_tax));
  const [localTaxError, setLocalTaxError] = useState<string | null>(null);
  const [taxCountry, setTaxCountry] = useState<string>(() => planTaxCountry(plan));
  const [taxRegion, setTaxRegion] = useState<string | null>(plan?.tax_region ?? null);
  const [currency, setCurrency] = useState<string>(plan?.currency || "USD");

  // Revisions distinguish the value submitted from edits made while it saves.
  const edits = useRef<Record<string, number>>({});
  const draftPlanId = useRef(plan?.id);
  const saveQueue = useRef<Promise<void> | null>(null);
  function edited(field: keyof PlanCreate) {
    edits.current[field] = (edits.current[field] ?? 0) + 1;
  }
  // Fields whose last save failed keep their drafts. While any do, closing the editor asks first
  // (EditSheet reads `data-unsaved-changes`) and so does leaving the page.
  const [failedSave, setFailedSave] = useState<{ fields: string[]; message: string } | null>(null);
  useUnloadWarning(failedSave !== null);
  function settled(fields: string[]) {
    setFailedSave((prev) => {
      const rest = prev?.fields.filter((field) => !fields.includes(field)) ?? [];
      return prev && rest.length ? { ...prev, fields: rest } : null;
    });
  }

  useEffect(() => {
    if (!plan) return;
    if (draftPlanId.current !== plan.id) {
      edits.current = {};
      draftPlanId.current = plan.id;
      setFailedSave(null);
    }
    if (!edits.current.name) setName(plan.name);
    if (!edits.current.plan_type) setPlanType(plan.plan_type);
    const savedText: Record<string, string> = {};
    for (const { field } of extensions.planner?.planTextFields ?? [])
      if (!edits.current[field]) savedText[field] = plan[field] ?? "";
    setTextDrafts((drafts) => ({ ...drafts, ...savedText }));
    if (!edits.current.birth_year) setBirthYear(plan.birth_year.toString());
    if (!edits.current.birth_month)
      setBirthMonth(plan.birth_month != null ? String(plan.birth_month) : "");
    if (!edits.current.life_expectancy)
      setLifeExpectancy(plan.life_expectancy != null ? String(plan.life_expectancy) : "");
    if (!edits.current.filing_status) setFilingStatus(plan.filing_status);
    if (!edits.current.tax_settings) {
      setMfsApart(plan.tax_settings?.mfs_lived_apart_all_year ?? false);
      setMedicalDeductions(plan.tax_settings?.medical_expense_deductions ?? false);
      setStateEducationDeduction(plan.tax_settings?.state_529_deduction ?? false);
      setChildYears((plan.tax_settings?.dependent_birth_years ?? []).join(", "));
    }
    if (!edits.current.start_date) setStartDate(plan.start_date ?? "");
    if (!edits.current.state_code) setStateCode(plan.state_code ?? "");
    if (!edits.current.local_tax) setLocalTax(localTaxDraft(plan.local_tax));
    if (!edits.current.tax_country) setTaxCountry(planTaxCountry(plan));
    if (!edits.current.tax_region) setTaxRegion(plan.tax_region ?? null);
    if (!edits.current.currency) setCurrency(plan.currency || "USD");
  }, [plan]);

  if (!plan) return null;
  const currentPlan = plan;
  const birthDate = birthDateOf(birthYear, birthMonth);
  const dateError =
    planType === "FIXED_DATE" && startDate && startDate < birthDate
      ? "Start date must be on or after your birth year/month."
      : null;
  const horizonError = longevityError(
    lifeExpectancy,
    Number(birthYear),
    startYearOf(planType, startDate),
  );
  const birthError = birthYearError(birthYear);
  // The saved plan decides what shows: if the server rejects a country switch
  // over a US-only setting, that setting stays visible to fix.
  const coverage = usCoverage(currentPlan);
  const countries = planCountries(currentPlan);
  const benefitRules = benefitRulesFor(regimes.countries, countries);
  const savedBenefits = currentPlan.intl_settings?.benefits ?? [];
  const roomKinds = roomKindsFor(regimes.countries, countries);
  const savedRoom = currentPlan.intl_settings?.starting_room ?? [];
  const usesCustomCountry = countries.includes(CUSTOM_COUNTRY);

  function save(data: Partial<PlanCreate>) {
    // A blur without an edit must not write an older tab's value back.
    if (!Object.keys(data).some((field) => edits.current[field])) return;
    if (TIMELINE_FIELDS.some((field) => field in data)) {
      const nextType = data.plan_type ?? planType;
      const nextDate = data.start_date === undefined ? startDate : data.start_date;
      const nextBirthYear = data.birth_year ?? Number(birthYear);
      const nextBirthMonth = data.birth_month === undefined ? birthMonth : data.birth_month;
      const nextLongevity =
        data.life_expectancy === undefined ? lifeExpectancy : String(data.life_expectancy);
      if (birthYearError(String(nextBirthYear))) return;
      if (
        nextType === "FIXED_DATE" &&
        nextDate &&
        nextDate < birthDateOf(nextBirthYear, nextBirthMonth)
      )
        return;
      if (longevityError(nextLongevity, nextBirthYear, startYearOf(nextType, nextDate))) return;
    }
    const submitted = { ...edits.current };
    const persist = async () => {
      await updatePlan(currentPlan.id, data);
      if (draftPlanId.current !== currentPlan.id) return;
      const fields = Object.keys(data);
      const error = usePlanStore.getState().error;
      if (error) {
        setFailedSave((prev) => ({
          fields: [...new Set([...(prev?.fields ?? []), ...fields])],
          message: error,
        }));
        return;
      }
      for (const field of fields) {
        if (edits.current[field] === submitted[field]) delete edits.current[field];
      }
      settled(fields);
    };
    // Preserve write order even when the same field is edited again in flight.
    const pending = saveQueue.current ? saveQueue.current.then(persist) : persist();
    saveQueue.current = pending;
    void pending.finally(() => {
      if (saveQueue.current === pending) saveQueue.current = null;
    });
  }

  /** Saves every edited date field together with the latest change. */
  function saveTimeline(changes: Partial<PlanCreate> = {}) {
    const type = changes.plan_type ?? planType;
    const draft: Partial<PlanCreate> = {
      plan_type: type,
      start_date: type === "FIXED_DATE" ? startDate || null : null,
      birth_year: Number(birthYear),
      birth_month: birthMonth ? Number(birthMonth) : null,
      life_expectancy: Number(lifeExpectancy),
      ...changes,
    };
    save(
      Object.fromEntries(
        TIMELINE_FIELDS.filter((field) => edits.current[field]).map((field) => [
          field,
          draft[field],
        ]),
      ) as Partial<PlanCreate>,
    );
  }

  function saveChildYears() {
    const parsed = parseBirthYears(childYears);
    if (typeof parsed === "string") {
      setChildYearsError(parsed);
      return;
    }
    setChildYearsError(null);
    save({
      tax_settings: {
        ...TAX_SETTINGS_DEFAULTS,
        ...currentPlan.tax_settings,
        dependent_birth_years: parsed,
      },
    });
  }

  function saveLocalTax(draft: LocalTaxDraft) {
    const result = localTaxSelection(draft);
    if ("error" in result) {
      setLocalTaxError(result.error);
      return;
    }
    setLocalTaxError(null);
    save({ local_tax: result.selection });
  }

  /** Sends only the fields that differ from the saved plan. */
  function saveCountry(change: CountryChange) {
    const data: Partial<PlanCreate> = {};
    if (change.tax_country !== planTaxCountry(currentPlan)) data.tax_country = change.tax_country;
    if (change.tax_region !== (currentPlan.tax_region ?? null)) data.tax_region = change.tax_region;
    if (change.currency && change.currency !== (currentPlan.currency || "USD"))
      data.currency = change.currency;
    for (const field of Object.keys(data) as (keyof PlanCreate)[]) edited(field);
    setTaxCountry(change.tax_country);
    setTaxRegion(change.tax_region);
    if (change.currency) setCurrency(change.currency);
    save(data);
  }

  async function saveIntlSettings(changes: Partial<NonNullable<PlanCreate["intl_settings"]>>) {
    await updatePlan(currentPlan.id, {
      intl_settings: { ...(currentPlan.intl_settings ?? {}), ...changes },
    });
    const error = usePlanStore.getState().error;
    if (error) throw new Error(error);
  }

  return (
    <CollapsibleSection title="Plan details" defaultOpen={false}>
      {failedSave && (
        <div data-unsaved-changes="true">
          <SaveErrorNotice message={failedSave.message} focus={false} />
        </div>
      )}
      <div style={formGridStyle}>
        <label>
          Plan name
          <input
            value={name}
            required
            onChange={(e) => {
              edited("name");
              setName(e.target.value);
            }}
            onBlur={() => {
              // A plan always has a name: clearing it puts the saved name back.
              if (!name.trim()) {
                delete edits.current.name;
                setName(currentPlan.name);
                settled(["name"]);
                return;
              }
              save({ name: name.trim() });
            }}
          />
        </label>

        <label>
          Plan type
          <select
            value={planType}
            onChange={(e) => {
              const val = e.target.value as PlanType;
              edited("plan_type");
              edited("start_date");
              setPlanType(val);
              saveTimeline({
                plan_type: val,
                start_date: val === "FIXED_DATE" ? startDate || null : null,
              });
            }}
          >
            <option value="NOW">Now (starts today)</option>
            <option value="FIXED_DATE">Fixed date</option>
          </select>
        </label>

        {planType === "FIXED_DATE" && (
          <label>
            Start date
            <input
              type="date"
              min={birthDate}
              aria-invalid={dateError ? true : undefined}
              aria-describedby={dateError ? "plan-start-date-error" : undefined}
              value={startDate}
              onChange={(e) => {
                edited("start_date");
                setStartDate(e.target.value);
              }}
              onBlur={() => saveTimeline()}
            />
            {dateError && (
              <span id="plan-start-date-error" role="alert" className="field-error">
                {dateError} The forecast keeps the last saved date.
              </span>
            )}
          </label>
        )}

        <label>
          Birth year
          <input
            type="number"
            min={EARLIEST_BIRTH_YEAR}
            max={new Date().getFullYear()}
            aria-invalid={birthError ? true : undefined}
            aria-describedby={birthError ? "plan-birth-year-error" : undefined}
            value={birthYear}
            onChange={(e) => {
              edited("birth_year");
              setBirthYear(e.target.value);
            }}
            onBlur={() => saveTimeline()}
          />
          {birthError && (
            <span id="plan-birth-year-error" role="alert" className="field-error">
              {birthError} The forecast keeps {plan.birth_year}.
            </span>
          )}
        </label>

        <label>
          Birth month
          <select
            value={birthMonth}
            onChange={(e) => {
              const val = e.target.value;
              edited("birth_month");
              setBirthMonth(val);
              saveTimeline({ birth_month: val ? Number(val) : null });
            }}
          >
            <option value="">Not specified (January assumed)</option>
            {MONTH_NAMES.map((month, i) => (
              <option key={month} value={i + 1}>
                {month}
              </option>
            ))}
          </select>
        </label>

        <label>
          Longevity age
          <input
            type="number"
            min={50}
            max={120}
            step={1}
            aria-invalid={horizonError ? true : undefined}
            aria-describedby={horizonError ? "plan-longevity-error" : undefined}
            value={lifeExpectancy}
            onChange={(e) => {
              edited("life_expectancy");
              setLifeExpectancy(e.target.value);
            }}
            onBlur={() => saveTimeline()}
          />
          {horizonError && (
            <span id="plan-longevity-error" role="alert" className="field-error">
              {horizonError} The forecast keeps age {plan.life_expectancy}.
            </span>
          )}
        </label>

        <PlanCountryFields
          regimes={regimes}
          country={taxCountry}
          region={taxRegion}
          currency={currency}
          onCountryChange={saveCountry}
          onRegionChange={(region) => {
            edited("tax_region");
            setTaxRegion(region);
            save({ tax_region: region });
          }}
          onCurrencyChange={(code) => {
            edited("currency");
            setCurrency(code);
            save({ currency: code });
          }}
        />

        <label>
          Filing status
          <select
            value={filingStatus}
            onChange={(e) => {
              const val = e.target.value as FilingStatus;
              edited("filing_status");
              setFilingStatus(val);
              save({ filing_status: val });
            }}
          >
            {filingStatuses.map((status) => (
              <option key={status.value} value={status.value}>
                {status.label}
              </option>
            ))}
          </select>
        </label>

        {planTaxCountry(currentPlan) === US_COUNTRY && (
          <label>
            State
            <select
              value={stateCode}
              onChange={(e) => {
                const val = e.target.value;
                edited("state_code");
                setStateCode(val);
                // The server clears a locality from the old state with this save.
                setLocalTax(withoutCatalogLocality(localTax));
                save({ state_code: val || null });
              }}
            >
              {usStates.map((state) => (
                <option key={state.value} value={state.value}>
                  {state.label}
                </option>
              ))}
            </select>
          </label>
        )}

        {planTaxCountry(currentPlan) === US_COUNTRY && (stateCode || localTax.jurisdiction) && (
          <LocalTaxFields
            stateCode={stateCode}
            value={localTax}
            jurisdictions={jurisdictions}
            onChange={(next) => {
              edited("local_tax");
              setLocalTax(next);
              setLocalTaxError(null);
              // Custom rates save once one is entered (on blur).
              if (next.jurisdiction !== CUSTOM_LOCAL_TAX) saveLocalTax(next);
            }}
            onRateBlur={() => saveLocalTax(localTax)}
          />
        )}
        {localTaxError && (
          <p role="alert" style={{ gridColumn: "1 / -1", margin: 0 }}>
            {localTaxError}
          </p>
        )}
      </div>

      {/* Everything past the essentials: collapsed, so the sheet opens on the fields every plan needs. Its
          tables (filing-status changes, residency, coverage, tax history) save with their own buttons. */}
      <details className="form-advanced" id="plan-advanced-tax">
        <summary>Advanced tax settings</summary>
        <div style={{ ...formGridStyle, marginTop: 12 }}>
          {(extensions.planner?.planTextFields ?? []).map(
            ({ field, label, autoComplete, maxLength }) => (
              <label key={field}>
                {label}
                <input
                  autoComplete={autoComplete}
                  maxLength={maxLength}
                  value={textDrafts[field] ?? ""}
                  onChange={(e) => {
                    edited(field);
                    setTextDrafts((drafts) => ({ ...drafts, [field]: e.target.value }));
                  }}
                  onBlur={() => save({ [field]: (textDrafts[field] ?? "").trim() || null })}
                />
              </label>
            ),
          )}

          <FilingStatusSchedule
            key={`filing-status-${plan.id}`}
            initial={plan.filing_status_changes ?? []}
            milestones={plan.milestones}
            onSave={async (rows) => {
              await updatePlan(plan.id, { filing_status_changes: rows });
              const error = usePlanStore.getState().error;
              if (error) throw new Error(error);
            }}
          />

          {coverage !== "non_us" && (
            <UsOnlyNote
              coverage={coverage}
              what="State and local tax and the US deductions and credits below"
            />
          )}

          {coverage !== "non_us" && filingStatus === "married_filing_separately" && (
            <label>
              <input
                type="checkbox"
                checked={mfsApart}
                onChange={(e) => {
                  const value = e.target.checked;
                  edited("tax_settings");
                  setMfsApart(value);
                  save({
                    tax_settings: {
                      ...TAX_SETTINGS_DEFAULTS,
                      ...currentPlan.tax_settings,
                      mfs_lived_apart_all_year: value,
                    },
                  });
                }}
              />{" "}
              Lived apart from spouse for the entire tax year
              <span style={{ display: "block", fontSize: 12 }}>
                Uses single-filer Social Security thresholds in every projected year.
              </span>
            </label>
          )}

          {coverage !== "non_us" && (
            <>
              <label>
                Children's birth years
                <input
                  inputMode="numeric"
                  placeholder="2019, 2022"
                  aria-invalid={childYearsError ? true : undefined}
                  aria-describedby="child-birth-years-help"
                  value={childYears}
                  onChange={(e) => {
                    edited("tax_settings");
                    setChildYears(e.target.value);
                    setChildYearsError(null);
                  }}
                  onBlur={saveChildYears}
                />
                <span
                  id="child-birth-years-help"
                  className={childYearsError ? "field-error" : undefined}
                  style={childYearsError ? undefined : { display: "block", fontSize: 12 }}
                >
                  {childYearsError ?? "Comma-separated; used for the federal child tax credit."}
                </span>
              </label>

              <label>
                <input
                  type="checkbox"
                  checked={medicalDeductions}
                  onChange={(e) => {
                    const value = e.target.checked;
                    edited("tax_settings");
                    setMedicalDeductions(value);
                    save({
                      tax_settings: {
                        ...TAX_SETTINGS_DEFAULTS,
                        ...currentPlan.tax_settings,
                        medical_expense_deductions: value,
                      },
                    });
                  }}
                />{" "}
                Deduct medical expenses
                <span style={{ display: "block", fontSize: 12 }}>
                  Itemizes modeled health costs above 7.5% of AGI, less HSA reimbursements;
                  self-employed households deduct premiums up to business profit.
                </span>
              </label>

              <label>
                <input
                  type="checkbox"
                  checked={stateEducationDeduction}
                  onChange={(e) => {
                    const value = e.target.checked;
                    edited("tax_settings");
                    setStateEducationDeduction(value);
                    save({
                      tax_settings: {
                        ...TAX_SETTINGS_DEFAULTS,
                        ...currentPlan.tax_settings,
                        state_529_deduction: value,
                      },
                    });
                  }}
                />{" "}
                State deduction for 529 contributions
                <span style={{ display: "block", fontSize: 12 }}>
                  Assumes contributions go to your state's own plan. Modeled for MA, MI, MO, NY and
                  SC; other states take no deduction.
                </span>
              </label>
            </>
          )}

          <ResidencyTimelineEditor
            key={`residency-${currentPlan.id}`}
            milestones={currentPlan.milestones}
            periods={currentPlan.residency_periods ?? []}
            onChange={(rows) => updateResidencyPeriods(currentPlan.id, rows)}
            jurisdictions={jurisdictions}
            planCountry={taxCountry}
            countries={regimes.countries}
          />

          {(benefitRules.length > 0 || savedBenefits.length > 0) && (
            <IntlBenefitsEditor
              key={`benefits-${currentPlan.id}`}
              benefits={savedBenefits}
              rules={benefitRules}
              milestones={currentPlan.milestones}
              hasPartner={currentPlan.spouse != null}
              onSave={(benefits) => saveIntlSettings({ benefits })}
            />
          )}

          {(roomKinds.length > 0 || savedRoom.length > 0) && (
            <IntlRoomEditor
              key={`room-${currentPlan.id}`}
              kinds={roomKinds}
              startingRoom={savedRoom}
              priorIncome={currentPlan.intl_settings?.prior_year_earned_income ?? null}
              hasPartner={currentPlan.spouse != null}
              onSave={(settings) => saveIntlSettings(settings)}
            />
          )}

          {usesCustomCountry && (
            <CustomRegimeEditor
              key={`custom-regime-${currentPlan.id}`}
              document={currentPlan.intl_settings?.custom_regime}
              baseYear={startYearOf(planType, startDate)}
              currency={currency}
              onSave={(custom_regime) => saveIntlSettings({ custom_regime })}
            />
          )}
        </div>
        {coverage !== "non_us" && (
          <>
            <UsOnlyNote
              coverage={coverage}
              what="Coverage, tax history, estimated payments, tax targets and tax adjustments"
            />
            <CoverageForm
              key={`coverage-${currentPlan.id}`}
              plan={currentPlan}
              onSave={async (tax_settings) => {
                await updatePlan(currentPlan.id, { tax_settings });
                const error = usePlanStore.getState().error;
                if (error) throw new Error(error);
              }}
            />
            <YearToDateTaxForm
              key={currentPlan.id}
              plan={currentPlan}
              accounts={accounts}
              onSave={async (tax_settings) => {
                await updatePlan(currentPlan.id, { tax_settings });
                const error = usePlanStore.getState().error;
                if (error) throw new Error(error);
              }}
            />
            <EstimatedTaxForm
              key={`estimated-${currentPlan.id}`}
              plan={currentPlan}
              onSave={async (tax_settings) => {
                await updatePlan(currentPlan.id, { tax_settings });
                const error = usePlanStore.getState().error;
                if (error) throw new Error(error);
              }}
            />
            <TaxTargetForm
              key={`tax-target-${currentPlan.id}`}
              plan={currentPlan}
              onSave={async (tax_settings) => {
                await updatePlan(currentPlan.id, { tax_settings });
                const error = usePlanStore.getState().error;
                if (error) throw new Error(error);
              }}
            />
            <TaxAdjustmentsForm
              key={`tax-adjustments-${currentPlan.id}`}
              plan={currentPlan}
              onSave={async (tax_settings) => {
                await updatePlan(currentPlan.id, { tax_settings });
                const error = usePlanStore.getState().error;
                if (error) throw new Error(error);
              }}
            />
            <TaxLawOverridesForm
              key={`tax-law-${currentPlan.id}`}
              plan={currentPlan}
              onSave={async (tax_settings) => {
                await updatePlan(currentPlan.id, { tax_settings });
                const error = usePlanStore.getState().error;
                if (error) throw new Error(error);
              }}
            />
          </>
        )}
      </details>
    </CollapsibleSection>
  );
}
