import { render, screen } from "@testing-library/react";
import { it, expect, beforeEach } from "vitest";
import { setDisplayCurrency } from "@/utils/format";
import EstateSummaryPanel from "./estate_summary_panel";
import { usePlanStore } from "@/stores/plan_store";
import type { NetLegacy, SimulationResult } from "@/types/plan";
import { makePlan } from "@/test_support/plan_builder";

const basePlan = makePlan({
  id: "p1",
  user_id: "u",
  name: "Plan",
  birth_year: 1970,
  filing_status: "married_filing_jointly",
  life_expectancy: 90,
  created_at: "2026-01-01",
  spouse: {
    id: "s",
    plan_id: "p1",
    name: "Sam",
    birth_year: 1971,
    life_expectancy: 80,
    income_streams: [],
    retirement_milestone_id: null,
  },
  estate_settings: {
    step_up_basis_on_death: true,
    filing_status_after_death: "single",
    federal_estate_exemption: 13_600_000,
    custom_federal_exemption_enabled: false,
    portability_election: true,
    state_estate_tax_enabled: true,
    state_estate_exemption: 2_000_000,
    state_estate_tax_rate: 0.16,
  },
});

const legacy: NetLegacy = {
  total_assets: 40_000_000,
  total_liabilities: 1_000_000,
  gross_estate: 39_000_000,
  federal_exemption: 20_000_000,
  dsue_amount: 15_000_000,
  federal_taxable_estate: 4_000_000,
  federal_estate_tax: 1_600_000,
  state_exemption: 2_000_000,
  state_taxable_estate: 37_000_000,
  state_estate_tax: 5_920_000,
  estate_tax: 7_520_000,
  net_legacy: 31_480_000,
  marital_deduction_applied: false,
  custom_federal_exemption: false,
  death_year: 2060,
  exclusions: ["Heir income taxes on inherited pre-tax accounts are not deducted."],
};

function simulation(netLegacy: NetLegacy | null): SimulationResult {
  return {
    metadata: {
      plan_id: "p1",
      start_year: 2026,
      end_year: 2060,
      success: true,
      failure_year: null,
      net_legacy: netLegacy,
      rmd_start_age: 75,
      warnings: [],
    },
    yearly_snapshots: [],
  } as unknown as SimulationResult;
}

beforeEach(() => usePlanStore.setState({ plan: basePlan, simulation: simulation(legacy) }));

it("renders the engine breakdown, including DSUE and separate federal and state tax", () => {
  render(<EstateSummaryPanel />);
  expect(
    screen.getByText("Deceased partner's unused exemption (DSUE)").parentElement,
  ).toHaveTextContent("$15.0M");
  expect(screen.getByText("Federal estate tax").parentElement).toHaveTextContent("−$1.6M");
  expect(screen.getByText("State estate tax").parentElement).toHaveTextContent("−$5.9M");
  expect(
    screen.getByText("Net estate", { selector: ".stat-label" }).parentElement,
  ).toHaveTextContent("$31.5M");
  expect(screen.getByText(/Born 1971, to age 80/)).toBeInTheDocument();
  expect(screen.getByText(/Heir income taxes/)).toBeInTheDocument();
});

it("explains deferral when the partner survives instead of inventing a tax split", () => {
  usePlanStore.setState({
    simulation: simulation({
      ...legacy,
      marital_deduction_applied: true,
      federal_estate_tax: 0,
      state_estate_tax: 0,
      estate_tax: 0,
      net_legacy: 39_000_000,
      dsue_amount: 0,
    }),
  });
  render(<EstateSummaryPanel />);
  expect(screen.getAllByText("Deferred: passes to surviving spouse")).toHaveLength(2);
  expect(screen.queryByText("Federal taxable estate")).toBeNull();
  expect(
    screen.getByText(/Tax at the surviving partner’s death is not projected/),
  ).toBeInTheDocument();
});

it("shows an unavailable state when the engine provides no breakdown", () => {
  usePlanStore.setState({ simulation: simulation(null) });
  render(<EstateSummaryPanel />);
  expect(screen.getByText(/unavailable for this projection/)).toBeInTheDocument();
});
it("omits survivor status and portability for a plan without a partner", () => {
  usePlanStore.setState({ plan: { ...basePlan, spouse: null, filing_status: "single" } });
  render(<EstateSummaryPanel />);
  expect(screen.queryByText("Status after partner's death")).not.toBeInTheDocument();
  expect(screen.queryByText("Portability")).not.toBeInTheDocument();
});

it("shows 529 balances outside the estate, the charitable bequest, selling costs and heirs' gains tax", () => {
  usePlanStore.setState({
    simulation: simulation({
      ...legacy,
      education_savings_outside_estate: 300_000,
      charitable_bequest: 3_900_000,
      selling_costs: 120_000,
      heir_capital_gains_tax: 450_000,
      net_to_heirs_after_income_tax: 31_030_000,
    }),
  });
  render(<EstateSummaryPanel />);
  expect(screen.getByText("529 accounts (outside the estate)").parentElement).toHaveTextContent(
    "−$300k",
  );
  expect(screen.getByText("Charitable bequest").parentElement).toHaveTextContent("−$3.9M");
  expect(screen.getByText("Selling costs on real assets").parentElement).toHaveTextContent(
    "−$120k",
  );
  expect(screen.getByText("Heirs' capital gains tax (no step-up)").parentElement).toHaveTextContent(
    "−$450k",
  );
  expect(screen.getByText("Net to heirs after their income tax").parentElement).toHaveTextContent(
    "$31.0M",
  );
});

it("labels the legacy basis in dollars for USD plans and as amounts in other currencies", () => {
  const { unmount } = render(<EstateSummaryPanel />);
  expect(screen.getByText("2060 · nominal dollars")).toBeInTheDocument();
  expect(screen.getByText("Net estate · future dollars")).toBeInTheDocument();
  unmount();
  setDisplayCurrency("GBP");
  try {
    render(<EstateSummaryPanel />);
    expect(screen.getByText("2060 · nominal amounts")).toBeInTheDocument();
    expect(screen.getByText("Net estate · future amounts")).toBeInTheDocument();
    expect(screen.queryByText(/dollars/)).toBeNull();
  } finally {
    setDisplayCurrency(null);
  }
});
