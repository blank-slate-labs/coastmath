import { Fragment, lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";

import { useAuthStore } from "@/stores/auth_store";
import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import { useThemeStore } from "@/stores/theme_store";
import { StorageProvider, useStorage } from "@/storage/context";
import { CreatePlanForm, PLAN_SECTIONS, type PlanSectionKey } from "@/pages/plan_setup";
import DashboardView from "@/components/dashboard_view";
import PlanSectionNav from "@/components/plan_section_nav";
import EditSheet from "@/components/edit_sheet";
import MetricDefinitionsPanel from "@/components/metric_definitions_panel";
import { LoadingStatus } from "@/components/loading_status";
import { TRANSACTIONS_ENABLED } from "@/feature_flags";
import SessionStatus from "@/components/session_status";
import HelpButton from "@/components/help_button";
import Toast from "@/components/toast";
import ErrorBoundary from "@/components/error_boundary";
import { dollarsOr, signedCompactCurrency } from "@/utils/format";
import { usePlanDisplayCurrency } from "@/components/intl/use_display_currency";
import { planStatus } from "@/utils/plan_status";
import { useMetricStore } from "@/stores/metric_store";
import { buildDeflators } from "@/utils/currency";
import { FormModal } from "@/components/form_modal";
import { confirmDiscard } from "@/components/confirm_dialog";
import { BrandMark } from "@/components/brand_mark";
import { ArchivedPlans } from "@/components/archived_plans";
import { extensions, type WorkspaceExtension } from "@/extensions";
import { NewScenarioForm, scenarioSource } from "@/components/scenario/new_scenario_form";
import { ScenarioBanner } from "@/components/scenario/scenario_banner";
import { useTabOverflow } from "@/components/use_tab_overflow";
import type { PlanSummary } from "@/types/plan";

// Overview renders with the planner; every other view and the printable report load their code when first opened.
const HistoricalStressTest = lazy(() => import("@/components/historical_stress_test"));
const MonteCarloDashboard = lazy(() => import("@/components/monte_carlo_dashboard"));
const WithdrawalStrategiesPanel = lazy(() => import("@/components/withdrawal_strategies_panel"));
const AnnualReport = lazy(() => import("@/components/annual_report"));
const PrintableReport = lazy(() => import("@/components/printable_report"));
const TaxToolsPanel = lazy(() => import("@/components/tax/tax_tools_panel"));
const PlanAccuracyCard = lazy(() => import("@/components/checkup/plan_accuracy_card"));
const WellnessScorecard = lazy(() => import("@/components/checkup/wellness_scorecard"));
const ClaimingExplorer = lazy(() => import("@/components/social_security/claiming_explorer"));
const ProgressHistory = lazy(() => import("@/components/progress_history"));
const MonthCompareTab = lazy(() => import("@/components/month_compare/month_compare_tab"));

const {
  HeaderLead,
  HeaderTrail,
  MobileBarActions,
  Banner,
  PlanNotice,
  SheetNotice,
  BeforeShell,
  Overlays,
} = extensions.planner ?? {};
const SampleMode = extensions.session?.sample.Mode;
const SampleBadge = extensions.session?.sample.Badge;
const Workspaces = extensions.planner?.workspaces;
// Without client workspaces the plan selector lists every plan.
const useWorkspaceScope: WorkspaceExtension["useScope"] =
  Workspaces?.useScope ?? ((plans) => ({ plans }));

/** Each Main or independent plan in list order, with its scenarios after it. */
function groupPlanOptions(plans: PlanSummary[]): { plan: PlanSummary; scenarios: PlanSummary[] }[] {
  const ids = new Set(plans.map((p) => p.id));
  const isGrouped = (p: PlanSummary) => !!p.parent_plan_id && ids.has(p.parent_plan_id);
  return plans
    .filter((p) => !isGrouped(p))
    .map((plan) => ({
      plan,
      scenarios: plans.filter((p) => isGrouped(p) && p.parent_plan_id === plan.id),
    }));
}

type RightTab =
  | "dashboard"
  | "checkup"
  | "monte_carlo"
  | "stress_test"
  | "social_security"
  | "month_compare"
  | "reports"
  | "tax_tools"
  | "progress";

const ENABLE_MONTE_CARLO = true;
const ENABLE_STRESS_TEST = true;
const hiddenTabs = new Set<RightTab>([
  ...(!ENABLE_MONTE_CARLO ? ["monte_carlo" as RightTab] : []),
  ...(!ENABLE_STRESS_TEST ? ["stress_test" as RightTab] : []),
  ...(!TRANSACTIONS_ENABLED ? ["month_compare" as RightTab] : []),
]);

const tabLabels: Record<RightTab, string> = {
  dashboard: "Overview",
  checkup: "Checkup",
  monte_carlo: "Success odds",
  stress_test: "Historical Stress Test",
  social_security: "Social Security",
  month_compare: "Compare months",
  tax_tools: "Tax tools",
  reports: "Exports",
  progress: "Track actuals",
};

/** The planner's place in the address: `?tab=checkup&edit=accounts&view=print`, so Back, reload and links keep it. */
function readPlannerLocation(): { tab: RightTab; section: number | null; print: boolean } {
  const params = new URLSearchParams(window.location.search);
  const tab = params.get("tab") as RightTab | null;
  const section = PLAN_SECTIONS.findIndex((s) => s.key === params.get("edit"));
  return {
    tab: tab && tab in tabLabels && !hiddenTabs.has(tab) ? tab : "dashboard",
    section: section >= 0 ? section : null,
    print: params.get("view") === "print",
  };
}

function plannerUrl(tab: RightTab, section: number | null, print = false) {
  const url = new URL(window.location.href);
  if (tab === "dashboard") url.searchParams.delete("tab");
  else url.searchParams.set("tab", tab);
  if (section === null) url.searchParams.delete("edit");
  else url.searchParams.set("edit", PLAN_SECTIONS[section].key);
  if (print) url.searchParams.set("view", "print");
  else url.searchParams.delete("view");
  return `${url.pathname}${url.search}${url.hash}`;
}

const loadingStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  height: "100vh",
};

