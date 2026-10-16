import type { ReactNode } from "react";

import type { YearSnapshot } from "@/types/plan";
import type { TimelineEvent } from "@/utils/timeline_events";
import { dollarsOr, fullCurrency, pct } from "@/utils/format";
import { countryName, isIntlYear } from "@/domain/intl_plan";

// Category keys match the Sankey groups so a colour means the same thing in
// the ledger, the cash-flow diagram and the tax chart.
export const LEDGER_KEYS = {
  income: "var(--viz-1)",
  taxes: "var(--viz-2)",
  saving: "var(--viz-3)",
  spending: "var(--viz-4)",
} as const;

type Tone = "positive" | "negative" | "danger" | "muted";

export function LedgerRow({
  label,
  value,
  tone,
  keyColor,
  sub,
  title,
}: {
  label: ReactNode;
  value: ReactNode;
  tone?: Tone;
  keyColor?: string;
  sub?: boolean;
  title?: string;
}) {
  return (
    <div className={`ledger-row${sub ? " is-sub" : ""}`} title={title}>
      <span className="ledger-label">
        {keyColor && (
          <span className="ledger-key" aria-hidden="true" style={{ background: keyColor }} />
        )}
        {label}
      </span>
      <span className={`ledger-value${tone ? ` is-${tone}` : ""}`}>{value}</span>
    </div>
  );
}

export function LedgerDivider() {
  return <div className="ledger-divider" role="presentation" />;
}

const signed = (value: number): string =>
  value > 0 ? `+${fullCurrency(value)}` : fullCurrency(value);
const signTone = (value: number): Tone | undefined =>
  value > 0 ? "positive" : value < 0 ? "negative" : undefined;
const sumValues = (record: Record<string, number>): number =>
  Object.values(record).reduce((sum, v) => sum + v, 0);

