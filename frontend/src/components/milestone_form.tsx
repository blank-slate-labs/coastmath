import { moneyLabel } from "@/utils/format";
import { useMemo, useState } from "react";
import type {
  Milestone,
  MilestoneCreate,
  MilestoneTriggerType,
  MilestoneConditions,
} from "@/types/plan";

import MilestoneConditionsEditor, { conditionsError } from "./milestone_conditions_editor";
import MoneyInput from "./money_input";
import { FormFooter } from "./form_footer";
import { formStyle } from "./form_styles";

interface MilestoneFormProps {
  initial?: Milestone;
  /** Starting values for a new milestone (ignored when editing ``initial``). */
  preset?: MilestoneCreate;
  /** Other milestones in the plan, used for relative references. */
  milestones?: Milestone[];
  accounts?: { id: string; name: string }[];
  /** Plan owner's birth year, used to flag ages that have already passed. */
  birthYear?: number | null;
  /** Partner's birth year; offers the Partner retirement preset when set. */
  spouseBirthYear?: number | null;
  onSubmit: (data: MilestoneCreate) => void;
  onCancel: () => void;
  /** Shown above the form actions, e.g. the inputs linked to an edited milestone. */
  children?: React.ReactNode;
}

type Metric = "liquid_net_worth" | "net_worth";

/** Age milestones with a fixed name; the user enters only the age. */
type PresetKind = "retirement" | "partner_retirement";
const PRESET_NAMES: Record<PresetKind, string> = {
  retirement: "Retirement",
  partner_retirement: "Partner retirement",
};
type MilestoneKind = PresetKind | "custom";

/** Presets not already in the plan by name; Partner retirement needs both birth years. */
export function availablePresets(
  milestones: Milestone[],
  birthYear: number | null,
  spouseBirthYear: number | null,
): PresetKind[] {
  const taken = new Set(milestones.map((m) => m.name.trim().toLowerCase()));
  const kinds: PresetKind[] = ["retirement"];
  if (birthYear != null && spouseBirthYear != null) kinds.push("partner_retirement");
  return kinds.filter((k) => !taken.has(PRESET_NAMES[k].toLowerCase()));
}

/**
 * A saved Partner retirement: the preset's name on an age trigger. Milestones
 * have no owner, so the name is the only record that the age is the partner's.
 */
export function isPartnerRetirement(milestone: Milestone): boolean {
  return (
    milestone.name.trim().toLowerCase() === PRESET_NAMES.partner_retirement.toLowerCase() &&
    milestone.trigger_type === "age" &&
    milestone.trigger_value != null
  );
}

const triggerTypes: { value: MilestoneTriggerType; label: string }[] = [
  { value: "age", label: "Age" },
  { value: "date", label: "Date" },
  { value: "net_worth", label: "Net worth reaches" },
  { value: "expense_multiple", label: "Financial independence (multiple of expenses)" },
  { value: "conditions", label: "Conditions" },
  { value: "relative", label: "Relative to another milestone" },
];

const helpStyle: React.CSSProperties = {
  display: "block",
  fontSize: 12,
  color: "var(--gray-500, #6b7280)",
};

/**
 * IDs that would create a circular relative chain if `editingId` referenced
 * them: the milestone itself plus everything whose chain leads back to it.
 */
export function circularReferenceIds(
  editingId: string | undefined,
  milestones: Milestone[],
): Set<string> {
  const blocked = new Set<string>();
  if (!editingId) return blocked;
  blocked.add(editingId);
  const parents = new Map(
    milestones.map((m) => {
      const references =
        m.trigger_type === "conditions"
          ? (m.conditions?.items.flatMap((item) =>
              item.kind === "milestone" ? [item.milestone_id] : [],
            ) ?? [])
          : m.relative_to_id
            ? [m.relative_to_id]
            : [];
      if (m.trigger_type === "conditions" && m.conditions?.deadline?.kind === "milestone")
        references.push(String(m.conditions.deadline.value));
      return [m.id, references];
    }),
  );
  for (const m of milestones) {
    const seen = new Set<string>();
    const pending = [m.id];
    while (pending.length) {
      const cursor = pending.pop()!;
      if (cursor === editingId) {
        blocked.add(m.id);
        break;
      }
      if (seen.has(cursor)) continue;
      seen.add(cursor);
      pending.push(...(parents.get(cursor) ?? []));
    }
  }
  return blocked;
}

