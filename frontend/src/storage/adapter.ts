import type {
  ArchivedPlanSummary,
  PlanData,
  PlanSummary,
  PlanCreate,
  PlanIntake,
  SimulationResult,
  CompareResponse,
  Milestone,
  MilestoneCreate,
  MilestoneUpdate,
  Income,
  IncomeCreate,
  IncomeUpdate,
  Expense,
  ExpenseCreate,
  ExpenseUpdate,
  Account,
  AccountCreate,
  AccountUpdate,
  CashFlowPriorityCreate,
  CashFlowPriority,
  DrawdownEntryCreate,
  DrawdownEntry,
  ProgressPoint,
  ProgressPointCreate,
  AssumptionCurve,
  AssumptionCurveCreate,
  AssumptionCurveUpdate,
  HistoricalStressResult,
  ScenarioStressRequest,
  ScenarioStressResult,
  LocalTaxCatalog,
  TaxRegimeCountry,
  TaxRegimeRegistry,
  User,
  RealAsset,
  RealAssetCreate,
  RealAssetUpdate,
  Liability,
  LiabilityCreate,
  LiabilityUpdate,
  MonteCarloResult,
  MonteCarloTrialDetail,
  WithdrawalCompareRequest,
  WithdrawalCompareResponse,
  ClaimingExplorerResponse,
  WellnessResponse,
} from "@/types/plan";
import type { PlanChecksResponse } from "@/types/plan";

import type { CharityEntity, CharityEntityCreate, CharityEntityUpdate } from "@/types/charity";
import type { InheritanceReset, InheritanceRestore, PlanInheritance } from "@/types/scenario";

import type { AmortizationResponse } from "@/api/liabilities";

// ── StorageAdapter interface ──────────────────────────────────────

export interface StorageAdapter {
  // Plans
  fetchPlans(): Promise<PlanSummary[]>;
  fetchPlan(id: string): Promise<PlanData>;
  createPlan(data: PlanCreate): Promise<PlanData>;
  duplicatePlan(id: string): Promise<PlanData>;
  // Scenarios: plans that receive their Main plan's changes
  createScenario(sourceId: string, name?: string): Promise<PlanData>;
  fetchInheritance(planId: string): Promise<PlanInheritance>;
  resetInheritance(planId: string, body: InheritanceReset): Promise<PlanInheritance>;
  restoreInheritance(planId: string, body: InheritanceRestore): Promise<PlanInheritance>;
  syncInheritance(planId: string): Promise<PlanInheritance>;
  detachScenario(planId: string): Promise<PlanData>;
  submitPlanIntake(id: string, data: PlanIntake): Promise<PlanData>;
  updatePlan(id: string, data: Partial<PlanCreate>): Promise<PlanData>;
  deletePlan(id: string): Promise<void>;
  archivePlan(id: string): Promise<PlanData>;
  restorePlan(id: string): Promise<PlanData>;
  fetchArchivedPlans(): Promise<ArchivedPlanSummary[]>;
  recordEditNotice(id: string): Promise<void>;
  listLocalTaxJurisdictions(): Promise<LocalTaxCatalog>;
  /** Countries with their own tax rules (GET /tax-regimes). */
  listTaxRegimes(): Promise<TaxRegimeRegistry | TaxRegimeCountry[]>;

  // Milestones
  listMilestones(planId: string): Promise<Milestone[]>;
  createMilestone(planId: string, data: MilestoneCreate): Promise<Milestone>;
  updateMilestone(planId: string, id: string, data: MilestoneUpdate): Promise<Milestone>;
  deleteMilestone(planId: string, id: string): Promise<void>;

  // Incomes
  listIncomes(planId: string): Promise<Income[]>;
  createIncome(planId: string, data: IncomeCreate): Promise<Income>;
  updateIncome(planId: string, id: string, data: IncomeUpdate): Promise<Income>;
  deleteIncome(planId: string, id: string): Promise<void>;

  // Expenses
  listExpenses(planId: string): Promise<Expense[]>;
  createExpense(planId: string, data: ExpenseCreate): Promise<Expense>;
  updateExpense(planId: string, id: string, data: ExpenseUpdate): Promise<Expense>;
  deleteExpense(planId: string, id: string): Promise<void>;

