import { useEffect, useState } from "react";

import TransactionsSection from "@/components/ledger/transactions_section";
import { extensions } from "@/extensions";
import { TRANSACTIONS_ENABLED } from "@/feature_flags";
import AssumptionsPanel from "@/components/assumptions_panel";
import SavingsPrioritiesPanel from "@/components/savings_priorities_panel";
import AssetsDebtPanel from "@/components/assets_debt_panel";
import CharityManager from "@/components/charity_manager";
import { CreatePlanForm } from "@/components/create_plan_form";
import { PlanHeader } from "@/pages/plan_header";
import { usePlanStore } from "@/stores/plan_store";
import { CollapsibleSection } from "@/pages/plan_setup_shared";
import { AccountsSection } from "@/pages/plan_sections/accounts_section";
import { DrawdownSection } from "@/pages/plan_sections/drawdown_section";
import { ExpenseSection } from "@/pages/plan_sections/expense_section";
import { IncomeSection } from "@/pages/plan_sections/income_section";
import { MilestonesSection } from "@/pages/plan_sections/milestones_section";
import {
  AssumptionsSection,
  CharitableSection,
  EstateSection,
  FlexRulesSection,
  HealthcareSection,
  IncomeAllocationSection,
  NotesSection,
  PropertyDebtSection,
} from "@/pages/plan_sections/panel_sections";

// Existing importers keep using this module's path for the moved pieces.
export { BuilderModeContext, type BuilderMode } from "@/pages/plan_setup_shared";
export { ResidencyTimelineEditor } from "@/components/residency_timeline_editor";
export { CreatePlanForm, PlanHeader };
export {
  AccountsSection,
  AssumptionsSection,
  CharitableSection,
  DrawdownSection,
  EstateSection,
  ExpenseSection,
  FlexRulesSection,
  HealthcareSection,
  IncomeAllocationSection,
  IncomeSection,
  MilestonesSection,
  NotesSection,
  PropertyDebtSection,
};

export default function PlanSetup({
  allocationFocusRequest = 0,
}: {
  allocationFocusRequest?: number;
}) {
  const plan = usePlanStore((s) => s.plan);
  const plans = usePlanStore((s) => s.plans);
  const error = usePlanStore((s) => s.error);
  const loadPlans = usePlanStore((s) => s.loadPlans);

  const [loaded, setLoaded] = useState(false);
  const [allocationOpen, setAllocationOpen] = useState(false);

  useEffect(() => {
    if (!loaded || !plan?.id || !allocationFocusRequest) return;
    setAllocationOpen(true);
    const frame = requestAnimationFrame(() => {
      const section = document.getElementById("income-allocation");
      section?.scrollIntoView({ block: "start" });
      section?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [loaded, plan?.id, allocationFocusRequest]);

  useEffect(() => {
    if (plans.length > 0) {
      setLoaded(true);
      return;
    }

    let cancelled = false;
    loadPlans().finally(() => {
      if (!cancelled) setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [loadPlans, plans.length]);

  if (!loaded) {
    return (
      <div
        style={{
          padding: 40,
          textAlign: "center",
          color: "var(--text-tertiary)",
        }}
      >
        <div
          style={{
            width: 24,
            height: 24,
            border: "2px solid var(--surface-border)",
            borderTopColor: "var(--brand-primary)",
            borderRadius: "50%",
            animation: "spin 0.8s linear infinite",
            margin: "0 auto 12px",
          }}
        />
        Loading plans...
      </div>
    );
  }

  return (
    <div>
      {error && (
        <div
          style={{
            padding: "12px 16px",
            marginBottom: 18,
            borderRadius: 12,
            border: "1px solid var(--delete-border)",
            background: "var(--color-danger-light)",
            color: "var(--color-danger)",
            fontSize: "13px",
            fontWeight: 500,
          }}
        >
          {error}
        </div>
      )}

      {plans.length === 0 ? (
        <CreatePlanForm onCreate={() => loadPlans()} />
      ) : (
        <>
          <div className="stagger-children">
            <PlanHeader />
            {plan && (
              <CollapsibleSection title="Assumptions">
                <AssumptionsPanel plan={plan} />
              </CollapsibleSection>
            )}
            <MilestonesSection />
            <IncomeSection />
            <ExpenseSection />
            {plan && <FlexRulesSection key={plan.id} />}
            <AccountsSection />
            {plan && (
              <CollapsibleSection
                id="income-allocation"
                title="Income allocation"
                open={allocationOpen}
                onOpenChange={setAllocationOpen}
              >
                <SavingsPrioritiesPanel key={plan.id} plan={plan} />
              </CollapsibleSection>
            )}
            {plan && (
              <CollapsibleSection title="Property and debt">
                <AssetsDebtPanel key={plan.id} plan={plan} />
              </CollapsibleSection>
            )}
            <DrawdownSection />
            {plan && (
              <CollapsibleSection title="Charitable giving">
                <CharityManager
                  key={`charity-${plan.id}`}
                  planId={plan.id}
                  milestones={plan.milestones}
                />
              </CollapsibleSection>
            )}
            {plan && <HealthcareSection key={`healthcare-${plan.id}`} />}
            {plan && <EstateSection key={`estate-${plan.id}`} />}
            {plan && <NotesSection key={`notes-${plan.id}`} />}
          </div>
        </>
      )}
    </div>
  );
}

/** Stable identity for each builder section — used by the sidebar nav, the sheet and deep links. */
export type PlanSectionKey =
  | "plan_details"
  | "assumptions"
  | "milestones"
  | "income"
  | "expenses"
  | "flex"
  | "accounts"
  | "connections"
  | "transactions"
  | "income_allocation"
  | "property_debt"
  | "drawdown"
  | "charitable"
  | "healthcare"
  | "estate"
  | "notes";

export interface PlanSectionDef {
  key: PlanSectionKey;
  title: string;
  Component: React.ComponentType;
  essential?: true;
}

/**
 * The ordered list of builder sections. Both the sidebar section list and
 * the Edit sheet iterate this so their order and titles stay in
 * lockstep. Each Component renders the section's editor (wrapped in a
 * CollapsibleSection); inside the sheet the BuilderModeContext strips the
 * accordion chrome so only the editor shows.
 */
export const PLAN_SECTIONS: PlanSectionDef[] = [
  { key: "plan_details", title: "Plan details", Component: PlanHeader, essential: true },
  { key: "assumptions", title: "Assumptions", Component: AssumptionsSection },
  { key: "milestones", title: "Milestones", Component: MilestonesSection },
  { key: "income", title: "Income streams", Component: IncomeSection, essential: true },
  { key: "expenses", title: "Expenses", Component: ExpenseSection, essential: true },
  { key: "flex", title: "Flexible spending", Component: FlexRulesSection },
  { key: "accounts", title: "Accounts", Component: AccountsSection, essential: true },
  ...(extensions.planner?.sections ?? []),
  ...(TRANSACTIONS_ENABLED
    ? [{ key: "transactions" as const, title: "Transactions", Component: TransactionsSection }]
    : []),
  { key: "income_allocation", title: "Income allocation", Component: IncomeAllocationSection },
  { key: "property_debt", title: "Property and debt", Component: PropertyDebtSection },
  { key: "drawdown", title: "Drawdown order", Component: DrawdownSection },
  { key: "charitable", title: "Charitable giving", Component: CharitableSection },
  { key: "healthcare", title: "Health coverage", Component: HealthcareSection },
  { key: "estate", title: "Partner and estate", Component: EstateSection },
  { key: "notes", title: "Notes", Component: NotesSection },
];
