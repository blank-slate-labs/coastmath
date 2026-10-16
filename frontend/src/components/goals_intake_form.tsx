import { useId, useRef, useState, type ReactNode } from "react";

import {
  GOAL_FIELDS,
  accountSlots,
  buildSetupSteps,
  needsSalary,
  partnerBirthYear,
  runSetupSteps,
  validateGoals,
  type GoalField,
  type GoalsDraft,
  type LeftoverTarget,
  type RetirementTiming,
  type SavedSteps,
  type SetupFailure,
} from "@/components/goals_setup";
import { usePlanStore } from "@/stores/plan_store";
import { useSetupFlow } from "@/stores/setup_flow_store";
import { useStorage } from "@/storage/context";
import type { PlanData } from "@/types/plan";
import MoneyInput from "@/components/money_input";
import { moneyLabel } from "@/utils/format";

/** What setup opens next: the Add income form, so the salary comes after the goals. */
export type SetupNext = "income";

const GOAL_LABELS: Record<GoalField, { label: string; age?: boolean }> = {
  retirement_spending: { label: "Retirement spending ($/yr, today's dollars)" },
  travel_budget: { label: "Travel ($/yr, today's dollars)" },
  travel_until_age: { label: "Travel until age", age: true },
  charitable_giving: { label: "Charitable giving ($/yr, nominal)" },
  legacy_target: { label: "Leave to heirs ($, today's dollars)" },
};

const TIMINGS: { value: RetirementTiming; label: string }[] = [
  { value: "age", label: "At an age" },
  { value: "independence", label: "When I can afford to" },
  { value: "stopped", label: "I've already stopped working" },
];

const choiceStyle: React.CSSProperties = { display: "flex", alignItems: "center", gap: 6 };

function initialDraft(plan: PlanData): GoalsDraft {
  const retirement = plan.milestones.find((milestone) => milestone.name === "Retirement");
  const legacy = plan.estate_settings?.legacy_target;
  return {
    timing: retirement?.trigger_type === "expense_multiple" ? "independence" : "age",
    retirementAge:
      retirement?.trigger_type === "age" && retirement.trigger_value != null
        ? String(retirement.trigger_value)
        : "",
    socialSecurityMonthly: "",
    pension: "",
    partnerRetirementAge: "",
    partnerStopped: false,
    partnerSocialSecurityMonthly: "",
    partnerPension: "",
    monthlySpending: "",
    goals: {
      retirement_spending: "",
      travel_budget: "",
      travel_until_age: "",
      charitable_giving: "",
      legacy_target: legacy != null ? String(legacy) : "",
    },
    balances: {},
    leftover: "",
  };
}

function NumberField({
  label,
  value,
  onChange,
  age = false,
  hint,
  invalid = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  age?: boolean;
  hint?: string;
  invalid?: boolean;
}) {
  const hintId = useId();
  return (
    <div className="goals-field">
      <label>
        {moneyLabel(label)}
        {age ? (
          <input
            type="number"
            inputMode="numeric"
            min={18}
            max={120}
            step={1}
            value={value}
            aria-invalid={invalid || undefined}
            aria-describedby={hint ? hintId : undefined}
            onChange={(event) => onChange(event.target.value)}
          />
        ) : (
          <MoneyInput
            min={0}
            step="any"
            value={value}
            aria-invalid={invalid || undefined}
            aria-describedby={hint ? hintId : undefined}
            onValueChange={onChange}
          />
        )}
      </label>
      {hint && (
        <p id={hintId} className="goals-hint">
          {hint}
        </p>
      )}
    </div>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="goals-group">
      <legend>{title}</legend>
      {children}
    </fieldset>
  );
}

/**
 * The goals asked right after a plan is created. Every answer is optional;
 * each one becomes an ordinary plan item through the existing routes. A failed
 * write keeps every answer, lists what was not saved and resends only that.
 */
