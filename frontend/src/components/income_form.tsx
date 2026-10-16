import { useState } from "react";
import type {
  Income,
  IncomeCreate,
  Milestone,
  MilestoneOutcome,
  PlanType,
  SsBenefitBasis,
} from "@/types/plan";
import {
  resolveMilestoneYear,
  milestoneWindowError,
  milestoneWindowWarning,
} from "@/utils/milestone_window";
import {
  entryAnnual,
  entryDisplay,
  hourlyAnnual,
  initialEntry,
  openingFrequency,
  type AmountEntry,
  type AmountFrequency,
} from "@/utils/amount_frequency";
import {
  scheduleFromRows,
  segmentRowsFrom,
  type SegmentRow,
} from "@/components/income_growth_schedule_editor";
import {
  exSpouseDraft,
  exSpouseFromDraft,
  type ExSpouseDraft,
} from "@/components/ex_spouse_fields";
import { IncomeAmountFields } from "./income/income_amount_fields";
import { IncomeGrowthTaxFields } from "./income/income_growth_tax_fields";
import { IncomeTimingFields } from "./income/income_timing_fields";
import {
  PensionFormulaFields,
  pensionDraft,
  type PensionDraft,
} from "./income/pension_formula_fields";
import {
  SocialSecurityBenefitFields,
  type PiaReflects,
} from "./income/social_security_benefit_fields";
import {
  useBenefitPreview,
  useSocialSecurityEstimate,
} from "./income/use_social_security_estimate";
import { PARTNER_LABEL, PRIMARY_PERSON_LABEL } from "@/domain/person_labels";
import { FormFooter } from "./form_footer";
import { choiceLabelStyle, formStyle } from "./form_styles";

interface IncomeFormProps {
  initial?: Income;
  milestones: Milestone[];
  /** The plan's other incomes; their earnings seed the Social Security estimate. */
  incomes?: Income[];
  hasPartner?: boolean;
  /** Plan owner's birth year, used to check that the start milestone precedes the end. */
  birthYear?: number | null;
  /** Milestone years from the latest projection, for windows that depend on it. */
  outcomes?: MilestoneOutcome[] | null;
  /** Partner's birth year, so a spouse's claiming age shows the right calendar year. */
  spouseBirthYear?: number | null;
  /** "Now" plans label the default start "Now"; fixed-date plans keep "Plan start". */
  planType?: PlanType;
  /** Outside the US the Social Security choice is a US benefit received abroad, with no estimate from local wages. */
  usCoverage?: "us" | "mixed" | "non_us";
  onSubmit: (data: IncomeCreate) => void;
  onCancel: () => void;
}

/** Unit for new incomes and for those saved before units were stored. */
const LEGACY_FREQUENCY: AmountFrequency = "annual";

/** A UI choice over the saved flags: salary is earned, other is not by default. */
type IncomeType = "salary" | "social_security" | "other";
const INCOME_TYPES: { value: IncomeType; label: string }[] = [
  { value: "salary", label: "Salary" },
  { value: "social_security", label: "Social Security" },
  { value: "other", label: "Other" },
];
/** Names a new income starts with; Other is left for the user to name. */
const TYPE_NAMES: Record<IncomeType, string> = {
  salary: "Salary",
  social_security: "Social Security",
  other: "",
};

/** Whether a valid growth schedule sets or adds dollars, so the income can start at $0. */
function schedulesDollars(rows: SegmentRow[]): boolean {
  return (scheduleFromRows(rows).schedule ?? []).some(
    (segment) =>
      (segment.kind === "set_amount" || segment.kind === "dollar_change") && segment.value > 0,
  );
}

function incomeTypeOf(income: Income | undefined): IncomeType {
  if (!income) return "salary";
  if (income.is_social_security) return "social_security";
  return income.is_earned_income ? "salary" : "other";
}

/**
 * The milestone a new salary ends at, with any trigger: the first named like
 * "Retirement" for the primary person. For the partner, the first named like
 * "Partner retirement", else the primary person's "Retirement", so a partner's
 * salary never silently runs to the end of the plan. Matches iOS
 * (`Plan.retirementMilestone(for:)`).
 */
