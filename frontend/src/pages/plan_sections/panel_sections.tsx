import AssumptionsPanel from "@/components/assumptions_panel";
import SavingsPrioritiesPanel from "@/components/savings_priorities_panel";
import AssetsDebtPanel from "@/components/assets_debt_panel";
import FlexSpendingConfig from "@/components/flex_spending_config";
import WithdrawalStrategyForm from "@/components/withdrawal_strategy_form";
import EstateSettingsForm from "@/components/estate_settings_form";
import PlanNotesForm from "@/components/plan_notes_form";
import CharityManager from "@/components/charity_manager";
import HealthcareForm from "@/components/healthcare_form";
import UsOnlyNote from "@/components/intl/us_only_note";
import { SaveGroup } from "@/components/save_group";
import { usCoverage } from "@/domain/intl_plan";
import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import { CollapsibleSection } from "@/pages/plan_setup_shared";

export function NotesSection() {
  const plan = usePlanStore((s) => s.plan);
  const { adapter } = useStorage();
  if (!plan) return null;
  return (
    <CollapsibleSection title="Notes">
      <PlanNotesForm
        key={plan.id}
        plan={plan}
        onSave={async (id, notes) => {
          await adapter.updatePlan(id, { notes });
          if (usePlanStore.getState().plan?.id === id) await usePlanStore.getState().loadPlan(id);
        }}
      />
    </CollapsibleSection>
  );
}

export function HealthcareSection() {
  const plan = usePlanStore((s) => s.plan);
  const { adapter } = useStorage();
  if (!plan) return null;
  const coverage = usCoverage(plan);
  return (
    <CollapsibleSection title="Health coverage">
      {coverage === "non_us" ? (
        <p style={{ margin: 0, fontSize: 13 }}>
          Health coverage here models US Marketplace plans and Medicare, which don&apos;t apply to
          plans outside the US. Add health insurance and care costs as expenses.
        </p>
      ) : (
        <>
          <UsOnlyNote coverage={coverage} what="Marketplace coverage, Medicare and IRMAA" />
          <HealthcareForm
            key={plan.id}
            plan={plan}
            onSave={async (id, healthcare_settings) => {
              await adapter.updatePlan(id, { healthcare_settings });
              if (usePlanStore.getState().plan?.id === id)
                await usePlanStore.getState().loadPlan(id);
            }}
          />
        </>
      )}
    </CollapsibleSection>
  );
}

export function EstateSection() {
  const plan = usePlanStore((s) => s.plan);
  const { adapter } = useStorage();
  if (!plan) return null;
  return (
    <CollapsibleSection title="Partner and estate">
      <EstateSettingsForm
        key={plan.id}
        plan={plan}
        onSave={async (id, data) => {
          await adapter.updatePlan(id, data);
          if (usePlanStore.getState().plan?.id === id) await usePlanStore.getState().loadPlan(id);
        }}
      />
    </CollapsibleSection>
  );
}

export function FlexRulesSection() {
  const plan = usePlanStore((s) => s.plan);
  const { adapter } = useStorage();
  if (!plan) return null;
  // Both forms save together, with the sheet's one Save.
  return (
    <CollapsibleSection title="Flexible spending">
      <SaveGroup
        label="Save spending"
        onSave={async (data) => {
          await adapter.updatePlan(plan.id, data);
          if (usePlanStore.getState().plan?.id === plan.id)
            await usePlanStore.getState().loadPlan(plan.id);
        }}
      >
        <FlexSpendingConfig
          key={`${plan.id}-${JSON.stringify(plan.spending_rules)}`}
          planId={plan.id}
          initial={plan.spending_rules}
          milestones={plan.milestones}
        />
        <WithdrawalStrategyForm
          key={`${plan.id}-${JSON.stringify(plan.withdrawal_strategy ?? null)}`}
          planId={plan.id}
          initial={plan.withdrawal_strategy}
          milestones={plan.milestones}
        />
      </SaveGroup>
    </CollapsibleSection>
  );
}

export function AssumptionsSection() {
  const plan = usePlanStore((s) => s.plan);
  if (!plan) return null;
  return (
    <CollapsibleSection title="Assumptions">
      <AssumptionsPanel plan={plan} />
    </CollapsibleSection>
  );
}

export function IncomeAllocationSection() {
  const plan = usePlanStore((s) => s.plan);
  if (!plan) return null;
  return (
    <CollapsibleSection id="income-allocation" title="Income allocation">
      <SavingsPrioritiesPanel key={plan.id} plan={plan} />
    </CollapsibleSection>
  );
}

export function PropertyDebtSection() {
  const plan = usePlanStore((s) => s.plan);
  if (!plan) return null;
  return (
    <CollapsibleSection title="Property and debt">
      <AssetsDebtPanel key={plan.id} plan={plan} />
    </CollapsibleSection>
  );
}

export function CharitableSection() {
  const plan = usePlanStore((s) => s.plan);
  if (!plan) return null;
  return (
    <CollapsibleSection title="Charitable giving">
      <CharityManager key={`charity-${plan.id}`} planId={plan.id} milestones={plan.milestones} />
    </CollapsibleSection>
  );
}
