import { moneyLabel } from "@/utils/format";
import type { Account, CashFlowPriorityCreate, PlanData } from "@/types/plan";
import { ELECTIVE_DEFERRAL_TYPES, EMPLOYER_ONLY_PLAN_TYPES } from "@/domain/account_types";
import { ownerSuffix } from "@/domain/person_labels";
import { ContributionLimitFields } from "@/components/employer_match_fields";
import MoneyInput from "@/components/money_input";
import {
  canWithdrawIfShort,
  isAfterTax,
  isDebt,
  isPayroll,
  isSurplus,
  payrollTargets,
  takesCustomLimit,
  workplaceTypes,
} from "./rules";

type Edit = (update: Partial<CashFlowPriorityCreate>) => void;

interface FieldProps {
  rule: CashFlowPriorityCreate;
  edit: Edit;
}

export interface RuleControlsProps extends FieldProps {
  accounts: Account[];
  plan: PlanData;
  /** The rule's shown name, "Rule 2" or "Payroll or transfer rule 1", for the action labels. */
  name: string;
  /** Absent at the edge of the rule's move group. */
  moveUp?: () => void;
  moveDown?: () => void;
  remove: () => void;
}

/** The fields every rule shares, below any type-specific ones, and the rule's move and remove actions. */
export default function RuleControls({
  rule: p,
  edit,
  accounts,
  plan,
  name,
  moveUp,
  moveDown,
  remove,
}: RuleControlsProps) {
  const surplus = isSurplus(p);
  const debt = isDebt(p);
  const target = accounts.find((a) => a.id === p.target_account_id);
  return (
    <div className="allocation-fields">
      <TargetField rule={p} edit={edit} accounts={accounts} plan={plan} />
      {surplus && <SurplusAmountFields rule={p} edit={edit} />}
      <FundingFields rule={p} edit={edit} />
      {takesCustomLimit(p) && <ContributionLimitFields rule={p} edit={edit} />}
      <label>
        {moneyLabel("Annual maximum ($; optional)")}
        <MoneyInput
          min={0}
          step="0.01"
          value={p.max_annual_amount ?? ""}
          onValueChange={(amount) =>
            edit({ max_annual_amount: amount === "" ? null : Number(amount) })
          }
        />
      </label>
      {debt && (
        <p className="allocation-help">
          Pays the loan down from surplus after the scheduled payment, up to its remaining balance.
          The scheduled payment and interest are unchanged; later years see the lower balance.
        </p>
      )}
      {surplus && !debt && (
        <label>
          {moneyLabel("Stop at account balance ($; optional)")}
          <MoneyInput
            min={0}
            step="0.01"
            value={p.target_balance ?? ""}
            onValueChange={(amount) =>
              edit({ target_balance: amount === "" ? null : Number(amount) })
            }
          />
        </label>
      )}
      <MilestoneFields rule={p} edit={edit} plan={plan} />
      <DestinationNotes rule={p} edit={edit} target={target} />
      <div className="allocation-actions">
        <button
          type="button"
          disabled={!moveUp}
          aria-label={`Move ${name.toLowerCase()} up`}
          onClick={moveUp}
        >
          Move up
        </button>
        <button
          type="button"
          disabled={!moveDown}
          aria-label={`Move ${name.toLowerCase()} down`}
          onClick={moveDown}
        >
          Move down
        </button>
        <button type="button" onClick={remove}>
          Remove rule
        </button>
      </div>
    </div>
  );
}

