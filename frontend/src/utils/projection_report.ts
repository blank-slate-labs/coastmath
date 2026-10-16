import type { PlanData, SimulationResult, YearSnapshot } from "@/types/plan";
import { isIntlYear, US_COUNTRY } from "@/domain/intl_plan";
import { buildDeflators, type CurrencyMode } from "./currency";

/** Tax totals of years taxed by another country; reported only when the projection has such a year. */
export const INTL_TAX_REPORT_KEYS = [
  "national_income_tax",
  "regional_income_tax",
  "social_contributions",
  "wealth_tax",
  "transaction_tax",
  "benefit_recovery_tax",
] as const satisfies readonly (keyof YearSnapshot)[];
type IntlTaxReportKey = (typeof INTL_TAX_REPORT_KEYS)[number];

/** Present only for projections with a year outside the US, so US exports keep their columns. */
export type IntlReportFields = { tax_country?: string } & Partial<Record<IntlTaxReportKey, number>>;

export function projectionReport(plan: PlanData, simulation: SimulationResult, mode: CurrencyMode) {
  const factors = buildDeflators(
    plan.assumption_curves.find((c) => c.curve_type === "inflation"),
    0.03,
    simulation.metadata.start_year,
    simulation.yearly_snapshots.length,
    plan.birth_year,
  );
  const intl = simulation.yearly_snapshots.some((s) => isIntlYear(s.tax_country));
  return simulation.yearly_snapshots.map((s, i) => {
    const f = mode === "nominal" ? 1 : factors[i];
    const mandatoryWithdrawals =
      s.cash_flow?.income_sources
        ?.filter((c) => c.source === "rmd" || c.source === "sepp")
        .reduce((sum, c) => sum + c.amount, 0) ?? 0;
    const intlFields: IntlReportFields = intl
      ? {
          tax_country: s.tax_country ?? US_COUNTRY,
          ...Object.fromEntries(INTL_TAX_REPORT_KEYS.map((key) => [key, (s[key] ?? 0) / f])),
        }
      : {};
    return {
      year: s.year,
      age: s.age,
      net_worth: s.net_worth / f,
      liquid_assets: Object.values(s.accounts).reduce((sum, value) => sum + value, 0) / f,
      real_assets: s.real_assets_value / f,
      debt: s.liabilities_balance / f,
      tax_balance: (s.tax_balance ?? 0) / f,
      unfunded_spending: (s.unfunded_expenses ?? 0) / f,
      income: s.gross_income / f,
      calendar_year_gross_income: (s.calendar_year_gross_income ?? s.gross_income) / f,
      expenses: s.expenses / f,
      taxes: s.taxes / f,
      federal_tax: s.federal_tax / f,
      state_tax: s.state_tax / f,
      capital_gains_tax: s.capital_gains_tax / f,
      payroll_tax: s.fica_tax / f,
      local_tax: (s.local_tax ?? 0) / f,
      net_investment_income_tax: (s.niit_tax ?? 0) / f,
      state_retirement_exclusion: (s.state_retirement_exclusion ?? 0) / f,
      state_social_security_subtraction: (s.state_social_security_subtraction ?? 0) / f,
      state_capital_gains_excise: (s.state_capital_gains_excise ?? 0) / f,
      rental_income: (s.rental_income ?? 0) / f,
      rental_expenses: (s.rental_expenses ?? 0) / f,
      rental_depreciation: (s.rental_depreciation ?? 0) / f,
      rental_taxable_income: (s.rental_taxable_income ?? 0) / f,
      suspended_passive_losses: (s.suspended_passive_losses ?? 0) / f,
      unrecaptured_section_1250_gain: (s.unrecaptured_section_1250_gain ?? 0) / f,
      real_estate_purchases: (s.real_estate_purchases ?? 0) / f,
      rule_funding_shortfall: (s.rule_funding_shortfall ?? 0) / f,
      early_withdrawal_penalty: (s.early_withdrawal_penalty ?? 0) / f,
      net_cash_flow: s.net_cash_flow / f,
      investment_growth: s.investment_growth / f,
      contributions: (s.cash_flow?.contributions.reduce((sum, c) => sum + c.amount, 0) ?? 0) / f,
      withdrawals:
        ((s.cash_flow?.drawdowns.reduce((sum, c) => sum + c.amount, 0) ?? 0) +
          mandatoryWithdrawals) /
        f,
      mandatory_withdrawals: mandatoryWithdrawals / f,
      transfers: s.transfers.reduce((sum, t) => sum + t.amount, 0) / f,
      effective_tax_percent: s.effective_rate * 100,
      marginal_tax_percent: s.marginal_rate * 100,
      flexible_spending_reduction: s.flex_spending_reduction / f,
      flexible_spending_increase: (s.flex_spending_increase ?? 0) / f,
      leftover_spending: (s.leftover_spending ?? 0) / f,
      ...intlFields,
    };
  });
}

export function csvCell(value: string | number): string {
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "";
  const safe = /^[\s]*[=+\-@]/.test(value) ? `'${value}` : value;
  return `"${safe.replace(/"/g, '""')}"`;
}

export function reportCsv(
  rows: ReturnType<typeof projectionReport>,
  mode: CurrencyMode,
  baseYear: number,
): string {
  if (!rows.length) return "";
  const keys = Object.keys(rows[0]) as (keyof (typeof rows)[number])[];
  return (
    [
      ["currency_mode", "base_year", ...keys].map(csvCell).join(","),
      ...rows.map((row) =>
        [mode, baseYear, ...keys.map((key) => row[key] ?? "")].map(csvCell).join(","),
      ),
    ].join("\r\n") + "\r\n"
  );
}

export function downloadReport(contents: string, filename: string, mime: string) {
  const url = URL.createObjectURL(new Blob([contents], { type: mime }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
