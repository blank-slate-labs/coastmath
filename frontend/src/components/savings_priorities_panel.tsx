import { useEffect, useRef, useState } from "react";
import { usePlanStore } from "@/stores/plan_store";
import { fullCurrency } from "@/utils/format";
import type {
  Account,
  CashFlowPriorityCreate,
  PlanData,
  SimulationResult,
  YearSnapshot,
} from "@/types/plan";
import { employerPlanFamily } from "@/domain/account_types";
import { usCoverage } from "@/domain/intl_plan";
import ConflictReview from "./savings_priorities/conflict_review";
import OtherRule from "./savings_priorities/other_rule";
import RuleControls from "./savings_priorities/rule_controls";
import SurplusRule from "./savings_priorities/surplus_rule";
import { useAllocationDraft } from "./savings_priorities/use_allocation_draft";
import {
  isSurplus,
  maxFundingIncome,
  maxableAccounts,
  neighbor,
  ruleNumbering,
} from "./savings_priorities/rules";

export { priorityPayload } from "./savings_priorities/rules";

export default function SavingsPrioritiesPanel({ plan }: { plan: PlanData }) {
  return <AllocationEditor key={`${plan.user_id}:${plan.id}`} plan={plan} />;
}

/** Adds, removes and moves draft rules, keeping each rule's open state with it. */
function useRuleList(
  items: CashFlowPriorityCreate[],
  change: (next: CashFlowPriorityCreate[]) => void,
) {
  // Rules start collapsed; open state follows each rule as rules are added, moved or removed.
  const [openRules, setOpenRules] = useState<ReadonlySet<number>>(() => new Set());
  function toggleRule(i: number, open: boolean) {
    setOpenRules((rules) => {
      if (rules.has(i) === open) return rules;
      const next = new Set(rules);
      if (open) next.add(i);
      else next.delete(i);
      return next;
    });
  }
  function addRule(rule: CashFlowPriorityCreate) {
    change([...items, rule]);
    toggleRule(items.length, true);
  }
  function removeRule(i: number) {
    change(items.filter((_, j) => j !== i));
    setOpenRules(
      (rules) => new Set([...rules].filter((j) => j !== i).map((j) => (j > i ? j - 1 : j))),
    );
  }
  function move(i: number, direction: number) {
    const j = neighbor(items, i, direction);
    if (j < 0) return;
    const next = [...items];
    [next[i], next[j]] = [next[j], next[i]];
    change(next);
    setOpenRules((rules) => new Set([...rules].map((k) => (k === i ? j : k === j ? i : k))));
  }
  return { openRules, toggleRule, addRule, removeRule, move };
}

// A collapsed rule hides its invalid field; open it so the browser can point at the field.
function openInvalidRule(event: React.FormEvent<HTMLFormElement>) {
  for (
    let rule = (event.target as HTMLElement).closest("details");
    rule;
    rule = rule.parentElement?.closest("details") ?? null
  )
    rule.open = true;
}

