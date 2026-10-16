import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ClaimingExplorer from "./claiming_explorer";
import { divergingFill } from "./claiming_charts";
import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import type {
  ClaimingExplorerResponse,
  ClaimingPerson,
  ClaimingRun,
  SimulationResult,
} from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";
import { makeIncome } from "@/test_support/record_builders";

const explore = vi.fn();
const adapter = makeAdapter({ exploreClaimingAges: explore });
vi.mock("@/storage/context", async (importOriginal) =>
  (await import("@/test_support/storage_mock")).mockStorageContextOver(
    await importOriginal<typeof import("@/storage/context")>(),
    () => (useRealStorage ? null : adapter),
  ),
);
let useRealStorage = false;

const YEARS = [2026, 2027, 2028];
const plan = makePlan({ id: "p1", birth_year: 1965 });
const simulation = (): SimulationResult =>
  ({
    metadata: { start_year: 2026 },
    yearly_snapshots: YEARS.map((year) => ({ year, accounts: {} })),
  }) as unknown as SimulationResult;

function person(
  owner: "self" | "spouse",
  current: number | null,
  ages: number[],
  reason: ClaimingPerson["reason"] = null,
): ClaimingPerson {
  return {
    owner,
    adjustable: reason === null,
    reason,
    income_id: reason === "no_benefit" ? null : `${owner}-ss`,
    birth_year: owner === "self" ? 1965 : 1967,
    birth_month: 1,
    full_retirement_age: 67,
    current_claim_age: current,
    candidate_ages: ages,
    benefit_basis: "amount",
  };
}

function run(
  ages: Record<string, number>,
  endChange: number,
  ssChange: number,
  success = true,
): ClaimingRun {
  return {
    claim_ages: ages,
    first_year_benefits: Object.fromEntries(Object.entries(ages).map(([o, a]) => [o, 1_000 * a])),
    social_security_by_year: [0, 10_000 + ssChange / 2, 10_000 + ssChange / 2],
    lifetime_social_security: 20_000 + ssChange,
    lifetime_taxes: 5_000,
    end_net_worth: 500_000 + endChange,
    end_net_worth_after_tax: 400_000 + endChange,
    success,
    failure_year: success ? null : 2028,
    end_net_worth_after_tax_change: endChange,
    lifetime_social_security_change: ssChange,
  };
}

/** Primary person 66–68 × partner 64–66; current 67/65; best 68/66. */
function couple(): ClaimingExplorerResponse {
  const runs: ClaimingRun[] = [];
  for (const a of [66, 67, 68])
    for (const b of [64, 65, 66]) {
      runs.push(
        run(
          { self: a, spouse: b },
          (a - 67) * 10_000 + (b - 65) * 5_000,
          (a - 67) * 2_000 + (b - 65) * 3_000,
        ),
      );
    }
  return {
    persons: [person("self", 67, [66, 67, 68]), person("spouse", 65, [64, 65, 66])],
    years: YEARS,
    current: run({ self: 67, spouse: 65 }, 0, 0),
    runs,
    best_index: 8,
    best_end_net_worth_after_tax_change: 15_000,
    best_lifetime_social_security_change: 5_000,
    pre_tax_discount_rate: 0.24,
    patches: [
      ...[66, 67, 68].map((age) => ({
        owner: "self" as const,
        claiming_age: age,
        income_id: "self-ss",
        changes: {
          claiming_age: age,
          start_milestone_id: null,
          start_month: null,
          annual_amount: 20_000 + age,
        },
      })),
      ...[64, 65, 66].map((age) => ({
        owner: "spouse" as const,
        claiming_age: age,
        income_id: "spouse-ss",
        changes: {
          claiming_age: age,
          start_milestone_id: null,
          start_month: null,
          annual_amount: 10_000 + age,
        },
      })),
    ],
  };
}

