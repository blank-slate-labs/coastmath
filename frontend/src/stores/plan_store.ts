import { create, type StoreApi } from "zustand";

import type { StorageAdapter } from "@/storage/adapter";
import type { CurrencyMode } from "@/utils/currency";
import { extensions } from "@/extensions";

// ── Module-level adapter (set by StorageProvider) ────────────────

let _adapter: StorageAdapter | null = null;

export function setStorageAdapter(a: StorageAdapter) {
  _adapter = a;
}

function adapter(): StorageAdapter {
  if (!_adapter) throw new Error("StorageAdapter not initialized — call setStorageAdapter() first");
  return _adapter;
}
import type {
  ArchivedPlanSummary,
  AccountCreate,
  AccountUpdate,
  PlanData,
  PlanSummary,
  PlanCreate,
  PlanIntake,
  SimulationResult,
  MilestoneCreate,
  IncomeCreate,
  ExpenseCreate,
  ExpenseUpdate,
  RealAssetCreate,
  LiabilityCreate,
  CashFlowPriorityCreate,
  DrawdownEntryCreate,
  ResidencyPeriodCreate,
} from "@/types/plan";

interface PlanState {
  accountsRevision: number;
  saveAccount: (id: string | null, data: AccountCreate | AccountUpdate) => Promise<void>;
  deleteAccount: (id: string) => Promise<void>;
  plan: PlanData | null;
  /** The plan most recently requested by loadPlan, set before its fetch resolves. */
  activePlanId: string | null;
  plans: PlanSummary[];
  simulation: SimulationResult | null;
  baselineSimulation: SimulationResult | null;
  compareMode: boolean;
  baselinePlanId: string | null;
  isComparing: boolean;
  isSimulating: boolean;
  /** Why the latest projection of the open plan could not run; null after it runs. */
  simulationError: string | null;
  error: string | null;
  currencyMode: CurrencyMode;

  setCurrencyMode: (mode: CurrencyMode) => void;
  saveBaseline: () => void;
  clearBaseline: () => void;
  setBaselinePlan: (planId: string | null) => Promise<void>;

  // Plan CRUD
  loadPlans: () => Promise<void>;
  loadPlan: (id: string) => Promise<void>;
  createPlan: (data: PlanCreate) => Promise<void>;
  duplicatePlan: (id: string) => Promise<void>;
  /**
   * Creates a scenario of a Main or independent plan, refreshes the plan
   * list and opens the scenario. Resolves to success; failures set `error`.
   */
  createScenario: (sourceId: string, name?: string) => Promise<boolean>;
  /** Makes a scenario an independent plan that keeps its current values. Resolves to success. */
  detachScenario: (id: string) => Promise<boolean>;
  /** Applies the new-plan goals. Rejects on failure so the form keeps its answers. */
  submitPlanIntake: (id: string, data: PlanIntake) => Promise<void>;
  updatePlan: (id: string, data: Partial<PlanCreate>) => Promise<void>;
  /** Deletes a plan and closes it when open; the app then opens the next plan. Resolves to success. */
  deletePlan: (id: string) => Promise<boolean>;

  // Archive actions call the server, which decides every rule.
  archivedPlans: ArchivedPlanSummary[];
  loadArchivedPlans: () => Promise<void>;
  /** Archives every active plan. Resolves to success. */
  archiveActivePlans: () => Promise<boolean>;
  restorePlan: (id: string) => Promise<boolean>;
  /** Permanently deletes an archived plan. Resolves to success. */
  deleteArchivedPlan: (id: string) => Promise<boolean>;
  /** Re-read the open plan's edit-window fields, e.g. when its countdown ends. */
  refreshPlanAccess: (id: string) => Promise<void>;

  // Milestone CRUD
  addMilestone: (planId: string, data: MilestoneCreate) => Promise<boolean>;
  updateMilestone: (planId: string, id: string, data: Partial<MilestoneCreate>) => Promise<boolean>;
  deleteMilestone: (planId: string, id: string) => Promise<void>;