function retirementMilestoneFor(milestones: Milestone[], owner: "self" | "spouse"): string {
  const retirement = milestones.filter((m) => /retire/i.test(m.name));
  const partner = retirement.filter((m) => /partner|spouse/i.test(m.name));
  const primary = retirement.find((m) => !partner.includes(m));
  return (owner === "spouse" ? (partner[0] ?? primary) : primary)?.id ?? "";
}

export default function IncomeForm({
  initial,
  milestones,
  incomes = [],
  hasPartner = true,
  birthYear = null,
  outcomes = null,
  spouseBirthYear = null,
  planType = "NOW",
  usCoverage = "us",
  onSubmit,
  onCancel,
}: IncomeFormProps) {
  const [paymentFrequency, setPaymentFrequency] = useState<"recurring" | "once">(
    initial?.frequency ?? "recurring",
  );
  const [repeatYears, setRepeatYears] = useState(initial?.recurrence_years?.toString() ?? "");
  // Every year is the default; an interval in years is asked for only when chosen.
  const [intervalRepeat, setIntervalRepeat] = useState(initial?.recurrence_years != null);
  const [pension, setPension] = useState<PensionDraft>(() =>
    pensionDraft(initial?.pension_formula),
  );
  const [name, setName] = useState(initial?.name ?? TYPE_NAMES.salary);
  const [owner, setOwner] = useState<"self" | "spouse">(initial?.owner ?? "self");
  // A new salary ends at its recipient's Retirement milestone when the plan has one.
  const retirementMilestoneId = retirementMilestoneFor(milestones, owner);
  // Reopen in the unit saved with the income; the amount itself stays annual.
  const savedUnit = initial?.amount_frequency === "hourly" ? "annual" : initial?.amount_frequency;
  const [frequency, setFrequency] = useState<AmountFrequency>(
    initial?.frequency === "once" ? "annual" : openingFrequency(savedUnit, LEGACY_FREQUENCY),
  );
  // Keep the entered value and its unit: changing the display unit must not
  // round an existing annual amount or repeatedly convert it back and forth.
  const [amount, setAmount] = useState<AmountEntry>(
    initialEntry(initial?.annual_amount, frequency),
  );
  // Hourly pay keeps its rate and weekly hours; the server derives the annual amount.
  const [hourly, setHourly] = useState(initial?.amount_frequency === "hourly");
  const [hourlyRate, setHourlyRate] = useState(initial?.hourly_rate?.toString() ?? "");
  const [hoursPerWeek, setHoursPerWeek] = useState(initial?.hours_per_week?.toString() ?? "40");
  const hourlyPay = hourly && paymentFrequency !== "once";
  const annualAmount = hourlyPay
    ? hourlyAnnual(Number(hourlyRate), Number(hoursPerWeek))
    : entryAnnual(amount);
  const displayedAmount = entryDisplay(amount, frequency);
  const [growthRate, setGrowthRate] = useState(initial?.growth_rate?.toString() ?? "");
  const [startMilestoneId, setStartMilestoneId] = useState(initial?.start_milestone_id ?? "");
  const [endMilestoneId, setEndMilestoneId] = useState(
    initial ? (initial.end_milestone_id ?? "") : retirementMilestoneId,
  );
  const [startMonth, setStartMonth] = useState<number | null>(initial?.start_month ?? null);
  const [endMonth, setEndMonth] = useState<number | null>(initial?.end_month ?? null);
  const windowError = milestoneWindowError(
    startMilestoneId,
    endMilestoneId,
    milestones,
    birthYear,
    startMonth,
    endMonth,
  );
  const windowWarning = windowError
    ? null
    : milestoneWindowWarning(startMilestoneId, endMilestoneId, milestones, outcomes);
  const [incomeType, setIncomeType] = useState<IncomeType>(incomeTypeOf(initial));
  const isSocialSecurity = incomeType === "social_security";
  // Only Other income can be marked earned or not; a salary is always earned.
  const [isEarnedIncome, setIsEarnedIncome] = useState(initial?.is_earned_income ?? true);
  const earned = incomeType === "salary" || (incomeType === "other" && isEarnedIncome);
  const [isSelfEmployed, setIsSelfEmployed] = useState(initial?.is_self_employed ?? false);
  const [unearnedCategory, setUnearnedCategory] = useState<
    NonNullable<Income["tax_category"]> | ""
  >(
    initial?.tax_category &&
      !["employment", "self_employment", "social_security"].includes(initial.tax_category)
      ? initial.tax_category
      : "",
  );
  const usesPensionFormula =
    !isSocialSecurity && !earned && unearnedCategory === "qualified_pension" && pension.kind !== "";
  const [growthCap, setGrowthCap] = useState(
    initial?.growth_cap != null ? String(initial.growth_cap) : "",
  );
  const [growthCapInflationLinked, setGrowthCapInflationLinked] = useState(
    initial?.growth_cap_inflation_linked ?? false,
  );
  const [withholdingPercent, setWithholdingPercent] = useState(
    initial?.withholding_percent != null ? String(initial.withholding_percent) : "",
  );
  const [isActive, setIsActive] = useState(initial?.is_active ?? true);
  const [validationError, setValidationError] = useState<string | null>(null);
  // Persisted on the income: the engine starts benefits the year this age is
  // reached unless a start milestone is chosen. Older streams without one
  // keep starting at the milestone or plan start, shown as "Not set".
  const [claimingAge, setClaimingAge] = useState<number | null>(
    initial ? (initial.claiming_age ?? null) : 67,
  );
  const claimBirthYear = owner === "spouse" ? (spouseBirthYear ?? null) : birthYear;
  const claimYear =
    claimingAge != null && claimBirthYear != null ? claimBirthYear + claimingAge : null;
  const startMilestone = milestones.find((m) => m.id === startMilestoneId);
  const startYear = startMilestone
    ? resolveMilestoneYear(startMilestone, milestones, birthYear)
    : null;
  const ssEstimate = useSocialSecurityEstimate({
    incomes,
    initialOwner: initial?.owner ?? "self",
    birthYear,
    spouseBirthYear,
    claimingAge,
    claimBirthYear,
    onEstimate: (annual) => setAmount({ value: annual.toFixed(2), frequency: "annual" }),
  });
  // PIA basis: the projection sizes the benefit from the PIA and claim date
  // and adds spousal and survivor amounts; annual_amount is only a preview.
  const [basis, setBasis] = useState<SsBenefitBasis>(
    initial?.ss_benefit_basis === "pia" ? "pia" : "amount",
  );
  const [piaReflects, setPiaReflects] = useState<PiaReflects>(
    initial?.pia_reflects ?? "continued_work",
  );
  const [coveredYears, setCoveredYears] = useState(initial?.covered_years_to_date ?? 35);
  const isPiaBasis = isSocialSecurity && basis === "pia";
  const [basisPia, setBasisPia] = useState(
    initial?.pia_monthly != null ? String(initial.pia_monthly) : "",
  );
  const [basisExpected, setBasisExpected] = useState(
    initial?.expected_benefit_percent != null ? String(initial.expected_benefit_percent) : "100",
  );
  const preview = useBenefitPreview({
    enabled: isPiaBasis,
    pia: basisPia,
    expectedPercent: basisExpected,
    claimingAge,
    claimBirthYear,
  });
  // Year-segment growth (not for Social Security or formula pensions) and a
  // former spouse's record (PIA basis only).
  const [segmentRows, setSegmentRows] = useState<SegmentRow[]>(() =>
    segmentRowsFrom(initial?.growth_schedule),
  );
  const scheduleAllowed = !isSocialSecurity && !usesPensionFormula;
  const [exSpouse, setExSpouse] = useState<ExSpouseDraft>(() => exSpouseDraft(initial?.ex_spouse));

  function selectType(next: IncomeType) {
    if (next === incomeType) return;
    setIncomeType(next);
    if (next === "other") setIsEarnedIncome(false);
    if (initial) return;
    // Swap the untouched defaults that belong to the previous type.
    if (name === TYPE_NAMES[incomeType] || name.trim() === "") setName(TYPE_NAMES[next]);
    if (next !== "salary" && endMilestoneId === retirementMilestoneId) setEndMilestoneId("");
    if (next === "salary" && endMilestoneId === "") setEndMilestoneId(retirementMilestoneId);
    const untouched = amount.value.trim() === "" || Number(amount.value) === 0;
    // Wages earned abroad build no US record, so all-non-US plans skip the estimate.
    if (next === "social_security" && untouched && usCoverage !== "non_us")
      ssEstimate.autoEstimate({ owner, age: claimingAge });
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setValidationError(null);
    const piaMonthly = Number(basisPia);
    const expectedPercent = Number(basisExpected);
    if (isPiaBasis) {
      if (basisPia.trim() === "" || !Number.isFinite(piaMonthly) || piaMonthly <= 0) {
        setValidationError("Enter a positive monthly PIA.");
        return;
      }
      if (claimingAge == null) {
        setValidationError("Choose a claiming age for a PIA-based benefit.");
        return;
      }
      if (
        basisExpected.trim() === "" ||
        !Number.isFinite(expectedPercent) ||
        expectedPercent < 0 ||
        expectedPercent > 100
      ) {
        setValidationError("Expected benefit must be a percentage between 0 and 100.");
        return;
      }
    } else if (!usesPensionFormula && hourlyPay) {
      const rate = Number(hourlyRate);
      const hours = Number(hoursPerWeek);
      if (
        hourlyRate.trim() === "" ||
        !Number.isFinite(rate) ||
        rate <= 0 ||
        hoursPerWeek.trim() === "" ||
        !Number.isFinite(hours) ||
        hours <= 0 ||
        hours > 168
      ) {
        setValidationError("Enter an hourly rate above zero and between 0 and 168 hours a week.");
        return;
      }
    } else if (
      !usesPensionFormula &&
      (amount.value.trim() === "" || !Number.isFinite(annualAmount))
    ) {
      setValidationError("Enter a finite income amount.");
      return;
    } else if (!usesPensionFormula && annualAmount < 0) {
      // As for expenses: a loss or a cost is an expense, not a negative income.
      setValidationError("Enter 0 or more.");
      return;
    } else if (
      annualAmount === 0 &&
      !usesPensionFormula &&
      !isSocialSecurity &&
      !schedulesDollars(segmentRows) &&
      initial?.annual_amount !== 0
    ) {
      // A $0 income pays nothing. Social Security and formula pensions are
      // computed, a dollar schedule can start from 0, and an income already
      // saved at 0 stays editable.
      setValidationError("Enter an amount.");
      return;
    }
    const growth = growthRate.trim() === "" ? null : Number(growthRate);
    if (growth !== null && (!Number.isFinite(growth) || growth < -100 || growth > 100)) {
      setValidationError("Growth rate must be a percent between -100 and 100.");
      return;
    }
    const cap = growthCap.trim() === "" ? null : Number(growthCap);
    if (cap !== null && (!Number.isFinite(cap) || cap < 0)) {
      setValidationError("Growth cap must be zero or a positive annual dollar amount.");
      return;
    }
    const withholding = withholdingPercent.trim() === "" ? null : Number(withholdingPercent);
    if (
      withholding !== null &&
      (!Number.isFinite(withholding) || withholding < 0 || withholding > 100)
    ) {
      setValidationError("Withholding must be a percent between 0 and 100.");
      return;
    }
    const scheduled = scheduleAllowed
      ? scheduleFromRows(segmentRows)
      : { schedule: null, error: null };
    if (scheduled.error) {
      setValidationError(scheduled.error);
      return;
    }
    const former = isPiaBasis ? exSpouseFromDraft(exSpouse) : { record: null, error: null };
    if (former.error) {
      setValidationError(former.error);
      return;
    }
    if (
      startMonth != null &&
      endMonth != null &&
      startMonth > endMonth &&
      !startMilestoneId &&
      !endMilestoneId
    ) {
      setValidationError("Start month must not be after end month within the same year.");
      return;
    }
    if (windowError) {
      return;
    }
    if (
      !isSocialSecurity &&
      !earned &&
      !unearnedCategory &&
      (!initial || initial.is_earned_income || initial.is_social_security)
    ) {
      setValidationError("Choose the income tax treatment for this unearned income.");
      return;
    }
    const data: IncomeCreate = {
      name,
      frequency: paymentFrequency,
      recurrence_years: repeatYears ? Number(repeatYears) : null,
      pension_formula:
        !isSocialSecurity && !earned && unearnedCategory === "qualified_pension" && pension.kind
          ? {
              kind: pension.kind,
              linked_income_id: pension.linkedSalary || null,
              benefit_percent_per_year: Number(pension.benefitPercent),
              years_of_service_before_plan: Number(pension.priorService),
              final_average_years: Number(pension.averageYears),
              flat_annual_amount: Number(pension.flatAmount),
              cola_percent: pension.cola === "" ? null : Number(pension.cola),
            }
          : null,
      owner,
      annual_amount: usesPensionFormula ? (initial?.annual_amount ?? 0) : annualAmount,
      amount_frequency: hourlyPay && !usesPensionFormula ? "hourly" : frequency,
      ...(hourlyPay && !usesPensionFormula
        ? { hourly_rate: Number(hourlyRate), hours_per_week: Number(hoursPerWeek) }
        : initial?.amount_frequency === "hourly"
          ? { hourly_rate: null, hours_per_week: null }
          : {}),
      growth_rate: growth,
      growth_cap: cap,
      growth_cap_inflation_linked: cap !== null && growthCapInflationLinked,
      withholding_percent: withholding,
      start_milestone_id: startMilestoneId || null,
      end_milestone_id: endMilestoneId || null,
      start_month: startMonth,
      end_month: endMonth,
      is_social_security: isSocialSecurity,
      is_earned_income: earned,
      is_self_employed: earned && isSelfEmployed,
      tax_category: isSocialSecurity
        ? "social_security"
        : earned
          ? isSelfEmployed
            ? "self_employment"
            : "employment"
          : unearnedCategory || null,
      claiming_age: isSocialSecurity ? claimingAge : null,
      is_active: isActive,
      growth_schedule: scheduled.schedule,
      ex_spouse: former.record,
    };
    if (isPiaBasis) {
      // The saved amount is the first-year preview; the engine recomputes it.
      data.annual_amount = preview ?? (Number.isFinite(annualAmount) ? annualAmount : 0);
      data.amount_frequency = "annual";
      data.ss_benefit_basis = "pia";
      data.pia_reflects = piaReflects;
      data.covered_years_to_date = coveredYears;
      data.pia_monthly = piaMonthly;
      data.expected_benefit_percent = expectedPercent;
    } else if (initial?.ss_benefit_basis === "pia") {
      data.ss_benefit_basis = isSocialSecurity ? "amount" : null;
      data.pia_monthly = null;
      data.expected_benefit_percent = null;
    }
    if (
      initial &&
      initial.tax_category == null &&
      !isPiaBasis &&
      data.is_social_security === initial.is_social_security &&
      data.is_earned_income === initial.is_earned_income &&
      data.is_self_employed === initial.is_self_employed &&
      (isSocialSecurity || earned || !unearnedCategory)
    )
      delete data.tax_category;
    // A record saved before units were stored stays unset until a unit is chosen.
    if (initial && initial.amount_frequency == null && data.amount_frequency === LEGACY_FREQUENCY)
      delete data.amount_frequency;
    onSubmit(data);
  }

  return (
    <form onSubmit={handleSubmit} style={formStyle}>
      <label>
        Repeats
        <select
          value={paymentFrequency === "once" ? "once" : intervalRepeat ? "interval" : "recurring"}
          onChange={(e) => {
            const choice = e.target.value as "recurring" | "interval" | "once";
            setPaymentFrequency(choice === "once" ? "once" : "recurring");
            setIntervalRepeat(choice === "interval");
            if (choice === "recurring") setRepeatYears("");
            if (choice === "once") setFrequency("annual");
          }}
        >
          <option value="recurring">Every year</option>
          <option value="interval">Every few years</option>
          <option value="once">Once</option>
        </select>
      </label>
      {paymentFrequency === "once" ? (
        <p>
          Enter the full payment amount using the annual entry unit. It arrives in the start month.
        </p>
      ) : (
        intervalRepeat && (
          <label>
            Repeat every (years)
            <input
              type="number"
              min={1}
              max={100}
              step={1}
              value={repeatYears}
              onChange={(e) => setRepeatYears(e.target.value)}
            />
          </label>
        )
      )}
      {!earned && unearnedCategory === "qualified_pension" && (
        <PensionFormulaFields
          draft={pension}
          onChange={setPension}
          incomes={incomes}
          incomeId={initial?.id}
          owner={owner}
        />
      )}
      <fieldset style={{ gridColumn: "1 / -1", border: "none", padding: 0, margin: 0 }}>
        <legend style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 6 }}>
          Income type
        </legend>
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
          {INCOME_TYPES.map((t) => (
            <label key={t.value} style={choiceLabelStyle}>
              <input
                type="radio"
                name="income-type"
                value={t.value}
                checked={incomeType === t.value}
                onChange={() => selectType(t.value)}
              />
              {t.value === "social_security" && usCoverage !== "us"
                ? "US Social Security"
                : t.label}
            </label>
          ))}
        </div>
        {usCoverage !== "us" && (
          <p style={{ margin: "6px 0 0", fontSize: 12, color: "var(--text-secondary)" }}>
            Other countries&apos; state pensions are Other income.
          </p>
        )}
      </fieldset>

      <label>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>

      {!isPiaBasis && !usesPensionFormula && (
        <IncomeAmountFields
          hourlyPay={hourlyPay}
          onHourlyChange={setHourly}
          hourlyRate={hourlyRate}
          onHourlyRateChange={setHourlyRate}
          hoursPerWeek={hoursPerWeek}
          onHoursPerWeekChange={setHoursPerWeek}
          annualAmount={annualAmount}
          frequency={frequency}
          onFrequencyChange={setFrequency}
          displayedAmount={displayedAmount}
          onAmountInput={(value) => {
            ssEstimate.cancel();
            setAmount({ value, frequency });
          }}
          onAmountChange={setAmount}
          once={paymentFrequency === "once"}
        />
      )}

      {/* Single-person plans have only one recipient; a legacy partner income keeps the select so it can be reassigned. */}
      {(hasPartner || owner === "spouse") && (
        <label>
          Income recipient
          <select
            value={owner}
            onChange={(e) => {
              const next = e.target.value as "self" | "spouse";
              setOwner(next);
              // An untouched default end follows the recipient.
              if (!initial && incomeType === "salary" && endMilestoneId === retirementMilestoneId)
                setEndMilestoneId(retirementMilestoneFor(milestones, next));
              if (isSocialSecurity && ssEstimate.autoEstimated)
                ssEstimate.autoEstimate({ owner: next, age: claimingAge });
            }}
          >
            <option value="self">{PRIMARY_PERSON_LABEL}</option>
            <option value="spouse">
              {PARTNER_LABEL}
              {!hasPartner ? " (partner profile missing)" : ""}
            </option>
          </select>
          {!hasPartner && (
            <span className="allocation-help">
              Add a partner under Partner and estate before assigning new partner income.
            </span>
          )}
        </label>
      )}

      {incomeType === "other" && !earned && (
        <label>
          Income tax treatment
          <select
            value={unearnedCategory}
            onChange={(e) =>
              setUnearnedCategory(e.target.value as NonNullable<Income["tax_category"]>)
            }
          >
            <option value="">Choose income tax treatment</option>
            <option value="investment">Investment income</option>
            <option value="qualified_pension">Qualified pension or retirement distribution</option>
            <option value="nonqualified_annuity">Nonqualified annuity taxable income</option>
            <option value="nontaxable">Nontaxable cash receipt</option>
            <option value="other_ordinary">Other ordinary income excluded from NIIT</option>
          </select>
          {!unearnedCategory && initial && (
            <span style={{ display: "block", fontSize: 12 }}>
              Unclassified legacy income retains its existing investment-tax treatment until you
              choose a category.
            </span>
          )}
          <span style={{ display: "block", fontSize: 12 }}>
            Taxable categories use the taxable portion. Nontaxable receipts enter cash flow only.
            Qualified pensions are exempt from NIIT; investment income and nonqualified annuities
            are not.
          </span>
        </label>
      )}

      {isSocialSecurity && (
        <SocialSecurityBenefitFields
          basis={basis}
          onBasisChange={setBasis}
          piaReflects={piaReflects}
          onPiaReflectsChange={setPiaReflects}
          coveredYears={coveredYears}
          onCoveredYearsChange={setCoveredYears}
          pia={basisPia}
          onPiaChange={setBasisPia}
          expectedPercent={basisExpected}
          onExpectedPercentChange={setBasisExpected}
          preview={preview}
          exSpouse={exSpouse}
          onExSpouseChange={setExSpouse}
          claimingAge={claimingAge}
          onClaimingAgeChange={(next) => {
            setClaimingAge(next);
            if (ssEstimate.autoEstimated) ssEstimate.autoEstimate({ owner, age: next });
          }}
          claimYear={claimYear}
          startMilestoneId={startMilestoneId}
          startMilestone={startMilestone}
          startYear={startYear}
          estimate={ssEstimate}
        />
      )}
      <IncomeTimingFields
        milestones={milestones}
        isSocialSecurity={isSocialSecurity}
        planType={planType}
        claimingAge={claimingAge}
        claimYear={claimYear}
        startMilestoneId={startMilestoneId}
        onStartMilestoneChange={setStartMilestoneId}
        endMilestoneId={endMilestoneId}
        onEndMilestoneChange={setEndMilestoneId}
        startMonth={startMonth}
        onStartMonthChange={setStartMonth}
        endMonth={endMonth}
        onEndMonthChange={setEndMonth}
        startMilestone={startMilestone}
        startYear={startYear}
        windowError={windowError}
        windowWarning={windowWarning}
      />
      <IncomeGrowthTaxFields
        forceOpen={Boolean(validationError)}
        isActive={isActive}
        onActiveChange={setIsActive}
        growthRate={growthRate}
        onGrowthRateChange={setGrowthRate}
        growthCap={growthCap}
        onGrowthCapChange={setGrowthCap}
        growthCapInflationLinked={growthCapInflationLinked}
        onGrowthCapInflationLinkedChange={setGrowthCapInflationLinked}
        segmentRows={segmentRows}
        onSegmentRowsChange={setSegmentRows}
        scheduleAllowed={scheduleAllowed}
        isSocialSecurity={isSocialSecurity}
        isOther={incomeType === "other"}
        isEarnedIncome={isEarnedIncome}
        onEarnedIncomeChange={setIsEarnedIncome}
        earned={earned}
        isSelfEmployed={isSelfEmployed}
        onSelfEmployedChange={setIsSelfEmployed}
        withholdingPercent={withholdingPercent}
        onWithholdingPercentChange={setWithholdingPercent}
      />
      {validationError && (
        <div
          role="alert"
          style={{ gridColumn: "1 / -1", color: "var(--color-danger)", fontSize: 13 }}
        >
          {validationError}
        </div>
      )}

      <FormFooter onCancel={onCancel} submitLabel={initial ? "Save income" : "Add income"} />
    </form>
  );
}