function single(): ClaimingExplorerResponse {
  const runs = [62, 67, 70].map((age) =>
    run({ self: age }, (age - 67) * 1_000, (age - 67) * 500, age !== 62),
  );
  return {
    persons: [person("self", 66.5, [62, 67, 70]), person("spouse", null, [], "already_claimed")],
    years: YEARS,
    current: run({ self: 66.5 }, 0, 0),
    runs,
    best_index: 2,
    best_end_net_worth_after_tax_change: 3_000,
    best_lifetime_social_security_change: 1_500,
    pre_tax_discount_rate: 0.3,
    patches: [62, 67, 70].map((age) => ({
      owner: "self" as const,
      claiming_age: age,
      income_id: "self-ss",
      changes: { claiming_age: age, start_milestone_id: null, start_month: null },
    })),
  };
}

const updateIncome = vi.fn();
const onEditSection = vi.fn();

beforeEach(() => {
  useRealStorage = false;
  explore.mockReset().mockResolvedValue(couple());
  updateIncome.mockReset().mockResolvedValue(true);
  onEditSection.mockReset();
  usePlanStore.setState({
    plan,
    simulation: simulation(),
    isSimulating: false,
    currencyMode: "nominal",
    error: null,
    updateIncome,
  } as never);
  useSaveStore.setState({ pending: 0, failed: [], failures: {}, lastSavedAt: null } as never);
});

const cells = () =>
  screen
    .getAllByRole("button", { pressed: false })
    .concat(screen.getAllByRole("button", { pressed: true }))
    .filter((el) => el.hasAttribute("data-cell"));
const selectedCell = () =>
  screen.getAllByRole("button", { pressed: true }).find((el) => el.hasAttribute("data-cell"))!;