  // Income CRUD
  addIncome: (planId: string, data: IncomeCreate) => Promise<boolean>;
  updateIncome: (planId: string, id: string, data: Partial<IncomeCreate>) => Promise<boolean>;
  deleteIncome: (planId: string, id: string) => Promise<boolean>;

  // Expense CRUD
  addExpense: (planId: string, data: ExpenseCreate) => Promise<boolean>;
  updateExpense: (planId: string, id: string, data: ExpenseUpdate) => Promise<boolean>;
  deleteExpense: (planId: string, id: string) => Promise<void>;

  // Real Asset CRUD
  addRealAsset: (planId: string, data: RealAssetCreate) => Promise<boolean>;
  updateRealAsset: (planId: string, id: string, data: Partial<RealAssetCreate>) => Promise<boolean>;
  deleteRealAsset: (planId: string, id: string) => Promise<void>;

  // Liability CRUD
  addLiability: (planId: string, data: LiabilityCreate) => Promise<boolean>;
  updateLiability: (planId: string, id: string, data: Partial<LiabilityCreate>) => Promise<boolean>;
  deleteLiability: (planId: string, id: string) => Promise<void>;

  // Bulk updates
  updatePriorities: (
    planId: string,
    priorities: CashFlowPriorityCreate[],
    expectedRevision: number,
  ) => Promise<void>;
  updateDrawdownOrder: (planId: string, entries: DrawdownEntryCreate[]) => Promise<void>;
  updateResidencyPeriods: (planId: string, periods: ResidencyPeriodCreate[]) => Promise<void>;

  // Simulation
  runSimulation: (planId: string) => Promise<void>;
}

let comparisonRequest = 0;
let planLoadRequest = 0;
let simulationRequest = 0;
let _debounceTimer: ReturnType<typeof setTimeout> | null = null;
let errorTimer: ReturnType<typeof setTimeout> | null = null;

function debouncedSimulate(planId: string, get: () => PlanState) {
  if (get().plan?.id !== planId) return;
  simulationRequest += 1;
  usePlanStore.setState({ isSimulating: true, simulation: null });
  if (_debounceTimer) clearTimeout(_debounceTimer);
  _debounceTimer = setTimeout(() => {
    _debounceTimer = null;
    get().runSimulation(planId);
  }, 300);
}

/** The server's reason when it rejected the plan's inputs (422); otherwise a plain failure. */
function simulationFailure(err: unknown): string {
  const status = (err as { response?: { status?: number } })?.response?.status;
  if (status === 422 && err instanceof Error && err.message) return err.message;
  return "The projection could not run.";
}

function handleError(set: (s: Partial<PlanState>) => void, err: unknown) {
  // An extension's own prompt already explained it.
  if (extensions.api?.isExplained?.(err)) return;
  const message = err instanceof Error ? err.message : "An unexpected error occurred";
  set({ error: message });
  if (errorTimer) clearTimeout(errorTimer);
  errorTimer = setTimeout(() => {
    errorTimer = null;
    set({ error: null });
  }, 5000);
}

/** The server's edit-window fields of a PlanRead, without its inputs. */
function editFields(plan: PlanData): Partial<PlanData> {
  const { archived_at, edit_window_ends_at, edit_notice_seen_at, edit_grace_ends_at, editable } =
    plan;
  return { archived_at, edit_window_ends_at, edit_notice_seen_at, edit_grace_ends_at, editable };
}

async function refreshAfterAccountChange(get: () => PlanState) {
  const plan = get().plan;
  // Account balances live outside PlanData. Notify every account consumer and
  // invalidate the forecast before any follow-up GET can delay recalculation.
  usePlanStore.setState((s) => ({ accountsRevision: s.accountsRevision + 1, simulation: null }));
  if (!plan) return;
  const request = ++planLoadRequest;
  debouncedSimulate(plan.id, get);
  try {
    const updated = await adapter().fetchPlan(plan.id);
    // Creating/deleting accounts can also change the server's drawdown order.
    if (request === planLoadRequest && get().plan === plan) {
      usePlanStore.setState((s) => ({
        plan: updated,
        plans: s.plans.map((p) => (p.id === updated.id ? updated : p)),
      }));
    }
  } catch (err) {
    handleError(usePlanStore.setState, err);
  }
}

