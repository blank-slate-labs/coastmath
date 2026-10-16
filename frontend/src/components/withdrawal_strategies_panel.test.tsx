import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import WithdrawalStrategiesPanel from "./withdrawal_strategies_panel";
import { usePlanStore } from "@/stores/plan_store";
import type { WithdrawalCompareResponse } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const compare = vi.fn();
const adapter = makeAdapter({ compareWithdrawalStrategies: compare });
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

const plan = makePlan({ id: "p1", milestones: [{ id: "m1", name: "Retire" }] });
const outcome = (method: string, label: string, first: number, min: number, success = true) => ({
  method,
  label,
  success,
  failure_year: success ? null : 2060,
  start_year: 2040,
  first_year_spending: first,
  total_real_spending: first * 20,
  median_real_spending: first,
  min_real_spending: min,
  max_real_spending: first * 1.1,
  real_spending_drawdown: (first - min) / first,
  years_below_planned: 3,
  final_net_worth: 900000,
  lifetime_taxes: 120000,
  monte_carlo_success_rate: success ? 0.9 : 0.4,
  monte_carlo_p10_final_net_worth: 100000,
  spending_path: [
    {
      year: 2040,
      age: 65,
      nominal: first,
      real: first,
      planned_nominal: 50000,
      net_worth: 1000000,
    },
    {
      year: 2041,
      age: 66,
      nominal: first * 1.02,
      real: min,
      planned_nominal: 51000,
      net_worth: 950000,
    },
  ],
  notes: [],
});
const response: WithdrawalCompareResponse = {
  initial_rate: 0.04,
  planned: outcome("planned", "Planned", 50000, 50000),
  strategies: [
    outcome("constant_dollar", "Constant dollar", 48000, 48000),
    outcome("guyton_klinger", "Guyton-Klinger guardrails", 48000, 43200, false),
  ],
  caveats: ["The comparison ranks nothing."],
  method_labels: {},
};

describe("WithdrawalStrategiesPanel", () => {
  beforeEach(() => {
    compare.mockReset().mockResolvedValue(response);
    usePlanStore.setState({ plan } as never);
  });

  it("defaults to retirement and sends the chosen rules in decimal units", async () => {
    render(<WithdrawalStrategiesPanel />);
    expect(screen.getByLabelText("Withdrawals start at milestone")).toHaveValue("m1");
    fireEvent.change(screen.getByLabelText(/Initial withdrawal rate/), {
      target: { value: "3.5" },
    });
    fireEvent.click(screen.getByLabelText(/Vanguard dynamic spending/));
    fireEvent.change(screen.getByLabelText(/Monte Carlo trials/), { target: { value: "100" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare withdrawal rules" }));
    await waitFor(() =>
      expect(compare).toHaveBeenCalledWith("p1", {
        methods: ["constant_dollar", "guyton_klinger"],
        initial_rate: 0.035,
        start_milestone_id: "m1",
        start_age: null,
        monte_carlo_trials: 100,
        seed: 42,
      }),
    );
    const table = await screen.findByRole("table", { name: "Withdrawal strategy comparison" });
    expect(table).toHaveTextContent("Planned spending (this plan)");
    expect(table).toHaveTextContent("Fails 2060");
    expect(table).toHaveTextContent("10%"); // Guyton-Klinger largest real cut
    expect(table).toHaveTextContent("90%");
    expect(screen.getByRole("img", { name: /Real spending by year/ })).toBeInTheDocument();
  });

  it("starts from the plan's saved strategy", async () => {
    usePlanStore.setState({
      plan: makePlan({
        ...plan,
        withdrawal_strategy: {
          enabled: true,
          method: "rmd_table",
          initial_rate: 0.045,
          start_age: 63,
        },
      }),
    });
    render(<WithdrawalStrategiesPanel />);
    expect(screen.getByLabelText(/Initial withdrawal rate/)).toHaveValue(4.5);
    expect(screen.getByLabelText(/or at age/)).toHaveValue(63);
    expect(screen.getByLabelText("Withdrawals start at milestone")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Compare withdrawal rules" }));
    await waitFor(() =>
      expect(compare).toHaveBeenCalledWith(
        "p1",
        expect.objectContaining({
          methods: ["rmd_table", "constant_dollar", "guyton_klinger", "vanguard_dynamic"],
          initial_rate: 0.045,
          start_milestone_id: null,
          start_age: 63,
        }),
      ),
    );
  });

  it("reports comparison failures", async () => {
    compare.mockRejectedValueOnce(new Error("boom"));
    render(<WithdrawalStrategiesPanel />);
    fireEvent.change(screen.getByLabelText(/or at age/), { target: { value: "65" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare withdrawal rules" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not compare"));
  });
});
