import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

import { TaxStrategySearchPanel, windowRequest } from "./tax_strategy_search_panel";
import {
  applyStrategyCandidate,
  canonical,
  StrategyApplyConflict,
  StrategyApplyPartial,
} from "./tax_strategy_apply";
import { usePlanStore } from "@/stores/plan_store";
import type { Account, StrategySearchCandidate, StrategySearchResponse } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
const search = vi.fn();
vi.mock("@/api/client", () => ({ searchTaxStrategies: (...args: unknown[]) => search(...args) }));

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
    name: "No basis",
    account_type: "taxable_brokerage",
    balance: 4000,
    owner: "self",
    cost_basis: null,
  },
] as Account[];

const existingRule = {
  id: "r1",
  plan_id: "p1",
  priority_rank: 1,
  priority_type: "contribution",
  target_account_id: "roth",
  max_annual_amount: 500,
};
const plan = makePlan({
  id: "p1",
  priorities: [existingRule],
  priorities_revision: 4,
  milestones: [
    { id: "m1", name: "Retire" },
    { id: "m2", name: "Age 75" },
  ],
});

const metrics = {
  lifetime_taxes: 800000,
  lifetime_healthcare: 0,
  final_net_worth: 5e6,
  net_legacy: 4.5e6,
  lifetime_income: 4e6,
  lifetime_effective_tax_rate: 0.2,
  total_aca_subsidies: 0,
  total_rmd_distributions: 900000,
  total_irmaa_surcharge: 12000,
  total_converted: 0,
  total_harvested: 0,
  peak_marginal_rate: 0.24,
  failure_year: null,
  success: true,
  notes: [],
  window_index: null,
  improves_baseline: false,
};

const rule = {
  priority_rank: 2,
  priority_type: "roth_conversion",
  source_account_id: "ira",
  target_account_id: "roth",
  conversion_mode: "fill_bracket",
  use_plan_tax_target: true,
};
const best: StrategySearchCandidate = {
  ...metrics,
  key: "conversion+blend@2200/pretax_first/all",
  label: "Convert and blend at 22%, pre-tax first",
  stage: "combination",
  rank: 1,
  is_baseline: false,
  is_best: true,
  improves_baseline: true,
  actions: ["conversion", "blend"],
  bracket_rate: 0.22,
  drawdown_preset: "pretax_first",
  objective_value: 700000,
  delta_vs_baseline: -100000,
  lifetime_taxes: 700000,
  total_converted: 400000,
  changes: [
    {
      kind: "add",
      target: "priority",
      summary: "Add rule 2: Roth conversion from IRA to Roth, sized to the tax target",
      before: null,
      after: 2,
    },
    {
      kind: "add",
      target: "tax_target",
      summary: "Set the tax target to stay within the 22% federal bracket",
      before: null,
      after: { kind: "federal_bracket", bracket_rate: 0.22 },
    },
    {
      kind: "replace",
      target: "blend_drawdown",
      summary: "Turn on tax-targeted withdrawal blending",
      before: false,
      after: true,
    },
    {
      kind: "replace",
      target: "drawdown_order",
      summary: "Replace the withdrawal order: IRA > Brokerage > Roth",
      before: ["brok", "ira", "roth"],
      after: ["ira", "brok", "roth"],
    },
  ],
  proposal: {
    priorities_to_add: [rule as never],
    tax_settings: {
      tax_target: { kind: "federal_bracket", bracket_rate: 0.22 },
      blend_drawdown_to_tax_target: true,
    },
    drawdown_order: [
      { rank: 1, source_account_id: "ira" },
      { rank: 2, source_account_id: "brok" },
      { rank: 3, source_account_id: "roth" },
    ],
  },
};
const baseline: StrategySearchCandidate = {
  ...metrics,
  key: "baseline",
  label: "Keep the saved plan",
  stage: "baseline",
  rank: 2,
  is_baseline: true,
  is_best: false,
  actions: [],
  bracket_rate: null,
  drawdown_preset: "saved",
  objective_value: 800000,
  delta_vs_baseline: 0,
  changes: [],
  proposal: { priorities_to_add: [], tax_settings: null, drawdown_order: null },
};
const response: StrategySearchResponse = {
  objective: "lifetime_taxes",
  objective_description: "Lifetime income taxes (lower is better)",
  objective_direction: "lower",
  baseline_key: "baseline",
  best_key: best.key,
  candidates: [best, baseline],
  counts: {
    max_simulations: 12,
    simulated: 12,
    stage1_simulated: 3,
    stage2_simulated: 8,
    cache_hits: 2,
    grid_requested: 40,
    grid_size: 30,
    skipped_by_budget: 18,
    screened_out: 4,
    budget_exhausted: true,
  },
  survivor_rates: [0.12, 0.22],
  windows: [{ index: 0, label: "From Retire", start_milestone_id: "m1", end_milestone_id: null }],
  caveats: ["The best result is the best of those simulated, not a global optimum."],
  pre_tax_discount_rate: 0.24,
  priorities_revision: 4,
};

