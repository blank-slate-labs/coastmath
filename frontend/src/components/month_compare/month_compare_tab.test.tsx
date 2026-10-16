import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import MonthCompareTab from "./month_compare_tab";
import { comparison, feedState, outcome } from "./month_compare_test_data";
import { CATEGORIES, month } from "@/components/ledger/ledger_test_data";
import { usePlanStore } from "@/stores/plan_store";
import { makePlan } from "@/test_support/plan_builder";

const mocks = vi.hoisted(() => ({
  months: vi.fn(),
  categories: vi.fn(),
  compare: vi.fn(),
  apply: vi.fn(),
  get: vi.fn(),
  put: vi.fn(),
  stop: vi.fn(),
  loadPlan: vi.fn(),
  sample: false,
}));
vi.mock("@/api/ledger", () => ({ ledger: { months: mocks.months, categories: mocks.categories } }));
vi.mock("@/api/spending_models", async (original) => ({
  ...(await original<typeof import("@/api/spending_models")>()),
  spendingModels: { compare: mocks.compare, apply: mocks.apply },
  spendingFeeds: { get: mocks.get, put: mocks.put, stop: mocks.stop },
}));
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(null, {
    sample: () => mocks.sample,
  }),
);

const MONTHS = [
  month({ month: "2026-06" }),
  month({ month: "2026-07", essential: 2500 }),
  month({
    month: "2026-08",
    complete: false,
    reasons: [{ code: "partial_coverage", source_ids: ["a1"] }],
  }),
  month({
    month: "2026-09",
    complete: false,
    reasons: [{ code: "in_progress", source_ids: [] }],
    income: 0,
  }),
];
const SOURCES = [
  { id: "a1", provider: "file", name: "Synthetic card", coverage: [], settled: [], waiting: false },
];

function monthButton(key: string) {
  return document.querySelector(`button[data-month="${key}"]`) as HTMLButtonElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.sample = false;
  usePlanStore.setState({
    plan: makePlan({ id: "plan-1", currency: "USD" }),
    loadPlan: mocks.loadPlan,
    currencyMode: "nominal",
  });
  mocks.months.mockResolvedValue({
    currency: "USD",
    months: MONTHS,
    sources: SOURCES,
    duplicates: [],
  });
  mocks.categories.mockResolvedValue([
    ...CATEGORIES,
    { id: "travel", role: "spending", bucket: "discretionary", kind: null, label: "Travel" },
  ]);
  mocks.get.mockResolvedValue(feedState());
  mocks.compare.mockResolvedValue(comparison());
  mocks.apply.mockResolvedValue({
    fingerprint: "a".repeat(64),
    updated_expense_ids: ["e1"],
    created_expense_ids: [],
    essential_ratio: 0.8,
    discretionary_ratio: 0.5,
    basis: null,
  });
  mocks.put.mockResolvedValue(feedState({ active: true }));
  mocks.loadPlan.mockResolvedValue(undefined);
});

async function compareTwo() {
  render(<MonthCompareTab onOpenTransactions={vi.fn()} />);
  await screen.findByRole("group", { name: "Months" });
  fireEvent.click(monthButton("2026-06"));
  fireEvent.click(monthButton("2026-07"));
  fireEvent.click(screen.getByRole("button", { name: "Compare" }));
  await screen.findByRole("img", { name: /Net worth by year/ });
}

it("shows months, explains incomplete ones and keeps them out of the selection", async () => {
  render(<MonthCompareTab onOpenTransactions={vi.fn()} />);
  await screen.findByRole("group", { name: "Months" });
  expect(mocks.months).toHaveBeenCalledWith({ plan_id: "plan-1" });
  const partial = monthButton("2026-08");
  expect(partial).toHaveAttribute("aria-disabled", "true");
  fireEvent.focus(partial);
  expect(screen.getByRole("status")).toHaveTextContent("Not fully covered: Synthetic card.");
  fireEvent.mouseEnter(monthButton("2026-09"));
  expect(screen.getByRole("status")).toHaveTextContent("Month in progress.");
  fireEvent.mouseLeave(monthButton("2026-09"));
  fireEvent.focus(monthButton("2026-06"));
  expect(screen.getByRole("status")).toHaveTextContent(
    "essential $2,000, discretionary $500, take-home $4,000",
  );
  fireEvent.blur(monthButton("2026-06"));
  fireEvent.click(partial);
  expect(partial).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByRole("button", { name: "Compare" })).toBeDisabled();
});

