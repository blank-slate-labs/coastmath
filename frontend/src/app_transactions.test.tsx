import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import App from "./app";
import { useAuthStore } from "@/stores/auth_store";
import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import type { SimulationResult, User } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

// The release flag is read when App and PlanSetup load, so the flag-on shell needs its own file.
// App.test.tsx covers the same shell with TRANSACTIONS_ENABLED off.
vi.hoisted(() => {
  window.matchMedia = vi.fn(() => ({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
});
vi.mock("@/feature_flags", async (original) => ({
  ...(await original<typeof import("@/feature_flags")>()),
  TRANSACTIONS_ENABLED: true,
}));
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
vi.mock("@/components/dashboard_view", () => ({ default: () => <div>Dashboard content</div> }));
// Leaf content has its own suites; the shell decides whether they are reachable.
vi.mock("@/components/month_compare/month_compare_tab", () => ({
  default: ({ onOpenTransactions }: { onOpenTransactions: () => void }) => (
    <div>
      Month comparison<button onClick={onOpenTransactions}>Open transactions</button>
    </div>
  ),
}));
vi.mock("@/components/ledger/transactions_section", () => ({
  default: () => <div>Transactions panel</div>,
}));
// The sheet and the nav render the real section list, so registration in PlanSetup is what is tested.
vi.mock("@/components/edit_sheet", async () => {
  const { PLAN_SECTIONS } = await import("@/pages/plan_setup");
  return {
    default: ({ index }: { index: number }) => {
      const { title, Component } = PLAN_SECTIONS[index];
      return (
        <div role="dialog" aria-label={title}>
          <Component />
        </div>
      );
    },
  };
});
vi.mock("@/components/plan_section_nav", async () => {
  const { PLAN_SECTIONS } = await import("@/pages/plan_setup");
  return {
    default: ({ onEdit }: { onEdit: (key: string) => void }) => (
      <nav>
        {PLAN_SECTIONS.map((s) => (
          <button key={s.key} onClick={() => onEdit(s.key)}>
            Edit {s.title}
          </button>
        ))}
      </nav>
    ),
  };
});

const adapter = makeAdapter();
const plan = makePlan({ id: "p", name: "Primary", birth_year: 1990 });
const simulation = {
  metadata: { start_year: 2026, success: true, warnings: [] },
  yearly_snapshots: [{ year: 2026, age: 36, net_worth: 10000 }],
} as unknown as SimulationResult;
const loadPlans = vi.fn().mockResolvedValue(undefined);
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  useAuthStore.setState({
    user: { id: "u", is_anonymous: false, email: "test@example.test" } as User,
    isLoading: false,
    error: null,
    ensureSession: vi.fn().mockResolvedValue(undefined),
  });
  usePlanStore.setState({
    ...usePlanStore.getInitialState(),
    plan,
    plans: [plan],
    simulation,
    loadPlans,
    loadPlan: vi.fn().mockResolvedValue(undefined),
  });
  useSaveStore.setState({ pending: 0, failed: [], lastSavedAt: null });
});

it("opens the Compare months tab and goes from it to the Transactions section", async () => {
  render(<App />);
  await waitFor(() => expect(loadPlans).toHaveBeenCalledOnce());
  fireEvent.click(screen.getByRole("button", { name: "Compare months" }));
  expect(await screen.findByText("Month comparison")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Open transactions" }));
  expect(screen.getByRole("dialog", { name: "Transactions" })).toHaveTextContent(
    "Transactions panel",
  );
});

it("lists the Transactions section in the plan builder", async () => {
  render(<App />);
  await waitFor(() => expect(loadPlans).toHaveBeenCalledOnce());
  fireEvent.click(screen.getByRole("button", { name: "Edit Transactions" }));
  expect(screen.getByRole("dialog", { name: "Transactions" })).toHaveTextContent(
    "Transactions panel",
  );
});
