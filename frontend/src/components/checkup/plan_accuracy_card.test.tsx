import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PlanAccuracyCard from "./plan_accuracy_card";
import { usePlanStore } from "@/stores/plan_store";
import type { PlanChecksResponse, SimulationResult } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { deferred } from "@/test_support/deferred";
import { makePlan } from "@/test_support/plan_builder";

const mocks = vi.hoisted(() => ({ runPlanChecks: vi.fn() }));
const adapter = makeAdapter({ runPlanChecks: mocks.runPlanChecks });
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

const response: PlanChecksResponse = {
  score: 71,
  checks: [
    { key: "accounts_entered", weight: 20, passes: true },
    { key: "expenses_entered", weight: 20, passes: true },
    { key: "social_security_self", weight: 15, passes: true },
    { key: "social_security_spouse", weight: 15, passes: false },
    { key: "earned_income_ends", weight: 10, passes: false },
  ],
  items: [
    {
      key: "social_security_spouse",
      kind: "missing",
      section: "income",
      title: "No Social Security for your partner",
      person: "spouse",
    },
    {
      key: "earned_income_ends",
      kind: "missing",
      section: "income",
      title: "Salary never ends: Acme",
      target_id: "w",
    },
    { key: "low_inflation", kind: "review", section: "assumptions", title: "Inflation under 1%" },
    {
      key: "milestone_missed",
      kind: "review",
      section: "milestones",
      title: "Missed milestone: Goal",
      target_id: "g",
    },
  ],
};
const allPass: PlanChecksResponse = {
  score: 100,
  checks: [{ key: "accounts_entered", weight: 20, passes: true }],
  items: [],
};

const plan = (id: string) => makePlan({ id, name: id });
const simulation = () => ({ timeline: [] }) as unknown as SimulationResult;

beforeEach(() => {
  vi.clearAllMocks();
  usePlanStore.setState({ plan: plan("p1"), simulation: simulation(), isSimulating: false });
});

describe("PlanAccuracyCard", () => {
  it("renders the score, missing items, then review items whose buttons open their section", async () => {
    mocks.runPlanChecks.mockResolvedValue(response);
    const onEditSection = vi.fn();
    render(<PlanAccuracyCard onEditSection={onEditSection} />);
    expect(screen.getByText("Checking…")).toBeInTheDocument();
    expect(await screen.findByText("71")).toBeInTheDocument();
    expect(mocks.runPlanChecks).toHaveBeenCalledWith("p1");
    expect(screen.getByRole("img", { name: "Plan accuracy 71 of 100" })).toBeInTheDocument();
    // One score: no second "N of M checks" count beside it.
    expect(screen.queryByText(/checks$/)).not.toBeInTheDocument();
    const missing = within(screen.getByRole("list", { name: "Missing" })).getAllByRole("button");
    expect(missing.map((b) => b.textContent)).toEqual([
      "No Social Security for your partner›",
      "Salary never ends: Acme›",
    ]);
    const review = within(screen.getByRole("list", { name: "Review" })).getAllByRole("button");
    expect(review.map((b) => b.textContent)).toEqual([
      "Inflation under 1%›",
      "Missed milestone: Goal›",
    ]);
    fireEvent.click(screen.getByRole("button", { name: /Salary never ends/ }));
    fireEvent.click(screen.getByRole("button", { name: /Inflation under/ }));
    fireEvent.click(screen.getByRole("button", { name: /Missed milestone/ }));
    expect(onEditSection.mock.calls).toEqual([["income"], ["assumptions"], ["milestones"]]);
  });

  it("shows only the figure when everything passes", async () => {
    mocks.runPlanChecks.mockResolvedValue(allPass);
    render(<PlanAccuracyCard onEditSection={vi.fn()} />);
    expect(await screen.findByText("100")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.queryByText(/checks$/)).not.toBeInTheDocument();
  });

  it("waits for a projection refresh, then reloads after it", async () => {
    mocks.runPlanChecks.mockResolvedValueOnce(response).mockResolvedValueOnce(allPass);
    render(<PlanAccuracyCard onEditSection={vi.fn()} />);
    expect(await screen.findByText("71")).toBeInTheDocument();
    act(() => {
      usePlanStore.setState({ isSimulating: true, simulation: null });
    });
    expect(screen.getByRole("region", { name: "Plan accuracy" })).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(mocks.runPlanChecks).toHaveBeenCalledTimes(1);
    act(() => {
      usePlanStore.setState({ isSimulating: false, simulation: simulation() });
    });
    expect(await screen.findByText("100")).toBeInTheDocument();
    expect(mocks.runPlanChecks).toHaveBeenCalledTimes(2);
  });

  it("never renders a previous plan's response", async () => {
    const first = deferred<PlanChecksResponse>();
    mocks.runPlanChecks.mockReturnValueOnce(first.promise).mockResolvedValueOnce(allPass);
    render(<PlanAccuracyCard onEditSection={vi.fn()} />);
    act(() => {
      usePlanStore.setState({ plan: plan("p2"), simulation: simulation() });
    });
    expect(await screen.findByText("100")).toBeInTheDocument();
    expect(mocks.runPlanChecks).toHaveBeenLastCalledWith("p2");
    await act(async () => {
      first.resolve(response);
      await first.promise;
    });
    expect(screen.queryByText("71")).not.toBeInTheDocument();
  });

  it("shows an error and retries", async () => {
    mocks.runPlanChecks.mockRejectedValueOnce(new Error("down")).mockResolvedValueOnce(response);
    render(<PlanAccuracyCard onEditSection={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not check this plan.");
    expect(screen.queryByText("Checking…")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("71")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("renders nothing and requests nothing without a plan", () => {
    usePlanStore.setState({ plan: null });
    const { container } = render(<PlanAccuracyCard onEditSection={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
    expect(mocks.runPlanChecks).not.toHaveBeenCalled();
  });
});
