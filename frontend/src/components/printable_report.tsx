import { useMemo } from "react";

import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import {
  FI_ESTIMATE_LABEL,
  financialIndependence,
  resolveFinancialIndependence,
} from "@/utils/financial_independence";
import { useFiEstimateHidden } from "@/stores/fi_estimate_store";
import NetWorthChart from "@/components/net_worth_chart";
import TaxOverviewChart from "@/components/tax/tax_overview_chart";
import { projectionReport } from "@/utils/projection_report";
import {
  compactCurrency,
  displayCurrency,
  dollarsOr,
  fullCurrency,
  pct,
  plainAmount,
} from "@/utils/format";
import {
  CUSTOM_COUNTRY,
  US_COUNTRY,
  countryName,
  planCountries,
  usCoverage,
} from "@/domain/intl_plan";
import type { AssumptionCurve, PlanData } from "@/types/plan";

interface PrintableReportProps {
  onClose: () => void;
  now?: Date;
}

const filingLabel: Record<string, string> = {
  single: "Single",
  married_filing_jointly: "Married filing jointly",
  married_filing_separately: "Married filing separately",
  head_of_household: "Head of household",
};

const assumptionDefaults: { type: AssumptionCurve["curve_type"]; label: string; rate: number }[] = [
  { type: "inflation", label: "Inflation", rate: 0.03 },
  { type: "market_return", label: "Stock price growth", rate: 0.07 },
  { type: "dividend_yield", label: "Stock dividend yield", rate: 0 },
  { type: "cash_yield", label: "Cash yield", rate: 0 },
  { type: "bond_return", label: "Bond return", rate: 0.04 },
  { type: "bond_allocation", label: "Bond allocation", rate: 0 },
];

function describeAssumption(plan: PlanData, def: (typeof assumptionDefaults)[number]): string {
  const curve = plan.assumption_curves.find((c) => c.curve_type === def.type);
  if (!curve) return `${pct(def.rate)} (default)`;
  if (curve.mode === "curve" && curve.control_points.length) {
    return curve.control_points.map((p) => `${pct(p.y)} at age ${p.x}`).join(", ");
  }
  return pct(curve.fixed_rate ?? def.rate);
}

const sectionStyle: React.CSSProperties = { marginBottom: 22, breakInside: "avoid" };
const h2Style: React.CSSProperties = { fontSize: 16, margin: "0 0 8px", breakAfter: "avoid" };
const cell: React.CSSProperties = {
  padding: "4px 6px",
  textAlign: "right",
  borderBottom: "1px solid var(--surface-border)",
  whiteSpace: "nowrap",
};
// Labels wrap, so a long one never pushes its value past the table's edge.
const labelCell: React.CSSProperties = { ...cell, textAlign: "left", whiteSpace: "normal" };

/**
 * Print-ready projection report. Uses the same store data as the app; the
 * browser's print dialog produces the PDF. Charts are the app's React-rendered
 * SVGs sized to the page width.
 */
/**
 * The tax rules each of the plan's countries uses. The US tax mode applies
 * only to US years; other countries use their own resident rules, and the
 * user-defined country uses the plan's custom rules.
 */
function taxModeLabel(
  plan: Pick<PlanData, "tax_country" | "tax_region" | "residency_periods" | "tax_settings">,
): string {
  const us =
    plan.tax_settings?.mode === "flat"
      ? "Flat rates"
      : "Federal and state brackets (2026 data, indexed with inflation)";
  const countries = planCountries(plan);
  const label = (code: string) =>
    code === US_COUNTRY
      ? us
      : code === CUSTOM_COUNTRY
        ? "Custom rules"
        : `${countryName(code)} resident tax rules`;
  if (countries.length === 1) return label(countries[0]);
  return countries
    .map((code) =>
      code === US_COUNTRY
        ? `United States: ${us}`
        : code === CUSTOM_COUNTRY
          ? "Other country: custom rules"
          : label(code),
    )
    .join("; ");
}

