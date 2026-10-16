import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { TerminalDashboard } from "./terminal_dashboard";
import { usePlanStore } from "@/stores/plan_store";
import { useAuthStore } from "@/stores/auth_store";
import type { SimulationResult } from "@/types/plan";
import { displayCurrency } from "@/utils/format";
import { makePlan } from "@/test_support/plan_builder";
import { makeYearSnapshot } from "@/test_support/record_builders";
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(null),
);
const loadPlans = vi.fn().mockResolvedValue(undefined);
const loadPlan = vi.fn().mockResolvedValue(undefined);
const ensureSession = vi.fn().mockResolvedValue(undefined);
const snap = makeYearSnapshot({
  year: 2026,
  age: 40,
  net_worth: 100000,
  accounts: { cash: 100000 },
  gross_income: 100000,
  expenses: 20000,
  taxes: 10000,
  federal_tax: 6000,
  state_tax: 2000,
  fica_tax: 2000,
  capital_gains_tax: 0,
  effective_rate: 0.1,
  marginal_rate: 0.22,
  net_cash_flow: 70000,
  real_assets_value: 0,
  liabilities_balance: 0,
});
function result(
  snapshots = [
    snap,
    { ...snap, year: 2027, net_worth: 200000, accounts: { cash: 150000, savings: 50000 } },
  ],
  success = true,
): SimulationResult {
  return {
    yearly_snapshots: snapshots,
    metadata: { success, failure_year: success ? null : 2026 },
  } as SimulationResult;
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-07T16:00:00Z"));
  vi.stubGlobal("requestAnimationFrame", vi.fn().mockReturnValue(1));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  useAuthStore.setState({
    ensureSession,
    isLoading: false,
    error: null,
    user: { id: "u", is_anonymous: true } as never,
  });
  usePlanStore.setState({
    plan: null,
    plans: [makePlan({ id: "p", name: "Household" })],
    simulation: null,
    loadPlans,
    loadPlan,
  });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
it("loads the initial plan and replaces the empty state with reconciled saved values", async () => {
  const view = render(<TerminalDashboard />);
  expect(screen.getByText("AWAITING_DATA ...")).toBeInTheDocument();
  await act(async () => {});
  expect(ensureSession).toHaveBeenCalledOnce();
  expect(loadPlans).toHaveBeenCalledOnce();
  expect(loadPlan).toHaveBeenCalledWith("p");
  act(() => usePlanStore.setState({ simulation: result(), plan: makePlan({ id: "p" }) }));
  expect(screen.queryByText("AWAITING_DATA ...")).not.toBeInTheDocument();
  expect(screen.getByText("+100.0% over 1yr projection")).toBeInTheDocument();
  expect(screen.getByText(/TOTAL: \$200,000/)).toBeInTheDocument();
  expect(screen.getByText("70.0%")).toBeInTheDocument();
  expect(screen.getByText(/EFF_RATE: 10.0%/)).toBeInTheDocument();
  const flow = screen.getByTitle("2026: $70,000");
  fireEvent.mouseEnter(flow);
  expect(flow).toHaveStyle({ transform: "scaleY(1.25)" });
  fireEvent.mouseLeave(flow);
  expect(flow).toHaveStyle({ transform: "scaleY(1)" });
  act(() => vi.advanceTimersByTime(1000));
  view.unmount();
  expect(cancelAnimationFrame).toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
});
it("never marks a failed projection as funded merely because its final net worth is positive", async () => {
  usePlanStore.setState({ simulation: result(undefined, false) });
  render(<TerminalDashboard />);
  await act(async () => {});
  expect(screen.getByText("Spending unfunded from 2026")).toBeInTheDocument();
  expect(screen.queryByText("ON_TRACK")).not.toBeInTheDocument();
});
it("reports insolvent years and negative flows even when wealth later recovers", async () => {
  usePlanStore.setState({
    simulation: result([
      { ...snap, net_worth: -100, net_cash_flow: -500 },
      { ...snap, year: 2027 },
    ]),
  });
  const view = render(<TerminalDashboard />);
  await act(async () => {});
  expect(screen.getByText("Net worth negative from 2026")).toBeInTheDocument();
  expect(screen.getByTitle("2026: -$500")).toBeInTheDocument();
  act(() =>
    usePlanStore.setState({
      simulation: result([
        { ...snap, net_worth: 0, gross_income: 0, taxes: 0, accounts: {}, net_cash_flow: 0 },
      ]),
    }),
  );
  expect(view.container.textContent).not.toMatch(/NaN|Infinity/);
});
it("uses calendar-year gross income beside full-year taxes in the tax trend", async () => {
  const opening = {
    ...snap,
    year: 2026,
    gross_income: 50000,
    calendar_year_gross_income: 100000,
    taxes: 10000,
    effective_rate: 0.1,
  };
  usePlanStore.setState({ simulation: result([opening, { ...opening, year: 2027 }]) });
  render(<TerminalDashboard />);
  await act(async () => {});
  expect(screen.getByText("CAL_GROSS")).toBeInTheDocument();
  expect(screen.getByText("FULL_YEAR_TAXES")).toBeInTheDocument();
  expect(screen.getByText(/EFF_RATE: 10.0%/)).toBeInTheDocument();
});
it("prints money in the plan currency and restores USD when it closes", async () => {
  usePlanStore.setState({ simulation: result(), plan: makePlan({ id: "p", currency: "EUR" }) });
  const view = render(<TerminalDashboard />);
  await act(async () => {});
  expect(screen.getByText(/TOTAL: €200,000/)).toBeInTheDocument();
  expect(screen.getByTitle("2026: €70,000")).toBeInTheDocument();
  expect(view.container.textContent).not.toMatch(/\$\d/);
  view.unmount();
  expect(displayCurrency()).toBe("USD");
});