  // Accounts
  listAccounts(planId?: string): Promise<Account[]>;
  createAccount(data: AccountCreate, planId?: string): Promise<Account>;
  updateAccount(id: string, data: AccountUpdate, planId?: string): Promise<Account>;
  deleteAccount(id: string, planId?: string): Promise<void>;

  // Priorities
  listPriorities(planId: string): Promise<CashFlowPriority[]>;
  updatePriorities(
    planId: string,
    items: CashFlowPriorityCreate[],
    expectedRevision: number,
  ): Promise<{ items: CashFlowPriority[]; revision: number }>;

  // Drawdown order
  listDrawdownOrder(planId: string): Promise<DrawdownEntry[]>;
  updateDrawdownOrder(planId: string, items: DrawdownEntryCreate[]): Promise<DrawdownEntry[]>;

  // Progress points
  listProgressPoints(since?: string): Promise<ProgressPoint[]>;
  createProgressPoint(data: ProgressPointCreate): Promise<ProgressPoint>;
  deleteProgressPoint(id: string): Promise<void>;

  // Assumptions
  listAssumptions(planId: string): Promise<AssumptionCurve[]>;
  createAssumption(planId: string, data: AssumptionCurveCreate): Promise<AssumptionCurve>;
  updateAssumption(
    planId: string,
    curveId: string,
    data: AssumptionCurveUpdate,
  ): Promise<AssumptionCurve>;
  deleteAssumption(planId: string, curveId: string): Promise<void>;

  // Simulation
  runSimulation(planId: string): Promise<SimulationResult>;
  runStressTest(planId: string, historicalStartYear: number): Promise<HistoricalStressResult>;
  runScenarioStressTest(planId: string, body: ScenarioStressRequest): Promise<ScenarioStressResult>;
  fetchCompare(planId: string, baselinePlanId: string): Promise<CompareResponse>;

  // Auth
  getMe(): Promise<User>;
  logout(): Promise<void>;

  // Charities
  listCharities(planId: string): Promise<CharityEntity[]>;
  createCharity(planId: string, data: CharityEntityCreate): Promise<CharityEntity>;
  updateCharity(planId: string, id: string, data: CharityEntityUpdate): Promise<CharityEntity>;
  deleteCharity(planId: string, id: string): Promise<void>;

  // Real assets
  listRealAssets(planId: string): Promise<RealAsset[]>;
  createRealAsset(planId: string, data: RealAssetCreate): Promise<RealAsset>;
  updateRealAsset(planId: string, id: string, data: RealAssetUpdate): Promise<RealAsset>;
  deleteRealAsset(planId: string, id: string): Promise<void>;

  // Liabilities
  listLiabilities(planId: string): Promise<Liability[]>;
  createLiability(planId: string, data: LiabilityCreate): Promise<Liability>;
  updateLiability(planId: string, id: string, data: LiabilityUpdate): Promise<Liability>;
  deleteLiability(planId: string, id: string): Promise<void>;
  getAmortizationSchedule(planId: string, liabilityId: string): Promise<AmortizationResponse>;

  // Monte Carlo
  runMonteCarlo(
    planId: string,
    nTrials?: number,
    options?: monteCarloApi.MonteCarloOptions,
  ): Promise<MonteCarloResult>;
  runMonteCarloTrial(
    planId: string,
    index: number,
    nTrials: number,
    baseSeed: number,
    options?: monteCarloApi.MonteCarloOptions,
  ): Promise<MonteCarloTrialDetail>;

  // Withdrawal strategies (a comparison; the plan is unchanged)
  compareWithdrawalStrategies(
    planId: string,
    body: WithdrawalCompareRequest,
  ): Promise<WithdrawalCompareResponse>;

  // Plan accuracy checklist (an analysis; the plan is unchanged)
  runPlanChecks(planId: string): Promise<PlanChecksResponse>;
  // Social Security claiming ages (a comparison; the plan is unchanged)
  exploreClaimingAges(planId: string): Promise<ClaimingExplorerResponse>;
  // Wellness scorecard (an analysis; nothing is saved)
  runWellness(planId: string): Promise<WellnessResponse>;
}

// ── ApiStorageAdapter ─────────────────────────────────────────────

import * as clientApi from "@/api/client";
import * as charityApi from "@/api/charity";
import * as realAssetsApi from "@/api/real_assets";
import * as liabilitiesApi from "@/api/liabilities";
import * as monteCarloApi from "@/api/monte_carlo";