const latestPlan = {
  ...plan,
  priorities: [existingRule],
  priorities_revision: 4,
  tax_settings: null,
};

async function openAndRun() {
  render(<TaxStrategySearchPanel accounts={accounts} />);
  fireEvent.click(screen.getByText("Advanced search"));
  fireEvent.change(screen.getByLabelText("Conversion source"), { target: { value: "ira" } });
  fireEvent.change(screen.getByLabelText("Conversion destination"), { target: { value: "roth" } });
  fireEvent.change(screen.getByLabelText("Search objective"), {
    target: { value: "lifetime_taxes" },
  });
  fireEvent.click(screen.getByLabelText("Blend withdrawals up to the tax target"));
  fireEvent.click(screen.getByLabelText("Pre-tax accounts first"));
  fireEvent.click(screen.getByRole("button", { name: "Add timing window" }));
  fireEvent.change(screen.getByLabelText("Window 1 starts"), { target: { value: "m1" } });
  fireEvent.change(screen.getByLabelText("Simulation budget (2 to 128)"), {
    target: { value: "12" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Run search" }));
  await screen.findByRole("table", { name: "Search results" });
}

describe("TaxStrategySearchPanel", () => {
  beforeEach(() => {
    Object.values(adapter).forEach((fn) => fn.mockReset());
    adapter.fetchPlan.mockResolvedValue(latestPlan);
    adapter.updatePriorities.mockResolvedValue({ items: [], revision: 5 });
    adapter.updatePlan.mockResolvedValue(plan);
    adapter.listDrawdownOrder.mockResolvedValue([
      { id: "d3", plan_id: "p1", rank: 3, source_account_id: "roth" },
      { id: "d1", plan_id: "p1", rank: 1, source_account_id: "brok" },
      { id: "d2", plan_id: "p1", rank: 2, source_account_id: "ira" },
    ]);
    adapter.updateDrawdownOrder.mockResolvedValue([]);
    search.mockReset().mockResolvedValue(response);
    usePlanStore.setState({
      plan,
      accountsRevision: 0,
      loadPlan: vi.fn().mockResolvedValue(undefined),
    } as never);
  });

  it("validates choices locally and never calls the server for an invalid search", async () => {
    render(<TaxStrategySearchPanel accounts={accounts} />);
    fireEvent.click(screen.getByText("Advanced search"));
    fireEvent.click(screen.getByLabelText("Roth conversions to fill the bracket"));
    fireEvent.click(screen.getByRole("button", { name: "Run search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Choose at least one action or withdrawal order",
    );
    fireEvent.click(screen.getByLabelText("Capital-gain harvesting"));
    fireEvent.change(screen.getByLabelText("Harvest account"), { target: { value: "nobasis" } });
    fireEvent.click(screen.getByRole("button", { name: "Run search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("cost basis");
    fireEvent.change(screen.getByLabelText("Harvest account"), { target: { value: "brok" } });
    fireEvent.change(screen.getByLabelText("Simulation budget (2 to 128)"), {
      target: { value: "129" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("from 2 to 128");
    fireEvent.change(screen.getByLabelText("Simulation budget (2 to 128)"), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("must cover the baseline");
    expect(search).not.toHaveBeenCalled();
  });

  it("sends the chosen dimensions and reports counts, exhausted budget and ranked results", async () => {
    await openAndRun();
    expect(search).toHaveBeenCalledWith("p1", {
      objective: "lifetime_taxes",
      bracket_rates: [0.12, 0.22, 0.24],
      conversion: { source_account_id: "ira", target_account_id: "roth" },
      harvest: null,
      blend_withdrawals: true,
      drawdown_presets: ["pretax_first"],
      windows: [{ start_milestone_id: "m1", end_milestone_id: null }],
      max_simulations: 12,
    });
    expect(screen.getByTestId("search-counts")).toHaveTextContent("Simulated 12 of up to 12");
    expect(screen.getByTestId("search-counts")).toHaveTextContent("Searched first: 12%, 22%");
    // Combinations at the surviving rates and at the other rates both count as left out.
    expect(
      screen.getByText(/Budget used up: 22 combinations were not simulated/),
    ).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Search results" });
    expect(table).toHaveTextContent("best simulated");
    expect(table).toHaveTextContent("-$100k");
    expect(screen.getByText(/not a global optimum/)).toBeInTheDocument();
    // The objective's own description carries the direction; it is said once.
    const objective = screen.getByText(/^Objective:/);
    expect(objective).toHaveTextContent("Objective: Lifetime income taxes (lower is better).");
    expect(objective.textContent?.match(/is better/g)).toHaveLength(1);
    expect(
      screen.queryByRole("button", { name: /Review Keep the saved plan/ }),
    ).not.toBeInTheDocument();
    expect(adapter.updatePriorities).not.toHaveBeenCalled();
  });

  it("does not offer the built-in top bracket, which has no top to fill", () => {
    render(<TaxStrategySearchPanel accounts={accounts} />);
    fireEvent.click(screen.getByText("Advanced search"));
    expect(
      screen.getAllByLabelText(/% bracket$/).map((box) => box.parentElement?.textContent),
    ).toEqual([
      "10% bracket",
      "12% bracket",
      "22% bracket",
      "24% bracket",
      "32% bracket",
      "35% bracket",
    ]);
  });

  it("offers and sends only the plan's own bracket rates", async () => {
    usePlanStore.setState({
      plan: {
        ...plan,
        tax_settings: {
          ...plan.tax_settings,
          federal_brackets: [
            [50000, 0.1],
            [150000, 0.2],
            [1000000000, 0.3],
          ],
        },
      },
    } as never);
    render(<TaxStrategySearchPanel accounts={accounts} />);
    fireEvent.click(screen.getByText("Advanced search"));
    // The open 30% top bracket has nothing to fill, so it is not offered.
    expect(
      screen.getAllByLabelText(/% bracket$/).map((box) => box.parentElement?.textContent),
    ).toEqual(["10% bracket", "20% bracket"]);
    fireEvent.change(screen.getByLabelText("Conversion source"), { target: { value: "ira" } });
    fireEvent.change(screen.getByLabelText("Conversion destination"), {
      target: { value: "roth" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run search" }));
    // The default 12%, 22% and 24% choices are not in these brackets.
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose at least one bracket rate");
    fireEvent.click(screen.getByLabelText("20% bracket"));
    fireEvent.click(screen.getByRole("button", { name: "Run search" }));
    await waitFor(() => expect(search).toHaveBeenCalled());
    expect(search.mock.calls[0][1].bracket_rates).toEqual([0.2]);
  });

  it("formats the effective-rate objective as a rate", async () => {
    search.mockResolvedValue({
      ...response,
      objective: "lifetime_effective_tax_rate",
      objective_direction: "lower",
      candidates: [
        { ...best, objective_value: 0.2, delta_vs_baseline: -0.015 },
        { ...baseline, objective_value: 0.215 },
      ],
    });
    await openAndRun();
    const table = screen.getByRole("table", { name: "Search results" });
    expect(table).toHaveTextContent("20%");
    expect(table).toHaveTextContent("-1.5 pts");
  });

  it("applies after review: rules with the search revision, then tax settings, then the withdrawal order", async () => {
    await openAndRun();
    fireEvent.click(screen.getByRole("button", { name: `Review ${best.label}` }));
    const panel = screen.getByRole("region", { name: "Review changes" });
    for (const change of best.changes) expect(panel).toHaveTextContent(change.summary);
    expect(panel).toHaveTextContent("revision 4");
    fireEvent.click(within(panel).getByRole("button", { name: "Apply to plan" }));
    await waitFor(() => expect(adapter.updateDrawdownOrder).toHaveBeenCalled());
    expect(adapter.updatePriorities).toHaveBeenCalledWith(
      "p1",
      [
        expect.objectContaining({
          priority_rank: 1,
          priority_type: "contribution",
          target_account_id: "roth",
        }),
        expect.objectContaining({
          priority_rank: 2,
          priority_type: "roth_conversion",
          source_account_id: "ira",
          use_plan_tax_target: true,
        }),
      ],
      4,
    );
    expect(adapter.updatePlan).toHaveBeenCalledWith("p1", {
      tax_settings: expect.objectContaining({
        tax_target: { kind: "federal_bracket", bracket_rate: 0.22 },
        blend_drawdown_to_tax_target: true,
        mode: "detailed",
      }),
    });
    expect(adapter.updateDrawdownOrder).toHaveBeenCalledWith("p1", best.proposal.drawdown_order);
    expect(await screen.findByText(/Applied "Convert and blend/)).toBeInTheDocument();
    expect(usePlanStore.getState().loadPlan).toHaveBeenCalledWith("p1");
    expect(screen.queryByRole("table", { name: "Search results" })).not.toBeInTheDocument();
  });

  it("keeps the draft and requires review when the allocation save answers 409", async () => {
    adapter.updatePriorities.mockRejectedValue(
      Object.assign(new Error("conflict"), { status: 409 }),
    );
    await openAndRun();
    fireEvent.click(screen.getByRole("button", { name: `Review ${best.label}` }));
    fireEvent.click(screen.getByRole("button", { name: "Apply to plan" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "changed in another session. Nothing more was applied",
    );
    expect(adapter.updatePlan).not.toHaveBeenCalled();
    expect(adapter.updateDrawdownOrder).not.toHaveBeenCalled();
    // The draft stays visible; the only way forward is an explicit review, not a retry.
    expect(screen.getByRole("region", { name: "Review changes" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply to plan" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Retry remaining changes" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Search results" })).toBeInTheDocument();
    expect(adapter.updatePriorities).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Review latest saved plan" }));
    await waitFor(() => expect(usePlanStore.getState().loadPlan).toHaveBeenCalledWith("p1"));
  });

  it("stops before writing anything when the saved rules moved on since the search", async () => {
    adapter.fetchPlan.mockResolvedValue({ ...latestPlan, priorities_revision: 5 });
    await openAndRun();
    fireEvent.click(screen.getByRole("button", { name: `Review ${best.label}` }));
    fireEvent.click(screen.getByRole("button", { name: "Apply to plan" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "allocation rules changed since the search ran",
    );
    expect(adapter.updatePriorities).not.toHaveBeenCalled();
    expect(adapter.updatePlan).not.toHaveBeenCalled();
  });

  it("after a partial failure retries only the unsaved steps", async () => {
    adapter.updatePlan.mockRejectedValueOnce(new Error("offline"));
    await openAndRun();
    fireEvent.click(screen.getByRole("button", { name: `Review ${best.label}` }));
    fireEvent.click(screen.getByRole("button", { name: "Apply to plan" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Saved: allocation rules. Not saved: tax target settings, withdrawal order.",
    );
    expect(adapter.updateDrawdownOrder).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry remaining changes" }));
    await waitFor(() => expect(adapter.updateDrawdownOrder).toHaveBeenCalledTimes(1));
    expect(adapter.updatePriorities).toHaveBeenCalledTimes(1);
    expect(adapter.updatePlan).toHaveBeenCalledTimes(2);
  });

  it("discards a finished search when the underlying plan changes", async () => {
    await openAndRun();
    usePlanStore.setState({ plan: { ...plan, birth_year: 1980 } } as never);
    await waitFor(() =>
      expect(screen.queryByRole("table", { name: "Search results" })).not.toBeInTheDocument(),
    );
  });
});

describe("applyStrategyCandidate", () => {
  beforeEach(() => {
    Object.values(adapter).forEach((fn) => fn.mockReset());
    adapter.fetchPlan.mockResolvedValue(latestPlan);
    adapter.listDrawdownOrder.mockResolvedValue([
      { id: "d1", plan_id: "p1", rank: 1, source_account_id: "brok" },
      { id: "d2", plan_id: "p1", rank: 2, source_account_id: "ira" },
      { id: "d3", plan_id: "p1", rank: 3, source_account_id: "roth" },
    ]);
  });

  it("refuses a changed saved tax target, blend flag or withdrawal order before any write", async () => {
    adapter.fetchPlan.mockResolvedValue({
      ...latestPlan,
      tax_settings: { tax_target: { kind: "magi", amount: 90000 } },
    });
    await expect(applyStrategyCandidate(adapter, "p1", best, 4)).rejects.toBeInstanceOf(
      StrategyApplyConflict,
    );
    adapter.fetchPlan.mockResolvedValue({
      ...latestPlan,
      tax_settings: { blend_drawdown_to_tax_target: true },
    });
    await expect(applyStrategyCandidate(adapter, "p1", best, 4)).rejects.toThrow(
      /blending changed/,
    );
    adapter.fetchPlan.mockResolvedValue(latestPlan);
    adapter.listDrawdownOrder.mockResolvedValue([
      { id: "d1", plan_id: "p1", rank: 1, source_account_id: "ira" },
    ]);
    await expect(applyStrategyCandidate(adapter, "p1", best, 4)).rejects.toThrow(
      /withdrawal order changed/,
    );
    expect(adapter.updatePriorities).not.toHaveBeenCalled();
    expect(adapter.updatePlan).not.toHaveBeenCalled();
    expect(adapter.updateDrawdownOrder).not.toHaveBeenCalled();
  });

  it("applies a saved target that differs only in unset defaults and merges, never drops, other settings", async () => {
    const saved = { kind: "federal_bracket", bracket_rate: 0.12, avoid_niit: false, amount: null };
    const replacing = {
      ...best,
      changes: best.changes.map((c) =>
        c.target === "tax_target"
          ? { ...c, before: { kind: "federal_bracket", bracket_rate: 0.12 } }
          : c,
      ),
    };
    adapter.fetchPlan.mockResolvedValue({
      ...latestPlan,
      tax_settings: { tax_target: saved, dependent_birth_years: [2010] },
    });
    adapter.updatePriorities.mockResolvedValue({ items: [], revision: 5 });
    adapter.updatePlan.mockResolvedValue(plan);
    adapter.updateDrawdownOrder.mockResolvedValue([]);
    expect(await applyStrategyCandidate(adapter, "p1", replacing, 4)).toEqual([
      "rules",
      "tax_settings",
      "drawdown_order",
    ]);
    expect(adapter.updatePlan).toHaveBeenCalledWith("p1", {
      tax_settings: expect.objectContaining({
        dependent_birth_years: [2010],
        tax_target: { kind: "federal_bracket", bracket_rate: 0.22 },
      }),
    });
  });

  it("skips untouched steps and reports a partial save with what is left", async () => {
    const orderOnly: StrategySearchCandidate = {
      ...best,
      proposal: {
        priorities_to_add: [],
        tax_settings: null,
        drawdown_order: best.proposal.drawdown_order,
      },
      changes: best.changes.filter((c) => c.target === "drawdown_order"),
    };
    adapter.updateDrawdownOrder.mockRejectedValue(new Error("down"));
    const failure = await applyStrategyCandidate(adapter, "p1", orderOnly, 99).catch((e) => e);
    expect(failure).toBeInstanceOf(StrategyApplyPartial);
    expect(failure.remaining).toEqual(["drawdown_order"]);
    expect(adapter.updatePriorities).not.toHaveBeenCalled(); // no rules to add, so the revision is not compared
    expect(adapter.updatePlan).not.toHaveBeenCalled();
  });

  it("canonicalises targets by dropping unset members", () => {
    expect(canonical({ b: null, a: 1, c: false, d: { e: undefined, f: 2 } })).toEqual({
      a: 1,
      d: { f: 2 },
    });
  });

  it("builds year, age and milestone windows and rejects incomplete ones", () => {
    expect(
      windowRequest({ start: "__age", startValue: "60", end: "__age", endValue: "72" }),
    ).toEqual({ window: { start_age: 60, end_age: 72 }, error: null });
    expect(windowRequest({ start: "__year", startValue: "2030", end: "m1" })).toEqual({
      window: { start_year: 2030, end_milestone_id: "m1" },
      error: null,
    });
    expect(windowRequest({ start: "m1", end: "" }).window).toEqual({
      start_milestone_id: "m1",
      end_milestone_id: null,
    });
    expect(windowRequest({ start: "", end: "" }).error).toMatch(/needs a start or an end/);
    expect(windowRequest({ start: "__year", startValue: "", end: "" }).error).toMatch(
      /start year must be a whole number/,
    );
    expect(
      windowRequest({ start: "__age", startValue: "70", end: "__age", endValue: "65" }).error,
    ).toMatch(/end age must not be before/);
  });

  it("sends a year window from the panel", async () => {
    render(<TaxStrategySearchPanel accounts={accounts} />);
    fireEvent.click(screen.getByText("Advanced search"));
    fireEvent.change(screen.getByLabelText("Conversion source"), { target: { value: "ira" } });
    fireEvent.change(screen.getByLabelText("Conversion destination"), {
      target: { value: "roth" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add timing window" }));
    fireEvent.change(screen.getByLabelText("Window 1 starts"), { target: { value: "__year" } });
    fireEvent.change(screen.getByLabelText("Window 1 start year"), { target: { value: "2030" } });
    fireEvent.change(screen.getByLabelText("Window 1 ends"), { target: { value: "__age" } });
    fireEvent.change(screen.getByLabelText("Window 1 end age"), { target: { value: "72" } });
    search.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Run search" }));
    await waitFor(() => expect(search).toHaveBeenCalled());
    expect(search.mock.calls[0][1].windows).toEqual([{ start_year: 2030, end_age: 72 }]);
  });

  it("creates a window's milestones before the rules, reusing a matching saved one", async () => {
    const windowed: StrategySearchCandidate = {
      ...best,
      proposal: {
        priorities_to_add: [
          {
            ...rule,
            start_milestone_id: "strategy-window-1-start",
            end_milestone_id: "strategy-window-1-end",
          } as never,
        ],
        tax_settings: null,
        drawdown_order: null,
        milestones_to_add: [
          {
            id: "strategy-window-1-start",
            name: "Start of 2030",
            trigger_type: "date",
            trigger_value: null,
            trigger_date: "2030-01-01",
          },
          {
            id: "strategy-window-1-end",
            name: "Age 73",
            trigger_type: "age",
            trigger_value: 73,
            trigger_date: null,
          },
        ],
      },
    };
    adapter.fetchPlan.mockResolvedValue({
      ...latestPlan,
      milestones: [{ id: "m73", name: "RMDs", trigger_type: "age", trigger_value: 73 }],
    });
    adapter.createMilestone.mockResolvedValue({ id: "new-2030" });
    await applyStrategyCandidate(adapter, "p1", windowed, 4);
    expect(adapter.createMilestone).toHaveBeenCalledTimes(1);
    expect(adapter.createMilestone).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ trigger_type: "date", trigger_date: "2030-01-01" }),
    );
    expect(adapter.updatePriorities).toHaveBeenCalledWith(
      "p1",
      [
        expect.objectContaining({ priority_rank: 1 }),
        expect.objectContaining({
          priority_rank: 2,
          start_milestone_id: "new-2030",
          end_milestone_id: "m73",
        }),
      ],
      4,
    );
  });
});