describe("two people", () => {
  it("draws the age grid with the best cell selected and a readout for it", async () => {
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    const grid = await screen.findByRole("group", {
      name: /Primary person by Partner, End net worth, after tax change/,
    });
    expect(explore).toHaveBeenCalledWith("p1");
    expect(cells()).toHaveLength(9);
    expect(selectedCell()).toHaveAttribute("data-cell", "68|66");
    expect(selectedCell()).toHaveAccessibleName(
      "Primary person 68, Partner 66: End net worth, after tax +$15k, highest",
    );
    expect(within(grid).getByTestId("current-marker")).toBeInTheDocument();
    const readout = screen.getByText("End net worth, after tax", { selector: "dt" }).closest("dl")!;
    expect(readout).toHaveTextContent("68 · $68,000/yr");
    expect(readout).toHaveTextContent("66 · $66,000/yr");
    expect(readout).toHaveTextContent("$415,000 +$15k");
    expect(readout).toHaveTextContent("$25,000 +$5k");
    expect(screen.getByRole("button", { name: "Use these ages" })).toBeEnabled();
    expect(
      screen.getByRole("img", { name: "Household Social Security received to date by year" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Selected (highest)")).toBeInTheDocument();
  });

  it("moves the selection with the keyboard and hides the apply button on the current ages", async () => {
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    await screen.findAllByRole("group");
    const start = selectedCell();
    fireEvent.keyDown(start, { key: "ArrowUp" });
    expect(selectedCell()).toHaveAttribute("data-cell", "67|66");
    expect(document.activeElement).toBe(selectedCell());
    fireEvent.keyDown(selectedCell(), { key: "ArrowLeft" });
    expect(selectedCell()).toHaveAttribute("data-cell", "67|65");
    expect(screen.queryByRole("button", { name: "Use these ages" })).not.toBeInTheDocument();
    expect(screen.getByText("Selected")).toBeInTheDocument();
    fireEvent.keyDown(selectedCell(), { key: "Home" });
    expect(selectedCell()).toHaveAttribute("data-cell", "67|64");
    fireEvent.keyDown(selectedCell(), { key: "End" });
    expect(selectedCell()).toHaveAttribute("data-cell", "67|66");
    fireEvent.keyDown(selectedCell(), { key: "ArrowDown" });
    fireEvent.keyDown(selectedCell(), { key: "ArrowDown" });
    fireEvent.keyDown(selectedCell(), { key: "ArrowRight" });
    expect(selectedCell()).toHaveAttribute("data-cell", "68|66");
    fireEvent.keyDown(selectedCell(), { key: "a" });
    const other = cells().find((el) => el.getAttribute("data-cell") === "66|64")!;
    fireEvent.keyDown(other, { key: "Enter" });
    expect(selectedCell()).toHaveAttribute("data-cell", "66|64");
    fireEvent.click(cells().find((el) => el.getAttribute("data-cell") === "66|65")!);
    expect(selectedCell()).toHaveAttribute("data-cell", "66|65");
  });

  it("recolors by lifetime Social Security", async () => {
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    await screen.findAllByRole("group");
    const fillOf = () => selectedCell().querySelector("rect")!.getAttribute("fill");
    const before = cells()
      .find((el) => el.getAttribute("data-cell") === "66|66")!
      .querySelector("rect")!
      .getAttribute("fill");
    fireEvent.click(screen.getByRole("button", { name: "Lifetime Social Security" }));
    expect(
      screen.getByRole("group", { name: /Lifetime Social Security change/ }),
    ).toBeInTheDocument();
    expect(selectedCell()).toHaveAccessibleName(
      "Primary person 68, Partner 66: Lifetime Social Security +$5k, highest",
    );
    const after = cells()
      .find((el) => el.getAttribute("data-cell") === "66|66")!
      .querySelector("rect")!
      .getAttribute("fill");
    expect(after).not.toBe(before);
    expect(fillOf()).toContain("var(--viz-1)");
  });

  it("shows today's dollars with the plan deflators", async () => {
    usePlanStore.setState({ currencyMode: "inflation_adjusted" } as never);
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    await screen.findAllByRole("group");
    const readout = screen.getByText("End net worth, after tax", { selector: "dt" }).closest("dl")!;
    const factor = 1.03 ** 2; // the default 3% inflation, two years on
    expect(readout).toHaveTextContent(`$${Math.round(415_000 / factor).toLocaleString("en-US")}`);
    const lifetime = 12_500 / 1.03 + 12_500 / factor;
    expect(readout).toHaveTextContent(`$${Math.round(lifetime).toLocaleString("en-US")}`);
    fireEvent.click(screen.getByRole("button", { name: "Lifetime Social Security" }));
    const delta = lifetime - (10_000 / 1.03 + 10_000 / factor);
    expect(selectedCell().getAttribute("aria-label")).toContain(`+$${Math.round(delta / 1000)}k`);
  });

  it("saves the changed ages through the income update and keeps the plan's own age otherwise", async () => {
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    await screen.findAllByRole("group");
    fireEvent.click(cells().find((el) => el.getAttribute("data-cell") === "68|65")!);
    fireEvent.click(screen.getByRole("button", { name: "Use these ages" }));
    await waitFor(() => expect(updateIncome).toHaveBeenCalledTimes(1));
    expect(updateIncome).toHaveBeenCalledWith("p1", "self-ss", {
      claiming_age: 68,
      start_milestone_id: null,
      start_month: null,
      annual_amount: 20_068,
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Use these ages" })).toBeEnabled(),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("states the change it applied and undoes it with the saved values", async () => {
    usePlanStore.setState({
      plan: {
        ...plan,
        income_streams: [
          {
            id: "self-ss",
            claiming_age: 67,
            start_milestone_id: "ss",
            start_month: 3,
            annual_amount: 24_000,
          },
        ],
      },
    } as never);
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    await screen.findAllByRole("group");
    fireEvent.click(cells().find((el) => el.getAttribute("data-cell") === "68|65")!);
    fireEvent.click(screen.getByRole("button", { name: "Use these ages" }));
    const done = await screen.findByText(/^Claiming ages .+ → /);
    expect(done.textContent).toMatch(/→ 68 \/ 65\./);
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(updateIncome).toHaveBeenLastCalledWith("p1", "self-ss", {
        claiming_age: 67,
        start_milestone_id: "ss",
        start_month: 3,
        annual_amount: 24_000,
      }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument(),
    );
    usePlanStore.setState({ plan } as never);
  });

  it("keeps the selection and shows the save error when a save fails", async () => {
    updateIncome.mockImplementation(async (planId: string, incomeId: string) => {
      if (incomeId === "spouse-ss") {
        useSaveStore.setState({
          failures: {
            [`put /plans/${planId}/incomes/${incomeId}`]: {
              message: "Save income was not saved.",
              rejected: true,
            },
          },
        } as never);
        return false;
      }
      return true;
    });
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    await screen.findAllByRole("group");
    fireEvent.click(screen.getByRole("button", { name: "Use these ages" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Save income was not saved.");
    expect(updateIncome).toHaveBeenCalledTimes(2);
    expect(selectedCell()).toHaveAttribute("data-cell", "68|66");
  });

  it("falls back to the store error or a plain message", async () => {
    updateIncome.mockImplementation(async () => {
      usePlanStore.setState({ error: "Network down" } as never);
      return false;
    });
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    await screen.findAllByRole("group");
    fireEvent.click(screen.getByRole("button", { name: "Use these ages" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Network down");
    expect(updateIncome).toHaveBeenCalledTimes(1);
  });
});

describe("one person", () => {
  it("draws columns, marks the current age and names the partner's reason", async () => {
    explore.mockResolvedValue(single());
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    const chart = await screen.findByRole("group", {
      name: /change from the current plan by Primary person's claim age/,
    });
    expect(within(chart).getAllByRole("button")).toHaveLength(3);
    expect(within(chart).getByTestId("current-marker")).toBeInTheDocument();
    expect(selectedCell()).toHaveAttribute("data-cell", "70");
    expect(screen.getByText("Partner: benefits already started.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit income" }));
    expect(onEditSection).toHaveBeenCalledWith("income");
    fireEvent.keyDown(selectedCell(), { key: "ArrowLeft" });
    fireEvent.keyDown(selectedCell(), { key: "ArrowLeft" });
    expect(selectedCell()).toHaveAttribute("data-cell", "62");
    expect(screen.getByText("Fails in 2028")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use these ages" }));
    await waitFor(() =>
      expect(updateIncome).toHaveBeenCalledWith("p1", "self-ss", {
        claiming_age: 62,
        start_milestone_id: null,
        start_month: null,
      }),
    );
    expect(screen.getAllByText(/net of 30(\.0)?% income tax/).length).toBeGreaterThan(0);
  });

  it("says whose earnings withhold benefits before full retirement age, only when they do", async () => {
    const response = couple();
    response.persons[1] = { ...response.persons[1], earnings_test_withholds: true };
    explore.mockResolvedValue(response);
    const { unmount } = render(<ClaimingExplorer onEditSection={onEditSection} />);
    expect(
      await screen.findByText("Partner's earnings withhold benefits before 67."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Primary person's earnings/)).not.toBeInTheDocument();
    unmount();

    explore.mockResolvedValue(couple());
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    await screen.findByRole("group", { name: /Primary person by Partner/ });
    expect(screen.queryByText(/earnings withhold/)).not.toBeInTheDocument();
  });

  it("formats a fractional current age in the data table", async () => {
    explore.mockResolvedValue({
      ...single(),
      runs: [run({ self: 66.5 }, 0, 0)],
      best_index: 0,
      patches: [],
    });
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    await screen.findByRole("group", { name: /claim age/ });
    expect(screen.queryByRole("button", { name: "Use these ages" })).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Show data table" })[0]);
    expect(screen.getByRole("table", { name: "Claiming-age comparison" })).toHaveTextContent(
      "66 y 6 m",
    );
  });
});

describe("states", () => {
  it("names the empty plan", async () => {
    explore.mockResolvedValue({
      ...single(),
      persons: [person("self", null, [], "no_benefit")],
      current: null,
      runs: [],
      best_index: null,
      patches: [],
      years: [],
    });
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    expect(
      await screen.findByText("No Social Security benefits in this plan."),
    ).toBeInTheDocument();
  });

  it("lists every person who cannot be varied", async () => {
    explore.mockResolvedValue({
      ...single(),
      current: null,
      runs: [],
      best_index: null,
      patches: [],
      years: [],
      persons: [
        person("self", null, [], "unresolved_claim_date"),
        person("spouse", null, [], "no_benefit"),
      ],
    });
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    expect(
      await screen.findByText(
        "Primary person: claim date depends on a milestone without a fixed date.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Partner: no Social Security benefit.")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Edit income" })).toHaveLength(2);
  });

  it("shows a busy state, then an error", async () => {
    let reject: (error: Error) => void = () => {};
    explore.mockReturnValue(
      new Promise((_, r) => {
        reject = r;
      }),
    );
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    expect(screen.getByRole("status")).toHaveTextContent("Comparing claiming ages…");
    await act(async () => reject(new Error("boom")));
    expect(screen.getByRole("alert")).toHaveTextContent("Could not compare claiming ages.");
  });

  it("reserves the grid's space while comparing", () => {
    explore.mockReturnValue(new Promise(() => {}));
    const ss = (owner: "self" | "spouse") =>
      makeIncome({ id: `${owner}-ss`, owner, is_social_security: true, is_active: true });
    usePlanStore.setState({
      plan: { ...plan, income_streams: [ss("self"), ss("spouse")] },
    } as never);
    const { unmount } = render(<ClaimingExplorer onEditSection={onEditSection} />);
    expect(screen.getByRole("status")).toHaveTextContent("Comparing claiming ages…");
    // jsdom has no layout, so the chart falls back to 560 wide: a 460 square grid less margins.
    expect(screen.getByTestId("claiming-placeholder")).toHaveStyle({ height: "448px" });
    unmount();

    usePlanStore.setState({ plan: { ...plan, income_streams: [ss("self")] } } as never);
    const { unmount: unmountOne } = render(<ClaimingExplorer onEditSection={onEditSection} />);
    expect(screen.getByTestId("claiming-placeholder")).toHaveStyle({ height: "220px" });
    unmountOne();

    usePlanStore.setState({ plan: { ...plan, income_streams: [] } } as never);
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    expect(screen.queryByTestId("claiming-placeholder")).not.toBeInTheDocument();
  });

  it("waits for the projection and renders nothing without a plan", () => {
    usePlanStore.setState({ simulation: null, isSimulating: true } as never);
    const { rerender } = render(<ClaimingExplorer onEditSection={onEditSection} />);
    expect(explore).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toBeInTheDocument();
    usePlanStore.setState({ plan: null } as never);
    rerender(<ClaimingExplorer onEditSection={onEditSection} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("asks once per projection and reloads when the projection refreshes", async () => {
    const { rerender } = render(<ClaimingExplorer onEditSection={onEditSection} />);
    await screen.findAllByRole("group");
    rerender(<ClaimingExplorer onEditSection={onEditSection} />);
    expect(explore).toHaveBeenCalledTimes(1);
    explore.mockResolvedValue(single());
    await act(async () => {
      usePlanStore.setState({ simulation: simulation() } as never);
    });
    expect(explore).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Partner: benefits already started.")).toBeInTheDocument();
  });

  it("never renders a response for a previous plan", async () => {
    let resolve: (value: ClaimingExplorerResponse) => void = () => {};
    explore.mockReturnValueOnce(
      new Promise((r) => {
        resolve = r;
      }),
    );
    render(<ClaimingExplorer onEditSection={onEditSection} />);
    explore.mockResolvedValue(single());
    await act(async () => {
      usePlanStore.setState({ plan: { ...plan, id: "p2" }, simulation: simulation() } as never);
    });
    await screen.findByText("Partner: benefits already started.");
    await act(async () => resolve(couple()));
    expect(
      screen.queryByRole("group", { name: /Primary person by Partner/ }),
    ).not.toBeInTheDocument();
    expect(explore).toHaveBeenLastCalledWith("p2");
  });

  it("keeps a neutral midpoint at zero", () => {
    expect(divergingFill(0, 10)).toBe("var(--surface-card)");
    expect(divergingFill(5, 0)).toBe("var(--surface-card)");
    expect(divergingFill(10, 10)).toContain("var(--viz-1) 95%");
    expect(divergingFill(-20, 10)).toContain("var(--viz-2) 95%");
  });
});
