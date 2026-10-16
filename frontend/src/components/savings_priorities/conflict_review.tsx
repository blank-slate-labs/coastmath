import type { RefObject } from "react";
import { fullCurrency } from "@/utils/format";
import type { Account, CashFlowPriorityCreate, Income, PlanData } from "@/types/plan";
import { STALE_RATE_NOTE, isStaleConversionCeiling } from "@/domain/federal_bracket_rates";
import {
  allocationSummary,
  employerSummary,
  isAfterTax,
  isDebt,
  isPayroll,
  isSurplus,
  rankedPayload,
  ruleSignature,
} from "./rules";

/** One line describing a saved rule in the review list. */
function reviewSummary(
  p: CashFlowPriorityCreate,
  saved: PlanData,
  accounts: Account[],
  incomes: Income[],
) {
  const target = isDebt(p)
    ? `Pay down ${(saved.liabilities ?? []).find((l) => l.id === p.target_liability_id)?.name ?? "a loan"}`
    : (accounts.find((a) => a.id === p.target_account_id)?.name ?? "Account rule");
  const kind = isSurplus(p)
    ? allocationSummary(p)
    : isAfterTax(p)
      ? "mega backdoor Roth"
      : (p.priority_type ?? "contribution").replace(/_/g, " ");
  return [
    `${target} · ${kind}`,
    p.max_annual_amount != null && ` · annual maximum ${fullCurrency(p.max_annual_amount)}`,
    p.source_income_id &&
      ` · from ${incomes.find((i) => i.id === p.source_income_id)?.name ?? "income"}`,
    p.source_account_id &&
      ` · from ${accounts.find((a) => a.id === p.source_account_id)?.name ?? "account"}`,
    isPayroll(p) &&
      !isAfterTax(p) &&
      ` · employee ${p.employee_rate ?? 0}% · ${employerSummary(p)}`,
    p.limit_mode === "custom" &&
      p.custom_annual_limit != null &&
      ` · plan limit ${fullCurrency(p.custom_annual_limit)}`,
    p.magi_cap != null && ` · income cap ${fullCurrency(p.magi_cap)}`,
    p.start_milestone_id &&
      ` · starts ${saved.milestones.find((m) => m.id === p.start_milestone_id)?.name ?? "at milestone"}`,
    p.end_milestone_id &&
      ` · ends ${saved.milestones.find((m) => m.id === p.end_milestone_id)?.name ?? "at milestone"}`,
    p.target_balance != null && ` · balance target ${fullCurrency(p.target_balance)}`,
    p.bracket_ceiling_rate != null &&
      ` · bracket ${p.bracket_ceiling_rate * 100}%${isStaleConversionCeiling(p, saved.tax_settings) ? ` ${STALE_RATE_NOTE}` : ""}`,
    p.use_plan_tax_target && " · plan tax target",
    p.withdraw_if_short && " · withdraws if short",
    p.reduce_employer_contribution && " · reduces employer contribution when pay is short",
  ]
    .filter(Boolean)
    .join("");
}

/**
 * The latest saved rules, shown when they moved on underneath the draft. It lists them as the
 * editor does and marks where they differ, then keeps the draft or takes the saved rules.
 */
export default function ConflictReview({
  latest,
  items,
  accounts,
  incomes,
  focusRef,
  reconcile,
}: {
  latest: PlanData;
  items: CashFlowPriorityCreate[];
  accounts: Account[];
  incomes: Income[];
  focusRef: RefObject<HTMLElement>;
  reconcile: (keepDraft: boolean) => void;
}) {
  const latestRules = rankedPayload(latest.priorities);
  const latestSignatures = new Set(latestRules.map(ruleSignature));
  const draftSignatures = new Set(items.map(ruleSignature));
  return (
    <section
      ref={focusRef}
      tabIndex={-1}
      aria-label="Review allocation conflict"
      className="allocation-notice"
    >
      <h3>Review the latest saved rules</h3>
      <p>
        Review before saving: your draft replaces the entire saved list, including rules from Tax
        tools and other tabs.
      </p>
      {[
        { title: "After spending", rules: latestRules.filter(isSurplus) },
        {
          title: "Payroll contributions and account transfers",
          rules: latestRules.filter((p) => !isSurplus(p)),
        },
      ]
        .filter((group) => group.rules.length)
        .map((group) => (
          <div key={group.title}>
            <h4 style={{ margin: "8px 0 4px" }}>{group.title}</h4>
            <ol style={{ paddingInlineStart: 20, margin: 0 }}>
              {group.rules.map((p) => (
                <li key={ruleSignature(p)}>
                  {reviewSummary(p, latest, accounts, incomes)}
                  {!draftSignatures.has(ruleSignature(p)) && (
                    <strong> · differs from your draft</strong>
                  )}
                </li>
              ))}
            </ol>
          </div>
        ))}
      {items.some((p) => !latestSignatures.has(ruleSignature(p))) && (
        <p style={{ margin: 0 }}>Your draft also has rules that are not saved.</p>
      )}
      <button type="button" onClick={() => reconcile(true)}>
        Keep my draft after reviewing these rules
      </button>
      <button type="button" onClick={() => reconcile(false)}>
        Use latest rules and discard my draft
      </button>
    </section>
  );
}
