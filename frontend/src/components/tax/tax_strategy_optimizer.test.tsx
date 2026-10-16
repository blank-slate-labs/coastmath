import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";

import { TaxStrategyOptimizer } from "./tax_strategy_optimizer";
import { usePlanStore } from "@/stores/plan_store";
import type { Account, TaxStrategyCompareResponse } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const listAccounts = vi.fn();
const updatePriorities = vi.fn();
const adapter = makeAdapter({ listAccounts, updatePriorities });
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
const compare = vi.fn();
vi.mock("@/api/client", () => ({
  compareTaxStrategies: (...args: unknown[]) => compare(...args),
  searchTaxStrategies: vi.fn(),
}));

const accounts = [
  {
    id: "ira",
    user_id: "u",
    name: "IRA",
    account_type: "traditional_ira",
    balance: 900000,
    owner: "self",
  },
  {
    id: "roth",
    user_id: "u",
    name: "Roth",
    account_type: "roth_ira",
    balance: 50000,
    owner: "self",
  },
  {
    id: "spouse-roth",
    user_id: "u",
    name: "Spouse Roth",
    account_type: "roth_ira",
    balance: 50000,
    owner: "spouse",
  },
  {
    id: "brok",
    user_id: "u",
    name: "Brokerage",
    account_type: "taxable_brokerage",
    balance: 400000,
    owner: "self",
    cost_basis: 150000,
  },
  {
    id: "nobasis",
    user_id: "u",
    name: "Unknown basis",
    account_type: "taxable_brokerage",
    balance: 40000,
    owner: "self",
    cost_basis: null,
  },
] as Account[];

const plan = makePlan({
  id: "p1",
  milestones: [{ id: "m1", name: "Retire" }],
  spouse: { name: "Sam", birth_year: 1982 },
});

const response: TaxStrategyCompareResponse = {
  objective: "net_legacy",
  objective_description:
    "Net estate after estate tax and income tax on pre-tax balances (higher is better)",
  baseline_key: "baseline",
  best_key: "fill_2200",
  candidates: [
    {
      key: "baseline",
      label: "No new conversions",
      success: true,
      failure_year: null,
      lifetime_taxes: 900000,
      lifetime_healthcare: 100000,
      final_net_worth: 5000000,
      net_legacy: 4800000,
      total_converted: 0,
      conversion_years: 0,
      irmaa_years: 6,
      aca_credit_lost_years: 0,
      peak_marginal_rate: 0.24,
      objective_value: 4800000,
      delta_vs_baseline: 0,
      is_best: false,
      notes: [],
    },
    {
      key: "fill_2200",
      label: "Convert to fill the 22% bracket",
      success: true,
      failure_year: null,
      lifetime_taxes: 850000,
      lifetime_healthcare: 90000,
      final_net_worth: 5100000,
      net_legacy: 4950000,
      total_converted: 600000,
      conversion_years: 8,
      irmaa_years: 2,
      aca_credit_lost_years: 1,
      peak_marginal_rate: 0.22,
      objective_value: 4950000,
      delta_vs_baseline: 150000,
      is_best: true,
      notes: [],
    },
  ],
  caveats: [
    "Only the listed candidates were simulated; the best result is the best of these, not a global optimum.",
  ],
  proposed_priority: null,
  pre_tax_discount_rate: 0.24,
};

