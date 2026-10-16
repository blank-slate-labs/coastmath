import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WellnessScorecard, { bandGeometry, formatWellnessValue } from "./wellness_scorecard";
import { usePlanStore } from "@/stores/plan_store";
import type { SimulationResult, WellnessMetric, WellnessResponse } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { deferred } from "@/test_support/deferred";
import { makePlan } from "@/test_support/plan_builder";

const runWellness = vi.fn();
const adapter = makeAdapter({ runWellness });
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

const plan = makePlan({
  id: "p1",
  birth_year: 1980,
  assumption_curves: [
    { curve_type: "inflation", mode: "fixed", fixed_rate: 0.1, control_points: [] },
  ],
});
const simulation = (tag: string) =>
  ({
    metadata: { start_year: 2026, tag },
    yearly_snapshots: [2026, 2027, 2028].map((year) => ({
      year,
      accounts: {},
      expenses: 40_000,
      gross_income: 90_000,
    })),
  }) as unknown as SimulationResult;

const metric = (overrides: Partial<WellnessMetric>): WellnessMetric => ({
  key: "savings_rate",
  label: "Savings rate",
  value: 0.15,
  unit: "percent",
  status: "fair",
  bands: { better: "higher", fair_at: 0.1, strong_at: 0.2 },
  basis_year: 2026,
  section: "income_allocation",
  ...overrides,
});
const response: WellnessResponse = {
  start_year: 2026,
  metrics: [
    metric({}),
    metric({
      key: "emergency_fund",
      label: "Emergency fund",
      value: 7.5,
      unit: "months",
      status: "strong",
      bands: { better: "higher", fair_at: 3, strong_at: 6 },
      section: "accounts",
    }),
    metric({
      key: "debt_to_income",
      label: "Debt payments to income",
      value: null,
      status: "not_applicable",
      bands: null,
      basis_year: null,
      section: "property_debt",
    }),
    metric({
      key: "withdrawal_rate",
      label: "Withdrawal rate at retirement",
      value: 0.075,
      status: "needs_attention",
      bands: { better: "lower", fair_at: 0.05, strong_at: 0.04 },
      basis_year: 2041,
      section: "drawdown",
    }),
    metric({
      key: "fi_timing",
      label: "Financial independence",
      value: null,
      unit: "year",
      status: "needs_attention",
      bands: { better: "lower", fair_at: 2045, strong_at: 2040 },
      basis_year: 2040,
      section: "milestones",
    }),
    metric({
      key: "funded_years",
      label: "Funded years",
      value: 1,
      status: "strong",
      bands: { better: "higher", fair_at: 0.9, strong_at: 1 },
      section: null,
    }),
  ],
};

beforeEach(() => {
  runWellness.mockReset().mockResolvedValue(response);
  usePlanStore.setState({
    plan,
    simulation: simulation("a"),
    isSimulating: false,
    currencyMode: "nominal",
  } as never);
});