function AllocationEditor({ plan }: { plan: PlanData }) {
  const draft = useAllocationDraft(plan);
  const { items, latest, dirty, saving, accounts, edit } = draft;
  const { openRules, toggleRule, addRule, removeRule, move } = useRuleList(items, draft.change);
  const review = useRef<HTMLElement>(null);
  const simulation = usePlanStore((s) => s.simulation);
  // The review renders at the top of the editor, far above the Review and Save buttons: bring it to the user.
  useEffect(() => {
    if (!latest) return;
    review.current?.scrollIntoView?.({ block: "start" });
    review.current?.focus({ preventScroll: true });
  }, [latest]);
  const { surplusOrder, ruleNumber, ruleName } = ruleNumbering(items);
  const surplusItems = items.filter(isSurplus);
  const percentTotal = surplusItems.reduce(
    (sum, p) => sum + (p.allocation_mode === "percentage" ? (p.allocation_value ?? 0) : 0),
    0,
  );
  const firstYear = simulation?.yearly_snapshots[0];
  // Funding notes describe the saved rules, so they wait until the draft is saved.
  const savedYear = dirty ? undefined : firstYear;
  // "Earlier rules used all the surplus" is said once, on the first rule it starved.
  const firstStarved = firstYear?.cash_flow?.contributions.find(
    (flow) =>
      flow.source === "priority" &&
      flow.amount === 0 &&
      flow.funding_reasons?.includes("earlier_rules"),
  )?.priority_rank;
  const maxable = maxableAccounts(accounts, items, plan.income_streams);
  function maxWorkplacePlan(account: Account) {
    addRule({
      priority_rank: items.length + 1,
      priority_type: "pre_tax_contribution",
      target_account_id: account.id,
      source_income_id: maxFundingIncome(account, plan.income_streams)!.id,
      allocation_mode: "remaining",
      allocation_value: null,
      max_annual_amount: null,
    });
  }
  // Roth conversions and gain harvests are US tax tools: hidden for new rules
  // when no year of the plan is a US year, noted when the plan moves abroad.
  const coverage = usCoverage(plan);
  const controls = (p: CashFlowPriorityCreate, i: number) => (
    <RuleControls
      rule={p}
      edit={(update) => edit(i, update)}
      accounts={accounts}
      plan={plan}
      name={ruleName(i)}
      moveUp={neighbor(items, i, -1) < 0 ? undefined : () => move(i, -1)}
      moveDown={neighbor(items, i, 1) < 0 ? undefined : () => move(i, 1)}
      remove={() => removeRule(i)}
    />
  );
  return (
    <form
      className="allocation-editor"
      data-unsaved-changes={dirty || undefined}
      data-save-pending={saving || undefined}
      onInvalidCapture={openInvalidRule}
      onSubmit={(e) => {
        e.preventDefault();
        void draft.save();
      }}
    >
      {draft.recovered && <p role="status">Unsaved draft recovered.</p>}
      {draft.storageError && (
        <p role="alert">
          This browser could not preserve the draft. Keep this tab open until you save.
        </p>
      )}
      {latest && (
        <ConflictReview
          latest={latest}
          items={items}
          accounts={accounts}
          incomes={plan.income_streams}
          focusRef={review}
          reconcile={draft.reconcile}
        />
      )}
      <fieldset disabled={!draft.accountsReady || saving}>
        <h3>After spending</h3>
        {!surplusItems.length && <p className="allocation-empty">No allocation rules.</p>}
        {percentTotal > 100 && (
          <p role="status" className="allocation-notice">
            Percentages total {percentTotal}%. Earlier rules are funded first; later rules may
            receive less than requested.
          </p>
        )}
        {surplusOrder.map((i) => (
          <SurplusRule
            key={i}
            rule={items[i]}
            index={i}
            number={ruleNumber(i)}
            open={openRules.has(i)}
            onToggle={(open) => toggleRule(i, open)}
            accounts={accounts}
            plan={plan}
            edit={(update) => edit(i, update)}
            controls={controls(items[i], i)}
            firstYear={savedYear}
            firstStarved={firstStarved}
          />
        ))}
        <button
          type="button"
          onClick={() =>
            addRule({
              priority_rank: items.length + 1,
              priority_type: "contribution",
              target_account_id: null,
              allocation_mode: "remaining",
              allocation_value: null,
            })
          }
        >
          Add allocation
        </button>
        {(plan.liabilities ?? []).length > 0 && (
          <button
            type="button"
            onClick={() =>
              addRule({
                priority_rank: items.length + 1,
                priority_type: "debt_payment",
                target_account_id: null,
                target_liability_id: null,
                allocation_mode: "remaining",
                allocation_value: null,
              })
            }
          >
            Add debt payment
          </button>
        )}
        <LeftoverNotice accounts={accounts} firstYear={firstYear} dirty={dirty} />
        {maxable.length > 0 && (
          <div className="allocation-actions">
            {maxable.map((a) => (
              <button type="button" key={a.id} onClick={() => maxWorkplacePlan(a)}>
                Max {employerPlanFamily(a.account_type)} · {a.name}
              </button>
            ))}
          </div>
        )}
        <details className="allocation-other" open={items.some((p) => !isSurplus(p)) || undefined}>
          <summary>Payroll contributions and account transfers</summary>
          <p className="allocation-help">Blank maximum fills remaining contribution room.</p>
          {items.map(
            (p, i) =>
              !isSurplus(p) && (
                <OtherRule
                  key={i}
                  rule={p}
                  number={ruleNumber(i)}
                  open={openRules.has(i)}
                  onToggle={(open) => toggleRule(i, open)}
                  accounts={accounts}
                  plan={plan}
                  coverage={coverage}
                  edit={(update) => edit(i, update)}
                  controls={controls(p, i)}
                  firstYear={savedYear}
                />
              ),
          )}
          <button
            type="button"
            onClick={() =>
              addRule({
                priority_rank: items.length + 1,
                priority_type: "income_percent",
                target_account_id: null,
              })
            }
          >
            Add payroll or transfer rule
          </button>
        </details>
        <SaveFooter planId={plan.id} simulation={simulation} draft={draft} />
      </fieldset>
      {!draft.accountsReady && (
        <button type="button" onClick={draft.retryAccounts} data-sample-view>
          Retry loading accounts
        </button>
      )}
    </form>
  );
}

