import type { SpendingOutcome } from "@/api/spending_models";
import type { CurrencyMode } from "@/utils/currency";
import { money } from "@/components/ledger/ledger_format";
import { fiChange, finalNetWorth, PLAN_COLOR, SERIES_COLORS, srOnly } from "./month_format";

function fi(outcome: SpendingOutcome): string {
  return outcome.fi_age == null ? "Not reached" : `${outcome.fi_age} (${outcome.fi_year})`;
}

function success(outcome: SpendingOutcome): string {
  return outcome.success
    ? "Funded"
    : outcome.failure_year
      ? `Short in ${outcome.failure_year}`
      : "Short";
}

/** FI, success, final net worth and Monte Carlo success for the plan and each variant. */
export default function OutcomeTable({
  plan,
  variants,
  currency,
  mode,
  busy,
  onApply,
}: {
  plan: SpendingOutcome;
  variants: SpendingOutcome[];
  currency: string;
  mode: CurrencyMode;
  busy: boolean;
  onApply: (index: number) => void;
}) {
  const monteCarlo = plan.monte_carlo_success_rate != null;
  const rows = [plan, ...variants];
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="chart-table" style={{ width: "100%" }}>
        <caption style={srOnly}>Outcomes by spending model</caption>
        <thead>
          <tr>
            <th scope="col">Model</th>
            <th scope="col" className="num">
              Spending / yr
            </th>
            <th scope="col">FI age</th>
            <th scope="col">Plan</th>
            <th scope="col" className="num">
              Final net worth
            </th>
            {monteCarlo && (
              <th scope="col" className="num">
                Monte Carlo
              </th>
            )}
            <th scope="col">
              <span style={srOnly}>Apply</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((outcome, index) => {
            const change = index === 0 ? null : fiChange(outcome, plan);
            const color =
              index === 0 ? PLAN_COLOR : SERIES_COLORS[(index - 1) % SERIES_COLORS.length];
            return (
              <tr key={index}>
                <th scope="row" style={{ textAlign: "left", fontWeight: 500 }}>
                  <span
                    aria-hidden="true"
                    style={{
                      display: "inline-block",
                      width: 10,
                      height: 3,
                      background: color,
                      marginRight: 6,
                      verticalAlign: "middle",
                    }}
                  />
                  {outcome.label}
                </th>
                <td className="num">
                  {money(outcome.essential_annual + outcome.discretionary_annual, currency)}
                </td>
                <td>
                  {fi(outcome)}
                  {change && <span style={{ color: "var(--text-secondary)" }}> · {change}</span>}
                </td>
                <td>{success(outcome)}</td>
                <td className="num">{money(finalNetWorth(outcome, mode), currency)}</td>
                {monteCarlo && (
                  <td className="num">
                    {outcome.monte_carlo_success_rate == null
                      ? "—"
                      : `${Math.round(outcome.monte_carlo_success_rate * 100)}%`}
                  </td>
                )}
                <td>
                  {index > 0 && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onApply(index - 1)}
                      aria-label={`Apply ${outcome.label}`}
                    >
                      Apply
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
