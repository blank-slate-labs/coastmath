import type {
  ConditionMetric,
  Milestone,
  MilestoneCondition,
  MilestoneConditions,
} from "@/types/plan";
import { PARTNER_LABEL, PRIMARY_PERSON_LABEL } from "@/domain/person_labels";
import { dollarsOr, moneyLabel } from "@/utils/format";
import MoneyInput from "@/components/money_input";

const metrics: { value: ConditionMetric; label: string }[] = [
  { value: "net_worth", label: "Net worth" },
  { value: "liquid_net_worth", label: "Liquid net worth" },
  { value: "account_balance", label: "Account balance" },
  { value: "total_debt", label: "Total debt" },
  { value: "annual_spending", label: "Annual spending" },
  { value: "passive_income", label: "Passive income" },
  { value: "savings_rate", label: "Savings rate" },
];
export const newCondition = (kind: MilestoneCondition["kind"]): MilestoneCondition => {
  switch (kind) {
    case "age":
      return { kind, owner: "self", age: 50 };
    case "year":
      return { kind, year: new Date().getFullYear() };
    case "date":
      return { kind, date: `${new Date().getFullYear()}-01` };
    case "milestone":
      return { kind, milestone_id: "", offset_years: 0 };
    case "metric":
      return {
        kind,
        metric: "liquid_net_worth",
        comparator: ">=",
        value_unit: "dollars",
        value: 0,
      };
  }
};

export function conditionsError(settings: MilestoneConditions): string | null {
  for (const item of settings.items) {
    if (item.kind === "milestone" && !item.milestone_id)
      return "Choose a milestone for each milestone condition.";
    if (item.kind === "metric") {
      if (!Number.isFinite(item.value)) return "Enter a finite condition value.";
      if (
        (item.metric === "account_balance" || item.other_metric === "account_balance") &&
        !item.account_id
      )
        return "Choose an account for the account balance condition.";
      if (item.value_unit === "multiple_of_metric" && !item.other_metric)
        return "Choose a comparison metric.";
    }
  }
  if (settings.deadline && settings.deadline.value === "") return "Enter a deadline.";
  return null;
}

