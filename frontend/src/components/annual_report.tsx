import { useMemo, useState } from "react";
import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import {
  downloadReport,
  INTL_TAX_REPORT_KEYS,
  projectionReport,
  reportCsv,
} from "@/utils/projection_report";
import {
  currencySymbol,
  displayCurrency,
  dollarsOr,
  fullCurrency,
  plainAmount,
} from "@/utils/format";
import { useAuthStore } from "@/stores/auth_store";
import { extensions } from "@/extensions";
import { isEmptyProjection } from "@/utils/plan_inputs";
type ReportColumn = keyof ReturnType<typeof projectionReport>[number];
const views: Record<string, ReportColumn[]> = {
  Summary: ["year", "age", "net_worth", "liquid_assets", "net_cash_flow", "unfunded_spending"],
  Balances: ["year", "age", "net_worth", "liquid_assets", "real_assets", "debt", "tax_balance"],
  "Cash flow": [
    "year",
    "age",
    "income",
    "expenses",
    "taxes",
    "net_cash_flow",
    "contributions",
    "withdrawals",
    "transfers",
    "rule_funding_shortfall",
  ],
  Taxes: [
    "year",
    "age",
    "taxes",
    "federal_tax",
    "state_tax",
    "capital_gains_tax",
    "payroll_tax",
    "local_tax",
    "state_retirement_exclusion",
    "state_social_security_subtraction",
    "state_capital_gains_excise",
    "net_investment_income_tax",
    "early_withdrawal_penalty",
    "effective_tax_percent",
    "marginal_tax_percent",
  ],
};
const definitions: Partial<Record<ReportColumn, string>> = {
  net_worth: "Year-end assets less debt, outstanding tax balance and unfunded spending.",
  liquid_assets: "Year-end financial account balances.",
  tax_balance: "Outstanding tax liability; a negative balance means a refund.",
  unfunded_spending: "Unmet spending carried into net worth.",
  income: "Includes taxable distributions. Do not add income and withdrawals together.",
  withdrawals: "Discretionary draws plus mandatory RMD and SEPP distributions, before tax.",
  mandatory_withdrawals: "RMD and SEPP subset already included in withdrawals.",
  contributions: "Includes reinvested dividends.",
  transfers: "Internal movements between accounts, not new income or spending.",
  net_cash_flow:
    "Cash remaining or needed before surplus allocation and discretionary withdrawals.",
  state_retirement_exclusion:
    "Pension and retirement income the state excluded before computing state tax. Not a tax.",
  state_social_security_subtraction:
    "Federally taxable Social Security the state subtracted before computing state tax. Not a tax.",
  state_capital_gains_excise:
    "Washington capital gains tax on long-term gains, already included in state tax.",
  rental_income: "Rent collected from rental properties, after vacancy.",
  rental_expenses: "Rental operating expenses, property tax, upkeep, insurance and loan interest.",
  rental_depreciation: "Depreciation deducted on rental buildings. Not a cash expense.",
  rental_taxable_income: "Net rental income or loss included in AGI after the passive loss limits.",
  suspended_passive_losses: "Rental losses carried to later years by the passive loss limits.",
  unrecaptured_section_1250_gain: "Sale gain from depreciation, taxed at no more than 25%.",
  real_estate_purchases:
    "Down payments (or full prices) and closing costs paid for planned purchases.",
  rule_funding_shortfall:
    "Withdraw-if-short savings or debt payments, within their limits, that neither surplus nor withdrawals could fund. Not unfunded spending.",
  tax_country: "The country whose tax rules applied to the year.",
  national_income_tax:
    "Income tax to the national government of the year's country. Included in taxes.",
  regional_income_tax:
    "Income tax to a province, state, canton or other region of the year's country. Included in taxes.",
  social_contributions:
    "Social insurance contributions and levies charged on income. Included in taxes.",
  wealth_tax: "Tax on net worth or other assets. Included in taxes.",
  transaction_tax: "Tax on buying or selling investments. Included in taxes.",
  benefit_recovery_tax:
    "Government benefits paid back because income was above a threshold. Included in taxes.",
};
/** A table cell: whole amounts, percents with one decimal, text as is. */
function cellText(key: string, value: string | number | undefined): string | number {
  if (value === undefined) return "";
  if (typeof value === "string" || ["year", "age"].includes(key)) return value;
  return key.endsWith("_percent") ? `${value.toFixed(1)}%` : plainAmount(value);
}
const columnLabel = (key: string) =>
  key
    .replace(/_percent$/, " (%)")
    .replace(/_/g, " ")
    .replace(/^./, (c) => c.toUpperCase());
