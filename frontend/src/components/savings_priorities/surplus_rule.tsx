import type { ReactNode } from "react";
import type { Account, CashFlowPriorityCreate, PlanData, YearSnapshot } from "@/types/plan";
import { employerPlanFamily } from "@/domain/account_types";
import { fundingReasons } from "@/components/surplus_allocation_summary";
import { allocationSummary, isDebt, workplaceTypes } from "./rules";

/** A rule funded after spending: a collapsible summary over its fields and its funding notes. */
export default function SurplusRule({
  rule: p,
  index: i,
  number,
  open,
  onToggle,
  accounts,
  plan,
  edit,
  controls,
  firstYear,
  firstStarved,
}: {
  rule: CashFlowPriorityCreate;
  index: number;
  number: number;
  open: boolean;
  onToggle: (open: boolean) => void;
  accounts: Account[];
  plan: PlanData;
  edit: (update: Partial<CashFlowPriorityCreate>) => void;
  controls: ReactNode;
  /** The projection's first year; absent while the draft has unsaved changes. */
  firstYear?: YearSnapshot;
  /** The rank of the first rule earlier rules starved, which alone says so. */
  firstStarved?: number | null;
}) {
  const targetType = accounts.find((a) => a.id === p.target_account_id)?.account_type;
  return (
    <section
      id={`allocation-rule-${i + 1}`}
      tabIndex={-1}
      className="allocation-rule"
      aria-label={`Allocation rule ${number}`}
    >
      <details open={open} onToggle={(e) => onToggle(e.currentTarget.open)}>
        <summary>
          {number}.{" "}
          {isDebt(p)
            ? `Pay down ${(plan.liabilities ?? []).find((l) => l.id === p.target_liability_id)?.name ?? "a loan"}`
            : (accounts.find((a) => a.id === p.target_account_id)?.name ?? "New allocation")}{" "}
          · {allocationSummary(p)}
          {p.withdraw_if_short ? " · withdraws if short" : ""}
        </summary>
        {controls}
        {workplaceTypes.includes(targetType ?? "") && (
          <>
            <p className="allocation-notice">
              Legacy {employerPlanFamily(targetType)} surplus rule. Convert to payroll to change its
              funding.
            </p>
            <button
              type="button"
              onClick={() =>
                edit({
                  priority_type: "pre_tax_contribution",
                  allocation_mode: "remaining",
                  allocation_value: null,
                })
              }
            >
              Use payroll for this {employerPlanFamily(targetType)}
            </button>
          </>
        )}
      </details>
      {firstYear?.cash_flow?.contributions
        .filter(
          (flow) =>
            flow.source === "priority" &&
            flow.priority_rank === p.priority_rank &&
            (flow.amount === 0 || flow.funding_reasons?.includes("withdrawal_shortfall")),
        )
        .map((flow, j) => {
          const reasons = (flow.funding_reasons ?? []).filter(
            (reason) => reason !== "earlier_rules" || flow.priority_rank === firstStarved,
          );
          return reasons.length ? (
            <p key={j} className="allocation-notice">
              {reasons.map((reason) => fundingReasons[reason]).join(" ")}
            </p>
          ) : null;
        })}
    </section>
  );
}