it("compares each selected month and shows outcomes and category differences", async () => {
  await compareTwo();
  expect(mocks.compare).toHaveBeenCalledWith("plan-1", {
    variants: [
      { kind: "months", months: ["2026-06"] },
      { kind: "months", months: ["2026-07"] },
    ],
    future_phases: "scale",
    income: "as_planned",
    monte_carlo_trials: 0,
  });
  const table = screen.getByRole("table", { name: "Outcomes by spending model" });
  const july = within(table).getByRole("row", { name: /Jul 2026/ });
  expect(july).toHaveTextContent("58 (2043) · 1 yr later");
  expect(july).toHaveTextContent("Short in 2070");
  expect(within(table).getByRole("row", { name: /Jun 2026/ })).toHaveTextContent("2 yrs earlier");
  expect(within(table).getByRole("row", { name: /This plan/ })).toHaveTextContent("$1,500,000");
  expect(within(table).queryByText("Monte Carlo")).toBeNull();
  expect(screen.getByText("Only the covered spending changes.")).toBeVisible();
  const differences = screen.getByRole("region", { name: "Category differences" });
  expect(within(differences).getByRole("heading")).toHaveTextContent("Jun 2026 vs Jul 2026");
  const rows = within(differences)
    .getAllByRole("row")
    .slice(1)
    .map((row) => row.textContent);
  expect(rows[0]).toContain("Groceries");
  expect(rows[0]).toContain("+$300");
  expect(rows).toHaveLength(3);
  // Today's dollars deflate by the inflation factor.
  fireEvent.click(screen.getByRole("button", { name: /Today/ }));
  expect(within(table).getByRole("row", { name: /This plan/ })).toHaveTextContent("$1,413,894");
});

it("averages selected months into one variant with the chosen options", async () => {
  mocks.compare.mockResolvedValue(
    comparison({
      plan: outcome({
        kind: "plan",
        label: "This plan",
        monte_carlo_success_rate: 0.9,
        months: null,
        by_category: null,
      }),
      variants: [
        outcome({
          label: "Jun – Jul 2026",
          monte_carlo_success_rate: 0.95,
          fi_age: null,
          fi_year: null,
        }),
      ],
    }),
  );
  render(<MonthCompareTab onOpenTransactions={vi.fn()} />);
  await screen.findByRole("group", { name: "Months" });
  fireEvent.click(screen.getByRole("button", { name: "Average them" }));
  fireEvent.click(monthButton("2026-07"));
  fireEvent.click(monthButton("2026-06"));
  fireEvent.click(screen.getByRole("button", { name: "As planned", pressed: false }));
  fireEvent.click(screen.getByRole("button", { name: "Scale to month" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Monte Carlo" }));
  fireEvent.click(screen.getByRole("button", { name: "Compare" }));
  await screen.findByRole("img", { name: /Net worth by year/ });
  expect(mocks.compare).toHaveBeenCalledWith("plan-1", {
    variants: [{ kind: "months", months: ["2026-06", "2026-07"] }],
    future_phases: "as_planned",
    income: "scale_to_take_home",
    monte_carlo_trials: 250,
  });
  const table = screen.getByRole("table", { name: "Outcomes by spending model" });
  expect(within(table).getByRole("row", { name: /Jun – Jul 2026/ })).toHaveTextContent(
    "Not reached",
  );
  expect(within(table).getByRole("row", { name: /Jun – Jul 2026/ })).toHaveTextContent("95%");
  expect(screen.queryByRole("region", { name: "Category differences" })).toBeNull();
  // Back to separate months; Clear empties the selection.
  fireEvent.click(screen.getByRole("button", { name: "Each month" }));
  fireEvent.click(screen.getByRole("button", { name: "Clear" }));
  expect(monthButton("2026-06")).toHaveAttribute("aria-pressed", "false");
});

it("limits separate months to six", async () => {
  const many = Array.from({ length: 8 }, (_, index) =>
    month({ month: `2025-${String(index + 1).padStart(2, "0")}` }),
  );
  mocks.months.mockResolvedValue({ currency: "USD", months: many, sources: [], duplicates: [] });
  render(<MonthCompareTab onOpenTransactions={vi.fn()} />);
  await screen.findByRole("group", { name: "Months" });
  fireEvent.click(screen.getByRole("button", { name: "Average them" }));
  for (const m of many) fireEvent.click(monthButton(m.month));
  expect(
    many.filter((m) => monthButton(m.month).getAttribute("aria-pressed") === "true"),
  ).toHaveLength(8);
  fireEvent.click(screen.getByRole("button", { name: "Each month" }));
  expect(
    many.filter((m) => monthButton(m.month).getAttribute("aria-pressed") === "true"),
  ).toHaveLength(6);
  expect(monthButton("2025-08")).toHaveAttribute("aria-disabled", "true");
  fireEvent.click(monthButton("2025-08"));
  expect(monthButton("2025-08")).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(monthButton("2025-01"));
  expect(monthButton("2025-01")).toHaveAttribute("aria-pressed", "false");
});

it("confirms what changes, applies the variant and refreshes the plan", async () => {
  await compareTwo();
  fireEvent.click(screen.getByRole("button", { name: "Apply Jun 2026" }));
  const dialog = screen.getByRole("dialog", { name: "Apply Jun 2026" });
  expect(dialog).toHaveTextContent(
    "Living expenses scale to $24,000 essential and $6,000 discretionary a year, later phases included. Income stays as entered.",
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Apply Jun 2026" }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Apply" }));
  await waitFor(() =>
    expect(mocks.apply).toHaveBeenCalledWith("plan-1", {
      variant: { kind: "months", months: ["2026-06"] },
      future_phases: "scale",
      expected_fingerprint: "f".repeat(64),
    }),
  );
  await waitFor(() => expect(mocks.loadPlan).toHaveBeenCalledWith("plan-1"));
  expect(await screen.findByText("Applied Jun 2026.")).toBeVisible();
  expect(mocks.compare).toHaveBeenCalledTimes(2);
});

it("refreshes the preview and keeps the selection when the plan changed", async () => {
  await compareTwo();
  mocks.apply.mockRejectedValue(
    Object.assign(new Error("changed"), { response: { data: { error: { code: "CONFLICT" } } } }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Apply Jul 2026" }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Apply" }));
  expect(await screen.findByText(/The plan changed after this preview/)).toBeVisible();
  expect(mocks.compare).toHaveBeenCalledTimes(2);
  expect(mocks.loadPlan).not.toHaveBeenCalled();
  expect(monthButton("2026-07")).toHaveAttribute("aria-pressed", "true");
});