type RowCollection = "milestones" | "income_streams" | "expenses" | "real_assets" | "liabilities";
type RowOf<K extends RowCollection> = PlanData[K][number];

/**
 * Writes one plan row, then puts the server's copy into the open plan: it replaces
 * the row with `id`, or is appended when `id` is null. Resolves to success.
 */
async function saveRow<K extends RowCollection>(
  set: StoreApi<PlanState>["setState"],
  get: () => PlanState,
  planId: string,
  key: K,
  id: string | null,
  write: () => Promise<RowOf<K>>,
): Promise<boolean> {
  try {
    const saved = await write();
    set((s) => {
      if (s.plan?.id !== planId) return s;
      const rows = s.plan[key] as RowOf<K>[];
      const next =
        id === null ? [...rows, saved] : rows.map((row) => (row.id === id ? saved : row));
      return { plan: { ...s.plan, [key]: next } };
    });
    debouncedSimulate(planId, get);
    return true;
  } catch (err) {
    handleError(set, err);
    return false;
  }
}

export const usePlanStore = create<PlanState>()((set, get) => ({
  accountsRevision: 0,
  saveAccount: async (id, data) => {
    const planId = get().plan?.id;
    if (id) await adapter().updateAccount(id, data, planId);
    else await adapter().createAccount(data as AccountCreate, planId);
    await refreshAfterAccountChange(get);
  },
  deleteAccount: async (id) => {
    await adapter().deleteAccount(id, get().plan?.id);
    await refreshAfterAccountChange(get);
  },
  plan: null,
  activePlanId: null,
  plans: [],
  simulation: null,
  baselineSimulation: null,
  compareMode: false,
  baselinePlanId: null,
  isComparing: false,
  isSimulating: false,
  simulationError: null,
  error: null,
  currencyMode: (() => {
    // Today's dollars, like the landing page and calculators, unless the viewer chose future dollars.
    try {
      return localStorage.getItem("coastmath:currency_mode") === "nominal"
        ? "nominal"
        : "inflation_adjusted";
    } catch {
      return "inflation_adjusted";
    }
  })(),

  setCurrencyMode: (mode) => {
    try {
      localStorage.setItem("coastmath:currency_mode", mode);
    } catch {
      /* Display still works when storage is unavailable. */
    }
    set({ currencyMode: mode });
  },
  saveBaseline: () => {
    const sim = get().simulation;
    if (sim && !get().isSimulating) {
      comparisonRequest += 1;
      set({
        baselineSimulation: structuredClone(sim),
        compareMode: true,
        baselinePlanId: null,
        isComparing: false,
      });
    }
  },
  clearBaseline: () => {
    comparisonRequest += 1;
    set({ baselineSimulation: null, compareMode: false, baselinePlanId: null, isComparing: false });
  },
  setBaselinePlan: async (planId) => {
    const request = ++comparisonRequest;
    if (!planId) {
      set({
        baselinePlanId: null,
        baselineSimulation: null,
        compareMode: false,
        isComparing: false,
      });
      return;
    }
    const currentPlan = get().plan;
    if (!currentPlan) return;
    set({
      baselinePlanId: planId,
      isComparing: true,
      baselineSimulation: null,
      compareMode: false,
    });
    try {
      const result = await adapter().fetchCompare(currentPlan.id, planId);
      if (request !== comparisonRequest || get().plan?.id !== currentPlan.id) return;
      set({
        baselineSimulation: result.baseline,
        compareMode: true,
        isComparing: false,
      });
    } catch (err) {
      if (request !== comparisonRequest || get().plan?.id !== currentPlan.id) return;
      set({ isComparing: false, baselinePlanId: null });
      handleError(set, err);
    }
  },

  // --- Plan CRUD ---

  loadPlans: async () => {
    try {
      const plans = await adapter().fetchPlans();
      set({ plans });
    } catch (err) {
      handleError(set, err);
    }
  },

  loadPlan: async (id) => {
    const request = ++planLoadRequest;
    const switching = get().plan?.id !== id;
    set({ activePlanId: id });
    if (switching) {
      comparisonRequest += 1;
      simulationRequest += 1;
      if (_debounceTimer) clearTimeout(_debounceTimer);
      _debounceTimer = null;
      set({
        baselineSimulation: null,
        compareMode: false,
        baselinePlanId: null,
        isComparing: false,
        simulation: null,
        isSimulating: false,
        simulationError: null,
      });
    }
    try {
      const plan = await adapter().fetchPlan(id);
      if (request !== planLoadRequest) return;
      set({ plan });
      debouncedSimulate(id, get);
    } catch (err) {
      if (request === planLoadRequest) handleError(set, err);
    }
  },

  createPlan: async (data) => {
    set({ error: null });
    try {
      const plan = await adapter().createPlan(data);
      set((s) => ({ plans: [...s.plans, plan] }));
      await get().loadPlan(plan.id);
    } catch (err) {
      handleError(set, err);
    }
  },

  duplicatePlan: async (id) => {
    set({ error: null });
    try {
      const plan = await adapter().duplicatePlan(id);
      set((s) => ({ plans: [...s.plans, plan] }));
      await get().loadPlan(plan.id);
    } catch (err) {
      handleError(set, err);
    }
  },

  createScenario: async (sourceId, name) => {
    set({ error: null });
    try {
      const plan = await adapter().createScenario(sourceId, name);
      await get().loadPlans();
      set((s) => ({ plans: s.plans.some((p) => p.id === plan.id) ? s.plans : [...s.plans, plan] }));
      await get().loadPlan(plan.id);
      return true;
    } catch (err) {
      handleError(set, err);
      return false;
    }
  },

  detachScenario: async (id) => {
    set({ error: null });
    try {
      const updated = await adapter().detachScenario(id);
      set((s) => ({
        plan: s.plan?.id === id ? updated : s.plan,
        plans: s.plans.map((p) => (p.id === id ? updated : p)),
      }));
      return true;
    } catch (err) {
      handleError(set, err);
      return false;
    }
  },

  submitPlanIntake: async (id, data) => {
    const updated = await adapter().submitPlanIntake(id, data);
    set((s) => ({ plan: s.plan?.id === id ? updated : s.plan }));
    debouncedSimulate(id, get);
  },

  updatePlan: async (id, data) => {
    set({ error: null });
    try {
      const updated = await adapter().updatePlan(id, data);
      set((s) => ({
        plan: s.plan?.id === id ? updated : s.plan,
        plans: s.plans.map((p) => (p.id === id ? updated : p)),
      }));
      debouncedSimulate(id, get);
    } catch (err) {
      handleError(set, err);
    }
  },

  deletePlan: async (id) => {
    set({ error: null });
    try {
      await adapter().deletePlan(id);
    } catch (err) {
      handleError(set, err);
      return false;
    }
    if (get().plan?.id === id) {
      // Drop the deleted plan's pending loads, results and comparison.
      planLoadRequest += 1;
      comparisonRequest += 1;
      simulationRequest += 1;
      if (_debounceTimer) clearTimeout(_debounceTimer);
      _debounceTimer = null;
      set({
        plan: null,
        simulation: null,
        isSimulating: false,
        baselineSimulation: null,
        compareMode: false,
        baselinePlanId: null,
        isComparing: false,
      });
    } else if (get().baselinePlanId === id) {
      comparisonRequest += 1;
      set({
        baselineSimulation: null,
        compareMode: false,
        baselinePlanId: null,
        isComparing: false,
      });
    }
    // A deleted Main's scenarios become independent plans with their current values.
    set((s) => ({
      plans: s.plans
        .filter((p) => p.id !== id)
        .map((p) => (p.parent_plan_id === id ? { ...p, parent_plan_id: null } : p)),
      plan: s.plan?.parent_plan_id === id ? { ...s.plan, parent_plan_id: null } : s.plan,
    }));
    return true;
  },

  // --- Archive ---

  archivedPlans: [],

  loadArchivedPlans: async () => {
    try {
      set({ archivedPlans: await adapter().fetchArchivedPlans() });
    } catch {
      // The archived list is secondary: a failed read keeps the last list and blocks nothing.
    }
  },

  archiveActivePlans: async () => {
    set({ error: null });
    const archived = new Set<string>();
    let ok = true;
    for (const plan of get().plans) {
      try {
        await adapter().archivePlan(plan.id);
        archived.add(plan.id);
      } catch (err) {
        ok = false;
        handleError(set, err);
        break;
      }
    }
    // Archived plans leave the active list at once: until the refreshed list arrives, the planner
    // would otherwise reopen one, which the access policy may refuse to open.
    set((s) => ({
      plans: s.plans.filter((p) => !archived.has(p.id)),
      activePlanId: s.activePlanId && archived.has(s.activePlanId) ? null : s.activePlanId,
    }));
    // Close an archived open plan and its results; the next plan starts empty.
    if (get().plan && archived.has(get().plan!.id)) {
      planLoadRequest += 1;
      comparisonRequest += 1;
      simulationRequest += 1;
      if (_debounceTimer) clearTimeout(_debounceTimer);
      _debounceTimer = null;
      set({
        plan: null,
        simulation: null,
        isSimulating: false,
        baselineSimulation: null,
        compareMode: false,
        baselinePlanId: null,
        isComparing: false,
      });
    }
    await Promise.all([get().loadPlans(), get().loadArchivedPlans()]);
    return ok;
  },

  restorePlan: async (id) => {
    try {
      const restored = await adapter().restorePlan(id);
      set((s) => ({
        archivedPlans: s.archivedPlans.filter((p) => p.id !== id),
        plans: s.plans.some((p) => p.id === id) ? s.plans : [...s.plans, restored],
        plan: s.plan?.id === id ? { ...s.plan, ...editFields(restored) } : s.plan,
      }));
      return true;
    } catch (err) {
      handleError(set, err);
      return false;
    }
  },

  deleteArchivedPlan: async (id) => {
    try {
      await adapter().deletePlan(id);
      set((s) => ({
        archivedPlans: s.archivedPlans.filter((p) => p.id !== id),
        plan: s.plan?.id === id ? null : s.plan,
        simulation: s.plan?.id === id ? null : s.simulation,
      }));
      return true;
    } catch (err) {
      handleError(set, err);
      return false;
    }
  },

  refreshPlanAccess: async (id) => {
    try {
      const fresh = await adapter().fetchPlan(id);
      set((s) => (s.plan?.id === id ? { plan: { ...s.plan, ...editFields(fresh) } } : s));
    } catch (err) {
      handleError(set, err);
    }
  },

  // --- Milestone CRUD ---

  addMilestone: (planId, data) =>
    saveRow(set, get, planId, "milestones", null, () => adapter().createMilestone(planId, data)),

  updateMilestone: (planId, id, data) =>
    saveRow(set, get, planId, "milestones", id, () => adapter().updateMilestone(planId, id, data)),

  deleteMilestone: async (planId, id) => {
    try {
      await adapter().deleteMilestone(planId, id);
      const updated = await adapter().fetchPlan(planId);
      set((s) => {
        if (s.plan?.id !== planId) return s;
        return { plan: updated };
      });
      debouncedSimulate(planId, get);
    } catch (err) {
      handleError(set, err);
    }
  },

  // --- Income CRUD ---

  addIncome: (planId, data) =>
    saveRow(set, get, planId, "income_streams", null, () => adapter().createIncome(planId, data)),

  updateIncome: (planId, id, data) =>
    saveRow(set, get, planId, "income_streams", id, () => adapter().updateIncome(planId, id, data)),

  deleteIncome: async (planId, id) => {
    set({ error: null });
    try {
      await adapter().deleteIncome(planId, id);
      // Refresh the income list and the server's allocation revision.
      const updated = await adapter().fetchPlan(planId);
      set((s) => {
        if (s.plan?.id !== planId) return s;
        return { plan: updated };
      });
      debouncedSimulate(planId, get);
      return true;
    } catch (err) {
      handleError(set, err);
      return false;
    }
  },

  // --- Expense CRUD ---

  addExpense: (planId, data) =>
    saveRow(set, get, planId, "expenses", null, () => adapter().createExpense(planId, data)),

  updateExpense: (planId, id, data) =>
    saveRow(set, get, planId, "expenses", id, () => adapter().updateExpense(planId, id, data)),

  deleteExpense: async (planId, id) => {
    try {
      await adapter().deleteExpense(planId, id);
      set((s) => {
        if (s.plan?.id !== planId) return s;
        return {
          plan: {
            ...s.plan,
            expenses: s.plan.expenses.filter((e) => e.id !== id),
          },
        };
      });
      debouncedSimulate(planId, get);
    } catch (err) {
      handleError(set, err);
    }
  },

  // --- Real Asset CRUD ---

  addRealAsset: (planId, data) =>
    saveRow(set, get, planId, "real_assets", null, () => adapter().createRealAsset(planId, data)),

  updateRealAsset: (planId, id, data) =>
    saveRow(set, get, planId, "real_assets", id, () => adapter().updateRealAsset(planId, id, data)),

  deleteRealAsset: async (planId, id) => {
    try {
      await adapter().deleteRealAsset(planId, id);
      set((s) => {
        if (s.plan?.id !== planId) return s;
        return {
          plan: {
            ...s.plan,
            real_assets: s.plan.real_assets.filter((a) => a.id !== id),
          },
        };
      });
      debouncedSimulate(planId, get);
    } catch (err) {
      handleError(set, err);
    }
  },

  // --- Liability CRUD ---

  addLiability: (planId, data) =>
    saveRow(set, get, planId, "liabilities", null, () => adapter().createLiability(planId, data)),

  updateLiability: (planId, id, data) =>
    saveRow(set, get, planId, "liabilities", id, () => adapter().updateLiability(planId, id, data)),

  deleteLiability: async (planId, id) => {
    try {
      await adapter().deleteLiability(planId, id);
      set((s) => {
        if (s.plan?.id !== planId) return s;
        return {
          plan: {
            ...s.plan,
            liabilities: s.plan.liabilities.filter((l) => l.id !== id),
          },
        };
      });
      debouncedSimulate(planId, get);
    } catch (err) {
      handleError(set, err);
    }
  },

  // --- Bulk updates ---

  updatePriorities: async (planId, priorities, expectedRevision) => {
    try {
      const updated = await adapter().updatePriorities(planId, priorities, expectedRevision);
      set((s) => {
        if (s.plan?.id !== planId) return s;
        return {
          plan: { ...s.plan, priorities: updated.items, priorities_revision: updated.revision },
        };
      });
      debouncedSimulate(planId, get);
    } catch (err) {
      handleError(set, err);
    }
  },

  updateDrawdownOrder: async (planId, entries) => {
    try {
      const updated = await adapter().updateDrawdownOrder(planId, entries);
      set((s) => {
        if (s.plan?.id !== planId) return s;
        return { plan: { ...s.plan, drawdown_order: updated } };
      });
      debouncedSimulate(planId, get);
    } catch (err) {
      handleError(set, err);
    }
  },

  updateResidencyPeriods: async (planId, periods) => {
    set({ error: null });
    try {
      const updated = await adapter().updatePlan(planId, {
        residency_periods: periods,
      });
      set((s) => ({
        plan: s.plan?.id === planId ? updated : s.plan,
        plans: s.plans.map((p) => (p.id === planId ? updated : p)),
      }));
      debouncedSimulate(planId, get);
    } catch (err) {
      handleError(set, err);
      throw err;
    }
  },

  // --- Simulation ---

  runSimulation: async (planId) => {
    if (get().plan?.id !== planId) return;
    const request = ++simulationRequest;
    set({ isSimulating: true });
    try {
      const result = await adapter().runSimulation(planId);
      if (request !== simulationRequest || get().plan?.id !== planId) return;
      set({ simulation: result, isSimulating: false, simulationError: null });
    } catch (err) {
      if (request !== simulationRequest || get().plan?.id !== planId) return;
      // Shown where the results would be, until the next projection runs.
      set({ simulation: null, isSimulating: false, simulationError: simulationFailure(err) });
    }
  },
}));