describe("WellnessScorecard", () => {
  it("grades nothing for an empty plan and names what is missing", () => {
    const empty = {
      metadata: { start_year: 2026 },
      yearly_snapshots: [
        {
          year: 2026,
          accounts: {},
          expenses: 0,
          gross_income: 0,
          real_assets_value: 0,
          liabilities_balance: 0,
        },
      ],
    };
    usePlanStore.setState({ simulation: empty } as never);
    render(<WellnessScorecard onEditSection={vi.fn()} />);
    expect(screen.getByText("No accounts, income or expenses yet.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Strong" })).toBeNull();
    expect(runWellness).not.toHaveBeenCalled();
  });

  it("groups graded metrics needing attention first and omits not-applicable ones", async () => {
    const { container } = render(<WellnessScorecard onEditSection={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "Needs attention" })).toBeInTheDocument();
    expect(runWellness).toHaveBeenCalledWith("p1");
    const headings = [...container.querySelectorAll("h4")].map((h) => h.textContent);
    expect(headings).toEqual(["Needs attention", "Fair", "Strong"]);
    const needsAttention = container.querySelector(".wellness-group-needs_attention")!;
    expect(
      within(needsAttention as HTMLElement).getByText("Withdrawal rate at retirement"),
    ).toBeInTheDocument();
    expect(within(needsAttention as HTMLElement).getByText("7.5%")).toBeInTheDocument();
    expect(within(needsAttention as HTMLElement).getByText("Not reached")).toBeInTheDocument();
    expect(screen.getByText("15.0%")).toBeInTheDocument();
    expect(screen.getByText("7.5 mo")).toBeInTheDocument();
    expect(screen.queryByText("Debt payments to income")).toBeNull();
    expect(
      screen.getByRole("img", {
        name: /Savings rate 15.0%: fair at 10.0%, strong at 20.0%, higher is better/,
      }),
    ).toBeInTheDocument();
  });

  it("places the band marker on the D3 scale", async () => {
    render(<WellnessScorecard onEditSection={vi.fn()} />);
    const bar = await screen.findByRole("img", { name: /^Savings rate/ });
    // Domain [0.075, 0.225]: 0.15 sits at the middle of the 100-unit bar.
    const marker = within(bar as unknown as HTMLElement).getByTestId("wellness-marker");
    expect(Number(marker.getAttribute("x")) + 0.75).toBeCloseTo(50);
    // The year metric with no value has no marker.
    const fi = screen.getByRole("img", { name: /^Financial independence/ });
    expect(within(fi as unknown as HTMLElement).queryByTestId("wellness-marker")).toBeNull();
  });

  it("opens a tile's plan section and leaves tiles without one static", async () => {
    const onEditSection = vi.fn();
    render(<WellnessScorecard onEditSection={onEditSection} />);
    fireEvent.click(await screen.findByRole("button", { name: /Withdrawal rate at retirement/ }));
    expect(onEditSection).toHaveBeenCalledWith("drawdown");
    expect(screen.queryByRole("button", { name: /Funded years/ })).toBeNull();
    expect(screen.getByText("Funded years")).toBeInTheDocument();
  });

  it("reloads when the projection refreshes and never renders a stale answer", async () => {
    const first = deferred<WellnessResponse>();
    const second = deferred<WellnessResponse>();
    runWellness.mockReset().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    render(<WellnessScorecard onEditSection={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Calculating");
    act(() => {
      usePlanStore.setState({ simulation: simulation("b") } as never);
    });
    expect(runWellness).toHaveBeenCalledTimes(2);
    await act(async () => {
      second.resolve({ start_year: 2026, metrics: [metric({ value: 0.25, status: "strong" })] });
    });
    expect(screen.getByText("25.0%")).toBeInTheDocument();
    await act(async () => {
      first.resolve(response);
    });
    expect(screen.getByText("25.0%")).toBeInTheDocument();
    expect(screen.queryByText("15.0%")).toBeNull();
  });

  it("waits for a projection before loading", () => {
    usePlanStore.setState({ simulation: null, isSimulating: true } as never);
    render(<WellnessScorecard onEditSection={vi.fn()} />);
    expect(runWellness).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent("Calculating");
  });

  it("renders nothing without a plan", () => {
    usePlanStore.setState({ plan: null } as never);
    const { container } = render(<WellnessScorecard onEditSection={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows an error and retries", async () => {
    runWellness
      .mockReset()
      .mockRejectedValueOnce(new Error("Plan not found"))
      .mockResolvedValueOnce(response);
    render(<WellnessScorecard onEditSection={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Plan not found");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Needs attention" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("falls back to a generic error message", async () => {
    runWellness.mockReset().mockRejectedValue("nope");
    render(<WellnessScorecard onEditSection={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The scorecard could not be calculated.",
    );
  });

  it("names the empty state when nothing is graded", async () => {
    runWellness.mockReset().mockResolvedValue({ start_year: 2026, metrics: [response.metrics[2]] });
    render(<WellnessScorecard onEditSection={vi.fn()} />);
    expect(await screen.findByText("No graded metrics for this plan.")).toBeInTheDocument();
  });

  it("shows currency values in the app's currency mode", async () => {
    runWellness.mockReset().mockResolvedValue({
      start_year: 2026,
      metrics: [
        metric({
          key: "savings_rate",
          label: "Amount",
          unit: "currency",
          value: 110_000,
          basis_year: 2027,
          bands: { better: "higher", fair_at: 55_000, strong_at: 110_000 },
          status: "strong",
        }),
      ],
    });
    usePlanStore.setState({ currencyMode: "inflation_adjusted" } as never);
    const { unmount } = render(<WellnessScorecard onEditSection={vi.fn()} />);
    // 2027 is one year of 10% inflation after the start.
    expect(await screen.findByText("$100.0K")).toBeInTheDocument();
    unmount();
    usePlanStore.setState({ currencyMode: "nominal" } as never);
    render(<WellnessScorecard onEditSection={vi.fn()} />);
    expect(await screen.findByText("$110.0K")).toBeInTheDocument();
  });
});

describe("helpers", () => {
  it("formats every unit", () => {
    expect(formatWellnessValue({ unit: "percent" }, 0.123)).toBe("12.3%");
    expect(formatWellnessValue({ unit: "months" }, 4.25)).toBe("4.3 mo");
    expect(formatWellnessValue({ unit: "multiple" }, 3.1)).toBe("3.1×");
    expect(formatWellnessValue({ unit: "ratio" }, 1.234)).toBe("1.23");
    expect(formatWellnessValue({ unit: "year" }, 2040)).toBe("2040");
    expect(formatWellnessValue({ unit: "age" }, 64.6)).toBe("65");
    expect(formatWellnessValue({ unit: "percent" }, null)).toBe("Not reached");
  });

  it("lays out zones in the scale's direction", () => {
    const lower = bandGeometry(
      { better: "lower", fair_at: 0.05, strong_at: 0.04 },
      0.02,
      true,
    );
    expect(lower.zones.map((z) => z.status)).toEqual(["strong", "fair", "needs_attention"]);
    expect(lower.zones[0].x).toBe(0);
    const higher = bandGeometry(
      { better: "higher", fair_at: 3, strong_at: 6 },
      null,
      true,
    );
    expect(higher.zones.map((z) => z.status)).toEqual(["needs_attention", "fair", "strong"]);
    expect(higher.marker).toBeNull();
    // Equal points still give the scale a span.
    const flat = bandGeometry({ better: "higher", fair_at: 0, strong_at: 0 }, 0, true);
    expect(flat.marker).toBe(0);
    // Calendar years are not clamped at zero.
    const years = bandGeometry(
      { better: "lower", fair_at: 2045, strong_at: 2040 },
      2050,
      false,
    );
    expect(years.marker).toBeCloseTo((100 * (2050 - 2037.5)) / (2052.5 - 2037.5));
  });
});