/** The loan a debt payment pays down, or the account any other rule funds. */
function TargetField({
  rule: p,
  edit,
  accounts,
  plan,
}: FieldProps & { accounts: Account[]; plan: PlanData }) {
  const surplus = isSurplus(p);
  if (isDebt(p))
    return (
      <label>
        Loan to pay down
        <select
          required
          value={p.target_liability_id ?? ""}
          onChange={(e) => edit({ target_liability_id: e.target.value || null })}
        >
          <option value="">Choose loan</option>
          {(plan.liabilities ?? []).map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
      </label>
    );
  return (
    <label>
      Destination account
      <select
        required={p.priority_type !== "gain_harvest"}
        value={p.target_account_id ?? ""}
        onChange={(e) => edit({ target_account_id: e.target.value })}
      >
        <option value="">Choose account</option>
        {accounts.map((a) => (
          <option
            key={a.id}
            value={a.id}
            disabled={
              (surplus && workplaceTypes.includes(a.account_type)) ||
              (isPayroll(p) && !payrollTargets(p).includes(a.account_type))
            }
          >
            {a.name}
            {ownerSuffix(a.owner, plan.spouse != null)}
            {surplus && workplaceTypes.includes(a.account_type) ? " — use payroll" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

/** How much of the surplus a surplus rule takes. */
function SurplusAmountFields({ rule: p, edit }: FieldProps) {
  const mode = p.allocation_mode ?? "remaining";
  return (
    <>
      <label>
        Allocate
        <select
          value={mode}
          onChange={(e) =>
            edit({
              allocation_mode: e.target.value as typeof mode,
              allocation_value: e.target.value === "remaining" ? null : 0,
            })
          }
        >
          <option value="percentage">Percentage of surplus</option>
          <option value="amount">Cash amount per year</option>
          <option value="remaining">Remaining surplus</option>
        </select>
      </label>
      {mode !== "remaining" && (
        <label>
          {mode === "percentage" ? "Surplus percentage (%)" : moneyLabel("Annual allocation ($)")}
          {mode === "percentage" ? (
            <input
              type="number"
              required
              min={0}
              max={100}
              step="0.01"
              value={p.allocation_value ?? ""}
              onChange={(e) =>
                edit({
                  allocation_value: e.target.value === "" ? null : Number(e.target.value),
                })
              }
            />
          ) : (
            <MoneyInput
              required
              min={0}
              step="0.01"
              value={p.allocation_value ?? ""}
              onValueChange={(amount) =>
                edit({ allocation_value: amount === "" ? null : Number(amount) })
              }
            />
          )}
        </label>
      )}
      <p className="allocation-help">
        {mode === "percentage"
          ? "Percent of surplus before allocation."
          : mode === "amount"
            ? `Prorated for a partial first year; ${p.withdraw_if_short ? "drawn from your withdrawal order when surplus is short." : "limited by available surplus."}`
            : p.withdraw_if_short
              ? "Fills the rule’s tightest limit (annual maximum, contribution limit, balance target or loan balance); without one, remaining surplus only."
              : "Remaining surplus, subject to limits."}
      </p>
    </>
  );
}

/** Whether a rule is funded only from income or withdraws when the surplus is short, and what a short year does to it. */
function FundingFields({ rule: p, edit }: FieldProps) {
  return (
    <>
      {canWithdrawIfShort(p) && (
        <label className="allocation-check">
          <input
            type="checkbox"
            checked={p.withdraw_if_short ?? false}
            onChange={(e) =>
              edit(
                e.target.checked
                  ? { withdraw_if_short: true, reduce_employer_contribution: false }
                  : { withdraw_if_short: false },
              )
            }
          />{" "}
          Withdraw if surplus is short
        </label>
      )}
      {canWithdrawIfShort(p) && p.withdraw_if_short && (
        <p className="allocation-help">
          {isSurplus(p)
            ? "Runs before other rules after spending. If surplus is short, the rest is withdrawn in your withdrawal order (never from this account or one sharing its contribution limit), and the tax it causes is paid the same year. Spending is funded first; limits still apply."
            : "Payroll deferrals come out of pay before spending, so a shortfall in spending is withdrawn from your accounts. Pay and contribution limits still apply."}
        </p>
      )}
      {p.priority_type === "income_percent" && !p.withdraw_if_short && !p.employer_match && (
        <label className="allocation-check">
          <input
            type="checkbox"
            checked={p.reduce_employer_contribution ?? false}
            onChange={(e) => edit({ reduce_employer_contribution: e.target.checked })}
          />{" "}
          Prorate employer contribution if the deferral is cut
        </label>
      )}
    </>
  );
}

function MilestoneFields({ rule: p, edit, plan }: FieldProps & { plan: PlanData }) {
  const milestones = plan.milestones ?? [];
  return (
    <>
      <label>
        Start milestone
        <select
          value={p.start_milestone_id ?? ""}
          onChange={(e) => edit({ start_milestone_id: e.target.value || null })}
        >
          <option value="">Plan start</option>
          {milestones.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        End milestone
        <select
          value={p.end_milestone_id ?? ""}
          onChange={(e) => edit({ end_milestone_id: e.target.value || null })}
        >
          <option value="">End of plan</option>
          {milestones.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}

/** The destination account's own rules: IRA eligibility, HSA coverage, catch-up and 401(a) limits. */
function DestinationNotes({ rule: p, edit, target }: FieldProps & { target?: Account }) {
  return (
    <>
      {isSurplus(p) && target?.account_type === "roth_ira" && (
        <label className="allocation-check">
          <input
            type="checkbox"
            checked={p.backdoor_roth ?? false}
            onChange={(e) => edit({ backdoor_roth: e.target.checked })}
          />{" "}
          Backdoor Roth
        </label>
      )}
      {target?.account_type === "roth_ira" && (
        <p className="allocation-help">
          {p.backdoor_roth
            ? "IRA limits and pro-rata taxation apply."
            : "Income eligibility and shared IRA limits apply."}
        </p>
      )}
      {target?.account_type === "traditional_ira" && (
        <p className="allocation-help">
          Deductible, but phased out by income when the owner or their spouse contributes to a
          workplace plan. Nondeductible basis is not tracked.
        </p>
      )}
      {target?.account_type === "hsa" && (
        <p className="allocation-help">
          Limit assumes full-year individual coverage. Set a lower maximum for other situations.
        </p>
      )}
      {ELECTIVE_DEFERRAL_TYPES.has(target?.account_type ?? "") && !isAfterTax(p) && (
        <p className="allocation-help">
          Opening-year catch-up requires a Roth destination; later years use projected prior wages.
        </p>
      )}
      {EMPLOYER_ONLY_PLAN_TYPES.has(target?.account_type ?? "") && (
        <p className="allocation-help">
          A 401(a) takes employer contributions only: set the employer rate.
        </p>
      )}
      {isAfterTax(p) && (
        <p className="allocation-help">Fills the 415(c) room left by the rules above.</p>
      )}
    </>
  );
}
