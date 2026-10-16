import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { BuilderModeContext, MilestonesSection } from "./plan_setup";
import { useFiEstimateStore } from "@/stores/fi_estimate_store";
import { usePlanStore } from "@/stores/plan_store";
import type { Milestone, SimulationResult } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

const simulation = {
  metadata: {
    start_year: 2026,
    end_year: 2028,
    first_year_fraction: 1,
    milestone_outcomes: [],
    fi_estimate: { year: 2027, basis_year: 2026, target: 2000000, multiple: 25 },
  },
  yearly_snapshots: [
    { year: 2026, expenses: 80000, liabilities_balance: 0, accounts: { a: 2100000 } },
    { year: 2027, expenses: 80000, liabilities_balance: 0, accounts: { a: 2300000 } },
  ],
} as unknown as SimulationResult;

const addMilestone = vi.fn();

function setPlan(milestones: Milestone[] = []) {
  const plan = makePlan({ id: "p", birth_year: 1990, milestones });
  usePlanStore.setState({ ...usePlanStore.getInitialState(), plan, simulation, addMilestone });
}

async function renderSection() {
  await act(async () => {
    render(
      <BuilderModeContext.Provider value="sheet">
        <MilestonesSection />
      </BuilderModeContext.Provider>,
    );
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  useFiEstimateStore.setState({ hiddenByPlan: {} });
  setPlan();
});

it("lists the CoastMath estimate as a built-in milestone with its projected year", async () => {
  await renderSection();
  expect(screen.getByText("Financial independence (CoastMath estimate)")).toBeInTheDocument();
  expect(screen.getByTestId("fi-estimate-milestone")).toHaveTextContent(
    "25× expenses (liquid) · reached 2027",
  );
  expect(screen.queryByText("No milestones yet.")).not.toBeInTheDocument();
});

it("edit turns the estimate into a real 25× liquid milestone", async () => {
  await renderSection();
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));
  fireEvent.click(screen.getByRole("button", { name: "Add Milestone" }));
  expect(addMilestone).toHaveBeenCalledExactlyOnceWith(
    "p",
    expect.objectContaining({
      name: "Financial independence",
      trigger_type: "expense_multiple",
      expense_multiple: 25,
      metric: "liquid_net_worth",
    }),
  );
});

it("remove hides the estimate for this plan and restore brings it back", async () => {
  await renderSection();
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  expect(screen.queryByTestId("fi-estimate-milestone")).not.toBeInTheDocument();
  expect(localStorage.getItem("coastmath:fi_estimate_hidden:p")).toBe("1");
  fireEvent.click(
    screen.getByRole("button", { name: /Restore the CoastMath financial independence estimate/ }),
  );
  expect(screen.getByTestId("fi-estimate-milestone")).toBeInTheDocument();
});

it("a user's own FI milestone replaces the estimate", async () => {
  setPlan([
    {
      id: "m1",
      plan_id: "p",
      name: "My FI",
      trigger_type: "expense_multiple",
      trigger_value: null,
      trigger_date: null,
      metric: "liquid_net_worth",
      expense_multiple: 25,
      relative_to_id: null,
      offset_years: 0,
      sort_order: 0,
    },
  ]);
  await renderSection();
  expect(screen.getByText("My FI")).toBeInTheDocument();
  expect(screen.queryByTestId("fi-estimate-milestone")).not.toBeInTheDocument();
  expect(screen.queryByText(/Restore the CoastMath/)).not.toBeInTheDocument();
});

it("keeps a rejected milestone draft open and displays a missed deadline", async () => {
  usePlanStore.setState({
    simulation: {
      ...simulation,
      metadata: {
        ...simulation.metadata,
        milestone_outcomes: [
          { id: "goal", name: "Goal", trigger_type: "conditions", year: null, missed_year: 2027 },
        ],
      },
    },
    plan: makePlan({
      id: "p",
      birth_year: 1980,
      milestones: [
        {
          id: "goal",
          name: "Goal",
          trigger_type: "conditions",
          conditions: { combinator: "all", items: [{ kind: "age", owner: "self", age: 60 }] },
        },
      ],
    }),
    updateMilestone: vi.fn().mockImplementation(async () => {
      usePlanStore.setState({ error: "Conditions could not be saved" });
    }),
  });
  await renderSection();
  expect(screen.getByText(/missed deadline 2027/)).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "Edit" }).at(-1)!);
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Keep my draft" } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Update Milestone" }));
  });
  expect(screen.getByLabelText("Name")).toHaveValue("Keep my draft");
  expect(screen.getByText("Conditions could not be saved")).toBeInTheDocument();
});

it("shows a switched-off milestone as inactive instead of its projected outcome", async () => {
  setPlan([
    {
      id: "m2",
      plan_id: "p",
      name: "Move abroad",
      trigger_type: "age",
      trigger_value: 50,
      trigger_date: null,
      metric: null,
      expense_multiple: null,
      relative_to_id: null,
      offset_years: 0,
      sort_order: 0,
      is_active: false,
    },
  ]);
  await renderSection();
  expect(screen.getByText("Move abroad (inactive)")).toBeInTheDocument();
  expect(screen.getByText(/switched off, never fires/)).toBeInTheDocument();
});

it("lists a Partner retirement at the partner's age", async () => {
  usePlanStore.setState({
    plan: makePlan({
      id: "p",
      birth_year: 1990,
      spouse: { name: "Sam", birth_year: 1992 },
      milestones: [
        { id: "pr", name: "Partner retirement", trigger_type: "age", trigger_value: 65 },
        { id: "r", name: "Retirement", trigger_type: "age", trigger_value: 60 },
      ],
    }),
  });
  await renderSection();
  expect(screen.getByText(/partner's age 63/)).toBeInTheDocument();
  expect(screen.getByText(/^age 60/)).toBeInTheDocument();
});