const spinnerStyle: React.CSSProperties = {
  width: 28,
  height: 28,
  border: "2px solid var(--surface-border)",
  borderTopColor: "var(--brand-primary)",
  borderRadius: "50%",
  animation: "spin 0.8s linear infinite",
};

function CollapseIcon({ open }: { open: boolean }) {
  return (
    <svg
      aria-hidden="true"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="3" y="4" width="18" height="16" rx="3" />
      <path d="M9 4v16" />
      <path d={open ? "m15.5 10-2 2 2 2" : "m13.5 10 2 2-2 2"} />
    </svg>
  );
}

/**
 * Collapsible sidebar. It holds the brand, the active-plan selector and a
 * navigation list of plan sections; the editors themselves open in the
 * Edit sheet so the sidebar can stay narrow.
 */
function LeftPane({
  open,
  onToggle,
  activeSection,
  onEditSection,
}: {
  open: boolean;
  onToggle: () => void;
  activeSection: PlanSectionKey | null;
  onEditSection: (key: PlanSectionKey) => void;
}) {
  const plan = usePlanStore((s) => s.plan);
  const activePlanId = usePlanStore((s) => s.activePlanId);
  const plans = usePlanStore((s) => s.plans);
  const loadPlans = usePlanStore((s) => s.loadPlans);
  const loadPlan = usePlanStore((s) => s.loadPlan);
  const error = usePlanStore((s) => s.error);
  const duplicatePlan = usePlanStore((s) => s.duplicatePlan);
  const deletePlan = usePlanStore((s) => s.deletePlan);
  const pendingSave = useSaveStore((s) => s.pending > 0);
  // A failed save is stated by the save status; the same text is not repeated here.
  const errorIsSaveFailure = useSaveStore(
    (s) => !!error && s.failed.some((key) => s.failures[key]?.message === error),
  );
  const { sample } = useStorage();
  const [planAction, setPlanAction] = useState<"new" | "duplicate" | "scenario" | "delete" | null>(
    null,
  );
  const [duplicating, setDuplicating] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const userId = useAuthStore((s) => s.user?.id);
  const access = extensions.access;
  const duplicateLocked = useAuthStore((s) => !!access?.locked(s.user, "duplicate"));
  // A policy may limit active plans: a new one then starts over, archiving the current one first.
  const startsOver =
    useAuthStore((s) => !!access?.locked(s.user, "additional_plans")) && plans.length > 0;
  const startDuplicate = () => {
    if (duplicateLocked) access?.explain("duplicate");
    else setPlanAction("duplicate");
  };
  // The selector lists the open plan's workspace; New plan creates there unless a client is named.
  const scope = useWorkspaceScope(plans, plan);
  const [newPlanClient, setNewPlanClient] = useState<string | null>(null);
  const clientsLocked = useAuthStore((s) => !!access?.locked(s.user, "client_workspaces"));
  const startNewPlan = (clientId: string | null = scope.clientId ?? null) => {
    // Explained up front: under a plan limit the form archives the open plan first, then the new one would be refused.
    if (clientId && clientsLocked) {
      access?.explain("client_workspaces");
      return;
    }
    setNewPlanClient(clientId);
    setPlanAction("new");
  };
  // Scenarios need a client workspace; legacy shared-account plans don't offer them.
  const offersScenario = !!plan?.client_id;
  // Once the new-plan form shows, it stays through Goals, even after the new plan counts
  // toward a plan limit again; Goals is titled with the plan it now belongs to.
  const [newPlanForm, setNewPlanForm] = useState(false);
  const [goalsFor, setGoalsFor] = useState<string | null>(null);
  if (planAction !== "new" && (newPlanForm || goalsFor)) {
    setNewPlanForm(false);
    setGoalsFor(null);
  }
  if (planAction === "new" && !(startsOver && access) && !newPlanForm) setNewPlanForm(true);
  const startScenario = () => {
    if (duplicateLocked) access?.explain("duplicate");
    else setPlanAction("scenario");
  };
  const mainName = plan?.parent_plan_id
    ? (plans.find((p) => p.id === plan.parent_plan_id)?.name ?? "the Main plan")
    : null;
  const scenarioCount = plan ? plans.filter((p) => p.parent_plan_id === plan.id).length : 0;
  const deleteLabel = plan?.parent_plan_id ? "Delete scenario" : "Delete plan";
  // Remember the requested plan before its fetch finishes so an early reload reopens it.
  useEffect(() => {
    if (activePlanId && userId)
      try {
        localStorage.setItem(`coastmath:active-plan:${userId}`, activePlanId);
      } catch {
        /* storage unavailable */
      }
  }, [activePlanId, userId]);

  const hasPlans = plans.length > 0;

  return (
    <aside
      className={`split-left ${open ? "is-open" : "is-collapsed"}`}
      style={{ width: open ? "var(--sidebar-width)" : 64 }}
    >
      <div className="mobile-plan-bar">
        <span className="app-brand">
          <BrandMark />
          CoastMath
        </span>
        <div className="mobile-plan-bar-actions">
          <HelpButton placement="bar" />
          {MobileBarActions && <MobileBarActions />}
          <button
            type="button"
            className="btn-secondary"
            aria-label={open ? "Close plan menu" : "Edit plan"}
            onClick={onToggle}
          >
            {open ? "Close" : "Plan"}
          </button>
        </div>
      </div>
      <FormModal
        open={planAction !== null}
        onClose={() => {
          if (!duplicating && !deleting) setPlanAction(null);
        }}
        title={
          planAction === "duplicate"
            ? "Duplicate plan"
            : planAction === "scenario"
              ? "New scenario"
              : planAction === "delete"
                ? deleteLabel
                : (goalsFor ?? (newPlanForm ? "New plan" : "Start a new plan"))
        }
      >
        {planAction === "new" ? (
          !newPlanForm && access ? (
            <access.LockedFeature feature="additional_plans" />
          ) : (
            <CreatePlanForm
              clientId={newPlanClient ?? undefined}
              onGoals={(created) => setGoalsFor(created.name)}
              onCreate={(next) => {
                setPlanAction(null);
                void loadPlans();
                onEditSection(next ?? "plan_details");
              }}
            />
          )
        ) : planAction === "scenario" ? (
          plan && (
            <NewScenarioForm
              source={scenarioSource(plan, plans)}
              onDone={() => setPlanAction(null)}
            />
          )
        ) : planAction === "delete" ? (
          <div className="delete-plan">
            {/* Plan-owned accounts are deleted with the plan; a legacy plan shares the household's. */}
            <p>
              {plan?.client_id
                ? `Deletes “${plan.name}”, its inputs and its own accounts.`
                : `Deletes “${plan?.name}” and its inputs; shared accounts stay.`}{" "}
              This can’t be undone.
            </p>
            {scenarioCount > 0 && (
              <p>
                {scenarioCount === 1
                  ? "1 scenario will become an independent plan and keep its current values."
                  : `${scenarioCount} scenarios will become independent plans and keep their current values.`}
              </p>
            )}
            {error && <p role="alert">{error}</p>}
            <button
              type="button"
              className="btn-danger"
              disabled={deleting || pendingSave || !plan}
              aria-busy={deleting}
              onClick={async () => {
                if (!plan) return;
                setDeleting(true);
                const deleted = await deletePlan(plan.id);
                setDeleting(false);
                if (deleted) setPlanAction(null);
              }}
            >
              {deleting ? "Deleting…" : deleteLabel}
            </button>
            <button
              type="button"
              className="btn-quiet"
              disabled={deleting}
              onClick={() => setPlanAction(null)}
            >
              Cancel
            </button>
          </div>
        ) : (
          <>
            {/* Workspace copies get their own accounts; a legacy copy keeps sharing the household's. */}
            <p>
              Copy “{plan?.name}”.{" "}
              {mainName
                ? `The copy is an independent plan: it starts with this scenario’s values and doesn’t receive changes from “${mainName}”. This scenario is unchanged.`
                : plan?.client_id
                  ? "The copy starts identical, then keeps its own balances and inputs. The original is unchanged."
                  : "Both plans use the same current account balances; balance edits affect both."}
            </p>
            {error && <p role="alert">{error}</p>}
            <button
              type="button"
              disabled={duplicating || pendingSave || !plan}
              onClick={async () => {
                if (!plan) return;
                setDuplicating(true);
                await duplicatePlan(plan.id);
                setDuplicating(false);
                if (!usePlanStore.getState().error) setPlanAction(null);
              }}
            >
              {duplicating ? "Duplicating…" : "Duplicate plan"}
            </button>
          </>
        )}
      </FormModal>
      <div className="split-left-header">
        {open && (
          <a className="app-brand" href="/" aria-label="CoastMath home">
            <BrandMark />
            <span>CoastMath</span>
          </a>
        )}
        <button
          type="button"
          className="collapse-toggle"
          onClick={onToggle}
          title={open ? "Collapse plan builder" : "Expand plan builder"}
        >
          <CollapseIcon open={open} />
        </button>
      </div>

      {open && hasPlans && (
        <div className="plan-switcher">
          {Workspaces && <Workspaces.Switcher onNewPlan={startNewPlan} />}
          <label className="plan-select-label" data-sample-view>
            Active plan
            <select
              aria-label="Active plan"
              value={plan?.id ?? ""}
              onChange={(e) => void loadPlan(e.target.value)}
              disabled={!plans.length}
            >
              {!plan && <option value="">Choose a plan</option>}
              {groupPlanOptions(scope.plans).map(({ plan: main, scenarios }) =>
                scenarios.length === 0 ? (
                  <option key={main.id} value={main.id}>
                    {main.name}
                  </option>
                ) : (
                  <Fragment key={main.id}>
                    <option value={main.id}>{main.name}</option>
                    <optgroup label={`Scenarios of ${main.name}`}>
                      {scenarios.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </optgroup>
                  </Fragment>
                ),
              )}
              {/* An archived plan can be open without being restored. */}
              {plan?.archived_at && !plans.some((p) => p.id === plan.id) && (
                <option value={plan.id}>{plan.name} (archived)</option>
              )}
            </select>
          </label>
          {/* In the read-only sample, every plan action asks the visitor to sign in. */}
          <div className="plan-actions" data-sample-editor>
            <button
              type="button"
              className="btn-quiet"
              disabled={pendingSave}
              onClick={() => startNewPlan()}
            >
              <svg
                aria-hidden="true"
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
              >
                <path d="M12 5v14M5 12h14" />
              </svg>
              New plan
            </button>
            <button
              type="button"
              className="btn-quiet"
              disabled={!plan || pendingSave}
              onClick={startDuplicate}
            >
              {duplicateLocked && access ? (
                <access.LockGlyph size={13} />
              ) : (
                <svg
                  aria-hidden="true"
                  width="13"
                  height="13"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <rect x="8" y="8" width="12" height="12" rx="2" />
                  <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" />
                </svg>
              )}
              Duplicate
            </button>
            {offersScenario && (
              <button
                type="button"
                className="btn-quiet"
                disabled={!plan || pendingSave || !!plan.archived_at}
                onClick={startScenario}
              >
                {duplicateLocked && access ? (
                  <access.LockGlyph size={13} />
                ) : (
                  <svg
                    aria-hidden="true"
                    width="13"
                    height="13"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <circle cx="6" cy="6" r="2" />
                    <circle cx="6" cy="18" r="2" />
                    <circle cx="18" cy="12" r="2" />
                    <path d="M6 8v8M8 6h4a4 4 0 0 1 4 4" />
                  </svg>
                )}
                New scenario
              </button>
            )}
            <button
              type="button"
              className="btn-quiet"
              disabled={!plan || pendingSave || !!plan.archived_at}
              onClick={() => setPlanAction("delete")}
            >
              <svg
                aria-hidden="true"
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" />
              </svg>
              Delete
            </button>
          </div>
        </div>
      )}

      <div hidden={!open} className="split-left-body">
        {error && !errorIsSaveFailure && (
          <div role="alert" className="sidebar-error">
            {error}
          </div>
        )}
        {hasPlans ? (
          <PlanSectionNav activeKey={activeSection} onEdit={onEditSection} />
        ) : sample ? (
          <p role="status" className="sample-loading">
            {extensions.session?.sample.loadingText}
          </p>
        ) : (
          <div className="left-pane-form">
            <CreatePlanForm
              onCreate={(next) => {
                void loadPlans();
                if (next) onEditSection(next);
              }}
            />
          </div>
        )}
        {!sample && <ArchivedPlans />}
      </div>

      {!open && (
        <div className="sidebar-rail">
          <button
            type="button"
            className="rail-button"
            title="Open plan builder"
            aria-label="Open plan builder"
            onClick={onToggle}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M4 21h16" />
              <path d="M7 21V7l5-4 5 4v14" />
            </svg>
          </button>
          {hasPlans && (
            <button
              type="button"
              className="rail-button"
              title="Edit plan details"
              aria-label="Edit plan details"
              onClick={() => onEditSection(PLAN_SECTIONS[0].key)}
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
              </svg>
            </button>
          )}
        </div>
      )}

      {open && (
        <div className="sidebar-footer">
          <ThemeToggle />
        </div>
      )}
    </aside>
  );
}

function ThemeToggle() {
  const { preference, setPreference } = useThemeStore();

  return (
    <div className="theme-toggle">
      <button
        className={`theme-toggle-option${preference === "light" ? " active" : ""}`}
        title="Light"
        onClick={() => setPreference("light")}
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="12" cy="12" r="5" />
          <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
        </svg>
      </button>
      <button
        className={`theme-toggle-option${preference === "system" ? " active" : ""}`}
        title="System"
        onClick={() => setPreference("system")}
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
          <line x1="8" y1="21" x2="16" y2="21" />
          <line x1="12" y1="17" x2="12" y2="21" />
        </svg>
      </button>
      <button
        className={`theme-toggle-option${preference === "dark" ? " active" : ""}`}
        title="Dark"
        onClick={() => setPreference("dark")}
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      </button>
    </div>
  );
}

function RightPane({
  tab,
  onTabChange,
  onPrint,
  onEditAllocation,
  onReviewHistory,
  onEditAccounts,
  onReviewConnections,
  onEditSection,
}: {
  tab: RightTab;
  onTabChange: (t: RightTab) => void;
  onPrint: () => void;
  onEditAllocation: (rank?: number) => void;
  onReviewHistory: () => void;
  onEditAccounts: () => void;
  onReviewConnections: () => void;
  onEditSection: (key: PlanSectionKey) => void;
}) {
  const tabs = (Object.keys(tabLabels) as RightTab[]).filter((t) => !hiddenTabs.has(t));
  const tabRow = useRef<HTMLElement>(null);
  const tabOverflow = useTabOverflow(tabRow, tab, tabs.length);
  const plan = usePlanStore((s) => s.plan);
  const { sample } = useStorage();
  const isExamplePlan = plan?.name === "Sample plan";
  const simulation = usePlanStore((s) => s.simulation);
  const baselineSimulation = usePlanStore((s) => s.baselineSimulation);
  const isSimulating = usePlanStore((s) => s.isSimulating);
  const simulationError = usePlanStore((s) => s.simulationError);
  const isSaving = useSaveStore((s) => s.pending > 0);
  const compareMode = usePlanStore((s) => s.compareMode);
  const currencyMode = usePlanStore((s) => s.currencyMode);
  const restorePlan = usePlanStore((s) => s.restorePlan);
  const access = extensions.access;
  const exportsLocked = useAuthStore((s) => !!access?.locked(s.user, "exports"));

  const snapshots = useMemo(() => simulation?.yearly_snapshots ?? [], [simulation]);
  const startSnapshot = snapshots[0] ?? null;
  const endSnapshot = snapshots[snapshots.length - 1] ?? null;
  const metricPlanId = useMetricStore((s) => s.planId);
  const loadMetrics = useMetricStore((s) => s.load);
  useEffect(() => {
    if (plan && plan.id !== metricPlanId) loadMetrics(plan.id);
  }, [plan, metricPlanId, loadMetrics]);

  const relativeOutcome = useMemo(() => {
    if (!compareMode || !baselineSimulation || !endSnapshot) return null;
    const baselineSnaps = baselineSimulation.yearly_snapshots ?? [];
    const currentByYear = new Map(snapshots.map((s) => [s.year, s]));
    const baselineEnd = [...baselineSnaps].reverse().find((s) => currentByYear.has(s.year)) ?? null;
    if (!baselineEnd) return null;
    const nominalDelta = currentByYear.get(baselineEnd.year)!.net_worth - baselineEnd.net_worth;
    const factors = buildDeflators(
      plan?.assumption_curves?.find((c) => c.curve_type === "inflation"),
      0.03,
      simulation?.metadata.start_year ?? 0,
      snapshots.length,
      plan?.birth_year ?? 0,
    );
    const factor =
      currencyMode === "nominal"
        ? 1
        : (factors[snapshots.findIndex((s) => s.year === baselineEnd.year)] ?? 1);
    return `${signedCompactCurrency(nominalDelta / factor)} vs baseline in ${baselineEnd.year} (${currencyMode === "nominal" ? "nominal" : `${dollarsOr("Today's $", "Today's money")} · ${simulation?.metadata.start_year} base`})`;
  }, [baselineSimulation, compareMode, endSnapshot, snapshots, currencyMode, plan, simulation]);

  const isEmpty = !simulation || snapshots.length === 0 || !startSnapshot || !endSnapshot;

  const status = planStatus(simulation);

  // A projection that failed or is still running is never shown as an empty plan.
  const planMeta = isEmpty
    ? sample
      ? extensions.session?.sample.loadingText
      : simulationError
        ? null
        : isSimulating
          ? "Updating projection…"
          : "Add income, expenses, and accounts to see the projection."
    : // "through": the last projected year is the one before the longevity age, so "to 89" read as a typo for 90.
      `${startSnapshot.year}–${endSnapshot.year} · age ${startSnapshot.age} through ${endSnapshot.age}`;

  return (
    <div className="split-right">
      <header className="right-tab-bar">
        <div className="workspace-top">
          <div className="workspace-heading">
            <div className="workspace-title-row">
              <h1 className="workspace-title">{plan?.name ?? "Projection dashboard"}</h1>
              {sample && SampleBadge ? (
                <SampleBadge />
              ) : (
                isExamplePlan && (
                  <span
                    className="pill pill-example"
                    tabIndex={0}
                    title="Sample data. Choose New plan for your own finances."
                  >
                    Example plan
                  </span>
                )
              )}
              {plan?.archived_at && !sample && (
                <>
                  <span className="pill">Archived</span>
                  <button
                    type="button"
                    className="btn-quiet"
                    onClick={() => void restorePlan(plan.id)}
                  >
                    Restore
                  </button>
                </>
              )}
            </div>
            <div className="workspace-meta-row">
              <p className="workspace-meta">{planMeta}</p>
              {status && status.tone !== "success" && (
                <span className={`pill pill-${status.tone}`} title={status.detail}>
                  {status.label}
                </span>
              )}
              {compareMode && relativeOutcome && (
                <span className="pill pill-info">{relativeOutcome}</span>
              )}
            </div>
            {status && status.tone !== "success" && (
              <p className="workspace-meta" role="status">
                {status.detail}
              </p>
            )}
            {simulationError && !sample && plan && (
              <div className="workspace-meta simulation-error" role="alert">
                <span>{simulationError}</span>{" "}
                <button
                  type="button"
                  className="btn-quiet"
                  onClick={() => void usePlanStore.getState().runSimulation(plan.id)}
                >
                  Retry
                </button>
              </div>
            )}
            {!sample && plan?.parent_plan_id && <ScenarioBanner />}
            {PlanNotice && <PlanNotice plan={plan} />}
          </div>
          <div className="workspace-session">
            {HeaderLead && <HeaderLead />}
            <SessionStatus />
            {HeaderTrail && <HeaderTrail />}
          </div>
        </div>

        {tabs.length > 1 && (
          <nav
            ref={tabRow}
            className="tab-cluster"
            aria-label="Plan views"
            data-overflow-start={tabOverflow.start || undefined}
            data-overflow-end={tabOverflow.end || undefined}
          >
            {tabs.map((key) => (
              <button
                key={key}
                type="button"
                className={`right-tab${tab === key ? " is-active" : ""}`}
                aria-current={tab === key ? "page" : undefined}
                onClick={() => onTabChange(key)}
              >
                {tabLabels[key]}
              </button>
            ))}
          </nav>
        )}
      </header>

      <div className="right-content">
        {Banner && <Banner onReviewConnections={onReviewConnections} />}
        <Suspense fallback={<LoadingStatus label="Loading…" />}>
          {tab === "dashboard" && (
            <>
              <DashboardView
                onEditAllocation={onEditAllocation}
                onReviewHistory={onReviewHistory}
              />
              <details className="card">
                <summary>Overview display preferences</summary>
                <MetricDefinitionsPanel />
              </details>
            </>
          )}

          {tab === "reports" && (
            <div className="page-shell">
              <AnnualReport />
              <div
                className="card"
                style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}
              >
                <div style={{ flex: "1 1 240px" }}>
                  <h3 style={{ margin: 0 }}>Printable report</h3>
                </div>
                {exportsLocked && access ? (
                  <access.LockedFeature feature="exports" />
                ) : (
                  <button
                    type="button"
                    onClick={onPrint}
                    disabled={!simulation || isSaving || isSimulating}
                  >
                    Open printable report
                  </button>
                )}
              </div>
            </div>
          )}
          {tab === "checkup" && (
            <div className="page-shell">
              <PlanAccuracyCard onEditSection={onEditSection} />
              <WellnessScorecard onEditSection={onEditSection} />
            </div>
          )}
          {tab === "social_security" && (
            <div className="page-shell">
              <ClaimingExplorer onEditSection={onEditSection} />
            </div>
          )}
          {TRANSACTIONS_ENABLED && tab === "month_compare" && (
            <MonthCompareTab onOpenTransactions={() => onEditSection("transactions")} />
          )}
          {tab === "progress" && <ProgressHistory />}
          {tab === "tax_tools" && (
            <TaxToolsPanel
              onEditAccounts={onEditAccounts}
              onEditHealth={() => onEditSection("healthcare")}
            />
          )}
          {ENABLE_MONTE_CARLO && tab === "monte_carlo" && (
            <div className="page-shell">
              <MonteCarloDashboard />
              <details className="mc-methodology">
                <summary>Compare withdrawal strategies</summary>
                <WithdrawalStrategiesPanel />
              </details>
            </div>
          )}

          {ENABLE_STRESS_TEST && tab === "stress_test" && (
            <div className="page-shell">
              <HistoricalStressTest />
            </div>
          )}
        </Suspense>
      </div>
    </div>
  );
}

