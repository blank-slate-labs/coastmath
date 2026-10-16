import type { TaxStrategyObjective } from "@/types/plan";
import { compactCurrency, ratePct, signedCompactCurrency } from "@/utils/format";

export interface ObjectiveOption {
  value: TaxStrategyObjective;
  label: string;
  direction: "higher" | "lower";
  /** Reads the objective's value as a dollar amount or a rate. */
  unit: "dollars" | "rate";
  /** Pre-tax balances are discounted by the heir tax rate in this objective. */
  discounted?: boolean;
}

const NET_ESTATE: ObjectiveOption = {
  value: "net_legacy",
  label: "Net estate, pre-tax balances after income tax (higher is better)",
  direction: "higher",
  unit: "dollars",
  discounted: true,
};

/** End-of-plan wealth, then taxes, then health coverage costs and credits, then RMDs. */
export const STRATEGY_OBJECTIVES: ObjectiveOption[] = [
  {
    value: "final_net_worth",
    label: "End net worth, pre-tax balances after income tax (higher is better)",
    direction: "higher",
    unit: "dollars",
    discounted: true,
  },
  NET_ESTATE,
  {
    value: "lifetime_taxes",
    label: "Lifetime income taxes (lower is better)",
    direction: "lower",
    unit: "dollars",
  },
  {
    value: "lifetime_effective_tax_rate",
    label: "Lifetime effective tax rate, taxes over income (lower is better)",
    direction: "lower",
    unit: "rate",
  },
  {
    value: "lifetime_taxes_and_healthcare",
    label: "Lifetime taxes plus health coverage (lower is better)",
    direction: "lower",
    unit: "dollars",
  },
  {
    value: "total_irmaa_surcharge",
    label: "Total Medicare IRMAA surcharges (lower is better)",
    direction: "lower",
    unit: "dollars",
  },
  {
    value: "total_aca_subsidies",
    label: "Total ACA premium credits (higher is better)",
    direction: "higher",
    unit: "dollars",
  },
  {
    value: "total_rmd_distributions",
    label: "Total required minimum distributions (lower is better)",
    direction: "lower",
    unit: "dollars",
  },
];

export const objectiveOption = (value: TaxStrategyObjective): ObjectiveOption =>
  STRATEGY_OBJECTIVES.find((o) => o.value === value) ?? NET_ESTATE;

export const formatObjective = (value: TaxStrategyObjective, amount: number): string =>
  objectiveOption(value).unit === "rate" ? ratePct(amount) : compactCurrency(amount);

/** Whether a change of `delta` against the baseline is an improvement. */
export const isImprovement = (value: TaxStrategyObjective, delta: number): boolean =>
  objectiveOption(value).direction === "higher" ? delta > 0 : delta < 0;

export const formatObjectiveDelta = (value: TaxStrategyObjective, delta: number): string => {
  if (objectiveOption(value).unit === "rate")
    return `${delta > 0 ? "+" : ""}${Number((delta * 100).toFixed(2))} pts`;
  return signedCompactCurrency(delta);
};