export class ApiStorageAdapter implements StorageAdapter {
  // Plans
  fetchPlans() {
    return clientApi.fetchPlans();
  }
  fetchPlan(id: string) {
    return clientApi.fetchPlan(id);
  }
  createPlan(data: PlanCreate) {
    return clientApi.createPlan(data);
  }
  duplicatePlan(id: string) {
    return clientApi.duplicatePlan(id);
  }
  createScenario(sourceId: string, name?: string) {
    return clientApi.createScenario(sourceId, name);
  }
  fetchInheritance(planId: string) {
    return clientApi.fetchInheritance(planId);
  }
  resetInheritance(planId: string, body: InheritanceReset) {
    return clientApi.resetInheritance(planId, body);
  }
  restoreInheritance(planId: string, body: InheritanceRestore) {
    return clientApi.restoreInheritance(planId, body);
  }
  syncInheritance(planId: string) {
    return clientApi.syncInheritance(planId);
  }
  detachScenario(planId: string) {
    return clientApi.detachScenario(planId);
  }
  submitPlanIntake(id: string, data: PlanIntake) {
    return clientApi.submitPlanIntake(id, data);
  }
  updatePlan(id: string, data: Partial<PlanCreate>) {
    return clientApi.updatePlan(id, data);
  }
  deletePlan(id: string) {
    return clientApi.deletePlan(id);
  }
  archivePlan(id: string) {
    return clientApi.archivePlan(id);
  }
  restorePlan(id: string) {
    return clientApi.restorePlan(id);
  }
  fetchArchivedPlans() {
    return clientApi.fetchArchivedPlans();
  }
  recordEditNotice(id: string) {
    return clientApi.recordEditNotice(id);
  }
  listLocalTaxJurisdictions() {
    return clientApi.fetchLocalTaxJurisdictions();
  }
  listTaxRegimes() {
    return clientApi.fetchTaxRegimes();
  }

  // Milestones
  listMilestones(planId: string) {
    return clientApi.listMilestones(planId);
  }
  createMilestone(planId: string, data: MilestoneCreate) {
    return clientApi.createMilestone(planId, data);
  }
  updateMilestone(planId: string, id: string, data: MilestoneUpdate) {
    return clientApi.updateMilestone(planId, id, data);
  }
  deleteMilestone(planId: string, id: string) {
    return clientApi.deleteMilestone(planId, id);
  }

  // Incomes
  listIncomes(planId: string) {
    return clientApi.listIncomes(planId);
  }
  createIncome(planId: string, data: IncomeCreate) {
    return clientApi.createIncome(planId, data);
  }
  updateIncome(planId: string, id: string, data: IncomeUpdate) {
    return clientApi.updateIncome(planId, id, data);
  }
  deleteIncome(planId: string, id: string) {
    return clientApi.deleteIncome(planId, id);
  }

  // Expenses
  listExpenses(planId: string) {
    return clientApi.listExpenses(planId);
  }
  createExpense(planId: string, data: ExpenseCreate) {
    return clientApi.createExpense(planId, data);
  }
  updateExpense(planId: string, id: string, data: ExpenseUpdate) {
    return clientApi.updateExpense(planId, id, data);
  }
  deleteExpense(planId: string, id: string) {
    return clientApi.deleteExpense(planId, id);
  }

  // Accounts
  listAccounts(planId?: string) {
    return clientApi.listAccounts(planId);
  }
  createAccount(data: AccountCreate, planId?: string) {
    return clientApi.createAccount(data, planId);
  }
  updateAccount(id: string, data: AccountUpdate, planId?: string) {
    return clientApi.updateAccount(id, data, planId);
  }
  deleteAccount(id: string, planId?: string) {
    return clientApi.deleteAccount(id, planId);
  }

  // Priorities
  listPriorities(planId: string) {
    return clientApi.listPriorities(planId);
  }
  updatePriorities(planId: string, items: CashFlowPriorityCreate[], expectedRevision: number) {
    return clientApi.updatePriorities(planId, items, expectedRevision);
  }

  // Drawdown order
  listDrawdownOrder(planId: string) {
    return clientApi.listDrawdownOrder(planId);
  }
  updateDrawdownOrder(planId: string, items: DrawdownEntryCreate[]) {
    return clientApi.updateDrawdownOrder(planId, items);
  }

