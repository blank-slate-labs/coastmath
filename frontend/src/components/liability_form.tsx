import { fullCurrency, moneyLabel } from "@/utils/format";
import { useState, useMemo } from "react";
import type {
  InterestMethod,
  Liability,
  LiabilityCreate,
  PaymentType,
  Milestone,
  Account,
  RealAsset,
} from "@/types/plan";
import AmortizationTable from "./amortization_table";
import MoneyInput from "./money_input";
import LiabilityForgivenessFields, {
  forgivenessDraft,
  forgivenessPayload,
  forgivenessProblem,
} from "./liability_forgiveness_fields";

interface LiabilityFormProps {
  initial?: Liability;
  connectedBalance?: number;
  planId?: string;
  inflationRate?: number;
  milestones: Milestone[];
  accounts: Account[];
  realAssets: RealAsset[];
  onSubmit: (data: LiabilityCreate) => void;
  onCancel: () => void;
}

/** Monthly rate for an average month: daily compounding over 365/12 days, otherwise the annual rate / 12. */
function monthlyRate(annualRatePercent: number, method: InterestMethod): number {
  const rate = annualRatePercent / 100;
  return method === "daily" ? Math.pow(1 + rate / 365, 365 / 12) - 1 : rate / 12;
}

export function calculateMonthlyPayment(
  principal: number,
  annualRate: number,
  termMonths: number,
  method: InterestMethod = "monthly",
): number | null {
  if (principal <= 0 || termMonths <= 0) return null;
  const r = monthlyRate(annualRate, method);
  if (r === 0) return principal / termMonths;
  const factor = Math.pow(1 + r, termMonths);
  return (principal * r * factor) / (factor - 1);
}

