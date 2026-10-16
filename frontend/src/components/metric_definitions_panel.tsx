import { useEffect } from "react";

import { usePlanStore } from "@/stores/plan_store";
import {
  defaultMetricSettings,
  isDefaultMetricSettings,
  useMetricStore,
} from "@/stores/metric_store";

const rowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  fontSize: 13,
};

/**
 * Lets the user choose what "spending" and "effective tax rate" mean on the
 * dashboard. Display only: the projection engine's cash accounting is never
 * affected, and the defaults reproduce the engine's own figures.
 */
export default function MetricDefinitionsPanel() {
  const plan = usePlanStore((s) => s.plan);
  const { planId, settings, load, update, reset } = useMetricStore();
  useEffect(() => {
    if (plan && plan.id !== planId) load(plan.id);
  }, [plan, planId, load]);
  if (!plan) return null;
  const customised = !isDefaultMetricSettings(settings);
  return (
    <section className="card" style={{ display: "grid", gap: 12 }} data-sample-view>
      <div>
        <h2 style={{ margin: 0 }}>Metric definitions</h2>
        <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--text-secondary)" }}>
          Display settings only; reports are unchanged.
        </p>
      </div>
      <details open={customised}>
        <summary style={{ cursor: "pointer", fontSize: 13 }}>
          Default definitions (what the engine reports)
        </summary>
        <ul
          style={{
            margin: "6px 0 0",
            paddingLeft: 18,
            fontSize: 12,
            color: "var(--text-secondary)",
          }}
        >
          <li>
            <strong>Spending</strong> = every ordinary expense paid in the year: essential,
            discretionary and uncategorised expenses, loan payments, property carrying costs,
            charitable outflows and health coverage. Taxes are not spending. The CoastMath financial
            independence estimate lands the year after cash and investments, minus debt, exceed 25×
            that year's spending (annualized for a partial first year). Both sides are that year's
            dollars, so no separate inflation adjustment applies, and a plan whose debts exceed its
            liquid assets is never independent. It uses the same rule as a “Financial independence
            (multiple of expenses)” milestone at 25× with liquid accounts minus debt, and your own
            FI milestone replaces it. It always uses the full spending figure, whatever the
            definitions here. It is a planning threshold, not a guarantee, and does not change the
            retirement date.
          </li>
          <li>
            <strong>Effective tax rate</strong> = total taxes ÷ gross income. Taxes include federal
            and state income tax, capital gains tax, payroll tax, NIIT, AMT, early-withdrawal
            penalties and any estimated-tax underpayment penalty. Gross income includes wages,
            Social Security, RMDs, taxable withdrawals, employer contributions, realised gains and
            dividends for the year.
          </li>
          <li>
            <strong>Savings rate excl. payroll</strong> = net cash flow ÷ gross income for the first
            year. Checkup’s rate adds payroll contributions.
          </li>
        </ul>
      </details>
      <fieldset style={{ border: 0, padding: 0, margin: 0, display: "grid", gap: 8 }}>
        <legend style={{ fontSize: 13, fontWeight: 600 }}>Spending includes</legend>
        <label style={rowStyle}>
          <input
            type="checkbox"
            checked={settings.includeEssential}
            onChange={(e) => update({ includeEssential: e.target.checked })}
          />
          Essential expenses (including loan payments, property costs and health coverage)
        </label>
        <label style={rowStyle}>
          <input
            type="checkbox"
            checked={settings.includeDiscretionary}
            onChange={(e) => update({ includeDiscretionary: e.target.checked })}
          />
          Discretionary expenses (including charitable giving)
        </label>
        <label style={rowStyle}>
          <input
            type="checkbox"
            checked={settings.includeUncategorized}
            onChange={(e) => update({ includeUncategorized: e.target.checked })}
          />
          Uncategorised expenses
        </label>
        <label style={rowStyle}>
          <input
            type="checkbox"
            checked={settings.includeTaxesInSpending}
            onChange={(e) => update({ includeTaxesInSpending: e.target.checked })}
          />
          Count taxes as spending
        </label>
      </fieldset>
      <fieldset style={{ border: 0, padding: 0, margin: 0, display: "grid", gap: 8 }}>
        <legend style={{ fontSize: 13, fontWeight: 600 }}>Effective tax rate</legend>
        <label>
          Denominator
          <select
            value={settings.taxRateDenominator}
            onChange={(e) =>
              update({ taxRateDenominator: e.target.value as typeof settings.taxRateDenominator })
            }
          >
            <option value="gross_income">Gross income (engine default)</option>
            <option value="total_outflows">Taxes plus spending (share of all outflows)</option>
          </select>
        </label>
        <label style={rowStyle}>
          <input
            type="checkbox"
            checked={settings.includePayrollTax}
            onChange={(e) => update({ includePayrollTax: e.target.checked })}
          />
          Include payroll (FICA) taxes
        </label>
        {settings.taxRateDenominator === "total_outflows" && (
          <p style={{ margin: 0, fontSize: 12, color: "var(--text-secondary)" }}>
            {settings.includePayrollTax
              ? "Opening-year outflow rates use taxes after plan start when available."
              : "Excluding payroll keeps annual non-payroll tax in opening-year rates."}
          </p>
        )}
      </fieldset>
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <button type="button" onClick={reset} disabled={!customised}>
          Reset to engine defaults
        </button>
        {customised && (
          <span role="status" style={{ fontSize: 12, color: "var(--text-secondary)" }}>
            Custom definitions apply to the dashboard tiles only.
          </span>
        )}
        {!customised && (
          <span style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
            Using engine defaults ({Object.keys(defaultMetricSettings).length} settings).
          </span>
        )}
      </div>
    </section>
  );
}