it("reports other apply failures", async () => {
  await compareTwo();
  mocks.apply.mockRejectedValue(
    Object.assign(new Error("Connected spending is paused."), {
      response: { data: { error: { code: "SPENDING_FEED_PAUSED" } } },
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Apply Jul 2026" }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Apply" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Connected spending is paused.");
});

it("describes the feed basis, applies to it and switches back to recent months", async () => {
  mocks.get.mockResolvedValue(
    feedState({
      active: true,
      source_ids: ["a1"],
      basis: "months",
      basis_months: ["2026-07"],
      error: "A chosen month is no longer complete.",
    }),
  );
  mocks.compare.mockResolvedValue(comparison({ spending_feed: true }));
  await compareTwo();
  expect(screen.getByText("Jul 2026", { selector: "strong" })).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent("no longer complete");
  fireEvent.click(screen.getByRole("button", { name: "Apply Jun 2026" }));
  expect(screen.getByRole("dialog")).toHaveTextContent(
    "Spending from transactions follows Jun 2026 instead of Jul 2026: $24,000 essential and $6,000 discretionary a year.",
  );
  fireEvent.click(screen.getByRole("button", { name: "Use recent months" }));
  await waitFor(() =>
    expect(mocks.put).toHaveBeenCalledWith("plan-1", { source_ids: ["a1"], basis: "trailing" }),
  );
  await waitFor(() => expect(mocks.loadPlan).toHaveBeenCalledWith("plan-1"));
  expect(mocks.get).toHaveBeenCalledTimes(2);
});

it("names recent months for a trailing feed", async () => {
  mocks.get.mockResolvedValue(feedState({ active: true, source_ids: ["a1"] }));
  mocks.compare.mockResolvedValue(comparison({ spending_feed: true }));
  await compareTwo();
  expect(screen.getByText("Recent months", { selector: "strong" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Use recent months" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Apply Jun 2026" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("instead of recent months");
});

it("names what is missing when no month is complete", async () => {
  mocks.months.mockResolvedValue({
    currency: "USD",
    months: [MONTHS[3]],
    sources: [],
    duplicates: [],
  });
  const open = vi.fn();
  render(<MonthCompareTab onOpenTransactions={open} />);
  expect(await screen.findByText("No complete months yet.")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Open Transactions" }));
  expect(open).toHaveBeenCalled();
});

it("reports load and compare failures and renders nothing for the sample", async () => {
  mocks.months.mockRejectedValueOnce(new Error("Months unavailable."));
  const { unmount } = render(<MonthCompareTab onOpenTransactions={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Months unavailable.");
  unmount();
  mocks.compare.mockRejectedValueOnce(new Error("Only complete months can model spending."));
  render(<MonthCompareTab onOpenTransactions={vi.fn()} />);
  await screen.findByRole("group", { name: "Months" });
  fireEvent.click(monthButton("2026-06"));
  fireEvent.click(screen.getByRole("button", { name: "Compare" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Only complete months");
  mocks.sample = true;
  const { container } = render(<MonthCompareTab onOpenTransactions={vi.fn()} />);
  expect(container).toBeEmptyDOMElement();
});

it("compares separate months in date order whatever the click order", async () => {
  render(<MonthCompareTab onOpenTransactions={vi.fn()} />);
  await screen.findByRole("group", { name: "Months" });
  fireEvent.click(monthButton("2026-07"));
  fireEvent.click(monthButton("2026-06"));
  expect(monthButton("2026-07")).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Compare" }));
  await waitFor(() =>
    expect(mocks.compare).toHaveBeenCalledWith(
      "plan-1",
      expect.objectContaining({
        variants: [
          { kind: "months", months: ["2026-06"] },
          { kind: "months", months: ["2026-07"] },
        ],
      }),
    ),
  );
});