export default function MilestoneForm({
  initial,
  preset,
  milestones = [],
  accounts = [],
  birthYear = null,
  spouseBirthYear = null,
  onSubmit,
  onCancel,
  children,
}: MilestoneFormProps) {
  const start = initial ?? preset;
  // Age milestones fire on the primary person's age, so a partner's age is
  // shifted by the birth-year gap: the milestone fires the year the partner
  // reaches it.
  const birthYearGap =
    birthYear != null && spouseBirthYear != null ? spouseBirthYear - birthYear : null;
  // A saved Partner retirement reopens in its own mode, showing the partner's
  // age; without both birth years it opens as a custom age milestone.
  const editsPartnerRetirement =
    initial != null && birthYearGap != null && isPartnerRetirement(initial);
  // Presets apply only to a blank new milestone.
  const presets = useMemo(
    () => (start ? [] : availablePresets(milestones, birthYear, spouseBirthYear)),
    [start, milestones, birthYear, spouseBirthYear],
  );
  const kindChoices: MilestoneKind[] = editsPartnerRetirement
    ? ["partner_retirement", "custom"]
    : presets.length > 0
      ? [...presets, "custom"]
      : [];
  const [kind, setKind] = useState<MilestoneKind>(kindChoices[0] ?? "custom");
  const isPreset = kind !== "custom";
  const [name, setName] = useState(start?.name ?? "");
  const [triggerType, setTriggerType] = useState<MilestoneTriggerType>(
    start?.trigger_type ?? "age",
  );
  const [triggerValue, setTriggerValue] = useState(
    editsPartnerRetirement
      ? String(initial.trigger_value! - birthYearGap)
      : (initial?.trigger_value?.toString() ?? ""),
  );
  const partnerAgeOffset = kind === "partner_retirement" ? birthYearGap : null;

  function chooseKind(next: MilestoneKind) {
    // An edited milestone keeps the same event: convert the shown age between
    // the partner's and the primary person's instead of reinterpreting it.
    const age = Number(triggerValue);
    if (editsPartnerRetirement && triggerValue.trim() !== "" && Number.isFinite(age)) {
      if (kind === "partner_retirement" && next === "custom")
        setTriggerValue(String(age + birthYearGap));
      if (kind === "custom" && next === "partner_retirement" && triggerType === "age")
        setTriggerValue(String(age - birthYearGap));
    }
    setKind(next);
    setError(null);
  }
  const ageBirthYear = partnerAgeOffset != null ? spouseBirthYear : birthYear;
  const pastAgeNote = (() => {
    const age = Number(triggerValue);
    if (ageBirthYear == null || triggerValue.trim() === "" || !Number.isFinite(age)) return null;
    const reachedYear = ageBirthYear + Math.ceil(age);
    const thisYear = new Date().getFullYear();
    return reachedYear < thisYear
      ? `Age ${age} was reached in ${reachedYear}, before the plan starts. Anything tied to this milestone is treated as already in effect.`
      : null;
  })();
  const [triggerDate, setTriggerDate] = useState(initial?.trigger_date ?? "");
  const [metric, setMetric] = useState<Metric>(start?.metric ?? "liquid_net_worth");
  const [expenseMultiple, setExpenseMultiple] = useState(
    start?.expense_multiple != null ? String(start.expense_multiple) : "25",
  );
  const [relativeToId, setRelativeToId] = useState(initial?.relative_to_id ?? "");
  const [offsetYears, setOffsetYears] = useState(String(initial?.offset_years ?? 0));
  const [conditions, setConditions] = useState<MilestoneConditions>(
    start?.conditions ?? { combinator: "all", items: [{ kind: "age", owner: "self", age: 50 }] },
  );
  const [active, setActive] = useState(initial?.is_active ?? true);
  const [error, setError] = useState<string | null>(null);

  const blocked = useMemo(
    () => circularReferenceIds(initial?.id, milestones),
    [initial?.id, milestones],
  );
  const referenceOptions = milestones.filter((m) => !blocked.has(m.id));

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (isPreset) {
      const age = Number(triggerValue);
      if (triggerValue.trim() === "" || !Number.isFinite(age) || age < 0 || age > 130) {
        setError("Enter an age between 0 and 130.");
        return;
      }
      const data: MilestoneCreate = {
        // An edit keeps the saved spelling of the preset name.
        name: editsPartnerRetirement ? initial.name : PRESET_NAMES[kind],
        trigger_type: "age",
        trigger_value: age + (partnerAgeOffset ?? 0),
        trigger_date: null,
        metric: null,
        expense_multiple: null,
        relative_to_id: null,
        offset_years: 0,
      };
      if (initial?.conditions) data.conditions = null;
      if (active !== (initial?.is_active ?? true)) data.is_active = active;
      onSubmit(data);
      return;
    }
    const data: MilestoneCreate = {
      name,
      trigger_type: triggerType,
      trigger_value: null,
      trigger_date: null,
      metric: null,
      expense_multiple: null,
      relative_to_id: null,
      offset_years: 0,
    };
    if (triggerType === "age" || triggerType === "net_worth") {
      const value = Number(triggerValue);
      if (
        triggerValue.trim() === "" ||
        !Number.isFinite(value) ||
        (triggerType === "age" && (value < 0 || value > 130))
      ) {
        setError(
          triggerType === "age"
            ? "Enter an age between 0 and 130."
            : "Enter the net worth that triggers this milestone.",
        );
        return;
      }
      data.trigger_value = value;
    } else if (triggerType === "date") {
      if (!triggerDate) {
        setError("Enter a date.");
        return;
      }
      data.trigger_date = triggerDate;
    } else if (triggerType === "expense_multiple") {
      const multiple = Number(expenseMultiple);
      if (expenseMultiple.trim() === "" || !Number.isFinite(multiple) || multiple <= 0) {
        setError("Enter a positive multiple of annual expenses (e.g. 25).");
        return;
      }
      data.expense_multiple = multiple;
      data.metric = metric;
    } else if (triggerType === "relative") {
      if (!relativeToId) {
        setError("Choose the milestone this one is relative to.");
        return;
      }
      if (blocked.has(relativeToId)) {
        setError("That reference would create a circular chain.");
        return;
      }
      const offset = Number(offsetYears);
      if (offsetYears.trim() === "" || !Number.isInteger(offset) || offset < -100 || offset > 100) {
        setError("Offset must be a whole number of years between -100 and 100.");
        return;
      }
      data.relative_to_id = relativeToId;
      data.offset_years = offset;
    }
    if (triggerType === "conditions") {
      const issue = conditionsError(conditions);
      if (issue) {
        setError(issue);
        return;
      }
      data.conditions = conditions;
    } else if (initial?.conditions) data.conditions = null;
    if (active !== (initial?.is_active ?? true)) data.is_active = active;
    onSubmit(data);
  }

  const shownType: MilestoneTriggerType = isPreset ? "age" : triggerType;
  const savedOwnerAge =
    partnerAgeOffset != null && triggerValue.trim() !== "" && Number.isFinite(Number(triggerValue))
      ? Number(triggerValue) + partnerAgeOffset
      : null;

  return (
    <form onSubmit={handleSubmit} style={formStyle}>
      {kindChoices.length > 0 && (
        <fieldset style={{ gridColumn: "1 / -1", border: "none", padding: 0, margin: 0 }}>
          <legend style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 6 }}>
            Milestone
          </legend>
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
            {kindChoices.map((k) => (
              <label key={k} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <input
                  type="radio"
                  name="milestone-kind"
                  value={k}
                  checked={kind === k}
                  onChange={() => chooseKind(k)}
                />
                {k === "custom" ? "Custom" : PRESET_NAMES[k]}
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {!isPreset && (
        <>
          <label>
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>

          <label>
            Trigger Type
            <select
              value={triggerType}
              onChange={(e) => setTriggerType(e.target.value as MilestoneTriggerType)}
            >
              {triggerTypes.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
        </>
      )}

      {(shownType === "age" || shownType === "net_worth") && (
        <label>
          {shownType === "net_worth"
            ? moneyLabel("Net Worth ($)")
            : partnerAgeOffset != null
              ? "Partner's age"
              : "Age"}
          {shownType === "net_worth" ? (
            <MoneyInput value={triggerValue} onValueChange={setTriggerValue} />
          ) : (
            <input
              type="number"
              value={triggerValue}
              onChange={(e) => setTriggerValue(e.target.value)}
            />
          )}
          {shownType === "net_worth" && (
            <span style={helpStyle}>
              {moneyLabel("Total net worth including property, minus debt, in nominal dollars.")}
            </span>
          )}
          {savedOwnerAge != null && partnerAgeOffset !== 0 && (
            <span style={helpStyle}>Saved as the primary person's age {savedOwnerAge}.</span>
          )}
          {shownType === "age" && pastAgeNote && (
            <span role="status" style={helpStyle}>
              {pastAgeNote}
            </span>
          )}
        </label>
      )}

      {shownType === "date" && (
        <label>
          Date
          <input type="date" value={triggerDate} onChange={(e) => setTriggerDate(e.target.value)} />
        </label>
      )}

      {shownType === "expense_multiple" && (
        <>
          <label>
            Multiple of annual expenses
            <input
              type="number"
              min="0.1"
              step="any"
              value={expenseMultiple}
              onChange={(e) => setExpenseMultiple(e.target.value)}
            />
            <span style={helpStyle}>
              Fires the year after the balance exceeds this multiple of prior-year expenses.
            </span>
          </label>
          <label>
            Balance measured
            <select value={metric} onChange={(e) => setMetric(e.target.value as Metric)}>
              <option value="liquid_net_worth">Liquid accounts minus debt</option>
              <option value="net_worth">Total net worth incl. property</option>
            </select>
          </label>
        </>
      )}

      {shownType === "relative" && (
        <>
          <label>
            Relative to
            <select value={relativeToId} onChange={(e) => setRelativeToId(e.target.value)}>
              <option value="">— Choose a milestone —</option>
              {referenceOptions.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
            {milestones.length > referenceOptions.length && (
              <span style={helpStyle}>Dependent milestones are hidden to prevent cycles.</span>
            )}
          </label>
          <label>
            Offset (years)
            <input
              type="number"
              step="1"
              min="-100"
              max="100"
              value={offsetYears}
              onChange={(e) => setOffsetYears(e.target.value)}
            />
            <span style={helpStyle}>
              Negative offsets cannot fire in years the projection has already passed.
            </span>
          </label>
        </>
      )}

      {shownType === "conditions" && (
        <MilestoneConditionsEditor
          value={conditions}
          onChange={setConditions}
          milestones={referenceOptions}
          accounts={accounts}
        />
      )}

      {(!isPreset || initial) && (
        <label style={{ gridColumn: "1 / -1", display: "flex", alignItems: "center", gap: 8 }}>
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
          Active
          <span style={helpStyle}>
            Switched off, the milestone keeps its settings but never fires. Anything tied to it acts
            as if it is never reached.
          </span>
        </label>
      )}

      {error && (
        <div
          role="alert"
          style={{ gridColumn: "1 / -1", color: "var(--color-danger)", fontSize: 13 }}
        >
          {error}
        </div>
      )}

      {children && <div style={{ gridColumn: "1 / -1" }}>{children}</div>}

      <FormFooter onCancel={onCancel} submitLabel={`${initial ? "Update" : "Add"} Milestone`} />
    </form>
  );
}
