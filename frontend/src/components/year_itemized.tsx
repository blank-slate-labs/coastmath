import type { ReactNode } from "react";

import { LedgerRow } from "@/components/year_ledger";
import type { NamedAmount, YearSnapshot } from "@/types/plan";
import { fullCurrency } from "@/utils/format";
import { countryName, isIntlYear } from "@/domain/intl_plan";
import { ownerLabel } from "@/domain/person_labels";

// ---------------------------------------------------------------------------
// One year's cash flow, item by item, under the diagram. Every amount is the
// service's, nominal like the diagram. The only derived figure is the tax
// remainder ("other settlements"), shown as its own row so the tax column
// visibly adds up. Ported from the iOS year detail (`YearTotals`).
// ---------------------------------------------------------------------------

/** Amounts under half a dollar round to $0: they are hidden, and show no direction. */
export const VISIBLE_THRESHOLD = 0.5;

const isVisible = (value: number): boolean => Math.abs(value) >= VISIBLE_THRESHOLD;

/** The requested amount, when it differs from what was funded by a visible amount. */
export function requestedGap(row: NamedAmount): number | null {
  const requested = row.requested_amount;
  return requested != null && isVisible(requested - row.amount) ? requested : null;
}

export interface TaxSettlement {
  total: number;
  withheld: number;
  /** Settled at filing: positive is a payment, negative a refund (the service's `tax_delta`, negated). */
  paidAtFiling: number;
  /**
   * Total tax − (withheld + paid at filing): estimated or earlier payments,
   * premium credit reconciliation and penalty adjustments the service folds
   * into the year's tax or its filing settlement.
   */
  otherSettlements: number;
  showsOtherSettlements: boolean;
  equation: string;
}

export function taxSettlement(snapshot: YearSnapshot): TaxSettlement | null {
  const flow = snapshot.cash_flow;
  if (!flow) return null;
  const withheld = flow.tax_withheld ?? 0;
  const paidAtFiling = -(flow.tax_delta ?? 0);
  const otherSettlements = snapshot.taxes - withheld - paidAtFiling;
  const showsOtherSettlements = isVisible(otherSettlements);
  return {
    total: snapshot.taxes,
    withheld,
    paidAtFiling,
    otherSettlements,
    showsOtherSettlements,
    equation: showsOtherSettlements
      ? "Total tax = withheld + paid at filing + other settlements"
      : "Total tax = withheld + paid at filing",
  };
}

/** A part of the tax column with its sign, so the column reads as a sum. */
const signedMoney = (value: number): string =>
  !isVisible(value)
    ? fullCurrency(0)
    : value < 0
      ? `−${fullCurrency(-value)}`
      : fullCurrency(value);

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="ledger-rows itemized-group" role="group" aria-label={title}>
      <h4 className="ledger-group-title">{title}</h4>
      {children}
    </div>
  );
}

function ItemRows({ rows, empty }: { rows: NamedAmount[]; empty: string }) {
  // A row that rounds to $0 says nothing, unless something was requested for it.
  const shown = rows.filter((row) => isVisible(row.amount) || requestedGap(row) !== null);
  if (shown.length === 0) return <p className="ledger-empty">{empty}</p>;
  return (
    <>
      {shown.map((row, index) => {
        const requested = requestedGap(row);
        return (
          <LedgerRow
            key={`${row.account_id ?? row.name}-${row.source ?? ""}-${index}`}
            label={
              requested === null ? (
                row.name
              ) : (
                <span className="ledger-label-stack">
                  <span>{row.name}</span>
                  <span className="ledger-note">Requested {fullCurrency(requested)}</span>
                </span>
              )
            }
            value={fullCurrency(row.amount)}
          />
        );
      })}
    </>
  );
}

/** Collapsed by default; nothing renders for a year without item-level cash flow. */
export default function YearItemized({ snapshot }: { snapshot: YearSnapshot | null }) {
  const flow = snapshot?.cash_flow;
  const tax = snapshot ? taxSettlement(snapshot) : null;
  if (!snapshot || !flow || !tax) return null;
  const transfers = (flow.transfers ?? []).filter((transfer) => isVisible(transfer.amount));

  return (
    <details className="itemized">
      <summary>Itemized</summary>
      <div
        className="itemized-groups"
        role="group"
        aria-label={`Itemized cash flow, ${snapshot.year}`}
      >
        <Group title="Income received">
          <ItemRows rows={flow.income_sources ?? []} empty="None this year." />
        </Group>
        <Group title="Spending">
          <ItemRows rows={flow.expenses ?? []} empty="None this year." />
        </Group>
        <Group title="Account withdrawals">
          <ItemRows
            rows={flow.drawdowns ?? []}
            empty="None. Required distributions count as income."
          />
        </Group>
        <Group title="Contributions">
          <ItemRows rows={flow.contributions ?? []} empty="None this year." />
        </Group>
        {transfers.length > 0 && (
          <Group title="Transfers">
            {transfers.map((transfer, index) => (
              <LedgerRow
                key={`${transfer.source_account_id}-${transfer.target_account_id}-${index}`}
                label={`${transfer.source_account_name ?? "Source account"} → ${transfer.target_account_name ?? "Destination account"}`}
                value={fullCurrency(transfer.amount)}
              />
            ))}
          </Group>
        )}
        <Group title="Tax">
          <LedgerRow label="Total tax" value={fullCurrency(tax.total)} />
          <LedgerRow label="Withheld" value={fullCurrency(tax.withheld)} />
          <LedgerRow
            label={tax.paidAtFiling <= -VISIBLE_THRESHOLD ? "Refund at filing" : "Paid at filing"}
            value={signedMoney(tax.paidAtFiling)}
            tone={tax.paidAtFiling <= -VISIBLE_THRESHOLD ? "positive" : undefined}
          />
          {tax.showsOtherSettlements && (
            <LedgerRow
              label="Other tax settlements"
              value={signedMoney(tax.otherSettlements)}
              tone={tax.otherSettlements < 0 ? "positive" : undefined}
            />
          )}
          <p className="ledger-note itemized-equation">{tax.equation}</p>
        </Group>
        {isIntlYear(snapshot.tax_country) && (
          <Group title={`${countryName(snapshot.tax_country)} tax lines`}>
            {(snapshot.intl_tax_lines ?? [])
              .filter((line) => isVisible(line.amount))
              .map((line, index) => (
                <LedgerRow
                  key={`${line.code}-${line.person ?? "household"}-${index}`}
                  label={
                    line.person === "self" || line.person === "spouse"
                      ? `${line.label} (${ownerLabel(line.person)})`
                      : line.label
                  }
                  value={signedMoney(line.amount)}
                  tone={line.amount < 0 ? "positive" : undefined}
                />
              ))}
            {!(snapshot.intl_tax_lines ?? []).some((line) => isVisible(line.amount)) && (
              <p className="ledger-empty">No tax this year.</p>
            )}
          </Group>
        )}
      </div>
    </details>
  );
}