describe("TaxStrategyOptimizer", () => {
  beforeEach(() => {
    listAccounts.mockReset().mockResolvedValue(accounts);
    updatePriorities.mockReset().mockResolvedValue([]);
    compare.mockReset().mockResolvedValue(response);
    usePlanStore.setState({ plan, loadPlan: vi.fn().mockResolvedValue(undefined) } as never);
  });

  it("removes obsolete results after changing comparison inputs", async () => {
    render(<TaxStrategyOptimizer />);
    await screen.findAllByRole("option", { name: "IRA (Primary person)" });
    fireEvent.change(screen.getByLabelText("Pre-tax source"), { target: { value: "ira" } });
    fireEvent.change(screen.getByLabelText("Roth destination"), { target: { value: "roth" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare strategies" }));
    expect(await screen.findByRole("button", { name: "Apply" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText(/MAGI cap/), { target: { value: "80000" } });
    expect(screen.queryByRole("table", { name: "Strategy comparison" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
    expect(updatePriorities).not.toHaveBeenCalled();
  });

  it("discards a comparison that completes after the underlying plan changes", async () => {
    let resolve!: (value: TaxStrategyCompareResponse) => void;
    compare.mockReturnValue(
      new Promise<TaxStrategyCompareResponse>((done) => {
        resolve = done;
      }),
    );
    render(<TaxStrategyOptimizer />);
    await screen.findAllByRole("option", { name: "IRA (Primary person)" });
    fireEvent.change(screen.getByLabelText("Pre-tax source"), { target: { value: "ira" } });
    fireEvent.change(screen.getByLabelText("Roth destination"), { target: { value: "roth" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare strategies" }));
    act(() => usePlanStore.setState({ plan: { ...plan, birth_year: 1980 } }));
    await act(async () => {
      resolve(response);
    });
    expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Compare strategies" })).toBeEnabled();
  });

  it("runs the comparison with the chosen window and brackets and applies the best candidate", async () => {
    render(<TaxStrategyOptimizer />);
    const source = await screen.findByLabelText("Pre-tax source");
    fireEvent.change(source, { target: { value: "ira" } });
    const targetOptions = Array.from(
      screen.getByLabelText("Roth destination").querySelectorAll("option"),
    ).map((o) => o.textContent);
    expect(targetOptions.some((t) => t?.includes("Spouse Roth"))).toBe(false);
    fireEvent.change(screen.getByLabelText("Roth destination"), { target: { value: "roth" } });
    fireEvent.change(screen.getByLabelText("Convert from"), { target: { value: "m1" } });
    fireEvent.click(screen.getByLabelText("Fill to 24%"));
    fireEvent.change(screen.getByLabelText(/MAGI cap/), { target: { value: "150000" } });
    fireEvent.change(screen.getByLabelText("Objective"), { target: { value: "lifetime_taxes" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare strategies" }));
    await waitFor(() =>
      expect(compare).toHaveBeenCalledWith("p1", {
        strategy_type: "roth_conversion",
        source_account_id: "ira",
        target_account_id: "roth",
        bracket_ceilings: [0.12, 0.22],
        magi_cap: 150000,
        start_milestone_id: "m1",
        end_milestone_id: null,
        objective: "lifetime_taxes",
      }),
    );
    const table = await screen.findByRole("table", { name: "Strategy comparison" });
    expect(table).toHaveTextContent("Convert to fill the 22% bracket · best tested");
    expect(screen.getByText(/Pre-tax balances net of/)).toHaveTextContent(
      "Pre-tax balances net of 24% income tax.",
    );
    expect(table).toHaveTextContent("+$150k");
    expect(table).toHaveTextContent("$600k over 8 yrs");
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() =>
      expect(updatePriorities).toHaveBeenCalledWith(
        "p1",
        [
          expect.objectContaining({
            priority_type: "roth_conversion",
            conversion_mode: "fill_bracket",
            bracket_ceiling_rate: 0.22,
            magi_cap: 150000,
            source_account_id: "ira",
            target_account_id: "roth",
            start_milestone_id: "m1",
            priority_rank: 1,
          }),
        ],
        0,
      ),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Applied");
    expect(screen.getAllByText(/not a global optimum/).length).toBeGreaterThanOrEqual(1);
  });

  it("validates inputs and reports comparison failures without changing the plan", async () => {
    compare.mockRejectedValueOnce(new Error("boom"));
    render(<TaxStrategyOptimizer />);
    await screen.findByLabelText("Pre-tax source");
    fireEvent.submit(screen.getByRole("button", { name: "Compare strategies" }).closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a pre-tax source");
    fireEvent.change(screen.getByLabelText("Pre-tax source"), { target: { value: "ira" } });
    fireEvent.change(screen.getByLabelText("Roth destination"), { target: { value: "roth" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare strategies" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not compare"));
    expect(updatePriorities).not.toHaveBeenCalled();
  });

  it("switches to gain harvesting with capital-gains brackets and requires a known basis", async () => {
    render(<TaxStrategyOptimizer />);
    await screen.findByLabelText("Pre-tax source");
    fireEvent.change(screen.getByLabelText("Strategy"), { target: { value: "gain_harvest" } });
    expect(screen.getByLabelText("Fill to 0%")).toBeChecked();
    expect(screen.queryByLabelText("Roth destination")).toBeNull();
    fireEvent.change(screen.getByLabelText("Taxable account"), { target: { value: "nobasis" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare strategies" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("cost basis");
    fireEvent.change(screen.getByLabelText("Taxable account"), { target: { value: "brok" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare strategies" }));
    await waitFor(() =>
      expect(compare).toHaveBeenCalledWith(
        "p1",
        expect.objectContaining({
          strategy_type: "gain_harvest",
          source_account_id: "brok",
          target_account_id: null,
          bracket_ceilings: [0, 0.15],
        }),
      ),
    );
  });
});

describe("TaxStrategyOptimizer with built-in federal brackets", () => {
  it("does not offer the top bracket, which has no top to fill", async () => {
    listAccounts.mockReset().mockResolvedValue(accounts);
    usePlanStore.setState({ plan, loadPlan: vi.fn().mockResolvedValue(undefined) } as never);
    render(<TaxStrategyOptimizer />);
    await screen.findAllByRole("option", { name: "IRA (Primary person)" });
    expect(
      screen
        .getAllByRole("checkbox", { name: /^Fill to / })
        .map((box) => box.parentElement?.textContent),
    ).toEqual([
      "Fill to 10%",
      "Fill to 12%",
      "Fill to 22%",
      "Fill to 24%",
      "Fill to 32%",
      "Fill to 35%",
    ]);
  });
});

describe("TaxStrategyOptimizer with custom federal brackets", () => {
  it("offers and sends only the plan's bracket rates", async () => {
    listAccounts.mockReset().mockResolvedValue(accounts);
    compare.mockReset().mockResolvedValue(response);
    usePlanStore.setState({
      plan: {
        ...plan,
        tax_settings: {
          federal_brackets: [
            [50000, 0.1],
            [150000, 0.2],
            [999999999, 0.3],
          ],
        },
      },
      loadPlan: vi.fn().mockResolvedValue(undefined),
    } as never);
    render(<TaxStrategyOptimizer />);
    await screen.findAllByRole("option", { name: "IRA (Primary person)" });
    expect(screen.getByRole("checkbox", { name: "Fill to 10%" })).not.toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "Fill to 12%" })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Fill to 30%" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Fill to 20%" }));
    fireEvent.change(screen.getByLabelText("Pre-tax source"), { target: { value: "ira" } });
    fireEvent.change(screen.getByLabelText("Roth destination"), { target: { value: "roth" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare strategies" }));
    await waitFor(() =>
      expect(compare).toHaveBeenCalledWith(
        "p1",
        expect.objectContaining({ bracket_ceilings: [0.2] }),
      ),
    );
  });
});
