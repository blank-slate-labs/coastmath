import { moneyLabel, withCurrency } from "@/utils/format";
import { useState } from "react";
import type {
  Account,
  Expense,
  ExpenseCreate,
  Income,
  Milestone,
  MilestoneOutcome,
  PayrollTaxElections,
  PayrollTaxTreatment,
} from "@/types/plan";
import { MilestoneWindowFields } from "@/components/milestone_window_fields";
import MoneyInput from "@/components/money_input";
import { milestoneWindowError, milestoneWindowWarning } from "@/utils/milestone_window";
import {
  AMOUNT_FREQUENCIES,
  AMOUNT_LABELS,
  FREQUENCY_LABELS,
  PERIOD_SUFFIXES,
  entryAnnual,
  entryDisplay,
  initialEntry,
  maxEntry,
  openingFrequency,
  type AmountEntry,
  type AmountFrequency,
} from "@/utils/amount_frequency";
import {
  categoryForPercent,
  formatPercent,
  openingShareMode,
  parsePercent,
  type ShareMode,
} from "@/utils/discretionary_share";
import { SPENDING_CATEGORIES, spendingCategoryName } from "@/utils/spending_categories";
import { FormFooter } from "./form_footer";
import { formStyle } from "./form_styles";

interface ExpenseFormProps {
  initial?: Expense;
  /** The plan's expense names, so a spending category's name stays unique. */
  existingNames?: string[];
  milestones: Milestone[];
  /** Accounts eligible as a specific funding source (optional). */
  accounts?: Account[];
  incomeStreams?: Income[];
  /** Plan owner's birth year, used to check that the start milestone precedes the end. */
  birthYear?: number | null;
  /** Milestone years from the latest projection, for windows that depend on it. */
  outcomes?: MilestoneOutcome[] | null;
  onSubmit: (data: ExpenseCreate) => void;
  onReview?: (data: ExpenseCreate) => void;
  onCancel: () => void;
}

type GrowthMode = "inflation" | "fixed" | "custom";

/** New expenses open monthly; those saved before units were stored open annual. */
const NEW_FREQUENCY: AmountFrequency = "monthly";
const LEGACY_FREQUENCY: AmountFrequency = "annual";

function initialGrowthMode(initial?: Expense): GrowthMode {
  if (initial?.growth_rate != null) return "custom";
  if (initial && !initial.inflation_linked) return "fixed";
  return "inflation";
}

const checkboxLabel: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  fontSize: "13px",
  color: "var(--text-primary)",
  cursor: "pointer",
};

type PayrollWageBase = keyof PayrollTaxElections;

const PAYROLL_WAGE_BASES: { key: PayrollWageBase; label: string }[] = [
  { key: "federal", label: "Federal income tax" },
  { key: "state", label: "State income tax" },
  { key: "local", label: "Local income tax" },
  { key: "fica", label: "Social Security and Medicare" },
];

function payrollElectionDefaults(treatment: PayrollTaxTreatment): Required<PayrollTaxElections> {
  const preTax = treatment === "pre_tax";
  return { federal: preTax, state: preTax, local: preTax, fica: false };
}

/** The elections that differ from the treatment's defaults, or null when none do. */
function explicitPayrollElections(
  treatment: PayrollTaxTreatment,
  elections: PayrollTaxElections,
): PayrollTaxElections | null {
  const defaults = payrollElectionDefaults(treatment);
  const explicit: PayrollTaxElections = {};
  for (const { key } of PAYROLL_WAGE_BASES) {
    const value = elections[key];
    if (value != null && value !== defaults[key]) explicit[key] = value;
  }
  return Object.keys(explicit).length ? explicit : null;
}

