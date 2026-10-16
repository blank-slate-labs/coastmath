import { act, render, screen } from "@testing-library/react";
import { vi, it, expect } from "vitest";
import TaxToolsPanel from "./tax_tools_panel";
import { usePlanStore } from "@/stores/plan_store";
import type { SimulationResult } from "@/types/plan";
import { makePlan } from "@/test_support/plan_builder";
vi.mock("./roth_conversion_planner", () => ({
  RothConversionPlanner: () => <div>Manual planner</div>,
}));
vi.mock("./deduction_comparison", () => ({
  DeductionComparison: () => <div>Deduction chart</div>,
}));
vi.mock("./sepp_calculator", () => ({ SEPPCalculator: () => <div>SEPP planner</div> }));
vi.mock("./cash_reserve_control", () => ({ default: () => <div>Cash reserve</div> }));
vi.mock("./healthcare_panel", () => ({ HealthcarePanel: () => <div>Health panel</div> }));
vi.mock("./tax_strategy_optimizer", () => ({
  TaxStrategyOptimizer: () => <div>Strategy optimizer</div>,
}));
vi.mock("./tax_suggestions", () => ({ TaxSuggestions: () => <div>Tax suggestions</div> }));
it("suppresses bracket and deduction analysis for flat-tax plans", () => {
  usePlanStore.setState({
    plan: makePlan({ id: "p", tax_settings: { mode: "flat" } }),
    plans: [],
    baselineSimulation: null,
    simulation: {
      yearly_snapshots: [
        {
          year: 2030,
          gross_income: 0,
          taxes: 0,
          federal_tax: 0,
          capital_gains_tax: 0,
          state_tax: 0,
          fica_tax: 0,
          effective_rate: 0.2,
          marginal_rate: 0.2,
        },
      ],
    } as SimulationResult,
  });
  render(<TaxToolsPanel />);
  expect(screen.getByText(/Flat tax mode/)).toBeInTheDocument();
  expect(screen.queryByText("Deduction chart")).not.toBeInTheDocument();
  expect(screen.queryByText("Deduction and marginal-rate history")).not.toBeInTheDocument();
});

it("shows the early withdrawal penalty included in total taxes and the effective rate", () => {
  usePlanStore.setState({
    plan: makePlan({ id: "p", tax_settings: { mode: "flat" } }),
    simulation: {
      yearly_snapshots: [
        {
          year: 2036,
          gross_income: 170000,
          calendar_year_gross_income: 340000,
          taxes: 51000,
          federal_tax: 34000,
          capital_gains_tax: 0,
          state_tax: 0,
          fica_tax: 0,
          early_withdrawal_penalty: 17000,
          effective_rate: 0.15,
          marginal_rate: 0.2,
        },
      ],
    } as SimulationResult,
  });
  render(<TaxToolsPanel />);
  expect(screen.getByText("Calendar-year gross income").nextElementSibling).toHaveTextContent(
    "$340k",
  );
  expect(screen.getByText("Early withdrawal penalty").nextElementSibling).toHaveTextContent("$17k");
  expect(screen.getByText("Full-year taxes").nextElementSibling).toHaveTextContent("$51k");
  expect(screen.getByText("Effective rate").nextElementSibling).toHaveTextContent("15.0%");
});

it("shows estimated tax rows only when a strategy is on, reading omitted values as zero", () => {
  const year = {
    year: 2026,
    gross_income: 100000,
    taxes: 21027,
    federal_tax: 13170,
    capital_gains_tax: 0,
    state_tax: 0,
    fica_tax: 7650,
    effective_rate: 0.21,
    marginal_rate: 0.22,
    cash_flow: {
      income_sources: [],
      gross_income: 100000,
      tax_withheld: 15000,
      payroll_deductions: 0,
      net_pay: 85000,
      tax_delta: -5820,
      expenses: [],
      contributions: [],
      transfers: [],
      drawdowns: [],
      required_annual_payment: 11853,
      underpayment_penalty: 207,
    },
  };
  usePlanStore.setState({
    plan: makePlan({
      id: "p",
      tax_settings: { mode: "detailed", estimated_payments: { strategy: "settle_at_filing" } },
    }),
    simulation: { yearly_snapshots: [year] } as unknown as SimulationResult,
  });
  const { unmount } = render(<TaxToolsPanel />);
  expect(screen.getByText("Estimated tax payments").nextElementSibling).toHaveTextContent("$0");
  expect(screen.getByText("Required annual payment").nextElementSibling).toHaveTextContent("$12k");
  expect(screen.getByText("Underpayment penalty").nextElementSibling).toHaveTextContent("$207");
  expect(screen.getByText(/cover federal tax only/)).toBeInTheDocument();
  unmount();
  usePlanStore.setState({ plan: makePlan({ id: "p", tax_settings: { mode: "detailed" } }) });
  render(<TaxToolsPanel />);
  expect(screen.queryByText("Underpayment penalty")).not.toBeInTheDocument();
  expect(screen.queryByText("Estimated tax payments")).not.toBeInTheDocument();
});

it("keeps the tools mounted while a save reruns the projection", () => {
  const simulation = {
    yearly_snapshots: [
      {
        year: 2030,
        gross_income: 0,
        taxes: 0,
        federal_tax: 0,
        capital_gains_tax: 0,
        state_tax: 0,
        fica_tax: 0,
        effective_rate: 0.2,
        marginal_rate: 0.2,
      },
    ],
  } as SimulationResult;
  usePlanStore.setState({
    plan: makePlan({ id: "p", tax_settings: { mode: "detailed" } }),
    baselineSimulation: null,
    simulation,
    isSimulating: false,
  });
  render(<TaxToolsPanel />);
  expect(screen.getByText("Strategy optimizer")).toBeInTheDocument();
  act(() => usePlanStore.setState({ simulation: null, isSimulating: true }));
  expect(screen.getByText("Strategy optimizer")).toBeInTheDocument();
  expect(screen.getByText("Recalculating tax results…")).toBeInTheDocument();
  act(() => usePlanStore.setState({ simulation: null, isSimulating: false }));
  expect(screen.queryByText("Strategy optimizer")).not.toBeInTheDocument();
});