function PlanDataBootstrap() {
  const plan = usePlanStore((s) => s.plan);
  const plans = usePlanStore((s) => s.plans);
  const loadPlan = usePlanStore((s) => s.loadPlan);
  const loadPlans = usePlanStore((s) => s.loadPlans);
  const loadArchivedPlans = usePlanStore((s) => s.loadArchivedPlans);
  const { sample } = useStorage();
  const [loadedPlans, setLoadedPlans] = useState(false);

  useEffect(() => {
    if (!sample) void loadArchivedPlans();
  }, [sample, loadArchivedPlans]);

  useEffect(() => {
    let cancelled = false;
    loadPlans().finally(() => {
      if (!cancelled) setLoadedPlans(true);
    });
    return () => {
      cancelled = true;
    };
  }, [loadPlans]);

  useEffect(() => {
    if (loadedPlans && plans.length > 0 && !plan) {
      let saved: string | null = null;
      try {
        saved = localStorage.getItem(`coastmath:active-plan:${useAuthStore.getState().user?.id}`);
      } catch {
        /* storage unavailable */
      }
      loadPlan(plans.find((p) => p.id === saved)?.id ?? plans[0].id);
    }
  }, [loadedPlans, loadPlan, plan, plans]);

  return null;
}

const ALLOCATION_INDEX = PLAN_SECTIONS.findIndex((s) => s.key === "income_allocation");