export default function MilestoneConditionsEditor({
  value,
  onChange,
  milestones,
  accounts,
}: {
  value: MilestoneConditions;
  onChange: (value: MilestoneConditions) => void;
  milestones: Milestone[];
  accounts: { id: string; name: string }[];
}) {
  function change(index: number, item: MilestoneCondition) {
    onChange({ ...value, items: value.items.map((old, i) => (i === index ? item : old)) });
  }
  const deadline = value.deadline;
  return (
    <fieldset style={{ gridColumn: "1 / -1", display: "grid", gap: 12 }}>
      <legend>Conditions</legend>
      <label>
        Match
        <select
          value={value.combinator}
          onChange={(e) => onChange({ ...value, combinator: e.target.value as "all" | "any" })}
        >
          <option value="all">All conditions</option>
          <option value="any">Any condition</option>
        </select>
      </label>
      {value.items.map((item, index) => (
        <fieldset key={index} style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <legend>Condition {index + 1}</legend>
          <label>
            Kind
            <select
              value={item.kind}
              onChange={(e) =>
                change(index, newCondition(e.target.value as MilestoneCondition["kind"]))
              }
            >
              <option value="age">Age</option>
              <option value="year">Year</option>
              <option value="date">Date</option>
              <option value="milestone">Milestone</option>
              <option value="metric">Metric</option>
            </select>
          </label>
          {item.kind === "age" && (
            <>
              <label>
                Person
                <select
                  value={item.owner}
                  onChange={(e) =>
                    change(index, { ...item, owner: e.target.value as "self" | "spouse" })
                  }
                >
                  <option value="self">{PRIMARY_PERSON_LABEL}</option>
                  <option value="spouse">{PARTNER_LABEL}</option>
                </select>
              </label>
              <label>
                Age
                <input
                  type="number"
                  min="0"
                  max="130"
                  step="any"
                  required
                  value={item.age}
                  onChange={(e) => change(index, { ...item, age: Number(e.target.value) })}
                />
              </label>
            </>
          )}
          {item.kind === "year" && (
            <label>
              Year
              <input
                type="number"
                min="1"
                max="9999"
                required
                value={item.year}
                onChange={(e) => change(index, { ...item, year: Number(e.target.value) })}
              />
            </label>
          )}
          {item.kind === "date" && (
            <label>
              Date
              <input
                type="month"
                required
                value={item.date}
                onChange={(e) => change(index, { ...item, date: e.target.value })}
              />
            </label>
          )}
          {item.kind === "milestone" && (
            <>
              <label>
                Milestone
                <select
                  required
                  value={item.milestone_id}
                  onChange={(e) => change(index, { ...item, milestone_id: e.target.value })}
                >
                  <option value="">Choose a milestone</option>
                  {milestones.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Offset years
                <input
                  type="number"
                  min="-100"
                  max="100"
                  step="1"
                  required
                  value={item.offset_years ?? 0}
                  onChange={(e) => change(index, { ...item, offset_years: Number(e.target.value) })}
                />
              </label>
            </>
          )}
          {item.kind === "metric" && (
            <>
              <label>
                Metric
                <select
                  value={item.metric}
                  onChange={(e) => {
                    const metric = e.target.value as ConditionMetric;
                    change(index, {
                      ...item,
                      metric,
                      value_unit: metric === "savings_rate" ? "percent" : "dollars",
                      other_metric: null,
                    });
                  }}
                >
                  {metrics.map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Comparator
                <select
                  value={item.comparator}
                  onChange={(e) =>
                    change(index, { ...item, comparator: e.target.value as ">=" | "<=" })
                  }
                >
                  <option value=">=">At least</option>
                  <option value="<=">At most</option>
                </select>
              </label>
              <label>
                Value
                {item.value_unit === "dollars" || item.value_unit === "today_dollars" ? (
                  <MoneyInput
                    required
                    step="any"
                    value={item.value}
                    onValueChange={(amount) => change(index, { ...item, value: Number(amount) })}
                  />
                ) : (
                  <input
                    type="number"
                    required
                    step="any"
                    value={item.value}
                    onChange={(e) => change(index, { ...item, value: Number(e.target.value) })}
                  />
                )}
              </label>
              <label>
                Unit
                <select
                  value={item.value_unit}
                  onChange={(e) => {
                    const unit = e.target.value as typeof item.value_unit;
                    change(index, {
                      ...item,
                      value_unit: unit,
                      other_metric: unit === "multiple_of_metric" ? "annual_spending" : null,
                    });
                  }}
                >
                  {item.metric === "savings_rate" ? (
                    <option value="percent">Percent</option>
                  ) : (
                    <>
                      <option value="dollars">{dollarsOr("Dollars", "Nominal amount")}</option>
                      <option value="today_dollars">{moneyLabel("Today's dollars")}</option>
                      <option value="multiple_of_metric">Multiple of metric</option>
                    </>
                  )}
                </select>
              </label>
              {item.value_unit === "multiple_of_metric" && (
                <>
                  <label>
                    Comparison metric
                    <select
                      value={item.other_metric ?? "annual_spending"}
                      onChange={(e) =>
                        change(index, { ...item, other_metric: e.target.value as ConditionMetric })
                      }
                    >
                      {metrics
                        .filter((m) => m.value !== "savings_rate")
                        .map((m) => (
                          <option key={m.value} value={m.value}>
                            {m.label}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    Average years
                    <input
                      type="number"
                      min="1"
                      max="10"
                      step="1"
                      required
                      value={item.average_years ?? 1}
                      onChange={(e) =>
                        change(index, { ...item, average_years: Number(e.target.value) })
                      }
                    />
                  </label>
                </>
              )}
              {(item.metric === "account_balance" || item.other_metric === "account_balance") && (
                <label>
                  Account
                  <select
                    required
                    value={item.account_id ?? ""}
                    onChange={(e) => change(index, { ...item, account_id: e.target.value })}
                  >
                    <option value="">Choose an account</option>
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </>
          )}
          <button
            type="button"
            disabled={value.items.length === 1}
            onClick={() => onChange({ ...value, items: value.items.filter((_, i) => i !== index) })}
          >
            Remove condition {index + 1}
          </button>
        </fieldset>
      ))}
      <button
        type="button"
        disabled={value.items.length >= 10}
        onClick={() => onChange({ ...value, items: [...value.items, newCondition("age")] })}
      >
        Add condition
      </button>
      <label>
        <input
          type="checkbox"
          checked={!!deadline}
          onChange={(e) =>
            onChange({
              ...value,
              deadline: e.target.checked
                ? { kind: "age", value: 60, owner: "self", action: "fire" }
                : null,
            })
          }
        />
        Set a deadline
      </label>
      {deadline && (
        <fieldset style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <legend>Deadline</legend>
          <label>
            Deadline kind
            <select
              value={deadline.kind}
              onChange={(e) => {
                const kind = e.target.value as typeof deadline.kind;
                onChange({
                  ...value,
                  deadline: {
                    ...deadline,
                    kind,
                    value: kind === "age" ? 60 : kind === "year" ? new Date().getFullYear() : "",
                  },
                });
              }}
            >
              <option value="age">Age</option>
              <option value="year">Year</option>
              <option value="date">Date</option>
              <option value="milestone">Milestone</option>
            </select>
          </label>
          {deadline.kind === "age" && (
            <label>
              Deadline person
              <select
                value={deadline.owner ?? "self"}
                onChange={(e) =>
                  onChange({
                    ...value,
                    deadline: { ...deadline, owner: e.target.value as "self" | "spouse" },
                  })
                }
              >
                <option value="self">{PRIMARY_PERSON_LABEL}</option>
                <option value="spouse">{PARTNER_LABEL}</option>
              </select>
            </label>
          )}
          <label>
            Deadline value
            {deadline.kind === "milestone" ? (
              <select
                required
                value={deadline.value}
                onChange={(e) =>
                  onChange({ ...value, deadline: { ...deadline, value: e.target.value } })
                }
              >
                <option value="">Choose a milestone</option>
                {milestones.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            ) : (
              <input
                required
                type={deadline.kind === "date" ? "month" : "number"}
                min={deadline.kind === "age" ? 0 : 1}
                max={deadline.kind === "age" ? 130 : 9999}
                step={deadline.kind === "age" ? "any" : 1}
                value={deadline.value}
                onChange={(e) =>
                  onChange({
                    ...value,
                    deadline: {
                      ...deadline,
                      value: deadline.kind === "date" ? e.target.value : Number(e.target.value),
                    },
                  })
                }
              />
            )}
          </label>
          <label>
            At deadline
            <select
              value={deadline.action}
              onChange={(e) =>
                onChange({
                  ...value,
                  deadline: { ...deadline, action: e.target.value as "fire" | "miss" },
                })
              }
            >
              <option value="fire">Fire if not reached</option>
              <option value="miss">Mark missed if not reached</option>
            </select>
          </label>
        </fieldset>
      )}
      <small>
        Checked at each year's start. Spending, passive income and savings rate use completed years;
        rolling averages use available simulated years. Age and date conditions preserve their
        month; financial conditions use January.
      </small>
    </fieldset>
  );
}
