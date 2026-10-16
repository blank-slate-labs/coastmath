import axios from "axios";
import { saveRequestKey, useSaveStore } from "@/stores/save_store";
import { usePlanStore } from "@/stores/plan_store";
import { saveAction, saveFailure } from "./save_error";
import { extensions } from "@/extensions";

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
  SEPPPreviewRequest,
  SEPPPreviewResponse,
  TaxStrategyCompareRequest,
  TaxStrategyCompareResponse,
  StrategySearchRequest,
  StrategySearchResponse,
  TaxSuggestionsResponse,
  WithdrawalCompareRequest,
  ClaimingExplorerResponse,
  WithdrawalCompareResponse,
  WellnessResponse,
} from "@/types/plan";
import type { InheritanceReset, InheritanceRestore, PlanInheritance } from "@/types/scenario";
import type { PlanChecksResponse } from "@/types/plan";

// ── Axios instance ─────────────────────────────────────────────────

export const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
});

export const deleteCurrentUser = (): Promise<void> =>
  api.delete("/auth/me", { data: { confirmation: "DELETE" } }).then(() => undefined);

/** YYYY-MM-DD in the browser's own timezone (never toISOString, which is UTC). */
export function localCalendarDate(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

const saveAttempts = new WeakMap<object, { key: string; attempt: number; action: string }>();

const PLAN_IN_PATH = /(?:^|\/)plans\/([0-9a-f-]{36})(?:\/|$|\?)/i;
/**
 * Whether a refused request is one the person is waiting on. Every write is; a read is only when it
 * belongs to the plan they opened. Background reads (a plan just archived or switched away from, or
 * household data read without a plan, as panels do while a new plan loads) fail quietly instead of
 * stacking an upgrade prompt over whatever the person is doing.
 */
function userFacing(
  config: { method?: string; url?: string; params?: { plan_id?: unknown } } | undefined,
): boolean {
  if (!config || (config.method ?? "get").toLowerCase() !== "get") return true;
  const active = usePlanStore.getState().activePlanId;
  const planId =
    config.url?.match(PLAN_IN_PATH)?.[1] ??
    (typeof config.params?.plan_id === "string" ? config.params.plan_id : null);
  return planId !== null && planId === active;
}
// Several panels read the same accounts, plan lists and progress as a plan opens; one
// request in flight serves them all. Settled reads are not cached.
const sharedReads = new Map<string, Promise<unknown>>();
function sharedGet<T>(path: string, params?: Record<string, string>): Promise<T> {
  const key = params ? `${path}?${new URLSearchParams(params)}` : path;
  const pending = sharedReads.get(key);
  if (pending) return pending as Promise<T>;
  const request: Promise<T> = api
    .get(path, { params })
    .then((r) => r.data)
    .finally(() => {
      if (sharedReads.get(key) === request) sharedReads.delete(key);
    });
  sharedReads.set(key, request);
  return request;
}
api.interceptors.request.use((config) => {
  // A write may change what a read returns, so a read that started before it is never shared afterwards.
  if ((config.method ?? "get").toLowerCase() !== "get") sharedReads.clear();
  // Before save tracking, so a request an extension stops never reports a failed save.
  extensions.api?.beforeRequest?.(config);
  const key = saveRequestKey(config.method, config.url);
  if (key)
    saveAttempts.set(config, {
      key,
      attempt: useSaveStore.getState().begin(key),
      action: saveAction(config.method, config.url, config.data, usePlanStore.getState().plan),
    });
  // "Now" plans start on the user's calendar day, not the server's UTC day.
  config.headers["X-Client-Date"] = localCalendarDate();
  return config;
});

api.interceptors.response.use(
  (response) => {
    const save = saveAttempts.get(response.config);
    if (save) useSaveStore.getState().finish(save.key, true, save.attempt);
    return response;
  },
  (error) => {
    // A refusal an extension explains (e.g. with a prompt) is announced once;
    // callers get the extension's error instead of a generic failure.
    const refusal = extensions.api?.refusal?.(error);
    if (refusal && userFacing(error.config)) refusal.announce();
    const save = error.config && saveAttempts.get(error.config);
    if (save) {
      const failure = saveFailure(error, save.action);
      useSaveStore.getState().finish(save.key, false, save.attempt, failure);
      if (refusal) throw refusal.error(failure.message);
      // The status stays readable, e.g. for an allocation revision conflict (409).
      throw Object.assign(new Error(failure.message), {
        status: error.response?.status as number | undefined,
      });
    }
    if (refusal) throw refusal.error(refusal.message);
    const apiError = error.response?.data?.error;
    // Keep status/headers/envelope for callers that distinguish an expired
    // session (401) from a network or server failure.
    if (typeof apiError?.message === "string") error.message = apiError.message;
    throw error;
  },
);

// ── Plans ──────────────────────────────────────────────────────────

export const fetchPlans = (): Promise<PlanSummary[]> => sharedGet("/plans/summaries");

export const fetchPlan = (id: string): Promise<PlanData> =>
  api.get(`/plans/${id}`).then((r) => r.data);

export const createPlan = async (data: PlanCreate): Promise<PlanData> => {
  // New personal plans use the same independent account scope as native.
  // Resolve per request/session; never cache ownership across sign-out.
  const clientId = data.client_id ?? (await api.post<{ id: string }>("/clients/personal")).data.id;
  if (!clientId)
    throw new Error("Could not resolve your personal workspace. Your plan was not created.");
  return api.post("/plans", { ...data, client_id: clientId }).then((r) => r.data);
};

export const duplicatePlan = (id: string): Promise<PlanData> =>
  api.post(`/plans/${id}/duplicate`).then((r) => r.data);

// ── Scenarios: plans that receive their Main plan's changes ────────

/** Creates a scenario of a Main or independent plan; a scenario can't be the source. */
export const createScenario = (sourceId: string, name?: string): Promise<PlanData> =>
  api
    .post(`/plans/${sourceId}/duplicate`, { as_scenario: true, ...(name ? { name } : {}) })
    .then((r) => r.data);

export const fetchInheritance = (planId: string): Promise<PlanInheritance> =>
  api.get(`/plans/${planId}/inheritance`).then((r) => r.data);

/** Uses Main's values again for a row, plan fields or a whole list; returns the updated inheritance. */
export const resetInheritance = (
  planId: string,
  body: InheritanceReset,
): Promise<PlanInheritance> =>
  api.post(`/plans/${planId}/inheritance/reset`, body).then((r) => r.data);

export const restoreInheritance = (
  planId: string,
  body: InheritanceRestore,
): Promise<PlanInheritance> =>
  api.post(`/plans/${planId}/inheritance/restore`, body).then((r) => r.data);

export const syncInheritance = (planId: string): Promise<PlanInheritance> =>
  api.post(`/plans/${planId}/inheritance/sync`).then((r) => r.data);

/** The scenario keeps its current values and stops receiving Main's changes. */
export const detachScenario = (planId: string): Promise<PlanData> =>
  api.post(`/plans/${planId}/detach`).then((r) => r.data);

/** Turns the new-plan goals into plan items; returns the updated plan. */
export const submitPlanIntake = (id: string, data: PlanIntake): Promise<PlanData> =>
  api.post(`/plans/${id}/intake`, data).then((r) => r.data);

export const updatePlan = (id: string, data: Partial<PlanCreate>): Promise<PlanData> =>
  api.put(`/plans/${id}`, data).then((r) => r.data);

export const deletePlan = (id: string): Promise<void> =>
  api.delete(`/plans/${id}`).then(() => undefined);

/** Sets the plan aside; under a one-plan limit this is how a new plan is started. */
export const archivePlan = (id: string): Promise<PlanData> =>
  api.post(`/plans/${id}/archive`).then((r) => r.data);

/** Makes an archived plan active and editable again. */
export const restorePlan = (id: string): Promise<PlanData> =>
  api.post(`/plans/${id}/restore`).then((r) => r.data);

export const fetchArchivedPlans = (): Promise<ArchivedPlanSummary[]> =>
  sharedGet("/plans/archived");

/** Records that the closing edit-window notice was shown; the server keeps the first time. */
export const recordEditNotice = (id: string): Promise<void> =>
  api.post(`/plans/${id}/edit-notice`).then(() => undefined);

/** Every state's catalog localities (public, ~50 KB); callers filter by state. */
export const fetchLocalTaxJurisdictions = (): Promise<LocalTaxCatalog> =>
  api.get("/local-tax-jurisdictions").then((r) => r.data);

/** Countries with their own tax rules: regions, account kinds, benefit rules and approximations. */
export const fetchTaxRegimes = (): Promise<TaxRegimeRegistry | TaxRegimeCountry[]> =>
  api.get("/tax-regimes").then((r) => r.data);

// ── Milestones ─────────────────────────────────────────────────────

export const listMilestones = (planId: string): Promise<Milestone[]> =>
  api.get(`/plans/${planId}/milestones`).then((r) => r.data);

export const createMilestone = (planId: string, data: MilestoneCreate): Promise<Milestone> =>
  api.post(`/plans/${planId}/milestones`, data).then((r) => r.data);

export const updateMilestone = (
  planId: string,
  id: string,
  data: MilestoneUpdate,
): Promise<Milestone> => api.put(`/plans/${planId}/milestones/${id}`, data).then((r) => r.data);

export const deleteMilestone = (planId: string, id: string): Promise<void> =>
  api.delete(`/plans/${planId}/milestones/${id}`).then(() => undefined);

// ── Incomes ────────────────────────────────────────────────────────

export const listIncomes = (planId: string): Promise<Income[]> =>
  api.get(`/plans/${planId}/incomes`).then((r) => r.data);

export const createIncome = (planId: string, data: IncomeCreate): Promise<Income> =>
  api.post(`/plans/${planId}/incomes`, data).then((r) => r.data);

export const updateIncome = (planId: string, id: string, data: IncomeUpdate): Promise<Income> =>
  api.put(`/plans/${planId}/incomes/${id}`, data).then((r) => r.data);

export const deleteIncome = (planId: string, id: string): Promise<void> =>
  api.delete(`/plans/${planId}/incomes/${id}`).then(() => undefined);

// ── Expenses ───────────────────────────────────────────────────────

export const listExpenses = (planId: string): Promise<Expense[]> =>
  api.get(`/plans/${planId}/expenses`).then((r) => r.data);

export const createExpense = (planId: string, data: ExpenseCreate): Promise<Expense> =>
  api.post(`/plans/${planId}/expenses`, data).then((r) => r.data);

export const updateExpense = (planId: string, id: string, data: ExpenseUpdate): Promise<Expense> =>
  api.put(`/plans/${planId}/expenses/${id}`, data).then((r) => r.data);

export const deleteExpense = (planId: string, id: string): Promise<void> =>
  api.delete(`/plans/${planId}/expenses/${id}`).then(() => undefined);

// ── Accounts ───────────────────────────────────────────────────────

const accountPath = (planId?: string) => (planId ? `/plans/${planId}/accounts` : "/accounts");
export const listAccounts = (planId?: string): Promise<Account[]> => sharedGet(accountPath(planId));

export const createAccount = (data: AccountCreate, planId?: string): Promise<Account> =>
  api.post(accountPath(planId), data).then((r) => r.data);

export const updateAccount = (id: string, data: AccountUpdate, planId?: string): Promise<Account> =>
  api.put(`${accountPath(planId)}/${id}`, data).then((r) => r.data);

export const deleteAccount = (id: string, planId?: string): Promise<void> =>
  api.delete(`${accountPath(planId)}/${id}`).then(() => undefined);

// ── Priorities (bulk replace) ──────────────────────────────────────

export const listPriorities = (planId: string): Promise<CashFlowPriority[]> =>
  api.get(`/plans/${planId}/priorities`).then((r) => r.data.items);

export const updatePriorities = (
  planId: string,
  items: CashFlowPriorityCreate[],
  expectedRevision: number,
): Promise<{ items: CashFlowPriority[]; revision: number }> =>
  api
    .put(`/plans/${planId}/priorities`, { items, expected_revision: expectedRevision })
    .then((r) => r.data);

// ── Drawdown order (bulk replace) ──────────────────────────────────

export const listDrawdownOrder = (planId: string): Promise<DrawdownEntry[]> =>
  api.get(`/plans/${planId}/drawdown-order`).then((r) => r.data);

export const updateDrawdownOrder = (
  planId: string,
  items: DrawdownEntryCreate[],
): Promise<DrawdownEntry[]> =>
  api.put(`/plans/${planId}/drawdown-order`, { items }).then((r) => r.data);

// ── Progress Points ────────────────────────────────────────────────

export const listProgressPoints = (since?: string): Promise<ProgressPoint[]> => {
  return sharedGet("/progress-points", since ? { since } : undefined);
};

export const createProgressPoint = (data: ProgressPointCreate): Promise<ProgressPoint> =>
  api.post("/progress-points", data).then((r) => r.data);

export const deleteProgressPoint = (id: string): Promise<void> =>
  api.delete(`/progress-points/${id}`).then(() => undefined);

// ── Assumptions ────────────────────────────────────────────────────

export const listAssumptions = (planId: string): Promise<AssumptionCurve[]> =>
  api.get(`/plans/${planId}/assumptions`).then((r) => r.data);

export const createAssumption = (
  planId: string,
  data: AssumptionCurveCreate,
): Promise<AssumptionCurve> => api.post(`/plans/${planId}/assumptions`, data).then((r) => r.data);

export const updateAssumption = (
  planId: string,
  curveId: string,
  data: AssumptionCurveUpdate,
): Promise<AssumptionCurve> =>
  api.put(`/plans/${planId}/assumptions/${curveId}`, data).then((r) => r.data);

export const deleteAssumption = (planId: string, curveId: string): Promise<void> =>
  api.delete(`/plans/${planId}/assumptions/${curveId}`).then(() => undefined);

// ── Simulation ─────────────────────────────────────────────────────

export const runSimulation = (planId: string): Promise<SimulationResult> =>
  api.post(`/plans/${planId}/simulate`).then((r) => r.data);

export const runStressTest = (
  planId: string,
  historicalStartYear: number,
): Promise<HistoricalStressResult> =>
  api
    .post(`/plans/${planId}/simulate`, null, {
      params: { historical_start_year: historicalStartYear },
    })
    .then((r) => r.data);

export const runScenarioStressTest = (
  planId: string,
  body: ScenarioStressRequest,
): Promise<ScenarioStressResult> =>
  api.post(`/plans/${planId}/scenario-stress`, body).then((r) => r.data);

export const fetchCompare = (planId: string, baselinePlanId: string): Promise<CompareResponse> =>
  api.post(`/plans/${planId}/compare`, { baseline_plan_id: baselinePlanId }).then((r) => r.data);

// ── Social Security Estimate ───────────────────────────────────────

export interface SSEstimateResponse {
  estimated_annual_benefit: number;
  claiming_age: number;
  claiming_factor: number;
  full_retirement_age: number;
  expected_benefit_percentage?: number;
  expected_benefit_fraction?: number;
}

export interface SSEstimateOptions {
  monthlyPia?: number;
  expectedBenefitPercentage?: number;
}

export const compareWithdrawalStrategies = (
  planId: string,
  body: WithdrawalCompareRequest,
): Promise<WithdrawalCompareResponse> =>
  api.post(`/plans/${planId}/withdrawal-strategies/compare`, body).then((r) => r.data);

export const compareTaxStrategies = (
  planId: string,
  body: TaxStrategyCompareRequest,
): Promise<TaxStrategyCompareResponse> =>
  api.post(`/plans/${planId}/tax-strategies/compare`, body).then((r) => r.data);

export const searchTaxStrategies = (
  planId: string,
  body: StrategySearchRequest,
): Promise<StrategySearchResponse> =>
  api.post(`/plans/${planId}/tax-strategies/search`, body).then((r) => r.data);

export const suggestTaxStrategies = (planId: string): Promise<TaxSuggestionsResponse> =>
  api.post(`/plans/${planId}/tax-suggestions`).then((r) => r.data);

export const previewSepp = (body: SEPPPreviewRequest): Promise<SEPPPreviewResponse> =>
  api.post("/plans/sepp-preview", body).then((r) => r.data);

export const estimateSocialSecurity = (
  currentAnnualIncome: number | null,
  claimingAge: number,
  birthYear?: number | null,
  options?: SSEstimateOptions,
): Promise<SSEstimateResponse> =>
  api
    .post("/plans/ss-estimate", {
      ...(currentAnnualIncome != null ? { current_annual_income: currentAnnualIncome } : {}),
      claiming_age: claimingAge,
      ...(birthYear != null ? { birth_year: birthYear } : {}),
      ...(options?.monthlyPia != null ? { monthly_pia: options.monthlyPia } : {}),
      ...(options?.expectedBenefitPercentage != null
        ? { expected_benefit_percentage: options.expectedBenefitPercentage }
        : {}),
    })
    .then((r) => r.data);

// ── Auth ───────────────────────────────────────────────────────────

export function getMe(): Promise<User>;
/** `optional`: a visit with no session cookie resolves to null (204) instead of a 401 the browser logs. */
export function getMe(optional: true): Promise<User | null>;
export function getMe(optional = false): Promise<User | null> {
  return api
    .get("/auth/me", optional ? { params: { optional: true } } : undefined)
    .then((r) => (r.status === 204 ? null : r.data));
}

/** Resumes the session cookie's account, or starts an anonymous one. */
export const startSession = (): Promise<User> => api.post("/auth/session", {}).then((r) => r.data);

/** Changes the account's display name only; the server trims it and rejects a blank one. */
export const updateMe = (displayName: string): Promise<User> =>
  api.put("/auth/me", { display_name: displayName }).then((r) => r.data);

export const logout = (): Promise<void> => api.post("/auth/logout").then(() => undefined);

// ── Plan accuracy ──────────────────────────────────────────────────

/** Completeness score, missing inputs and review items; nothing is saved. */
export const runPlanChecks = (planId: string): Promise<PlanChecksResponse> =>
  api.post(`/plans/${planId}/plan-checks`).then((r) => r.data);

// ── Social Security claiming-age explorer ──────────────────────────

/** Runs the saved plan at each claiming-age combination; nothing is saved. */
export const exploreClaimingAges = (planId: string): Promise<ClaimingExplorerResponse> =>
  api.post(`/plans/${planId}/social-security/claiming`).then((r) => r.data);

/** The plan's wellness scorecard, from one deterministic projection. Not saved. */
export const runWellness = (planId: string): Promise<WellnessResponse> =>
  api.post(`/plans/${planId}/wellness`).then((r) => r.data);
