import type { SavedWithdrawalMethod } from "@/types/plan";

/** Methods a plan can save, with display labels and one-line descriptions. */
export const SAVED_METHODS: { value: SavedWithdrawalMethod; label: string; help: string }[] = [
  {
    value: "constant_dollar",
    label: "Constant dollar",
    help: "Initial rate × starting portfolio, then raised with inflation each year.",
  },
  {
    value: "constant_percentage",
    label: "Constant percentage",
    help: "The initial rate × each year's portfolio.",
  },
  {
    value: "guyton_klinger",
    label: "Guyton-Klinger guardrails",
    help: "Constant dollar with cuts and raises when the withdrawal rate leaves its guardrails.",
  },
  {
    value: "vanguard_dynamic",
    label: "Vanguard dynamic spending",
    help: "The initial rate × the portfolio, with yearly changes held between a floor and a ceiling.",
  },
  {
    value: "rmd_table",
    label: "IRS life-expectancy percentage",
    help: "Portfolio ÷ the IRS life-expectancy factor for your age.",
  },
  {
    value: "fixed_amount",
    label: "Fixed amount",
    help: "A set amount in today's dollars, optionally raised with inflation.",
  },
  {
    value: "one_over_n",
    label: "1/N",
    help: "Portfolio ÷ the years left in the plan, this year included.",
  },
  {
    value: "vpw",
    label: "Variable percentage withdrawal (VPW)",
    help: "A percentage that rises as the years left shrink, from your stock/bond mix and assumed real returns.",
  },
  {
    value: "kitces_ratchet",
    label: "Kitces ratchet",
    help: "Constant dollar that rises when the portfolio grows well past its start, and never falls.",
  },
  {
    value: "clyatt_95",
    label: "Clyatt 95% rule",
    help: "The larger of the initial rate × the portfolio and 95% of last year's withdrawal.",
  },
];
