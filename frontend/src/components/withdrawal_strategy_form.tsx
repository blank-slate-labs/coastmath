import { useState } from "react";
import { useFormDraftStatus } from "@/utils/form_draft_status";
import { useSaveGroupPart } from "./save_group";
import { SAVED_METHODS } from "@/domain/withdrawal_strategy";
import type {
  SavedWithdrawalMethod,
  WithdrawalBound,
  WithdrawalStrategySettings,
} from "@/types/plan";
import { moneyLabel } from "@/utils/format";
import MoneyInput from "@/components/money_input";

interface MilestoneOption {
  id: string;
  name: string;
}

interface WithdrawalStrategyFormProps {
  planId: string;
  initial: WithdrawalStrategySettings | null | undefined;
  milestones?: MilestoneOption[];
  /** Omitted inside a SaveGroup, which saves the form with the others. */
  onSave?: (planId: string, settings: WithdrawalStrategySettings) => void | Promise<void>;
}

const RATE_METHODS = new Set<SavedWithdrawalMethod>([
  "constant_dollar",
  "constant_percentage",
  "guyton_klinger",
  "vanguard_dynamic",
  "kitces_ratchet",
  "clyatt_95",
]);

/** Decimal → percent text without float noise (0.035 → "3.5"). */
function pctText(value: number | undefined, fallback: number): string {
  return String(Math.round((value ?? fallback) * 100 * 10000) / 10000);
}

interface BoundRow {
  on: boolean;
  unit: WithdrawalBound["unit"];
  amount: string;
}

function boundRow(bound: WithdrawalBound | null | undefined): BoundRow {
  if (!bound) return { on: false, unit: "today_dollars", amount: "" };
  return {
    on: true,
    unit: bound.unit,
    amount: bound.unit === "portfolio_percent" ? pctText(bound.amount, 0) : String(bound.amount),
  };
}

const fieldStyle = { display: "block", width: "100%" } as const;

/**
 * Saves a withdrawal strategy on the plan. When enabled, the projection,
 * Monte Carlo and reports spend by the strategy from its start.
 */