export function GoalsIntakeForm({
  plan,
  onDone,
}: {
  plan: PlanData;
  onDone: (next?: SetupNext) => void;
}) {
  const { adapter } = useStorage();
  const requestAddIncome = useSetupFlow((s) => s.requestAddIncome);
  const [draft, setDraft] = useState<GoalsDraft>(() => initialDraft(plan));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [failures, setFailures] = useState<SetupFailure[]>([]);
  const [conflict, setConflict] = useState(false);
  // What earlier attempts saved, so a retry never creates an item twice.
  const saved = useRef<SavedSteps>(new Map());

  const spouseBirth = partnerBirthYear(plan);
  const hasPartner = plan.spouse != null;
  const slots = accountSlots(hasPartner);
  const failedKeys = new Set(failures.map((failure) => failure.key));
  const set = <K extends keyof GoalsDraft>(key: K, value: GoalsDraft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const setGoal = (field: GoalField, value: string) =>
    setDraft((current) => ({ ...current, goals: { ...current.goals, [field]: value } }));
  const setBalance = (key: string, value: string) =>
    setDraft((current) => ({ ...current, balances: { ...current.balances, [key]: value } }));

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (saving) return;
    const currentYear = new Date().getFullYear();
    const invalid = validateGoals(plan, draft, currentYear);
    setError(invalid);
    if (invalid) return;
    const next = needsSalary(plan, draft) ? "income" : undefined;
    const steps = buildSetupSteps(plan, draft, currentYear);
    setSaving(true);
    setFailures([]);
    setConflict(false);
    const outcome = await runSetupSteps(steps, saved.current, {
      adapter,
      plan,
      accountIds: {},
      retirementId:
        plan.milestones.find((milestone) => milestone.name === "Retirement")?.id ?? null,
    });
    // A conflicting rule may still have created its blank destination account.
    if (outcome.wrote || outcome.conflict) {
      if (outcome.wroteAccounts || outcome.conflict)
        usePlanStore.setState((s) => ({ accountsRevision: s.accountsRevision + 1 }));
      await usePlanStore.getState().loadPlan(plan.id);
    }
    setSaving(false);
    if (outcome.conflict) {
      // Not retried: the rules changed elsewhere and need a look first.
      setConflict(true);
      set("leftover", "");
    }
    if (outcome.failures.length > 0) {
      setFailures(outcome.failures);
      return;
    }
    if (outcome.conflict) return;
    if (next) requestAddIncome(plan.id);
    onDone(next);
  }

  const timingHint =
    draft.timing === "independence"
      ? "Retirement starts when liquid net worth reaches 25× a year of spending."
      : undefined;

  return (
    <form
      className="goals-form"
      onSubmit={handleSubmit}
      aria-labelledby="goals-intake-title"
      noValidate
    >
      <h2 id="goals-intake-title" style={{ margin: 0, fontSize: 18 }}>
        Goals
      </h2>
      <fieldset disabled={saving} className="goals-body">
        <Group title="Stop working">
          <div style={{ display: "flex", gap: "6px 18px", flexWrap: "wrap" }}>
            {TIMINGS.map((timing) => (
              <label key={timing.value} style={choiceStyle}>
                <input
                  type="radio"
                  name="retirement-timing"
                  value={timing.value}
                  checked={draft.timing === timing.value}
                  onChange={() => set("timing", timing.value)}
                />
                {timing.label}
              </label>
            ))}
          </div>
          {timingHint && <p className="goals-hint">{timingHint}</p>}
          {draft.timing === "age" && (
            <NumberField
              label="Retirement age"
              age
              value={draft.retirementAge}
              onChange={(value) => set("retirementAge", value)}
            />
          )}
          {draft.timing === "stopped" && (
            <>
              <NumberField
                label="Social Security received ($/mo)"
                value={draft.socialSecurityMonthly}
                onChange={(value) => set("socialSecurityMonthly", value)}
                invalid={failedKeys.has("income:social_security:self")}
              />
              <NumberField
                label="Pension or other retirement income ($/yr)"
                value={draft.pension}
                onChange={(value) => set("pension", value)}
                invalid={failedKeys.has("income:pension:self")}
              />
            </>
          )}
          {spouseBirth != null && (
            <>
              {!draft.partnerStopped && (
                <NumberField
                  label="Partner retirement age"
                  age
                  value={draft.partnerRetirementAge}
                  onChange={(value) => set("partnerRetirementAge", value)}
                />
              )}
              <label style={choiceStyle}>
                <input
                  type="checkbox"
                  checked={draft.partnerStopped}
                  onChange={(event) => set("partnerStopped", event.target.checked)}
                />
                My partner has already stopped working
              </label>
              {draft.partnerStopped && (
                <>
                  <NumberField
                    label="Partner Social Security received ($/mo)"
                    value={draft.partnerSocialSecurityMonthly}
                    onChange={(value) => set("partnerSocialSecurityMonthly", value)}
                    invalid={failedKeys.has("income:social_security:spouse")}
                  />
                  <NumberField
                    label="Partner pension or other retirement income ($/yr)"
                    value={draft.partnerPension}
                    onChange={(value) => set("partnerPension", value)}
                    invalid={failedKeys.has("income:pension:spouse")}
                  />
                </>
              )}
            </>
          )}
        </Group>

        <Group title="Spending">
          <NumberField
            label="Monthly spending today ($/mo)"
            value={draft.monthlySpending}
            onChange={(value) => set("monthlySpending", value)}
            hint="Excludes taxes and savings."
            invalid={failedKeys.has("living_expenses")}
          />
          <NumberField
            label={GOAL_LABELS.retirement_spending.label}
            value={draft.goals.retirement_spending}
            onChange={(value) => setGoal("retirement_spending", value)}
            hint={
              draft.monthlySpending.trim() ? "Replaces monthly spending at Retirement." : undefined
            }
          />
        </Group>

        <details className="goals-more">
          <summary>Travel, giving and heirs</summary>
          {GOAL_FIELDS.filter((field) => field !== "retirement_spending").map((field) => (
            <NumberField
              key={field}
              label={GOAL_LABELS[field].label}
              age={GOAL_LABELS[field].age}
              value={draft.goals[field]}
              onChange={(value) => setGoal(field, value)}
            />
          ))}
        </details>

        <details
          className="goals-more"
          open={
            failures.some(
              (failure) => failure.key.startsWith("account:") || failure.key === "leftover",
            ) || undefined
          }
        >
          <summary>Account balances</summary>
          <p className="goals-hint">Blank skips an account; 0 adds it empty.</p>
          <div className="goals-balances">
            {slots.map((slot) => (
              <NumberField
                key={slot.key}
                label={slot.name}
                value={draft.balances[slot.key] ?? ""}
                onChange={(value) => setBalance(slot.key, value)}
                invalid={failedKeys.has(`account:${slot.key}`)}
              />
            ))}
          </div>
          <label>
            Leftover income goes to
            <select
              value={draft.leftover}
              onChange={(event) => set("leftover", event.target.value as LeftoverTarget)}
              aria-invalid={failedKeys.has("leftover") || undefined}
            >
              <option value="">Not set</option>
              <option value="brokerage">Brokerage</option>
              <option value="cash">Cash</option>
            </select>
          </label>
        </details>
      </fieldset>

      {error && <p role="alert">{error}</p>}
      {failures.length > 0 && (
        <div role="alert" className="goals-failures">
          <p>
            Not saved: {failures.map((failure) => failure.label).join(", ")}. Save again to retry.
          </p>
          <ul>
            {[...new Set(failures.map((failure) => failure.message))].map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      )}
      {conflict && (
        <p role="alert">
          Leftover income was not saved: income allocation changed since this plan opened. Set it
          under Income allocation.
        </p>
      )}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button type="submit" disabled={saving} style={{ minHeight: 42, flex: "1 1 160px" }}>
          {saving ? "Saving…" : "Save goals"}
        </button>
        <button
          type="button"
          className="btn-secondary"
          disabled={saving}
          onClick={() => onDone()}
          style={{ minHeight: 42, flex: "1 1 120px" }}
        >
          Skip
        </button>
      </div>
    </form>
  );
}
