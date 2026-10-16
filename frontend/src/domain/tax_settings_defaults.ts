import type { TaxSettings } from "@/types/plan";

/** Base settings a tax editor spreads under the saved plan settings when it writes them. */
export const DEFAULT_TAX_SETTINGS: Readonly<TaxSettings> = {
  mode: "detailed",
  ordinary_income_tax_rate: null,
  capital_gains_tax_rate: null,
  taxable_withholding_rate: 0,
  tax_deferred_withholding_rate: 0,
  settlement_lag_years: 0,
  cash_flow_frequency: "monthly",
};