export default function AnnualReport() {
  const { plan, simulation, currencyMode, setCurrencyMode, isSimulating } = usePlanStore();
  const [view, setView] = useState("Summary");
  const [custom, setCustom] = useState<ReportColumn[]>(views.Summary);
  const [selectedYear, setSelectedYear] = useState<number | null>(null);
  const isSaving = useSaveStore((s) => s.pending > 0);
  const isUpdating = isSaving || isSimulating;
  // Downloads are built in the browser, so the server cannot gate them; Free hides them.
  const access = extensions.access;
  const exportsLocked = useAuthStore((s) => !!access?.locked(s.user, "exports"));
  const rows = useMemo(
    () => (plan && simulation ? projectionReport(plan, simulation, currencyMode) : []),
    [plan, simulation, currencyMode],
  );
  // An empty plan projects rows of $0; those are not a report.
  if (!plan || !simulation || !rows.length || isEmptyProjection(simulation))
    return <p role="status">{isUpdating ? "Updating projection…" : "No projection yet."}</p>;
  const allColumns = Object.keys(rows[0]) as ReportColumn[];
  // Projections with a year outside the US add that year's country and its tax lines.
  const intlTaxColumns = allColumns.filter(
    (key) => key === "tax_country" || (INTL_TAX_REPORT_KEYS as readonly string[]).includes(key),
  );
  const viewColumns =
    view === "Taxes" && intlTaxColumns.length
      ? [...views.Taxes.slice(0, 3), ...intlTaxColumns, ...views.Taxes.slice(3)]
      : views[view];
  const columns =
    view === "Full detail"
      ? allColumns
      : view === "Custom"
        ? allColumns.filter((key) => ["year", "age", ...custom].includes(key))
        : viewColumns;
  const usd = displayCurrency() === "USD";
  // Named for the plan and the dollars shown: "Retire_at_55_todays_dollars.csv".
  const filename = `${
    plan.name
      .trim()
      .replace(/[^A-Za-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "projection"
  }_${currencyMode === "nominal" ? "future" : "todays"}_${usd ? "dollars" : "money"}`;
  const selectedRow = rows.find((row) => row.year === selectedYear) ?? rows[0];
  return (
    <section className="card">
      <h2>Annual projection report</h2>
      <p className="report-intro">
        First year may be partial. Downloads are results, not a plan backup.
      </p>
      <div
        className="report-view-controls seg-control task-tabs"
        role="group"
        aria-label="Report views"
      >
        {[...Object.keys(views), "Full detail", "Custom"].map((name) => (
          <button
            key={name}
            type="button"
            className={`seg-option${view === name ? " active" : ""}`}
            aria-pressed={view === name}
            onClick={() => setView(name)}
          >
            {name}
          </button>
        ))}
      </div>
      {view === "Custom" && (
        <fieldset className="report-column-picker" data-sample-view>
          <legend>Choose columns (year and age stay visible)</legend>
          {allColumns
            .filter((key) => !["year", "age"].includes(key))
            .map((key) => (
              <label key={key}>
                <input
                  type="checkbox"
                  checked={custom.includes(key)}
                  onChange={(e) =>
                    setCustom(
                      e.target.checked ? [...custom, key] : custom.filter((item) => item !== key),
                    )
                  }
                />
                {columnLabel(key)}
              </label>
            ))}
        </fieldset>
      )}
      <div
        style={{
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
          alignItems: "center",
          marginBottom: 16,
        }}
      >
        <label data-sample-view>
          {dollarsOr("Dollars", "Amounts")}
          <select
            value={currencyMode}
            onChange={(e) => setCurrencyMode(e.target.value as typeof currencyMode)}
          >
            <option value="nominal">{dollarsOr("Future $", "Future amounts")}</option>
            <option value="inflation_adjusted">
              {dollarsOr("Today's $", "Today's money")} ({simulation.metadata.start_year})
            </option>
          </select>
        </label>
        {exportsLocked && access ? (
          <access.LockedFeature feature="exports" />
        ) : (
          <>
            <button
              disabled={isUpdating}
              onClick={() =>
                downloadReport(
                  reportCsv(rows, currencyMode, simulation.metadata.start_year),
                  `${filename}.csv`,
                  "text/csv;charset=utf-8",
                )
              }
            >
              Download CSV
            </button>
            <button
              disabled={isUpdating}
              onClick={() =>
                downloadReport(
                  JSON.stringify(
                    {
                      plan_name: plan.name,
                      currency_mode: currencyMode,
                      base_year: simulation.metadata.start_year,
                      metadata: {
                        start_year: simulation.metadata.start_year,
                        end_year: simulation.metadata.end_year,
                        success: simulation.metadata.success,
                        failure_year: simulation.metadata.failure_year,
                        warnings: simulation.metadata.warnings,
                      },
                      annual_report: rows,
                    },
                    null,
                    2,
                  ),
                  `${filename}.json`,
                  "application/json",
                )
              }
            >
              Download JSON
            </button>
            {isUpdating && (
              <span role="status">Updating projection… Exports resume when it finishes.</span>
            )}
          </>
        )}
      </div>
      {columns.some((key) => definitions[key]) && (
        <details className="report-definitions">
          <summary>Definitions for this view</summary>
          <dl>
            {columns
              .filter((key) => definitions[key])
              .map((key) => (
                <div key={key}>
                  <dt>{columnLabel(key)}</dt>
                  <dd>{definitions[key]}</dd>
                </div>
              ))}
          </dl>
        </details>
      )}
      {view === "Summary" && (
        <div className="mobile-report-summary">
          <label data-sample-view>
            Report year
            <select
              value={selectedRow.year}
              onChange={(e) => setSelectedYear(Number(e.target.value))}
            >
              {rows.map((row) => (
                <option value={row.year} key={row.year}>
                  {row.year} · age {row.age}
                </option>
              ))}
            </select>
          </label>
          <p>
            {usd
              ? currencyMode === "nominal"
                ? "Nominal dollars"
                : `${simulation.metadata.start_year} dollars`
              : currencyMode === "nominal"
                ? `Nominal ${displayCurrency()}`
                : `${simulation.metadata.start_year} ${displayCurrency()}`}{" "}
            · balances at December 31
          </p>
          <dl>
            {views.Summary.filter((key) => !["year", "age"].includes(key)).map((key) => (
              <div key={key}>
                <dt>{columnLabel(key)}</dt>
                <dd>{fullCurrency(Number(selectedRow[key]))}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      <div
        className={view === "Summary" ? "report-summary-table" : undefined}
        style={{ overflowX: "auto", maxHeight: "70vh" }}
        tabIndex={0}
        aria-label="Scrollable annual projection report"
      >
        <table
          className="annual-report-table"
          style={{
            borderCollapse: "collapse",
            width: "100%",
            fontSize: 12,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          <caption style={{ textAlign: "left", paddingBottom: 12 }}>
            {plan.name} ·{" "}
            {currencyMode === "nominal"
              ? `Nominal ${currencySymbol()}`
              : `Today's ${currencySymbol()} (${simulation.metadata.start_year}), using this plan’s inflation assumptions`}
            . Amounts are rounded to whole {usd ? "US dollars" : `${displayCurrency()} units`};
            downloads retain precision.
          </caption>
          <thead>
            <tr>
              {columns.map((key) => (
                <th scope="col" title={definitions[key]} key={key}>
                  {columnLabel(key)}
                  {!["year", "age", "tax_country"].includes(key) && !key.endsWith("_percent")
                    ? ` (${currencySymbol()})`
                    : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.year}>
                {columns.map((key) => (
                  <td key={key}>{cellText(key, row[key])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
