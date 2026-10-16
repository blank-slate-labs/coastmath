import { LedgerRow } from "@/components/year_ledger";
import type { YearSnapshot } from "@/types/plan";
import { fullCurrency } from "@/utils/format";

export const fundingReasons = {
  insufficient_surplus: "No surplus remained after taxes, payroll and spending.",
  earlier_rules: "Earlier allocation rules used all available surplus.",
  ownership: "The destination’s ownership or inherited status prevents contributions.",
  income_eligibility: "Modeled income is above the Roth IRA eligibility range.",
  compensation: "No eligible compensation remains for this person’s contributions.",
  contribution_limit:
    "The modeled contribution limit has been reached, including shared accounts and year-to-date funding.",
  annual_maximum: "This rule’s annual maximum is zero.",
  target_balance: "The account has reached this rule’s balance target.",
  zero_request: "This rule requests no funding for this year.",
  inactive_rule: "This rule is outside its milestone window.",
  loan_paid_off: "The loan is already paid off.",
  withdrawal_shortfall:
    "This withdraw-if-short rule could not be fully funded: the surplus and the accounts it may draw from ran short.",
};

/**
 * Side ledger for the cash-flow diagram. In a surplus year it lists where the
 * allocation rules sent the money (and why a rule got nothing); in a deficit
 * year it lists which accounts covered the gap.
 */
export default function SurplusAllocationSummary({
  snapshot,
  onEdit,
  jointFiling = false,
  factor = 1,
}: {
  snapshot?: YearSnapshot;
  onEdit: (rank?: number) => void;
  jointFiling?: boolean;
  factor?: number;
}) {
  const flows =
    snapshot?.cash_flow?.contributions.filter(
      (c) => c.source === "priority" || c.source === "default_sink",
    ) ?? [];
  // Rules are numbered in the order they ran, as the editor numbers its after-spending list.
  const ruleRanks = flows.filter((c) => c.source === "priority").map((c) => c.priority_rank);
  const shownNumber = (rank: number | null | undefined) => ruleRanks.indexOf(rank) + 1;
  // "Earlier rules used all the surplus" is said once, on the first rule it starved.
  const firstStarved = flows.find(
    (c) => c.amount === 0 && c.funding_reasons?.includes("earlier_rules"),
  )?.priority_rank;
  const drawdowns = snapshot?.cash_flow?.drawdowns ?? [];
  const deficit = !!snapshot && snapshot.net_cash_flow < 0;

  return (
    <section
      className="ledger ledger-section allocation-summary"
      aria-label="Where your surplus goes"
    >
      <div className="ledger-section-head">
        <h3>{deficit ? "Funded from accounts" : "Surplus allocation"}</h3>
        <button type="button" className="link-button" onClick={() => onEdit()}>
          Edit income allocation
        </button>
      </div>

      {deficit ? (
        drawdowns.length ? (
          <div className="ledger-rows">
            {drawdowns.map((flow, i) => (
              <LedgerRow
                key={`${flow.account_id ?? flow.name}-${i}`}
                label={flow.account_name ?? flow.name}
                value={fullCurrency(flow.amount / factor)}
              />
            ))}
          </div>
        ) : (
          <p className="ledger-empty">
            No surplus in {snapshot?.year}. Withdrawals are not itemized for this year.
          </p>
        )
      ) : flows.length ? (
        <div className="ledger-rows">
          {flows.map((flow, i) => (
            <div
              key={`${flow.account_id}-${flow.priority_rank}-${i}`}
              className={`ledger-row is-rule${flow.amount === 0 ? " is-skipped" : ""}`}
            >
              <span className="ledger-label">
                <span
                  className="ledger-rank"
                  aria-label={
                    flow.source === "default_sink"
                      ? "Leftover"
                      : `Rule ${shownNumber(flow.priority_rank)}`
                  }
                >
                  {flow.source === "default_sink" ? "·" : shownNumber(flow.priority_rank)}
                </span>
                <span className="ledger-label-stack">
                  <span>{flow.account_name ?? flow.name}</span>
                  {flow.limited_by?.length ? (
                    <span className="ledger-note">Limited by {flow.limited_by.join(", ")}</span>
                  ) : null}
                  {(flow.amount === 0 || flow.funding_reasons?.includes("withdrawal_shortfall")) &&
                    (flow.priority_rank === firstStarved ||
                      !flow.funding_reasons?.every((reason) => reason === "earlier_rules")) && (
                      <span className="ledger-note">
                        {flow.funding_reasons?.length
                          ? flow.funding_reasons
                              .filter(
                                (reason) =>
                                  reason !== "earlier_rules" || flow.priority_rank === firstStarved,
                              )
                              .map((reason) =>
                                reason === "compensation" && jointFiling
                                  ? "No eligible compensation remains; IRA contributions on a joint return can use household compensation."
                                  : fundingReasons[reason],
                              )
                              .join(" ")
                          : "No funding explanation is available for this saved result. Recalculate to refresh it."}
                        {flow.priority_rank != null && (
                          <>
                            {" "}
                            <button
                              type="button"
                              className="link-button"
                              onClick={() => onEdit(flow.priority_rank ?? undefined)}
                            >
                              Review rule {shownNumber(flow.priority_rank)}
                            </button>
                          </>
                        )}
                      </span>
                    )}
                </span>
              </span>
              <span className={`ledger-value${flow.amount === 0 ? " is-muted" : ""}`}>
                {fullCurrency(flow.amount / factor)}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="ledger-empty">
          {snapshot && snapshot.net_cash_flow > 0
            ? "Add allocation rules to direct this surplus."
            : snapshot
              ? `No surplus in ${snapshot.year}. Rules apply in years with excess income.`
              : "Choose destinations in your plan’s income allocation section."}
        </p>
      )}
    </section>
  );
}