  // Progress points
  listProgressPoints(since?: string) {
    return clientApi.listProgressPoints(since);
  }
  createProgressPoint(data: ProgressPointCreate) {
    return clientApi.createProgressPoint(data);
  }
  deleteProgressPoint(id: string) {
    return clientApi.deleteProgressPoint(id);
  }

  // Assumptions
  listAssumptions(planId: string) {
    return clientApi.listAssumptions(planId);
  }
  createAssumption(planId: string, data: AssumptionCurveCreate) {
    return clientApi.createAssumption(planId, data);
  }
  updateAssumption(planId: string, curveId: string, data: AssumptionCurveUpdate) {
    return clientApi.updateAssumption(planId, curveId, data);
  }
  deleteAssumption(planId: string, curveId: string) {
    return clientApi.deleteAssumption(planId, curveId);
  }

  // Simulation
  runSimulation(planId: string) {
    return clientApi.runSimulation(planId);
  }
  runStressTest(planId: string, historicalStartYear: number) {
    return clientApi.runStressTest(planId, historicalStartYear);
  }
  runScenarioStressTest(planId: string, body: ScenarioStressRequest) {
    return clientApi.runScenarioStressTest(planId, body);
  }
  fetchCompare(planId: string, baselinePlanId: string) {
    return clientApi.fetchCompare(planId, baselinePlanId);
  }

  // Auth
  getMe() {
    return clientApi.getMe();
  }
  logout() {
    return clientApi.logout();
  }

  // Charities
  listCharities(planId: string) {
    return charityApi.listCharities(planId);
  }
  createCharity(planId: string, data: CharityEntityCreate) {
    return charityApi.createCharity(planId, data);
  }
  updateCharity(planId: string, id: string, data: CharityEntityUpdate) {
    return charityApi.updateCharity(planId, id, data);
  }
  deleteCharity(planId: string, id: string) {
    return charityApi.deleteCharity(planId, id);
  }

  // Real assets
  listRealAssets(planId: string) {
    return realAssetsApi.listRealAssets(planId);
  }
  createRealAsset(planId: string, data: RealAssetCreate) {
    return realAssetsApi.createRealAsset(planId, data);
  }
  updateRealAsset(planId: string, id: string, data: RealAssetUpdate) {
    return realAssetsApi.updateRealAsset(planId, id, data);
  }
  deleteRealAsset(planId: string, id: string) {
    return realAssetsApi.deleteRealAsset(planId, id);
  }

  // Liabilities
  listLiabilities(planId: string) {
    return liabilitiesApi.listLiabilities(planId);
  }
  createLiability(planId: string, data: LiabilityCreate) {
    return liabilitiesApi.createLiability(planId, data);
  }
  updateLiability(planId: string, id: string, data: LiabilityUpdate) {
    return liabilitiesApi.updateLiability(planId, id, data);
  }
  deleteLiability(planId: string, id: string) {
    return liabilitiesApi.deleteLiability(planId, id);
  }
  getAmortizationSchedule(planId: string, liabilityId: string) {
    return liabilitiesApi.getAmortizationSchedule(planId, liabilityId);
  }

  // Monte Carlo
  runMonteCarlo(planId: string, nTrials?: number, options?: monteCarloApi.MonteCarloOptions) {
    return monteCarloApi.runMonteCarlo(planId, nTrials, options);
  }
  runMonteCarloTrial(
    planId: string,
    index: number,
    nTrials: number,
    baseSeed: number,
    options?: monteCarloApi.MonteCarloOptions,
  ) {
    return monteCarloApi.runMonteCarloTrial(planId, index, nTrials, baseSeed, options);
  }

  // Withdrawal strategies
  compareWithdrawalStrategies(planId: string, body: WithdrawalCompareRequest) {
    return clientApi.compareWithdrawalStrategies(planId, body);
  }

  // Plan accuracy checklist
  runPlanChecks(planId: string) {
    return clientApi.runPlanChecks(planId);
  }

  // Social Security claiming ages
  exploreClaimingAges(planId: string) {
    return clientApi.exploreClaimingAges(planId);
  }

  // Wellness scorecard
  runWellness(planId: string) {
    return clientApi.runWellness(planId);
  }
}
