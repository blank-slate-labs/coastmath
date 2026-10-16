import { useId } from "react";
import type { PlanData } from "@/types/plan";

export interface MilestoneLink {
  key: string;
  kind: string;
  name: string;
  relationship: string;
}

const RELATIONSHIPS: [field: string, relationship: string][] = [
  ["start_milestone_id", "Starts here"],
  ["end_milestone_id", "Ends here"],
  ["payoff_milestone_id", "Paid off here"],
  ["relative_to_id", "Timing follows this milestone"],
];

type Linkable = { id: string; name?: string | null; priority_rank?: number };

/** Inputs whose timing references a milestone, matching iOS `MilestoneInputLink.affected`. */
export function milestoneLinks(plan: PlanData, milestoneId: string): MilestoneLink[] {
  const groups: [kind: string, records: Linkable[] | undefined][] = [
    ["Income", plan.income_streams],
    ["Expense", plan.expenses],
    ["Savings rule", plan.priorities],
    ["Debt", plan.liabilities],
    ["Milestone", plan.milestones],
  ];
  return groups.flatMap(([kind, records]) =>
    (records ?? []).flatMap((record) => {
      const fields = record as unknown as Record<string, unknown>;
      const name =
        kind === "Savings rule"
          ? `Savings rule ${record.priority_rank ?? ""}`.trim()
          : record.name || kind;
      return RELATIONSHIPS.filter(([field]) => fields[field] === milestoneId).map(
        ([field, relationship]) => ({
          key: `${kind}:${record.id}:${field}`,
          kind,
          name,
          relationship,
        }),
      );
    }),
  );
}

/** The incomes, expenses, savings rules, debts and milestones that move with this milestone. */
export function MilestoneLinks({ plan, milestoneId }: { plan: PlanData; milestoneId: string }) {
  const titleId = useId();
  const links = milestoneLinks(plan, milestoneId);
  return (
    <section aria-labelledby={titleId} style={{ display: "grid", gap: 6 }}>
      <h3 id={titleId} style={{ margin: 0, fontSize: 13, fontWeight: 600 }}>
        Linked inputs
      </h3>
      {links.length === 0 ? (
        <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>No linked inputs.</p>
      ) : (
        <ul style={{ margin: 0, paddingInlineStart: 18, display: "grid", gap: 4, fontSize: 13 }}>
          {links.map((link) => (
            <li key={link.key}>
              {link.name}
              <span style={{ color: "var(--text-secondary)" }}> · {link.relationship}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
