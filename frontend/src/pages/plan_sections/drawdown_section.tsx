import {
  EARLY_WITHDRAWAL_PENALTY_TYPES,
  TRADITIONAL_RETIREMENT_TYPES,
} from "@/domain/account_types";
import DrawdownEditor from "@/components/drawdown_editor";
import { BlendDrawdownToggle } from "@/components/tax_target_form";
import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import { usePlanAccounts } from "@/utils/use_plan_accounts";
import { CollapsibleSection } from "@/pages/plan_setup_shared";
import type { Account } from "@/types/plan";

const NO_ACCOUNTS: Account[] = [];

export function DrawdownSection() {
  const updatePlan = usePlanStore((s) => s.updatePlan);
  const { adapter } = useStorage();
  const plan = usePlanStore((s) => s.plan);

  // Re-fetch when the order changes size (e.g., after an account is
  // created/deleted and the backend adjusts the drawdown order).
  const entryCount = plan?.drawdown_order?.length ?? 0;
  const loaded = usePlanAccounts(adapter, plan?.id, { refreshKey: entryCount });
  // The editor gets no accounts while a read is pending or after one fails.
  const accounts = loaded.status === "ready" ? loaded.accounts : NO_ACCOUNTS;

  if (!plan) return null;

  const entries = [...(plan.drawdown_order ?? [])].sort((a, b) => a.rank - b.rank);
  const firstType =
    entries.length > 0
      ? (accounts.find((a) => a.id === entries[0].source_account_id)?.account_type ?? "")
      : "";

  return (
    <CollapsibleSection title="Drawdown order" count={entries.length} defaultOpen={false}>
      {TRADITIONAL_RETIREMENT_TYPES.has(firstType) &&
        EARLY_WITHDRAWAL_PENALTY_TYPES.has(firstType) && (
          <p role="alert">Traditional account first: early withdrawals may incur a penalty.</p>
        )}
      <BlendDrawdownToggle
        key={`blend-${plan.id}-${plan.tax_settings?.tax_target ? "target" : "none"}`}
        plan={plan}
        onSave={async (tax_settings) => {
          await updatePlan(plan.id, { tax_settings });
          const error = usePlanStore.getState().error;
          if (error) throw new Error(error);
        }}
      />
      <DrawdownEditor planId={plan.id} entries={entries} accounts={accounts} />
    </CollapsibleSection>
  );
}