export default function WithdrawalStrategyForm({
  planId,
  initial,
  milestones = [],
  onSave,
}: WithdrawalStrategyFormProps) {
  const [enabled, setEnabled] = useState(initial?.enabled ?? false);
  const [method, setMethod] = useState<SavedWithdrawalMethod>(initial?.method ?? "constant_dollar");
  const [rate, setRate] = useState(pctText(initial?.initial_rate, 0.04));
  const [startKind, setStartKind] = useState<"plan" | "milestone" | "age">(
    initial?.start_milestone_id ? "milestone" : initial?.start_age != null ? "age" : "plan",
  );
  const [startMilestoneId, setStartMilestoneId] = useState(
    initial?.start_milestone_id ?? milestones[0]?.id ?? "",
  );
  const [startAge, setStartAge] = useState(String(initial?.start_age ?? 65));
  const [upper, setUpper] = useState(pctText(initial?.upper_guardrail, 1.2));
  const [lower, setLower] = useState(pctText(initial?.lower_guardrail, 0.8));
  const [adjustment, setAdjustment] = useState(pctText(initial?.guardrail_adjustment, 0.1));
  const [freezeYears, setFreezeYears] = useState(String(initial?.guardrail_freeze_years ?? 15));
  const [floor, setFloor] = useState(pctText(initial?.floor, -0.025));
  const [ceiling, setCeiling] = useState(pctText(initial?.ceiling, 0.05));
  const [fixedAmount, setFixedAmount] = useState(
    initial?.fixed_amount ? String(initial.fixed_amount) : "",
  );
  const [fixedInflation, setFixedInflation] = useState(
    initial?.fixed_amount_inflation_adjusted ?? true,
  );
  const [stockReturn, setStockReturn] = useState(pctText(initial?.vpw_stock_return, 0.05));
  const [bondReturn, setBondReturn] = useState(pctText(initial?.vpw_bond_return, 0.019));
  const [threshold, setThreshold] = useState(pctText(initial?.ratchet_threshold, 1.5));
  const [ratchet, setRatchet] = useState(pctText(initial?.ratchet_increase, 0.1));
  const [cooldown, setCooldown] = useState(String(initial?.ratchet_cooldown_years ?? 3));
  const [clyattFloor, setClyattFloor] = useState(pctText(initial?.clyatt_floor, 0.95));
  const [minimum, setMinimum] = useState<BoundRow>(() => boundRow(initial?.minimum));
  const [maximum, setMaximum] = useState<BoundRow>(() => boundRow(initial?.maximum));
  const [incomeHandling, setIncomeHandling] = useState(
    initial?.income_handling ?? "replace_expenses",
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  function num(text: string, label: string, min: number, max: number): number {
    const value = Number(text);
    if (text.trim() === "" || !Number.isFinite(value) || value < min || value > max) {
      throw new Error(`${label} must be between ${min} and ${max}.`);
    }
    return value;
  }

  function bound(row: BoundRow, label: string): WithdrawalBound | null {
    if (!row.on) return null;
    return row.unit === "portfolio_percent"
      ? { unit: row.unit, amount: num(row.amount, `${label} (% of portfolio)`, 0, 100) / 100 }
      : {
          unit: row.unit,
          amount: num(row.amount, moneyLabel(`${label} (today's dollars)`), 0, 1e9),
        };
  }

  function build(): WithdrawalStrategySettings {
    const settings: WithdrawalStrategySettings = {
      ...(initial ?? {}),
      enabled,
      method,
      initial_rate: num(rate, "Initial rate (%)", 0.01, 20) / 100,
      start_milestone_id: startKind === "milestone" ? startMilestoneId || null : null,
      start_age: startKind === "age" ? num(startAge, "Start age", 18, 110) : null,
      upper_guardrail: num(upper, "Upper guardrail (%)", 100.01, 300) / 100,
      lower_guardrail: num(lower, "Lower guardrail (%)", 0.01, 99.99) / 100,
      guardrail_adjustment: num(adjustment, "Guardrail adjustment (%)", 0, 50) / 100,
      guardrail_freeze_years: num(freezeYears, "Final years without cuts", 0, 60),
      floor: num(floor, "Floor (%)", -50, 0) / 100,
      ceiling: num(ceiling, "Ceiling (%)", 0, 50) / 100,
      fixed_amount:
        method === "fixed_amount"
          ? num(fixedAmount, "Yearly amount", 1, 1e9)
          : Number(fixedAmount) || 0,
      fixed_amount_inflation_adjusted: fixedInflation,
      vpw_stock_return: num(stockReturn, "Stock real return (%)", -10, 15) / 100,
      vpw_bond_return: num(bondReturn, "Bond real return (%)", -10, 15) / 100,
      ratchet_threshold: num(threshold, "Ratchet threshold (%)", 100.01, 500) / 100,
      ratchet_increase: num(ratchet, "Ratchet increase (%)", 0, 100) / 100,
      ratchet_cooldown_years: num(cooldown, "Years between raises", 0, 30),
      clyatt_floor: num(clyattFloor, "Share of last year's withdrawal (%)", 0, 100) / 100,
      minimum: bound(minimum, "Minimum"),
      maximum: bound(maximum, "Maximum"),
      income_handling: incomeHandling,
    };
    if (startKind === "milestone" && !settings.start_milestone_id)
      throw new Error("Choose a start milestone.");
    const { minimum: lo, maximum: hi } = settings;
    if (lo && hi && lo.unit === hi.unit && lo.amount > hi.amount)
      throw new Error("The minimum must not exceed the maximum.");
    return settings;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    let settings: WithdrawalStrategySettings;
    try {
      settings = build();
    } catch (err) {
      setError((err as Error).message);
      return;
    }
    setSaving(true);
    try {
      await onSave?.(planId, settings);
      markSaved();
      setSaved(true);
    } catch {
      setError("Could not save the withdrawal strategy. Your edits are retained; try again.");
    } finally {
      setSaving(false);
    }
  }

  const { dirty, markSaved } = useFormDraftStatus(
    JSON.stringify([
      enabled,
      method,
      rate,
      startKind,
      startMilestoneId,
      startAge,
      upper,
      lower,
      adjustment,
      freezeYears,
      floor,
      ceiling,
      fixedAmount,
      fixedInflation,
      stockReturn,
      bondReturn,
      threshold,
      ratchet,
      cooldown,
      clyattFloor,
      minimum,
      maximum,
      incomeHandling,
    ]),
  );
  const embedded = useSaveGroupPart("withdrawal_strategy", {
    build: () => ({ withdrawal_strategy: build() }),
    dirty,
    markSaved,
  });
  const Wrapper = embedded ? "div" : "form";

  const methodHelp = SAVED_METHODS.find((m) => m.value === method)?.help;
  const boundEditor = (label: string, row: BoundRow, set: (row: BoundRow) => void) => (
    <div
      style={{ display: "grid", gridTemplateColumns: "auto 1fr 1fr", gap: 8, alignItems: "end" }}
    >
      <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <input
          type="checkbox"
          checked={row.on}
          onChange={(e) => set({ ...row, on: e.target.checked })}
        />
        {label}
      </label>
      <label>
        Unit
        <select
          aria-label={`${label} unit`}
          disabled={!row.on}
          value={row.unit}
          onChange={(e) => set({ ...row, unit: e.target.value as WithdrawalBound["unit"] })}
          style={fieldStyle}
        >
          <option value="today_dollars">{moneyLabel("Today's dollars")}</option>
          <option value="portfolio_percent">% of portfolio</option>
        </select>
      </label>
      <label>
        Amount
        {row.unit === "today_dollars" ? (
          <MoneyInput
            aria-label={`${label} amount`}
            step="any"
            disabled={!row.on}
            value={row.amount}
            onValueChange={(value) => set({ ...row, amount: value })}
            style={fieldStyle}
          />
        ) : (
          <input
            aria-label={`${label} amount`}
            type="number"
            step="any"
            disabled={!row.on}
            value={row.amount}
            onChange={(e) => set({ ...row, amount: e.target.value })}
            style={fieldStyle}
          />
        )}
      </label>
    </div>
  );
  const numberField = (label: string, value: string, set: (v: string) => void, step = "any") => (
    <label>
      {moneyLabel(label)}
      <input
        aria-label={moneyLabel(label)}
        type="number"
        step={step}
        value={value}
        onChange={(e) => set(e.target.value)}
        style={fieldStyle}
      />
    </label>
  );
  const amountField = (label: string, value: string, set: (v: string) => void) => (
    <label>
      {moneyLabel(label)}
      <MoneyInput
        aria-label={moneyLabel(label)}
        step="any"
        value={value}
        onValueChange={set}
        style={fieldStyle}
      />
    </label>
  );

  return (
    <Wrapper
      onSubmit={embedded ? undefined : handleSubmit}
      data-unsaved-changes={(!embedded && dirty) || undefined}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: 12,
        border: "1px solid var(--surface-border)",
        borderRadius: 4,
      }}
    >
      <fieldset disabled={saving} style={{ border: 0, padding: 0, display: "grid", gap: 10 }}>
        <h3 style={{ margin: 0 }}>Withdrawal strategy</h3>
        <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
          From its start, the strategy sets your yearly spending in the projection and Monte Carlo
          instead of your ordinary expenses.
        </p>
        <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Set spending with a withdrawal strategy
        </label>

        {enabled && (
          <>
            <label>
              Method
              <select
                aria-label="Method"
                value={method}
                onChange={(e) => setMethod(e.target.value as SavedWithdrawalMethod)}
                style={fieldStyle}
              >
                {SAVED_METHODS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
              {methodHelp && (
                <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                  {moneyLabel(methodHelp)}
                </span>
              )}
            </label>

            {RATE_METHODS.has(method) && numberField("Initial rate (%)", rate, setRate)}
            {method === "guyton_klinger" && (
              <>
                {numberField("Upper guardrail (% of initial rate)", upper, setUpper)}
                {numberField("Lower guardrail (% of initial rate)", lower, setLower)}
                {numberField("Guardrail adjustment (%)", adjustment, setAdjustment)}
                {numberField("Final years without cuts", freezeYears, setFreezeYears, "1")}
              </>
            )}
            {method === "vanguard_dynamic" && (
              <>
                {numberField("Floor (% change)", floor, setFloor)}
                {numberField("Ceiling (% change)", ceiling, setCeiling)}
              </>
            )}
            {method === "fixed_amount" && (
              <>
                {amountField("Yearly amount (today's dollars)", fixedAmount, setFixedAmount)}
                <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="checkbox"
                    checked={fixedInflation}
                    onChange={(e) => setFixedInflation(e.target.checked)}
                  />
                  Raise with inflation each year
                </label>
              </>
            )}
            {method === "vpw" && (
              <>
                {numberField("Stock real return (%)", stockReturn, setStockReturn)}
                {numberField("Bond real return (%)", bondReturn, setBondReturn)}
                <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                  Your stock/bond mix comes from the plan's bond allocation assumption.
                </span>
              </>
            )}
            {method === "kitces_ratchet" && (
              <>
                {numberField(
                  "Ratchet threshold (% of starting portfolio)",
                  threshold,
                  setThreshold,
                )}
                {numberField("Ratchet increase (%)", ratchet, setRatchet)}
                {numberField("Years between raises", cooldown, setCooldown, "1")}
              </>
            )}
            {method === "clyatt_95" &&
              numberField("Share of last year's withdrawal (%)", clyattFloor, setClyattFloor)}

            <label>
              Start
              <select
                aria-label="Start"
                value={startKind}
                onChange={(e) => setStartKind(e.target.value as typeof startKind)}
                style={fieldStyle}
              >
                <option value="plan">From the plan's start</option>
                <option value="milestone" disabled={milestones.length === 0}>
                  At a milestone
                </option>
                <option value="age">At an age</option>
              </select>
            </label>
            {startKind === "milestone" && (
              <label>
                Start milestone
                <select
                  aria-label="Start milestone"
                  value={startMilestoneId}
                  onChange={(e) => setStartMilestoneId(e.target.value)}
                  style={fieldStyle}
                >
                  {milestones.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {startKind === "age" && numberField("Start age", startAge, setStartAge, "1")}

            {boundEditor("Minimum", minimum, setMinimum)}
            {boundEditor("Maximum", maximum, setMaximum)}

            <label>
              Other income
              <select
                aria-label="Other income"
                value={incomeHandling}
                onChange={(e) => setIncomeHandling(e.target.value as typeof incomeHandling)}
                style={fieldStyle}
              >
                <option value="replace_expenses">
                  Income covers the strategy amount first; surplus is saved
                </option>
                <option value="withdrawal_plus_income">
                  Spend the withdrawal plus all net income
                </option>
              </select>
            </label>
          </>
        )}

        {error && (
          <div role="alert" style={{ color: "var(--color-danger)", fontSize: 13 }}>
            {error}
          </div>
        )}
        {!embedded && (
          <button type="submit">{saving ? "Saving…" : "Save withdrawal strategy"}</button>
        )}
      </fieldset>
      {!embedded && saved && <p role="status">Withdrawal strategy saved.</p>}
    </Wrapper>
  );
}
