import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { milestoneLinks } from "./milestone_links";
import { BuilderModeContext, MilestonesSection } from "@/pages/plan_setup";
import { useFiEstimateStore } from "@/stores/fi_estimate_store";
import { usePlanStore } from "@/stores/plan_store";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const adapter = makeAdapter();
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

const plan = makePlan({
  id: "p",
  birth_year: 1980,
  milestones: [
    { id: "ret", name: "Retirement", trigger_type: "age", trigger_value: 60, relative_to_id: null },
    {
      id: "after",
      name: "Downsize",
      trigger_type: "relative",
      trigger_value: null,
      relative_to_id: "ret",
      offset_years: 5,
    },
    {
      id: "fi",
      name: "FI",
      trigger_type: "expense_multiple",
      trigger_value: 25,
      relative_to_id: null,
    },
  ],
  income_streams: [{ id: "i", name: "Salary", start_milestone_id: null, end_milestone_id: "ret" }],
  expenses: [{ id: "e", name: "Travel", start_milestone_id: "ret", end_milestone_id: "after" }],
  priorities: [{ id: "r", priority_rank: 2, start_milestone_id: null, end_milestone_id: "ret" }],
  liabilities: [{ id: "d", name: "Mortgage", payoff_milestone_id: "ret" }],
});

beforeEach(() => {
  localStorage.clear();
  useFiEstimateStore.setState({ hiddenByPlan: {} });
  usePlanStore.setState({ ...usePlanStore.getInitialState(), plan, simulation: null });
});

function editButton(name: string) {
  return within(
    screen.getByText(name, { selector: "span" }).closest(".plan-list-item") as HTMLElement,
  ).getByRole("button", { name: "Edit" });
}

it("finds every input whose timing references the milestone", () => {
  expect(milestoneLinks(plan, "ret").map((link) => `${link.name}: ${link.relationship}`)).toEqual([
    "Salary: Ends here",
    "Travel: Starts here",
    "Savings rule 2: Ends here",
    "Mortgage: Paid off here",
    "Downsize: Timing follows this milestone",
  ]);
  expect(milestoneLinks(plan, "fi")).toEqual([]);
});

it("lists linked inputs under Edit milestone, and names an unlinked one's empty state", async () => {
  await act(async () => {
    render(
      <BuilderModeContext.Provider value="sheet">
        <MilestonesSection />
      </BuilderModeContext.Provider>,
    );
  });
  fireEvent.click(editButton("Retirement"));
  const linked = within(screen.getByRole("region", { name: "Linked inputs" }));
  expect(linked.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
    "Salary · Ends here",
    "Travel · Starts here",
    "Savings rule 2 · Ends here",
    "Mortgage · Paid off here",
    "Downsize · Timing follows this milestone",
  ]);
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(editButton("FI"));
  expect(
    within(screen.getByRole("region", { name: "Linked inputs" })).getByText("No linked inputs."),
  ).toBeInTheDocument();
});

it("shows no linked inputs while adding a milestone", async () => {
  await act(async () => {
    render(
      <BuilderModeContext.Provider value="sheet">
        <MilestonesSection />
      </BuilderModeContext.Provider>,
    );
  });
  fireEvent.click(screen.getByRole("button", { name: /Add milestone/ }));
  expect(screen.queryByRole("region", { name: "Linked inputs" })).not.toBeInTheDocument();
});
