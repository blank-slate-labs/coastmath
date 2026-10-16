import { vi } from "vitest";
import type { Mock } from "vitest";

import type { StorageAdapter } from "@/storage/adapter";

/**
 * A `StorageAdapter` whose every member is a `vi.fn()`. Arguments keep their types;
 * resolved values are free, since tests return partial records.
 */
export type MockAdapter = {
  [K in keyof StorageAdapter]: Mock<(...args: Parameters<StorageAdapter[K]>) => unknown> &
    StorageAdapter[K];
};

/** Per-test replacements, keyed by adapter member: a `vi.fn()` or a plain function. */
export type AdapterOverrides = Partial<{
  [K in keyof StorageAdapter]: Mock | ((...args: Parameters<StorageAdapter[K]>) => unknown);
}>;

type Default = "list" | "catalog" | "none";

// What each member resolves to until a test says otherwise: lists are empty, a write
// or a single record resolves to undefined. `satisfies` fails tsc when the interface
// gains or loses a member.
const DEFAULTS = {
  fetchPlans: "list",
  fetchPlan: "none",
  createPlan: "none",
  duplicatePlan: "none",
  createScenario: "none",
  fetchInheritance: "none",
  resetInheritance: "none",
  restoreInheritance: "none",
  syncInheritance: "none",
  detachScenario: "none",
  submitPlanIntake: "none",
  updatePlan: "none",
  deletePlan: "none",
  archivePlan: "none",
  restorePlan: "none",
  fetchArchivedPlans: "list",
  recordEditNotice: "none",
  listLocalTaxJurisdictions: "catalog",
  listTaxRegimes: "list",
  listMilestones: "list",
  createMilestone: "none",
  updateMilestone: "none",
  deleteMilestone: "none",
  listIncomes: "list",
  createIncome: "none",
  updateIncome: "none",
  deleteIncome: "none",
  listExpenses: "list",
  createExpense: "none",
  updateExpense: "none",
  deleteExpense: "none",
  listAccounts: "list",
  createAccount: "none",
  updateAccount: "none",
  deleteAccount: "none",
  listPriorities: "list",
  updatePriorities: "none",
  listDrawdownOrder: "list",
  updateDrawdownOrder: "none",
  listProgressPoints: "list",
  createProgressPoint: "none",
  deleteProgressPoint: "none",
  listAssumptions: "list",
  createAssumption: "none",
  updateAssumption: "none",
  deleteAssumption: "none",
  runSimulation: "none",
  runStressTest: "none",
  runScenarioStressTest: "none",
  fetchCompare: "none",
  getMe: "none",
  logout: "none",
  listCharities: "list",
  createCharity: "none",
  updateCharity: "none",
  deleteCharity: "none",
  listRealAssets: "list",
  createRealAsset: "none",
  updateRealAsset: "none",
  deleteRealAsset: "none",
  listLiabilities: "list",
  createLiability: "none",
  updateLiability: "none",
  deleteLiability: "none",
  getAmortizationSchedule: "none",
  runMonteCarlo: "none",
  runMonteCarloTrial: "none",
  compareWithdrawalStrategies: "none",
  runPlanChecks: "none",
  exploreClaimingAges: "none",
  runWellness: "none",
} satisfies Record<keyof StorageAdapter, Default>;

function resolved(kind: Default): () => Promise<unknown> {
  if (kind === "list") return () => Promise.resolve([]);
  if (kind === "catalog") return () => Promise.resolve({ tax_year: 2026, jurisdictions: [] });
  return () => Promise.resolve(undefined);
}

/**
 * A complete adapter of `vi.fn()` members. An override that is already a mock is used
 * as is, so a test keeps its handle on it; a plain function is wrapped in `vi.fn()`.
 * `mockReset()` returns a default member to its default resolution.
 */
export function makeAdapter(overrides: AdapterOverrides = {}): MockAdapter {
  const adapter: Record<string, unknown> = {};
  for (const [name, kind] of Object.entries(DEFAULTS) as [keyof StorageAdapter, Default][]) {
    const override = overrides[name] as ((...args: never[]) => unknown) | undefined;
    adapter[name] =
      override === undefined
        ? vi.fn(resolved(kind))
        : vi.isMockFunction(override)
          ? override
          : vi.fn(override);
  }
  return adapter as unknown as MockAdapter;
}