export default function ExpenseForm({
  initial,
  existingNames = [],
  milestones,
  accounts = [],
  incomeStreams = [],
  birthYear = null,
  outcomes = null,
  onSubmit,
  onReview,
  onCancel,
}: ExpenseFormProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [spendingCategory, setSpendingCategory] = useState("");
  // The name a spending category last filled in; a typed name is never replaced.
  const [automaticName, setAutomaticName] = useState("");
  // Reopen in the unit saved with the expense; the amount itself stays annual.
  const [frequency, setFrequency] = useState<AmountFrequency>(
    initial ? openingFrequency(initial.amount_frequency, LEGACY_FREQUENCY) : NEW_FREQUENCY,
  );
  // Keep the entered value and its unit, so switching the displayed unit never
  // rounds or drifts the annual amount unless the value itself is edited.
  const [amount, setAmount] = useState<AmountEntry>(
    initialEntry(initial?.annual_amount, frequency),
  );
  const displayedAmount = entryDisplay(amount, frequency);
  const [growthMode, setGrowthMode] = useState<GrowthMode>(initialGrowthMode(initial));
  const [growthRate, setGrowthRate] = useState(
    initial?.growth_rate != null ? String(initial.growth_rate) : "",
  );
  const [growthCap, setGrowthCap] = useState(
    initial?.growth_cap != null ? String(initial.growth_cap) : "",
  );
  const [growthCapInflationLinked, setGrowthCapInflationLinked] = useState(
    initial?.growth_cap_inflation_linked ?? false,
  );
  const [recurring, setRecurring] = useState(initial?.recurrence_years != null);
  const [recurrenceYears, setRecurrenceYears] = useState(
    initial?.recurrence_years != null ? String(initial.recurrence_years) : "5",
  );
  const [recurrenceGrowth, setRecurrenceGrowth] = useState(
    initial?.recurrence_growth_rate != null ? String(initial.recurrence_growth_rate) : "0",
  );
  const [fundingSourceIds, setFundingSourceIds] = useState<string[]>(
    initial?.specific_funding_source_ids ??
      (initial?.specific_funding_source_id ? [initial.specific_funding_source_id] : []),
  );
  const preserveLegacyFunding =
    initial != null &&
    initial.specific_funding_source_ids == null &&
    JSON.stringify(fundingSourceIds) ===
      JSON.stringify(
        initial.specific_funding_source_id ? [initial.specific_funding_source_id] : [],
      );
  const [validationError, setValidationError] = useState<string | null>(null);
  const [isPayrollDeduction, setIsPayrollDeduction] = useState(
    initial?.is_payroll_deduction ?? false,
  );
  const [qualifiedEducation, setQualifiedEducation] = useState(
    initial?.qualified_education ?? false,
  );
  const [payrollTaxTreatment, setPayrollTaxTreatment] = useState<PayrollTaxTreatment>(
    initial?.payroll_tax_treatment ?? "pre_tax",
  );
  const [payrollElections, setPayrollElections] = useState<PayrollTaxElections>(
    initial?.payroll_tax_elections ?? {},
  );
  const [tiedIncomeId, setTiedIncomeId] = useState(initial?.tied_income_id ?? "");
  const [startMilestoneId, setStartMilestoneId] = useState(initial?.start_milestone_id ?? "");
  const [endMilestoneId, setEndMilestoneId] = useState(initial?.end_milestone_id ?? "");
  // Essential and Discretionary are the all-or-nothing presets (0% and 100%);
  // Custom stores a percent and the server mirrors it into the category.
  const [shareMode, setShareMode] = useState<ShareMode>(
    openingShareMode(initial?.discretionary_percent, initial?.category),
  );
  const [customPercent, setCustomPercent] = useState(
    initial?.discretionary_percent != null && shareMode === "custom"
      ? String(initial.discretionary_percent)
      : "50",
  );
  const parsedCustomPercent = parsePercent(customPercent);
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

  /** A spending category sets the share, and the name unless one was typed. */
  function selectSpendingCategory(id: string) {
    setSpendingCategory(id);
    const category = SPENDING_CATEGORIES.find((c) => c.id === id);
    if (!category) return;
    setShareMode(category.share);
    if (name.trim() === "" || name === automaticName) {
      const next = spendingCategoryName(category.label, existingNames);
      setName(next);
      setAutomaticName(next);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setValidationError(null);
    const growth = growthMode === "custom" ? Number(growthRate) : null;
    if (
      growthMode === "custom" &&
      (growthRate.trim() === "" || !Number.isFinite(growth) || growth! < -100 || growth! > 100)
    ) {
      setValidationError("Custom growth must be a percent between -100 and 100.");
      return;
    }
    const cap = growthMode === "custom" && growthCap.trim() !== "" ? Number(growthCap) : null;
    if (cap !== null && (!Number.isFinite(cap) || cap < 0)) {
      setValidationError("Growth cap must be zero or a positive annual dollar amount.");
      return;
    }
    const every = recurring ? Number(recurrenceYears) : null;
    if (recurring && (!Number.isInteger(every) || every! < 1 || every! > 100)) {
      setValidationError("Repeat interval must be a whole number of years between 1 and 100.");
      return;
    }
    const perOccurrence = recurring ? Number(recurrenceGrowth) : 0;
    if (
      recurring &&
      (recurrenceGrowth.trim() === "" ||
        !Number.isFinite(perOccurrence) ||
        perOccurrence < -100 ||
        perOccurrence > 100)
    ) {
      setValidationError("Growth per occurrence must be a percent between -100 and 100.");
      return;
    }
    if (isPayrollDeduction && fundingSourceIds.length > 0) {
      setValidationError(
        "A payroll deduction comes out of pay and cannot also be funded from a specific account.",
      );
      return;
    }
    if (
      isPayrollDeduction &&
      !incomeStreams.some(
        (income) =>
          income.id === tiedIncomeId && income.is_earned_income && !income.is_social_security,
      )
    ) {
      setValidationError("Choose the employment income this deduction comes from.");
      return;
    }
    if (shareMode === "custom" && parsedCustomPercent === null) {
      setValidationError("Discretionary share must be a percent between 0 and 100.");
      return;
    }
    if (windowError) {
      return;
    }
    const presetPercent = shareMode === "essential" ? 0 : 100;
    // A preset is the category alone; a saved 0% or 100% is left as it is.
    const discretionaryPercent =
      shareMode === "custom"
        ? parsedCustomPercent
        : initial?.discretionary_percent === presetPercent
          ? presetPercent
          : null;
    const category = shareMode === "custom" ? categoryForPercent(parsedCustomPercent!) : shareMode;
    const data: ExpenseCreate = {
      name,
      annual_amount: entryAnnual(amount),
      amount_frequency: frequency,
      inflation_linked: growthMode === "inflation",
      growth_rate: growth,
      growth_cap: cap,
      growth_cap_inflation_linked: cap !== null && growthCapInflationLinked,
      recurrence_years: every,
      recurrence_growth_rate: recurring ? perOccurrence : 0,
      is_payroll_deduction: isPayrollDeduction,
      payroll_tax_treatment: payrollTaxTreatment,
      tied_income_id: isPayrollDeduction ? tiedIncomeId : null,
      specific_funding_source_id: fundingSourceIds[0] || null,
      specific_funding_source_ids: fundingSourceIds.length ? fundingSourceIds : null,
      start_milestone_id: startMilestoneId || null,
      end_milestone_id: endMilestoneId || null,
      category,
      discretionary_percent: discretionaryPercent,
      start_month: startMonth,
      end_month: endMonth,
      qualified_education: qualifiedEducation,
    };
    // An unrelated edit must not opt a legacy expense into restricted funding
    // or add a default field to an older API response's optimistic update.
    if (
      preserveLegacyFunding ||
      (initial && initial.specific_funding_source_ids == null && !fundingSourceIds.length)
    )
      delete data.specific_funding_source_ids;
    if (initial && initial.payroll_tax_treatment == null && payrollTaxTreatment === "pre_tax")
      delete data.payroll_tax_treatment;
    // Only elections that differ from the treatment's defaults are stored.
    const explicitElections = isPayrollDeduction
      ? explicitPayrollElections(payrollTaxTreatment, payrollElections)
      : null;
    // Unchanged elections keep the saved object so the edit diff skips them.
    if (
      JSON.stringify(explicitElections) === JSON.stringify(initial?.payroll_tax_elections ?? null)
    )
      delete data.payroll_tax_elections;
    else data.payroll_tax_elections = explicitElections;
    if (initial && (data.tied_income_id ?? null) === (initial.tied_income_id ?? null))
      delete data.tied_income_id;
    // A record saved before units were stored stays unset until a unit is chosen.
    if (initial && initial.amount_frequency == null && frequency === LEGACY_FREQUENCY)
      delete data.amount_frequency;
    // Category-only expenses stay category-only (and older servers never see the field).
    if (discretionaryPercent === null && initial?.discretionary_percent == null)
      delete data.discretionary_percent;
    // Older servers and unmarked expenses never see the education flag.
    if (!qualifiedEducation && !initial?.qualified_education) delete data.qualified_education;
    const submitter = (e.nativeEvent as SubmitEvent).submitter;
    if (submitter?.getAttribute("data-review") === "true" && onReview) onReview(data);
    else onSubmit(data);
  }

  return (
    <form onSubmit={handleSubmit} style={formStyle}>
      {!initial && (
        <label>
          Spending category
          <select value={spendingCategory} onChange={(e) => selectSpendingCategory(e.target.value)}>
            <option value="">None</option>
            {SPENDING_CATEGORIES.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>

      <label>
        {moneyLabel(AMOUNT_LABELS[frequency])}
        <MoneyInput
          required
          min="0"
          max={maxEntry(frequency)}
          step="any"
          value={displayedAmount}
          onValueChange={(value) => setAmount({ value, frequency })}
        />
      </label>

      <label>
        Amount frequency
        <select value={frequency} onChange={(e) => setFrequency(e.target.value as AmountFrequency)}>
          {AMOUNT_FREQUENCIES.map((unit) => (
            <option key={unit} value={unit}>
              {FREQUENCY_LABELS[unit]}
            </option>
          ))}
        </select>
      </label>
      <p style={{ gridColumn: "1 / -1", margin: 0 }}>
        {Number(displayedAmount) < 0 && "-"}
        {withCurrency(
          Math.abs(Number(displayedAmount)).toLocaleString(undefined, { maximumFractionDigits: 2 }),
        )}
        {PERIOD_SUFFIXES[frequency]} ·{" "}
        {growthMode === "inflation"
          ? "increases with inflation"
          : growthMode === "fixed"
            ? "fixed dollar amount"
            : `${growthRate}% annual growth`}{" "}
        ·{" "}
        {startMilestoneId || endMilestoneId || startMonth || endMonth
          ? "custom timing (see Advanced)"
          : "from plan start through plan end"}
        {recurring ? ` · charged every ${recurrenceYears} years` : ""}.
      </p>
      <fieldset style={{ border: "none", padding: 0, margin: 0, gridColumn: "1 / -1" }}>
        <legend
          style={{ fontWeight: 500, marginBottom: 8, fontSize: 13, color: "var(--text-secondary)" }}
        >
          Essential or discretionary
        </legend>
        <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
          <label style={checkboxLabel}>
            <input
              type="radio"
              name="category"
              value="essential"
              checked={shareMode === "essential"}
              onChange={() => setShareMode("essential")}
            />
            Essential
          </label>
          <label style={checkboxLabel}>
            <input
              type="radio"
              name="category"
              value="discretionary"
              checked={shareMode === "discretionary"}
              onChange={() => setShareMode("discretionary")}
            />
            Discretionary
          </label>
          <label style={checkboxLabel}>
            <input
              type="radio"
              name="category"
              value="custom"
              checked={shareMode === "custom"}
              onChange={() => setShareMode("custom")}
            />
            Custom
          </label>
        </div>
        {shareMode === "custom" && (
          <div
            style={{
              display: "flex",
              gap: 12,
              alignItems: "center",
              flexWrap: "wrap",
              marginTop: 8,
            }}
          >
            <input
              type="range"
              min="0"
              max="100"
              step="1"
              aria-label="Discretionary share slider"
              value={Math.round(parsedCustomPercent ?? 0)}
              onChange={(e) => setCustomPercent(e.target.value)}
              style={{ flex: "1 1 160px", maxWidth: 280 }}
            />
            <label style={checkboxLabel}>
              Discretionary share (%)
              <input
                type="number"
                min="0"
                max="100"
                step="any"
                value={customPercent}
                onChange={(e) => setCustomPercent(e.target.value)}
                style={{ width: 80 }}
              />
            </label>
          </div>
        )}
        <span
          style={{
            display: "block",
            fontSize: 12,
            color: "var(--gray-500, #6b7280)",
            marginTop: 6,
          }}
        >
          {shareMode === "essential"
            ? "Always paid in full; flexible spending never cuts it."
            : shareMode === "discretionary"
              ? "Flexible spending can cut all of it after weak market years."
              : parsedCustomPercent === null
                ? "Enter the share flexible spending may cut, from 0 to 100%."
                : `Flexible spending can cut ${formatPercent(parsedCustomPercent)} of it after weak market years; the other ${formatPercent(100 - parsedCustomPercent)} is always paid.`}
        </span>
      </fieldset>

      <details
        style={{ gridColumn: "1 / -1" }}
        open={
          initial &&
          (initial.growth_rate != null ||
            initial.recurrence_years != null ||
            initial.is_payroll_deduction ||
            initial.qualified_education ||
            !!initial.specific_funding_source_id ||
            !!initial.specific_funding_source_ids?.length ||
            !!initial.start_milestone_id ||
            !!initial.end_milestone_id ||
            !!initial.start_month ||
            !!initial.end_month)
            ? true
            : undefined
        }
      >
        <summary>Advanced: growth, funding and timing</summary>
        <div style={{ ...formStyle, padding: "12px 0" }}>
          <label>
            Amount growth
            <select
              value={growthMode}
              onChange={(e) => setGrowthMode(e.target.value as GrowthMode)}
            >
              <option value="inflation">Rises with plan inflation</option>
              <option value="custom">Custom rate per year</option>
              <option value="fixed">Fixed nominal amount</option>
            </select>
          </label>

          {growthMode === "custom" && (
            <>
              <label>
                Growth rate (% per year)
                <input
                  type="number"
                  step="0.1"
                  min="-100"
                  max="100"
                  value={growthRate}
                  onChange={(e) => setGrowthRate(e.target.value)}
                  placeholder="e.g. 5.0"
                />
              </label>
              <div
                style={{ gridColumn: "1 / -1", color: "var(--gray-500, #6b7280)", fontSize: 12 }}
              >
                {moneyLabel(
                  "Enter the amount in today's dollars. The rate compounds from the plan's start year even if this expense begins later, so a future cost is carried forward to its start date.",
                )}
              </div>
              <label>
                {moneyLabel("Growth cap ($ per year, optional)")}
                <MoneyInput
                  min="0"
                  step="0.01"
                  value={growthCap}
                  onValueChange={setGrowthCap}
                  placeholder="No cap"
                />
              </label>
              {growthCap.trim() !== "" && (
                <label style={{ ...checkboxLabel, gridColumn: "1 / -1" }}>
                  <input
                    type="checkbox"
                    checked={growthCapInflationLinked}
                    onChange={(e) => setGrowthCapInflationLinked(e.target.checked)}
                  />
                  {moneyLabel("Cap rises with inflation (entered in today's dollars)")}
                </label>
              )}
            </>
          )}

          <div
            style={{ display: "flex", flexDirection: "column", gap: 10, justifyContent: "center" }}
          >
            <label style={checkboxLabel}>
              <input
                type="checkbox"
                checked={recurring}
                onChange={(e) => setRecurring(e.target.checked)}
              />
              Repeats every few years (replacement or one-off)
            </label>
            <label style={checkboxLabel}>
              <input
                type="checkbox"
                checked={isPayrollDeduction}
                onChange={(e) => setIsPayrollDeduction(e.target.checked)}
              />
              Payroll Deduction
            </label>
            <label style={checkboxLabel}>
              <input
                type="checkbox"
                checked={qualifiedEducation}
                onChange={(e) => setQualifiedEducation(e.target.checked)}
              />
              Qualified education expense (529 withdrawals up to it are tax free)
            </label>
          </div>

          {isPayrollDeduction && (
            <label>
              Deduct from income
              <select value={tiedIncomeId} onChange={(e) => setTiedIncomeId(e.target.value)}>
                <option value="">Choose employment income</option>
                {incomeStreams
                  .filter((income) => income.is_earned_income && !income.is_social_security)
                  .map((income) => (
                    <option key={income.id} value={income.id}>
                      {income.name}
                    </option>
                  ))}
              </select>
              <span style={{ display: "block", fontSize: 12 }}>
                This deduction applies only while the selected income is active.
              </span>
            </label>
          )}

          {isPayrollDeduction && (
            <fieldset style={{ border: "none", padding: 0, margin: 0 }}>
              <legend
                style={{
                  fontWeight: 500,
                  marginBottom: 8,
                  fontSize: 13,
                  color: "var(--text-secondary)",
                }}
              >
                Payroll tax treatment
              </legend>
              <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
                <label style={checkboxLabel}>
                  <input
                    type="radio"
                    name="payroll-tax-treatment"
                    value="pre_tax"
                    checked={payrollTaxTreatment === "pre_tax"}
                    onChange={() => setPayrollTaxTreatment("pre_tax")}
                  />
                  Pre-tax
                </label>
                <label style={checkboxLabel}>
                  <input
                    type="radio"
                    name="payroll-tax-treatment"
                    value="after_tax"
                    checked={payrollTaxTreatment === "after_tax"}
                    onChange={() => setPayrollTaxTreatment("after_tax")}
                  />
                  After-tax
                </label>
              </div>
              <span style={{ display: "block", fontSize: 12 }}>
                Pre-tax reduces income-taxable wages. After-tax still reduces take-home pay, but
                does not reduce the income-tax base.
              </span>
            </fieldset>
          )}

          {isPayrollDeduction && (
            <fieldset style={{ border: "none", padding: 0, margin: 0 }}>
              <legend
                style={{
                  fontWeight: 500,
                  marginBottom: 8,
                  fontSize: 13,
                  color: "var(--text-secondary)",
                }}
              >
                Reduces taxable wages for
              </legend>
              <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
                {PAYROLL_WAGE_BASES.map(({ key, label }) => (
                  <label key={key} style={checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={
                        payrollElections[key] ?? payrollElectionDefaults(payrollTaxTreatment)[key]
                      }
                      onChange={(e) =>
                        setPayrollElections({ ...payrollElections, [key]: e.target.checked })
                      }
                    />
                    {label}
                  </label>
                ))}
              </div>
              <span style={{ display: "block", fontSize: 12 }}>
                Defaults follow the treatment: pre-tax reduces federal, state and local wages but
                not FICA (a 401(k) deferral). A Section 125 health premium also reduces FICA wages.
              </span>
            </fieldset>
          )}

          {recurring && (
            <>
              <label>
                Repeat every (years)
                <input
                  type="number"
                  min="1"
                  max="100"
                  step="1"
                  value={recurrenceYears}
                  onChange={(e) => setRecurrenceYears(e.target.value)}
                />
                <span style={{ display: "block", fontSize: 12, color: "var(--gray-500, #6b7280)" }}>
                  Charged in the first active year and every interval after it; nothing in between.
                </span>
              </label>
              <label>
                Change per occurrence (%)
                <input
                  type="number"
                  step="0.1"
                  min="-100"
                  max="100"
                  value={recurrenceGrowth}
                  onChange={(e) => setRecurrenceGrowth(e.target.value)}
                />
                <span style={{ display: "block", fontSize: 12, color: "var(--gray-500, #6b7280)" }}>
                  Compounds with the amount growth above.
                </span>
              </label>
            </>
          )}

          {!isPayrollDeduction && (
            <div style={{ gridColumn: "1 / -1" }}>
              <label>
                Fund from a specific account
                <select
                  value=""
                  onChange={(e) => {
                    const id = e.target.value;
                    if (id)
                      setFundingSourceIds((current) =>
                        current.includes(id) ? current : [...current, id],
                      );
                  }}
                >
                  <option value="">
                    {fundingSourceIds.length
                      ? "Add another account"
                      : "General cash flow (default)"}
                  </option>
                  {accounts
                    .filter((a) => !fundingSourceIds.includes(a.id))
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} ({a.account_type.replace(/_/g, " ")})
                      </option>
                    ))}
                </select>
              </label>
              {fundingSourceIds.length > 0 && (
                <ol
                  aria-label="Selected funding accounts"
                  style={{ margin: "8px 0 0", paddingLeft: 24 }}
                >
                  {fundingSourceIds.map((id, index) => {
                    const account = accounts.find((a) => a.id === id);
                    const label = account?.name ?? "Account";
                    return (
                      <li key={id} style={{ marginBottom: 4 }}>
                        <span>
                          {label} ({account?.account_type.replace(/_/g, " ") ?? "unknown"})
                        </span>{" "}
                        <button
                          type="button"
                          aria-label={`Move ${label} up`}
                          disabled={index === 0}
                          onClick={() =>
                            setFundingSourceIds((current) => {
                              const next = [...current];
                              [next[index - 1], next[index]] = [next[index], next[index - 1]];
                              return next;
                            })
                          }
                        >
                          ↑
                        </button>{" "}
                        <button
                          type="button"
                          aria-label={`Move ${label} down`}
                          disabled={index === fundingSourceIds.length - 1}
                          onClick={() =>
                            setFundingSourceIds((current) => {
                              const next = [...current];
                              [next[index], next[index + 1]] = [next[index + 1], next[index]];
                              return next;
                            })
                          }
                        >
                          ↓
                        </button>{" "}
                        <button
                          type="button"
                          aria-label={`Remove ${label}`}
                          onClick={() =>
                            setFundingSourceIds((current) =>
                              current.filter((accountId) => accountId !== id),
                            )
                          }
                        >
                          Remove
                        </button>
                      </li>
                    );
                  })}
                </ol>
              )}
              <span style={{ display: "block", fontSize: 12, color: "var(--gray-500, #6b7280)" }}>
                {preserveLegacyFunding && fundingSourceIds.length
                  ? "Selected accounts first, then general cash flow. Changing the selection restricts funding to selected accounts only."
                  : "Only selected accounts fund this expense, left to right within a type; Drawdown order sets type precedence."}
              </span>
            </div>
          )}

          <MilestoneWindowFields
            milestones={milestones}
            start={{
              label: "Start Milestone",
              placeholder: "From plan start",
              value: startMilestoneId,
              onChange: setStartMilestoneId,
            }}
            end={{
              label: "End Milestone",
              placeholder: "Through plan end",
              value: endMilestoneId,
              onChange: setEndMilestoneId,
            }}
            startMonth={{ label: "Start Month", value: startMonth, onChange: setStartMonth }}
            endMonth={{ label: "End Month", value: endMonth, onChange: setEndMonth }}
            windowError={windowError}
            windowWarning={windowWarning}
          />
        </div>
      </details>

      {validationError && (
        <div
          role="alert"
          style={{ gridColumn: "1 / -1", color: "var(--color-danger)", fontSize: 13 }}
        >
          {validationError}
        </div>
      )}

      <FormFooter onCancel={onCancel} submitLabel={`${initial ? "Update" : "Add"} Expense`}>
        {onReview && (
          <button type="submit" className="btn-secondary" data-review="true">
            Review latest saved values
          </button>
        )}
      </FormFooter>
    </form>
  );
}