function App() {
  const { user, isLoading, error: sessionError, ensureSession } = useAuthStore();
  const plans = usePlanStore((s) => s.plans);
  const [leftOpen, setLeftOpen] = useState(() =>
    typeof window === "undefined" ? true : window.matchMedia("(min-width: 901px)").matches,
  );
  const [rightTab, setRightTab] = useState<RightTab>(() => readPlannerLocation().tab);
  const [printView, setPrintView] = useState(() => readPlannerLocation().print);
  // The report is an export: an address with view=print opens it only where its button does.
  const exportsLocked = useAuthStore((s) => !!extensions.access?.locked(s.user, "exports"));
  const reportOpen = printView && !exportsLocked;
  // null = closed; otherwise the index into PLAN_SECTIONS being edited.
  const [sheetIndex, setSheetIndex] = useState<number | null>(() => readPlannerLocation().section);
  const [historyRequest, setHistoryRequest] = useState(0);

  const sheetIndexRef = useRef(sheetIndex);
  useEffect(() => {
    sheetIndexRef.current = sheetIndex;
  }, [sheetIndex]);
  // Set while the sheet's own Close steps back through history; the sheet already asked about drafts.
  const closingSheet = useRef(false);

  // Back and Forward move between tabs and editors. An editor with unsaved changes asks first.
  useEffect(() => {
    const onPop = () => {
      const next = readPlannerLocation();
      const asked = closingSheet.current;
      closingSheet.current = false;
      if (
        !asked &&
        next.section === null &&
        document.querySelector('[data-unsaved-changes="true"]')
      ) {
        // Stay in the editor while asking; Discard then steps back again.
        window.history.pushState(
          { planner: true, sheet: true },
          "",
          plannerUrl(next.tab, sheetIndexRef.current),
        );
        void confirmDiscard().then((confirmed) => {
          if (!confirmed) return;
          closingSheet.current = true;
          window.history.back();
        });
        return;
      }
      setRightTab(next.tab);
      setSheetIndex(next.section);
      setPrintView(next.print);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Reloading or closing the tab asks while any editor or form holds unsaved changes or a save is in flight.
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (!document.querySelector('[data-unsaved-changes="true"], [data-save-pending="true"]'))
        return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  // The printable report is a step in history: Back returns to the tab it opened from.
  function showPrint(open: boolean) {
    if (open === printView) return;
    if (open)
      window.history.pushState(
        { planner: true, print: true },
        "",
        plannerUrl(rightTab, sheetIndex, true),
      );
    else if (window.history.state?.print) {
      window.history.back();
      return;
    } else window.history.replaceState(window.history.state, "", plannerUrl(rightTab, sheetIndex));
    setPrintView(open);
  }

  function changeTab(tab: RightTab) {
    if (tab === rightTab) return;
    const go = () => {
      window.history.pushState({ planner: true }, "", plannerUrl(tab, sheetIndex));
      setRightTab(tab);
    };
    // Leaving a tab unmounts its forms (Tax tools' SEPP and cash reserve); ask before dropping their edits.
    if (document.querySelector('[data-save-pending="true"]')) return;
    if (!document.querySelector('[data-unsaved-changes="true"]')) {
      go();
      return;
    }
    void confirmDiscard().then((confirmed) => {
      if (confirmed) go();
    });
  }

  function showSheet(index: number | null) {
    if (index === sheetIndex) return;
    const url = plannerUrl(rightTab, index);
    // Opening an editor is a step Back can undo; moving between sections replaces it.
    if (sheetIndex === null && index !== null)
      window.history.pushState({ planner: true, sheet: true }, "", url);
    else if (index === null && window.history.state?.sheet) {
      closingSheet.current = true;
      window.history.back();
    } else window.history.replaceState(window.history.state, "", url);
    setSheetIndex(index);
  }

  useEffect(() => {
    const media = window.matchMedia("(min-width: 901px)");
    const resize = (event: MediaQueryListEvent) => setLeftOpen(event.matches);
    media.addEventListener?.("change", resize);
    return () => media.removeEventListener?.("change", resize);
  }, []);

  useEffect(() => {
    ensureSession();
  }, [ensureSession]);

  const hasPlans = plans.length > 0;
  const activeSection = sheetIndex === null ? null : (PLAN_SECTIONS[sheetIndex]?.key ?? null);
  const openPlan = usePlanStore((s) => s.plan);
  usePlanDisplayCurrency(openPlan?.currency);
  const openPlanId = openPlan?.id;
  useEffect(() => {
    if (user && openPlanId && activeSection)
      extensions.planner?.onSectionOpened?.(openPlanId, activeSection);
  }, [user, openPlanId, activeSection]);

  const openPlanName = openPlan?.name;
  useEffect(() => {
    const view =
      sheetIndex !== null && hasPlans ? PLAN_SECTIONS[sheetIndex]?.title : tabLabels[rightTab];
    document.title = openPlanName ? `${openPlanName} · ${view} | CoastMath` : "CoastMath";
  }, [openPlanName, rightTab, sheetIndex, hasPlans]);

  function openSheet(key: PlanSectionKey) {
    setHistoryRequest(0);
    const index = PLAN_SECTIONS.findIndex((s) => s.key === key);
    showSheet(index >= 0 ? index : 0);
    // On a phone the plan menu would stay open above the results once the editor closes.
    if (!window.matchMedia?.("(min-width: 901px)").matches) setLeftOpen(false);
  }

  function handleEditAllocation(rank?: number) {
    if (ALLOCATION_INDEX >= 0) showSheet(ALLOCATION_INDEX);
    if (rank != null) {
      window.setTimeout(() => {
        const rule = document.getElementById(`allocation-rule-${rank}`);
        const details = rule?.querySelector("details");
        if (details) details.open = true;
        rule?.scrollIntoView({ block: "center" });
        rule?.focus();
      }, 160);
    }
  }

  if (isLoading) {
    return (
      <div style={loadingStyle}>
        <div style={spinnerStyle} />
      </div>
    );
  }

  if (sessionError) {
    return (
      <main style={{ maxWidth: 480, margin: "15vh auto", padding: 24 }}>
        <h1>Unable to open CoastMath</h1>
        <p role="alert">{sessionError}</p>
        <button type="button" onClick={() => void ensureSession()}>
          Retry opening planner
        </button>
      </main>
    );
  }

  // Signed out, a sign-in extension shows its read-only sample plan.
  const sample = !user && !!extensions.session;
  const DeletionPending = extensions.session?.DeletionPending;
  if (user?.deletion_pending && DeletionPending) return <DeletionPending />;

  return (
    <ErrorBoundary>
      <StorageProvider sample={sample}>
        {sample && SampleMode && <SampleMode />}
        <PlanDataBootstrap />
        {reportOpen && (
          <Suspense fallback={<LoadingStatus />}>
            <PrintableReport onClose={() => showPrint(false)} />
          </Suspense>
        )}
        {!reportOpen && BeforeShell && <BeforeShell />}
        <div className="app-shell" style={reportOpen ? { display: "none" } : undefined}>
          <LeftPane
            open={leftOpen}
            onToggle={() => setLeftOpen((value) => !value)}
            activeSection={activeSection}
            onEditSection={openSheet}
          />
          <RightPane
            tab={rightTab}
            onTabChange={changeTab}
            onPrint={() => showPrint(true)}
            onEditAccounts={() => openSheet("accounts")}
            onEditSection={openSheet}
            onReviewConnections={() => openSheet("connections")}
            onEditAllocation={handleEditAllocation}
            onReviewHistory={() => {
              openSheet("plan_details");
              setHistoryRequest((value) => value + 1);
            }}
          />
        </div>
        {!reportOpen && <HelpButton compact={!leftOpen} />}
        {sheetIndex !== null && hasPlans && (
          <EditSheet
            index={sheetIndex}
            historyRequest={historyRequest}
            onIndexChange={(next) => {
              setHistoryRequest(0);
              showSheet(Math.max(0, Math.min(PLAN_SECTIONS.length - 1, next)));
            }}
            onClose={() => showSheet(null)}
          />
        )}
        {SheetNotice && sheetIndex === null && (
          <SheetNotice
            plan={openPlan}
            sections={PLAN_SECTIONS}
            onOpenSection={(key) => openSheet(key as PlanSectionKey)}
          />
        )}
        {Overlays && <Overlays />}
        <Toast />
      </StorageProvider>
    </ErrorBoundary>
  );
}

export default App;