export default function PrintableReport({ onClose, now = new Date() }: PrintableReportProps) {
  const plan = usePlanStore((s) => s.plan);
  const simulation = usePlanStore((s) => s.simulation);
  const isSimulating = usePlanStore((s) => s.isSimulating);
  const isSaving = useSaveStore((s) => s.pending > 0);
  const isUpdating = isSaving || isSimulating;
  const currencyMode = usePlanStore((s) => s.currencyMode);
  const fiEstimateHidden = useFiEstimateHidden(plan?.id);
  const rows = useMemo(
    () => (plan && simulation ? projectionReport(plan, simulation, currencyMode) : []),
    [plan, simulation, currencyMode],
  );

  if (isUpdating || !plan || !simulation || rows.length === 0) {
    return (
      <div className="print-report">
        <div className="no-print" style={{ display: "flex", gap: 10, marginBottom: 16 }}>
          <button type="button" onClick={onClose}>
            Back to the app
          </button>
        </div>
        <p role="status">
          {isUpdating
            ? "Updating projection… Printing resumes when it finishes."
            : "Run a plan before printing its report."}
        </p>
      </div>
    );
  }

  const snaps = simulation.yearly_snapshots;
  const first = snaps[0];
  const last = snaps[snaps.length - 1];
  const legacy = simulation.metadata.net_legacy;
  const lifetimeTaxes = snaps.reduce((sum, s) => sum + s.taxes, 0);
  const fi = resolveFinancialIndependence(plan, simulation, fiEstimateHidden);
  const fiLabel =
    fi?.source === "milestone"
      ? `${fi.milestone.name} (your milestone)`
      : `${FI_ESTIMATE_LABEL}: cash and investments minus debt exceed ${financialIndependence(simulation).multiple}× the prior year's spending`;
  const generated = now.toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
  const currencyLabel =
    currencyMode === "nominal"
      ? dollarsOr("nominal dollars", `nominal ${displayCurrency()}`)
      : `${dollarsOr(`${simulation.metadata.start_year} dollars`, `${simulation.metadata.start_year} ${displayCurrency()}`)} (inflation removed using the plan assumption)`;
  const estate = plan.estate_settings;
  const coverage = usCoverage(plan);
  // US estate tax applies only to a death in a US year, so a plan with no US
  // year leaves out the US exemptions; its saved settings are unchanged.
  const heirsTax =
    estate && (estate.heir_income_tax_rate ?? 0) > 0
      ? `heirs' income tax ${pct(estate.heir_income_tax_rate ?? 0)}`
      : null;
  const estateSummary =
    coverage === "non_us"
      ? ["No US estate tax", heirsTax].filter(Boolean).join(", ")
      : estate
        ? `${estate.custom_federal_exemption_enabled ? `Custom federal exemption ${compactCurrency(estate.federal_estate_exemption)}` : "Statutory federal exemption"}${estate.state_estate_tax_enabled ? `, state estate tax ${pct(estate.state_estate_tax_rate)} above ${compactCurrency(estate.state_estate_exemption)}` : ""}${heirsTax ? `, ${heirsTax}` : ""}`
        : "Defaults";
  const hc = plan.healthcare_settings;
  const tableColumns: { key: keyof (typeof rows)[number]; label: string }[] = [
    { key: "year", label: "Year" },
    { key: "age", label: "Age" },
    { key: "income", label: "Income" },
    { key: "taxes", label: "Taxes" },
    { key: "expenses", label: "Expenses" },
    { key: "net_cash_flow", label: "Net cash flow" },
    { key: "liquid_assets", label: "Liquid assets" },
    { key: "real_assets", label: "Property" },
    { key: "debt", label: "Debt" },
    { key: "net_worth", label: "Net worth" },
  ];

  return (
    <div
      className="print-report"
      style={{
        maxWidth: 860,
        margin: "0 auto",
        padding: 24,
        color: "var(--text-primary)",
        background: "var(--surface-card)",
      }}
    >
      <div
        className="no-print"
        style={{
          display: "flex",
          gap: 10,
          marginBottom: 16,
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <button type="button" onClick={() => window.print()}>
          Print or save as PDF
        </button>
        <button type="button" onClick={onClose}>
          Back to the app
        </button>
      </div>

      <header
        style={{
          borderBottom: "2px solid var(--text-primary)",
          paddingBottom: 10,
          marginBottom: 18,
        }}
      >
        <div
          style={{
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            color: "var(--text-secondary)",
          }}
        >
          CoastMath projection report
        </div>
        <h1 style={{ margin: "4px 0", fontSize: 24 }}>{plan.name}</h1>
        <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
          Generated {generated} · Projection {simulation.metadata.start_year}–
          {simulation.metadata.end_year} (age {first.age} to {last.age}) · Values in {currencyLabel}
        </div>
      </header>

      <section style={sectionStyle}>
        <h2 style={h2Style}>Key results</h2>
        <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
          <tbody>
            <tr>
              <td style={labelCell}>Outcome</td>
              <td style={cell}>
                {simulation.metadata.success
                  ? "Plan is funded through the final year"
                  : `Plan runs short in ${simulation.metadata.failure_year}`}
              </td>
            </tr>
            <tr>
              <td style={labelCell}>Year-end net worth ({first.year})</td>
              <td style={cell}>{fullCurrency(rows[0].net_worth)}</td>
            </tr>
            <tr>
              <td style={labelCell}>Net worth at end of plan ({last.year})</td>
              <td style={cell}>{fullCurrency(rows[rows.length - 1].net_worth)}</td>
            </tr>
            {fi && (
              <tr>
                <td style={labelCell}>{fiLabel}</td>
                <td style={cell}>
                  {fi.year != null
                    ? `${fi.year} at age ${fi.year - plan.birth_year}`
                    : "Not reached in projection"}
                </td>
              </tr>
            )}
            <tr>
              <td style={labelCell}>Lifetime taxes (nominal)</td>
              <td style={cell}>{fullCurrency(lifetimeTaxes)}</td>
            </tr>
            {legacy && (
              <tr>
                <td style={labelCell}>
                  Net estate after estate tax and settlement costs (nominal)
                </td>
                <td style={cell}>{fullCurrency(legacy.net_legacy)}</td>
              </tr>
            )}
            {legacy && (legacy.heir_income_tax ?? 0) > 0 && (
              <tr>
                <td style={labelCell}>Net to heirs after their income tax (nominal)</td>
                <td style={cell}>
                  {fullCurrency(legacy.net_to_heirs_after_income_tax ?? legacy.net_legacy)}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section style={sectionStyle}>
        <h2 style={h2Style}>Household and assumptions</h2>
        <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
          <tbody>
            <tr>
              <td style={labelCell}>Birth year / life expectancy</td>
              <td style={cell}>
                {plan.birth_year} / age {plan.life_expectancy}
              </td>
            </tr>
            {(coverage !== "us" || displayCurrency() !== "USD") && (
              <tr>
                <td style={labelCell}>Tax countries / currency</td>
                <td style={cell}>
                  {planCountries(plan)
                    .map((code) => countryName(code))
                    .join(", ")}{" "}
                  / {displayCurrency()}
                </td>
              </tr>
            )}
            <tr>
              <td style={labelCell}>Filing status / state</td>
              <td style={cell}>
                {filingLabel[plan.filing_status] ?? plan.filing_status} /{" "}
                {plan.state_code ?? "no state tax"}
              </td>
            </tr>
            <tr>
              <td style={labelCell}>Partner</td>
              <td style={cell}>
                {plan.spouse?.birth_year
                  ? `Born ${plan.spouse.birth_year}, life expectancy ${plan.spouse.life_expectancy ?? "not set"}`
                  : "None"}
              </td>
            </tr>
            {assumptionDefaults.map((def) => (
              <tr key={def.type}>
                <td style={labelCell}>{def.label}</td>
                <td style={cell}>{describeAssumption(plan, def)}</td>
              </tr>
            ))}
            <tr>
              <td style={labelCell}>Tax mode</td>
              <td style={cell}>{taxModeLabel(plan)}</td>
            </tr>
            <tr>
              <td style={labelCell}>Health coverage</td>
              <td style={cell}>
                {hc?.enabled
                  ? `${hc.aca_enabled ? "Marketplace with premium tax credit, then " : ""}Medicare${hc.medicare_apply_irmaa ? " with IRMAA" : ""}`
                  : "Not modeled"}
              </td>
            </tr>
            <tr>
              <td style={labelCell}>Estate</td>
              <td style={cell}>
                {estateSummary}
                {coverage === "mixed" && (
                  <div
                    className="us-only-note"
                    style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}
                  >
                    US estate tax, including the exemptions above, applies only to a death in a year
                    you live in the US. A death in another country&apos;s year uses that
                    country&apos;s estate rules, if it has any.
                  </div>
                )}
              </td>
            </tr>
            <tr>
              <td style={labelCell}>Flexible spending</td>
              <td style={cell}>
                {[
                  plan.spending_rules?.flex_threshold != null
                    ? `Cut discretionary spending ${pct(plan.spending_rules.flex_reduction)} after returns below ${pct(plan.spending_rules.flex_threshold)}`
                    : null,
                  plan.spending_rules?.upside_thresholds?.length
                    ? "Raised after new portfolio highs"
                    : null,
                  plan.spending_rules?.surplus_mode === "spend_leftover"
                    ? "Spends leftover cash"
                    : null,
                ]
                  .filter(Boolean)
                  .join("; ") || "Off"}
              </td>
            </tr>
            <tr>
              <td style={labelCell}>Milestones</td>
              <td style={cell}>
                {plan.milestones.length ? plan.milestones.map((m) => m.name).join(", ") : "None"}
              </td>
            </tr>
            <tr>
              <td style={labelCell}>Income streams / expenses / accounts</td>
              <td style={cell}>
                {plan.income_streams.length} / {plan.expenses.length} /{" "}
                {Object.keys(first.accounts).length}
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section style={{ ...sectionStyle, breakInside: "auto" }}>
        <h2 style={h2Style}>Net worth</h2>
        <div style={{ width: "100%" }}>
          <NetWorthChart />
        </div>
      </section>

      <section style={{ ...sectionStyle, breakBefore: "page" }}>
        <h2 style={h2Style}>Income and taxes</h2>
        <div style={{ width: "100%" }}>
          <TaxOverviewChart snapshots={snaps} />
        </div>
      </section>

      <section style={{ marginBottom: 22, breakBefore: "page" }}>
        <h2 style={h2Style}>
          Annual projection (
          {currencyMode === "nominal" ? "nominal" : `${simulation.metadata.start_year} dollars`})
        </h2>
        <table
          style={{
            width: "100%",
            fontSize: 11,
            borderCollapse: "collapse",
            fontVariantNumeric: "tabular-nums",
          }}
          aria-label="Annual projection"
        >
          <thead style={{ display: "table-header-group" }}>
            <tr>
              {tableColumns.map((c) => (
                <th
                  key={c.key}
                  style={{
                    ...cell,
                    fontWeight: 600,
                    borderBottom: "2px solid var(--text-primary)",
                  }}
                >
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.year} style={{ breakInside: "avoid" }}>
                {tableColumns.map((c) => (
                  <td key={c.key} style={cell}>
                    {c.key === "year" || c.key === "age"
                      ? row[c.key]
                      : plainAmount(Math.round(row[c.key] as number))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {plan.notes && (
        <section style={sectionStyle}>
          <h2 style={h2Style}>Plan notes</h2>
          <p style={{ whiteSpace: "pre-wrap", fontSize: 13, margin: 0 }}>{plan.notes}</p>
        </section>
      )}

      <section style={sectionStyle}>
        <h2 style={h2Style}>Caveats and assumptions to review</h2>
        <ul style={{ fontSize: 12, margin: 0, paddingLeft: 18 }}>
          {(simulation.metadata.warnings ?? []).map((w) => (
            <li key={w}>{w}</li>
          ))}
          <li>
            Deterministic projection of the plan's inputs; not a forecast or financial, tax or legal
            advice.
          </li>
          {coverage !== "non_us" && (
            <li>
              Taxes use 2026 federal and state data, inflation-indexed; future law changes are not
              modeled.
            </li>
          )}
          {coverage !== "us" && (
            <li>
              Years lived outside the US use that country's tax rules for residents, including the
              approximations listed in the help article "International plans". US citizenship
              taxation, foreign exchange and departure taxes are not modeled.
            </li>
          )}
          {legacy?.exclusions.map((e) => (
            <li key={e}>Estate: {e}</li>
          ))}
          <li>Regenerate after changing the plan.</li>
        </ul>
      </section>
      <footer
        style={{
          fontSize: 11,
          color: "var(--text-tertiary)",
          borderTop: "1px solid var(--surface-border)",
          paddingTop: 8,
        }}
      >
        CoastMath · {plan.name} · generated {generated}
      </footer>
    </div>
  );
}
