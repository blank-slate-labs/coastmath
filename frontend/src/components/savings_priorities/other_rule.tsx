import type { ReactNode } from "react";
import type { Account, CashFlowPriorityCreate, PlanData, YearSnapshot } from "@/types/plan";
import type { UsCoverage } from "@/domain/intl_plan";
import { STALE_RATE_NOTE, isStaleConversionCeiling } from "@/domain/federal_bracket_rates";
import { fundingReasons } from "@/components/surplus_allocation_summary";
import { EmployerMatchFields } from "@/components/employer_match_fields";
import UsOnlyNote from "@/components/intl/us_only_note";
import {
  canWithdrawIfShort,
  fillsUsBracket,
  isAfterTax,
  isPayroll,
  payrollIncomes,
  takesCustomLimit,
  usBracketRuleName,
} from "./rules";

type Edit = (update: Partial<CashFlowPriorityCreate>) => void;

/** A payroll contribution, account transfer, Roth conversion or gain harvest rule. */
export default function OtherRule({
  rule: p,
  number,
  open,
  onToggle,
  accounts,
  plan,
  coverage,
  edit,
  controls,
  firstYear,
}: {
  rule: CashFlowPriorityCreate;
  number: number;
  open: boolean;
  onToggle: (open: boolean) => void;
  accounts: Account[];
  plan: PlanData;
  coverage: UsCoverage;
  edit: Edit;
  controls: ReactNode;
  /** The projection's first year; absent while the draft has unsaved changes. */
  firstYear?: YearSnapshot;
}) {
  const incomes = payrollIncomes(p, accounts, plan.income_streams);
  return (
    <details
      className="allocation-rule"
      open={open}
      onToggle={(e) => onToggle(e.currentTarget.open)}
    >
      <summary>
        {number}. {accounts.find((a) => a.id === p.target_account_id)?.name ?? "Choose account"} ·{" "}
        {isAfterTax(p)
          ? "mega backdoor Roth"
          : (p.priority_type ?? "contribution").replace(/_/g, " ")}
        {p.priority_type === "roth_conversion" &&
          p.conversion_mode === "fill_bracket" &&
          !p.use_plan_tax_target &&
          p.bracket_ceiling_rate != null &&
          ` · fill to ${Math.round(p.bracket_ceiling_rate * 100)}%${isStaleConversionCeiling(p, plan.tax_settings) ? ` ${STALE_RATE_NOTE}` : ""}`}
      </summary>
      {isAfterTax(p) &&
        firstYear?.cash_flow?.contributions
          .filter(
            (flow) =>
              flow.source === "payroll" &&
              flow.priority_rank === p.priority_rank &&
              flow.amount === 0,
          )
          .map((flow, j) => (
            <p key={j} className="allocation-notice">
              {flow.funding_reasons?.map((reason) => fundingReasons[reason]).join(" ")}
            </p>
          ))}
      <RuleTypeField rule={p} edit={edit} coverage={coverage} />
      {isPayroll(p) && (
        <>
          <label>
            Source income
            <select
              required
              value={p.source_income_id ?? ""}
              onChange={(e) => edit({ source_income_id: e.target.value })}
            >
              <option value="">Choose income</option>
              {incomes.map((income) => (
                <option key={income.id} value={income.id}>
                  {income.name}
                </option>
              ))}
            </select>
          </label>
          <p className="allocation-help">
            Only earned income for the destination account’s owner can fund payroll contributions.
            {!incomes.length && " Add an earned income stream for this person in Income streams."}
          </p>
        </>
      )}
      {p.priority_type === "income_percent" && (
        <>
          <label>
            Employee contribution (%)
            <input
              type="number"
              required
              min={0}
              max={100}
              step="0.01"
              value={p.employee_rate ?? 0}
              onChange={(e) => edit({ employee_rate: Number(e.target.value) })}
            />
          </label>
          <EmployerMatchFields
            rule={p}
            target={accounts.find((a) => a.id === p.target_account_id)}
            edit={edit}
          />
        </>
      )}
      {coverage === "non_us" && fillsUsBracket(p) && (
        <p className="allocation-notice">
          {usBracketRuleName(p).replace(/^./, (c) => c.toUpperCase())} doesn&apos;t apply in a plan
          taxed outside the US in every year, and the projection won&apos;t run with it. Remove the
          rule or add a US residency period.
        </p>
      )}
      {["roth_conversion", "gain_harvest"].includes(p.priority_type ?? "") && (
        <UsOnlyNote coverage={coverage} what="Bracket-filling Roth conversions and gain harvests" />
      )}
      {["transfer", "roth_conversion"].includes(p.priority_type ?? "") && (
        <label>
          Source account
          <select
            required
            value={p.source_account_id ?? ""}
            onChange={(e) => edit({ source_account_id: e.target.value })}
          >
            <option value="">Choose account</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {p.priority_type === "transfer" && <TransferTimingField rule={p} edit={edit} />}
      {controls}
    </details>
  );
}

/** The rule's type; changing it clears the fields the new type does not take. */
function RuleTypeField({
  rule: p,
  edit,
  coverage,
}: {
  rule: CashFlowPriorityCreate;
  edit: Edit;
  coverage: UsCoverage;
}) {
  return (
    <label>
      Priority type
      <select
        value={p.priority_type ?? "contribution"}
        onChange={(e) =>
          edit({
            priority_type: e.target.value,
            allocation_mode: "remaining",
            allocation_value: null,
            // A formula belongs to percent-of-pay rules and a plan limit to contribution rules.
            ...(e.target.value !== "income_percent" && p.employer_match
              ? { employer_match: null }
              : {}),
            ...(!takesCustomLimit({ ...p, priority_type: e.target.value }) &&
            p.limit_mode === "custom"
              ? { limit_mode: "irs" as const, custom_annual_limit: null }
              : {}),
            // Transfers and conversions are funded from their source account.
            ...(p.withdraw_if_short && !canWithdrawIfShort({ ...p, priority_type: e.target.value })
              ? { withdraw_if_short: false }
              : {}),
            ...(p.reduce_employer_contribution && e.target.value !== "income_percent"
              ? { reduce_employer_contribution: false }
              : {}),
            ...(p.transfer_frequency === "monthly" && e.target.value !== "transfer"
              ? { transfer_frequency: "annual" as const }
              : {}),
          })
        }
      >
        <option value="income_percent">Payroll percent of income</option>
        <option value="pre_tax_contribution">Payroll annual amount / remaining room</option>
        <option value="after_tax_401k">Mega backdoor Roth</option>
        <option value="transfer">Account transfer</option>
        {(coverage !== "non_us" || p.priority_type === "roth_conversion") && (
          <option value="roth_conversion">Roth conversion</option>
        )}
        {(coverage !== "non_us" || p.priority_type === "gain_harvest") && (
          <option value="gain_harvest" disabled>
            Gain harvesting (set in Tax tools)
          </option>
        )}
      </select>
    </label>
  );
}

function TransferTimingField({ rule: p, edit }: { rule: CashFlowPriorityCreate; edit: Edit }) {
  return (
    <>
      <label>
        Transfer timing
        <select
          value={p.transfer_frequency ?? "annual"}
          onChange={(e) => edit({ transfer_frequency: e.target.value as "annual" | "monthly" })}
        >
          <option value="annual">Once a year</option>
          <option value="monthly">Monthly</option>
        </select>
      </label>
      <p className="allocation-help">
        {p.transfer_frequency === "monthly"
          ? "Moves 1/12 of the annual maximum at the end of each month the rule is active, counting milestone start and end months, so the money grows in the destination from then on. Without a maximum the whole balance moves in the first active month."
          : "Moves the year's amount once, after the year's growth."}
      </p>
    </>
  );
}