export default function LiabilityForm({
  initial,
  connectedBalance,
  planId,
  inflationRate = 0.03,
  milestones,
  accounts,
  realAssets,
  onSubmit,
  onCancel,
}: LiabilityFormProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [principalBalance, setPrincipalBalance] = useState(
    (connectedBalance ?? initial?.principal_balance)?.toString() ?? "",
  );
  const [interestRate, setInterestRate] = useState(initial?.interest_rate?.toString() ?? "");
  const [paymentType, setPaymentType] = useState<PaymentType>(initial?.payment_type ?? "fixed");
  const [termMonths, setTermMonths] = useState(initial?.term_months?.toString() ?? "");
  const [monthlyPayment, setMonthlyPayment] = useState(initial?.monthly_payment?.toString() ?? "");
  const [extraPayment, setExtraPayment] = useState(initial?.extra_payment?.toString() ?? "0");
  const [offsetAccountId, setOffsetAccountId] = useState(initial?.offset_account_id ?? "");
  const [linkedAssetId, setLinkedAssetId] = useState(initial?.linked_asset_id ?? "");
  const [payoffMilestoneId, setPayoffMilestoneId] = useState(initial?.payoff_milestone_id ?? "");
  const [interestMethod, setInterestMethod] = useState<InterestMethod>(
    initial?.interest_method ?? "monthly",
  );
  const [repeatYears, setRepeatYears] = useState(initial?.recurrence_years?.toString() ?? "");
  const [repeatEndYear, setRepeatEndYear] = useState(
    initial?.recurrence_end_year?.toString() ?? "",
  );
  const [repeatEndMilestoneId, setRepeatEndMilestoneId] = useState(
    initial?.recurrence_end_milestone_id ?? "",
  );
  const [repeatError, setRepeatError] = useState("");
  const [showAmortization, setShowAmortization] = useState(false);
  const [forgiveness, setForgiveness] = useState(() => forgivenessDraft(initial?.forgiveness));

  const calculatedPayment = useMemo(() => {
    if (paymentType !== "fixed") return null;
    if (!principalBalance || !interestRate || !termMonths) return null;
    return calculateMonthlyPayment(
      Number(principalBalance),
      Number(interestRate),
      Number(termMonths),
      interestMethod,
    );
  }, [paymentType, principalBalance, interestRate, termMonths, interestMethod]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (forgivenessProblem(forgiveness)) return;
    const every = repeatYears.trim() === "" ? null : Number(repeatYears);
    const endYear = every === null || repeatEndYear.trim() === "" ? null : Number(repeatEndYear);
    if (every !== null && (!Number.isInteger(every) || every < 1 || every > 100)) {
      setRepeatError("Repeat every 1 to 100 years, or leave it blank for a one-time loan.");
      return;
    }
    if (endYear !== null && (!Number.isInteger(endYear) || endYear < 1900 || endYear > 2200)) {
      setRepeatError("Enter a calendar year for the last repeat.");
      return;
    }
    setRepeatError("");
    const data: LiabilityCreate = {
      name,
      principal_balance: Number(principalBalance),
      interest_rate: Number(interestRate),
      payment_type: paymentType,
      term_months: null,
      monthly_payment: null,
      extra_payment: Number(extraPayment) || 0,
      offset_account_id: offsetAccountId || null,
      linked_asset_id: linkedAssetId || null,
      payoff_milestone_id: payoffMilestoneId || null,
    };

    if (paymentType === "fixed") {
      data.term_months = termMonths ? Number(termMonths) : null;
      // Use user-entered payment, or fall back to calculated
      if (monthlyPayment) {
        data.monthly_payment = Number(monthlyPayment);
      } else if (calculatedPayment !== null) {
        data.monthly_payment = Math.round(calculatedPayment * 100) / 100;
      }
    } else if (paymentType === "custom") {
      data.monthly_payment = monthlyPayment ? Number(monthlyPayment) : null;
    } else if (paymentType === "percent_of_balance") {
      data.monthly_payment = monthlyPayment ? Number(monthlyPayment) : null;
    }

    // Sent when set, or as null to clear a saved event; older payloads stay unchanged.
    const forgivenessData = forgivenessPayload(forgiveness);
    if (forgivenessData || initial?.forgiveness) data.forgiveness = forgivenessData;
    // Defaults (monthly, no repeat) stay out of the payload unless they clear a saved value.
    if (interestMethod !== "monthly" || initial?.interest_method)
      data.interest_method = interestMethod;
    if (every !== null || initial?.recurrence_years != null) {
      data.recurrence_years = every;
      data.recurrence_end_year = endYear;
      data.recurrence_end_milestone_id = every === null ? null : repeatEndMilestoneId || null;
    }

    onSubmit(data);
  }

  const hasMoreOptions = Boolean(
    initial &&
    ((initial.interest_method && initial.interest_method !== "monthly") ||
      initial.offset_account_id ||
      initial.linked_asset_id ||
      initial.forgiveness ||
      initial.recurrence_years != null),
  );
  // A payment below the month's interest never pays the loan down; say so before it is saved.
  const monthlyInterest =
    Number(principalBalance) * monthlyRate(Number(interestRate) || 0, interestMethod);
  const plannedPayment =
    paymentType === "percent_of_balance"
      ? Number(monthlyPayment) * Number(principalBalance)
      : monthlyPayment.trim() === ""
        ? (calculatedPayment ?? 0)
        : Number(monthlyPayment);
  const paymentShort =
    monthlyInterest > 0 &&
    Number.isFinite(plannedPayment) &&
    plannedPayment + (Number(extraPayment) || 0) / 12 < monthlyInterest;

  const showTermMonths = paymentType === "fixed";
  const showMonthlyPayment = paymentType === "fixed" || paymentType === "custom";

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: 12,
        border: "1px solid var(--surface-border)",
        borderRadius: 4,
      }}
    >
      <label>
        Name
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          style={{ display: "block", width: "100%" }}
        />
      </label>

      <label>
        {moneyLabel("Principal balance ($)")}
        <MoneyInput
          readOnly={connectedBalance !== undefined}
          value={principalBalance}
          onValueChange={setPrincipalBalance}
          min="0.01"
          step="0.01"
          required
          style={{ display: "block", width: "100%" }}
        />
      </label>

      <label>
        Interest rate (% per year)
        <input
          type="number"
          value={interestRate}
          onChange={(e) => setInterestRate(e.target.value)}
          min="0"
          max="100"
          step="0.001"
          required
          style={{ display: "block", width: "100%" }}
        />
      </label>

      <label>
        Payment type
        <select
          value={paymentType}
          onChange={(e) => setPaymentType(e.target.value as PaymentType)}
          style={{ display: "block", width: "100%" }}
        >
          <option value="fixed">Fixed</option>
          <option value="percent_of_balance">Percent of balance</option>
          <option value="custom">Custom</option>
        </select>
      </label>

      {showTermMonths && (
        <label>
          Remaining term (months)
          <input
            aria-label="Remaining term (months)"
            type="number"
            value={termMonths}
            onChange={(e) => setTermMonths(e.target.value)}
            min="1"
            step="1"
            style={{ display: "block", width: "100%" }}
          />
          <span style={{ display: "block", fontSize: 12 }}>
            Months remaining from the plan start, based on the balance entered above.
          </span>
        </label>
      )}

      {showMonthlyPayment && (
        <label>
          {moneyLabel("Monthly payment ($)")}
          <MoneyInput
            value={monthlyPayment}
            onValueChange={setMonthlyPayment}
            min="0.01"
            step="0.01"
            placeholder={calculatedPayment !== null ? `Auto: $${calculatedPayment.toFixed(2)}` : ""}
            style={{ display: "block", width: "100%" }}
          />
          {calculatedPayment !== null && !monthlyPayment && (
            <span style={{ fontSize: 12, color: "#666" }}>
              Calculated: ${calculatedPayment.toFixed(2)}/mo
            </span>
          )}
        </label>
      )}

      {paymentType === "percent_of_balance" && (
        <label>
          Monthly payment (fraction of balance; 0.02 = 2%)
          <input
            type="number"
            value={monthlyPayment}
            onChange={(e) => setMonthlyPayment(e.target.value)}
            min="0"
            max="1"
            step="0.01"
            style={{ display: "block", width: "100%" }}
          />
        </label>
      )}

      <label>
        {moneyLabel("Extra payment ($/year, spread monthly)")}
        <MoneyInput
          value={extraPayment}
          onValueChange={setExtraPayment}
          min="0"
          step="0.01"
          style={{ display: "block", width: "100%" }}
        />
      </label>
      {paymentShort && (
        <p
          role="status"
          className="field-warning"
          style={{ margin: 0, fontSize: 12, color: "var(--color-warning, #b45309)" }}
        >
          Payments are below the {fullCurrency(monthlyInterest)} monthly interest, so the balance
          grows.
        </p>
      )}

      <label>
        Payoff milestone
        <select
          value={payoffMilestoneId}
          onChange={(e) => setPayoffMilestoneId(e.target.value)}
          style={{ display: "block", width: "100%" }}
        >
          <option value="">— None —</option>
          {milestones.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </label>

      {/* Less common terms stay folded; a saved choice among them opens the group. */}
      <details className="form-advanced" open={hasMoreOptions || undefined}>
        <summary>More options</summary>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
          <label>
            Interest method
            <select
              aria-label="Interest method"
              value={interestMethod}
              onChange={(e) => setInterestMethod(e.target.value as InterestMethod)}
              style={{ display: "block", width: "100%" }}
            >
              <option value="monthly">Monthly amortization (most mortgages)</option>
              <option value="simple">Simple interest on principal</option>
              <option value="daily">Daily accrual (actual/365)</option>
            </select>
            <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
              {interestMethod === "simple"
                ? "Interest is charged on the principal only; unpaid interest is owed but never earns interest."
                : interestMethod === "daily"
                  ? "Interest compounds every day at the annual rate / 365 over each month's actual days."
                  : "Interest is charged each month at the annual rate / 12; unpaid interest is added to the balance."}
            </span>
          </label>

          <label>
            Offset account
            <select
              value={offsetAccountId}
              onChange={(e) => setOffsetAccountId(e.target.value)}
              style={{ display: "block", width: "100%" }}
            >
              <option value="">— None —</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>

          <label>
            Linked real asset
            <select
              value={linkedAssetId}
              onChange={(e) => setLinkedAssetId(e.target.value)}
              style={{ display: "block", width: "100%" }}
            >
              <option value="">— None —</option>
              {realAssets.map((ra) => (
                <option key={ra.id} value={ra.id}>
                  {ra.name}
                </option>
              ))}
            </select>
          </label>

          <LiabilityForgivenessFields
            value={forgiveness}
            onChange={setForgiveness}
            milestones={milestones}
          />

          <fieldset
            style={{ border: "1px solid var(--surface-border)", borderRadius: 4, padding: 8 }}
          >
            <legend>Repeat this loan</legend>
            <label>
              Take it again every (years)
              <input
                aria-label="Repeat every (years)"
                type="number"
                value={repeatYears}
                onChange={(e) => setRepeatYears(e.target.value)}
                min="1"
                max="100"
                step="1"
                placeholder="Never"
                style={{ display: "block", width: "100%" }}
              />
              <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
                For example a car loan every 7 years. Each repeat starts in January with this
                balance, payment and extra payment in today's dollars, grown with inflation, as a
                separate loan.
              </span>
            </label>
            {repeatYears.trim() !== "" && (
              <>
                <label>
                  Last repeat year (optional)
                  <input
                    aria-label="Last repeat year"
                    type="number"
                    value={repeatEndYear}
                    onChange={(e) => setRepeatEndYear(e.target.value)}
                    min="1900"
                    max="2200"
                    step="1"
                    style={{ display: "block", width: "100%" }}
                  />
                </label>
                <label>
                  Stop repeating at milestone (optional)
                  <select
                    aria-label="Stop repeating at milestone"
                    value={repeatEndMilestoneId}
                    onChange={(e) => setRepeatEndMilestoneId(e.target.value)}
                    style={{ display: "block", width: "100%" }}
                  >
                    <option value="">— None —</option>
                    {milestones.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            {repeatError && (
              <p role="alert" style={{ color: "var(--danger, #b00020)" }}>
                {repeatError}
              </p>
            )}
          </fieldset>
        </div>
      </details>

      <div style={{ display: "flex", gap: 8 }}>
        <button type="submit">{initial ? "Update" : "Save"} loan or debt</button>
        <button type="button" onClick={onCancel} data-sample-view>
          Cancel
        </button>
      </div>

      {initial?.id && planId && (
        <>
          <button
            type="button"
            onClick={() => setShowAmortization((s) => !s)}
            data-sample-view
            style={{ marginTop: 8 }}
          >
            {showAmortization ? "Hide" : "Show"} amortization schedule
          </button>
          <p style={{ fontSize: 12 }}>
            Uses saved values; excludes offset accounts, asset sales and payoff milestones.
            Inflation-adjusted at a constant {inflationRate * 100}%.
          </p>
          {showAmortization && (
            <AmortizationTable
              planId={planId}
              liabilityId={initial.id}
              inflationRate={inflationRate}
              extraPayment={initial.extra_payment}
              principalBalance={initial.principal_balance}
              interestRate={initial.interest_rate}
              termMonths={initial.term_months}
              monthlyPayment={initial.monthly_payment}
            />
          )}
        </>
      )}
    </form>
  );
}