/** Where the surplus no rule takes goes, and how much went there in the projection's first year. */
function LeftoverNotice({
  accounts,
  firstYear,
  dirty,
}: {
  accounts: Account[];
  firstYear?: YearSnapshot;
  dirty: boolean;
}) {
  const defaultFlow = firstYear?.cash_flow?.contributions.find((c) => c.source === "default_sink");
  const fallback = ["checking", "savings", "taxable_brokerage"].flatMap((type) =>
    accounts.filter((a) => a.account_type === type),
  )[0];
  return (
    <p className="allocation-notice">
      Leftover goes to{" "}
      <strong>{defaultFlow?.account_name ?? fallback?.name ?? "Unallocated cash"}</strong>
      {defaultFlow && !dirty ? ` · ${fullCurrency(defaultFlow.amount)} in ${firstYear?.year}` : ""}
    </p>
  );
}

/** The save outcome and the save, retry and review actions at the foot of the editor. */
function SaveFooter({
  planId,
  simulation,
  draft,
}: {
  planId: string;
  simulation: SimulationResult | null;
  draft: ReturnType<typeof useAllocationDraft>;
}) {
  const { error, saved, saving, dirty, latest } = draft;
  const feedback = useRef<HTMLParagraphElement>(null);
  const isSimulating = usePlanStore((s) => s.isSimulating);
  useEffect(() => {
    if (error) feedback.current?.focus();
  }, [error]);
  return (
    <>
      {error && (
        <p ref={feedback} tabIndex={-1} role="alert" className="allocation-feedback">
          {error}
        </p>
      )}
      {saved && (
        <p role="status" className="allocation-feedback">
          Allocation saved.
          {isSimulating
            ? " Recalculating projection…"
            : simulation
              ? " Projection updated."
              : " The projection could not refresh. Try recalculating again."}
        </p>
      )}
      <button type="submit" disabled={!dirty || !!latest}>
        {saving ? "Saving…" : "Save allocation"}
      </button>
      {saved && !simulation && !isSimulating && (
        <button
          type="button"
          onClick={() => void usePlanStore.getState().runSimulation(planId)}
          data-sample-view
        >
          Retry projection
        </button>
      )}
      {dirty && (
        <button type="button" onClick={() => void draft.reviewLatest()}>
          Review latest saved rules
        </button>
      )}
      {dirty && <p className="allocation-help">Unsaved changes.</p>}
    </>
  );
}