function shortDate(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

const TAX_BREAKDOWN = [
  ["Federal income tax", "federal_tax"],
  ["State income tax", "state_tax"],
  ["Local income tax", "local_tax"],
  ["Capital gains tax", "capital_gains_tax"],
  ["FICA", "fica_tax"],
  ["Net investment income tax", "niit_tax"],
  // The AMT owed, which federal income tax already includes.
  ["Alternative minimum tax, in federal", "amt_tax"],
  ["Early withdrawal penalties", "early_withdrawal_penalty"],
  // Years taxed under another country's rules (zero in US years).
  ["National income tax", "national_income_tax"],
  ["Regional income tax", "regional_income_tax"],
  ["Social contributions", "social_contributions"],
  ["Wealth tax", "wealth_tax"],
  ["Transaction tax", "transaction_tax"],
  ["Benefit recovery tax", "benefit_recovery_tax"],
] as const;
export type TaxLineKey = (typeof TAX_BREAKDOWN)[number][1];

/** The tax breakdown lines any year of the projection uses, in breakdown order. */
export function usedTaxLines(snapshots: YearSnapshot[]): TaxLineKey[] {
  return TAX_BREAKDOWN.map(([, key]) => key).filter((key) =>
    snapshots.some((snapshot) => (snapshot[key] ?? 0) !== 0),
  );
}

/** True when the earnings test withholds Social Security in any year of the projection. */
export function usesEarningsTest(snapshots: YearSnapshot[]): boolean {
  return snapshots.some((snapshot) => (snapshot.ss_earnings_test_withheld ?? 0) > 0);
}

export interface YearLedgerProps {
  /** Snapshot in the active currency mode. */
  snapshot: YearSnapshot;
  /** Names keyed by account identity; balances always come from the selected snapshot. */
  accountNames?: Record<string, string>;
  dollarLabel?: string;
  /** Prior year's snapshot in the same currency mode, for change and withdrawal rate. */
  previous: YearSnapshot | null;
  /** Actual balances on the projection start date; used as the first year's baseline. */
  initial?: { net_worth: number; accounts: Record<string, number>; as_of: string } | null;
  /** Divide nominal flow amounts (withdrawals) by this to match the currency mode. */
  factor?: number;
  /** The same deflator for the prior year; `previous` balances were divided by it. */
  previousFactor?: number;
  /** Projection start date when the first year is partial. */
  startDate?: string | null;
  /** Share of the first calendar year the projection covers (1 = full year). */
  yearFraction?: number;
  isFirstYear: boolean;
  events?: TimelineEvent[];
  /** Breakdown lines to list in every year (at $0 where a year has none), so
      the open breakdown keeps its height; see `usedTaxLines`. When omitted,
      only the year's nonzero lines are listed. */
  taxLines?: readonly TaxLineKey[];
  /** List the earnings-test row in every year (at $0 where a year has none);
      see `usesEarningsTest`. When omitted, the row shows only when nonzero. */
  earningsTest?: boolean;
  onStep?: (delta: 1 | -1) => void;
  canStepBack?: boolean;
  canStepForward?: boolean;
  /** True while the pointer is previewing a year that is not pinned. */
  preview?: boolean;
}

export default function YearLedger({
  snapshot,
  accountNames = {},
  dollarLabel = dollarsOr("Future dollars", "Future (nominal) amounts"),
  previous,
  initial = null,
  factor = 1,
  previousFactor = 1,
  startDate = null,
  yearFraction = 1,
  isFirstYear,
  events = [],
  taxLines,
  earningsTest,
  onStep,
  canStepBack = true,
  canStepForward = true,
  preview = false,
}: YearLedgerProps) {
  const liquid = sumValues(snapshot.accounts);
  const baselineNetWorth =
    previous?.net_worth ?? (isFirstYear ? (initial?.net_worth ?? null) : null);
  const change = baselineNetWorth === null ? null : snapshot.net_worth - baselineNetWorth;

  const nominalWithdrawals = (snapshot.cash_flow?.drawdowns ?? []).reduce(
    (sum, flow) => sum + flow.amount,
    0,
  );
  const withdrawals = nominalWithdrawals / factor;
  // The rate compares two nominal amounts. `previous` is already in the
  // display currency (deflated by last year's factor), so undo that before
  // dividing; otherwise the ratio drifts by a year of inflation between modes.
  const openingLiquid = previous
    ? sumValues(previous.accounts) * previousFactor
    : initial
      ? sumValues(initial.accounts)
      : null;
  const withdrawalRate =
    nominalWithdrawals <= 0 ? 0 : openingLiquid ? nominalWithdrawals / openingLiquid : null;

  // No surplus reads as 0%; without income the ratio is undefined.
  const savingsRate =
    snapshot.gross_income > 0 ? Math.max(snapshot.net_cash_flow, 0) / snapshot.gross_income : null;
  const taxBalance = snapshot.tax_balance ?? 0;
  const unfunded = snapshot.unfunded_expenses ?? 0;
  const goalShortfall = (snapshot.rule_funding_shortfall ?? 0) / factor;
  const earningsWithheld = snapshot.ss_earnings_test_withheld ?? 0;
  const eventsByYear = new Map<number, TimelineEvent[]>();
  for (const event of events)
    eventsByYear.set(event.year, [...(eventsByYear.get(event.year) ?? []), event]);

  // A partial first year holds only the months after the start date, so its
  // flows look small next to the annual inputs. Say so, and show the pace.
  const partial = isFirstYear && yearFraction > 0 && yearFraction < 0.995;
  const imputedHistory = isFirstYear && (snapshot.warnings ?? []).includes("ytd_imputed_pro_rata");
  // The partial-year fact, said once: its period and the share of the year it covers.
  const periodMeta = partial
    ? `${startDate ? `${shortDate(startDate)} – Dec 31` : "partial year"} · ${pct(yearFraction, 0)} of year`
    : "Dec 31";
  const paceTitle = `This year covers ${pct(yearFraction, 0)} of ${snapshot.year}; the full-year pace is the amount ÷ ${yearFraction.toFixed(2)}`;

  // Taxes are a full-year liability; in a partial first year they sit with the full-year figures.
  const taxRows = (
    <>
      <LedgerRow label="Taxes" value={fullCurrency(snapshot.taxes)} keyColor={LEDGER_KEYS.taxes} />
      <LedgerRow label="Effective rate" value={pct(snapshot.effective_rate)} sub />
      {partial && snapshot.post_start_taxes != null && (
        <LedgerRow
          label="Taxes after start"
          value={signed(snapshot.post_start_taxes)}
          sub
          title={
            imputedHistory
              ? "Pro-rata estimate; state payroll costs appear with spending."
              : "Full-year taxes less amounts paid before the start."
          }
        />
      )}
      <details className="ledger-tax-details">
        <summary>Tax breakdown</summary>
        {isIntlYear(snapshot.tax_country) && (
          <LedgerRow label="Tax rules" value={countryName(snapshot.tax_country)} sub />
        )}
        {TAX_BREAKDOWN.filter(([, key]) =>
          taxLines ? taxLines.includes(key) : (snapshot[key] ?? 0) !== 0,
        ).map(([label, key]) => (
          <LedgerRow
            key={label}
            label={label}
            value={fullCurrency((snapshot[key] ?? 0) / factor)}
            sub
          />
        ))}
        <LedgerRow label="Marginal rate" value={pct(snapshot.marginal_rate)} sub />
      </details>
    </>
  );

  return (
    <aside
      className={`ledger${preview ? " is-preview" : ""}`}
      aria-live="polite"
      aria-label={`Year ${snapshot.year} details`}
    >
      <div className="ledger-head">
        <div>
          <div className="ledger-year">{snapshot.year}</div>
          <div className="ledger-meta">
            age {snapshot.age} · {periodMeta}
          </div>
        </div>
        {onStep && (
          <div className="ledger-nav">
            <button
              type="button"
              aria-label="Previous year"
              disabled={!canStepBack}
              onClick={() => onStep(-1)}
            >
              ‹
            </button>
            <button
              type="button"
              aria-label="Next year"
              disabled={!canStepForward}
              onClick={() => onStep(1)}
            >
              ›
            </button>
          </div>
        )}
      </div>

      <div className="ledger-rows">
        <h3 className="ledger-group-title">
          Year-end balances <span>{dollarLabel}</span>
        </h3>
        <LedgerRow label="Net worth" value={fullCurrency(snapshot.net_worth)} />
        {change !== null && (
          <LedgerRow label="Change" value={signed(change)} tone={signTone(change)} sub />
        )}
        <LedgerRow label="Cash & investments" value={fullCurrency(liquid)} />
        <div className="ledger-account-balances" role="group" aria-label="Account balances">
          {Object.entries(snapshot.accounts).map(([id, balance]) => (
            <LedgerRow
              key={id}
              label={accountNames[id] || `Account ${id}`}
              value={fullCurrency(balance)}
              sub
            />
          ))}
          {Object.keys(snapshot.accounts).length === 0 && (
            <p className="ledger-empty">No account balances available.</p>
          )}
        </div>
        {snapshot.real_assets_value > 0 && (
          <LedgerRow label="Real assets" value={fullCurrency(snapshot.real_assets_value)} sub />
        )}
        {snapshot.liabilities_balance > 0 && (
          <LedgerRow
            label="Debts"
            value={`−${fullCurrency(snapshot.liabilities_balance)}`}
            tone="negative"
            sub
          />
        )}
        <LedgerRow
          label="Investment growth"
          value={signed(snapshot.investment_growth)}
          tone={signTone(snapshot.investment_growth)}
          sub
        />
        {(snapshot.investment_fees ?? 0) > 0 && (
          <LedgerRow
            label="Investment fees"
            value={`−${fullCurrency(snapshot.investment_fees ?? 0)}`}
            tone="negative"
            sub
            title="Account fees charged this year; investment growth above is already net of them"
          />
        )}

        <LedgerDivider />

        <h3 className="ledger-group-title">
          Cash flow <span>{partial ? "This period" : "Full year"}</span>
        </h3>
        <LedgerRow
          label="Income"
          value={fullCurrency(snapshot.gross_income)}
          keyColor={LEDGER_KEYS.income}
        />
        {(earningsTest ?? earningsWithheld > 0) && (
          <LedgerRow
            label="Social Security withheld"
            value={fullCurrency(earningsWithheld / factor)}
            sub
            title="Benefits withheld by the Social Security earnings test; Income already excludes them"
          />
        )}
        {/* Always present, even at $0, so the panel keeps its height between years. */}
        <LedgerRow
          label="Withdrawals"
          value={fullCurrency(withdrawals)}
          keyColor={LEDGER_KEYS.saving}
        />
        <LedgerRow
          label="Withdrawal rate"
          value={withdrawalRate === null ? "—" : pct(withdrawalRate)}
          sub
          title="Withdrawals as a share of cash and investments at the start of the year"
        />
        {!partial && taxRows}
        <LedgerRow
          label="Spending"
          value={fullCurrency(snapshot.expenses)}
          keyColor={LEDGER_KEYS.spending}
        />
        <LedgerRow
          label="Net cash flow"
          value={signed(snapshot.net_cash_flow)}
          tone={signTone(snapshot.net_cash_flow)}
        />
        <LedgerRow
          label="Savings rate excl. payroll"
          value={savingsRate === null ? "—" : pct(savingsRate, 0)}
          sub
        />
        {Math.abs(taxBalance) >= 1 && (
          <LedgerRow
            label={taxBalance > 0 ? "Tax due" : "Tax refund"}
            value={fullCurrency(Math.abs(taxBalance))}
            sub
          />
        )}
        {unfunded > 0.01 && (
          <LedgerRow label="Unfunded spending" value={fullCurrency(unfunded)} tone="danger" />
        )}
        {goalShortfall > 0.01 && (
          <LedgerRow
            label="Rule funding shortfall"
            value={fullCurrency(goalShortfall)}
            sub
            title="Withdraw-if-short savings or debt payments that neither surplus nor withdrawals could fund. Spending is not affected."
          />
        )}
        {/* A partial first year's full-year figures (taxes and the pace) form their own group, apart from
            the period's amounts. Other years keep the group's space, so stepping years never resizes the panel. */}
        <div className={`ledger-pace${partial ? "" : " is-reserved"}`} aria-hidden={!partial}>
          <LedgerDivider />
          <h3 className="ledger-group-title">Full year</h3>
          {partial && taxRows}
          <LedgerRow
            label="Income pace"
            value={partial ? fullCurrency(snapshot.gross_income / yearFraction) : "—"}
            sub
            title={partial ? paceTitle : undefined}
          />
          <LedgerRow
            label="Spending pace"
            value={partial ? fullCurrency(snapshot.expenses / yearFraction) : "—"}
            sub
            title={partial ? paceTitle : undefined}
          />
        </div>
      </div>

      {snapshot.cash_flow?.expenses.some(
        (flow) => flow.category === "state_payroll_tax" && flow.amount > 0,
      ) && (
        <p className="editor-save-note">
          State payroll premiums are included in Spending. The Taxes total excludes those premiums.
        </p>
      )}
      {/* Every year's chips share one grid cell; only the shown year's are
          visible. The slot always takes the tallest set's height, so stepping
          onto or off a milestone year never resizes the panel. */}
      {eventsByYear.size > 0 && (
        <div className="ledger-events-slot">
          {[...eventsByYear].map(([year, yearEvents]) => {
            const current = year === snapshot.year;
            return (
              <ul
                key={year}
                className={`ledger-events${current ? " is-current" : ""}`}
                aria-label="Events this year"
                aria-hidden={!current}
              >
                {yearEvents.map((event) => (
                  <li
                    key={event.key}
                    className={`ledger-event kind-${event.kind}`}
                    title={event.detail}
                  >
                    {event.label}
                  </li>
                ))}
              </ul>
            );
          })}
        </div>
      )}
    </aside>
  );
}
