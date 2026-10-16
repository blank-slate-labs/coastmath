import { useEffect, useState } from "react";
import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import { FormModal } from "./form_modal";
import { useFailedSaveGuard } from "./use_failed_save_guard";
import { confirmDelete } from "./confirm_dialog";
import SaveErrorNotice from "./save_error_notice";
import RealAssetForm from "./real_asset_form";
import LiabilityForm from "./liability_form";
import { compactCurrency } from "@/utils/format";
import { usePlanAccounts } from "@/utils/use_plan_accounts";
import { ScenarioBadge } from "@/components/scenario/scenario_badge";
import type {
  PlanData,
  RealAsset,
  Liability,
  RealAssetCreate,
  LiabilityCreate,
} from "@/types/plan";

export default function AssetsDebtPanel({ plan }: { plan: PlanData }) {
  const { adapter } = useStorage();
  const { accounts, status: accountStatus } = usePlanAccounts(adapter, plan.id);
  const ready = accountStatus === "ready";
  const [asset, setAsset] = useState<RealAsset | "new" | null>(null);
  const [debt, setDebt] = useState<Liability | "new" | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const item = asset ?? debt;
  const resource = asset ? "real-assets" : "liabilities";
  const saveKey =
    item && item !== "new"
      ? `put /plans/${plan.id}/${resource}/${item.id}`
      : `post /plans/${plan.id}/${resource}`;
  const closeForm = useFailedSaveGuard(saveKey, saving, error, () => {
    setAsset(null);
    setDebt(null);
    setError("");
  });
  useEffect(() => {
    if (accountStatus === "error")
      setError("Could not load accounts. Reopen this section to retry.");
  }, [accountStatus]);
  async function mutate(action: () => Promise<unknown>) {
    if (saving) return;
    setSaving(true);
    setError("");
    try {
      await action();
      if (usePlanStore.getState().plan?.id === plan.id)
        await usePlanStore.getState().loadPlan(plan.id);
      setAsset(null);
      setDebt(null);
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "The property or debt save could not be confirmed. Keep your draft and check saved values before retrying.",
      );
    } finally {
      setSaving(false);
    }
  }
  function saveAsset(data: RealAssetCreate) {
    void mutate(() =>
      asset && asset !== "new"
        ? adapter.updateRealAsset(plan.id, asset.id, data)
        : adapter.createRealAsset(plan.id, data),
    );
  }
  function saveDebt(data: LiabilityCreate) {
    void mutate(() =>
      debt && debt !== "new"
        ? adapter.updateLiability(plan.id, debt.id, data)
        : adapter.createLiability(plan.id, data),
    );
  }
  return (
    <div>
      <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
        Linked loans are repaid when the asset sells.
      </p>
      {plan.real_assets.map((a) => (
        <div key={a.id} style={{ borderTop: "1px solid var(--surface-border)", padding: "12px 0" }}>
          <strong>{a.name}</strong>
          <ScenarioBadge rowId={a.id} /> · {compactCurrency(a.current_value)}
          <p style={{ fontSize: 12 }}>
            {(a.annual_appreciation_rate * 100).toFixed(1)}% annual value change
            {a.sale_year ? ` · Sale ${a.sale_month}/${a.sale_year}` : ""}
          </p>
          <button
            disabled={saving || !ready}
            onClick={() => {
              setError("");
              setAsset(a);
            }}
            data-sample-view
          >
            Edit {a.name}
          </button>{" "}
          <button
            disabled={saving}
            onClick={() =>
              void confirmDelete(a.name).then((confirmed) => {
                if (confirmed) void mutate(() => adapter.deleteRealAsset(plan.id, a.id));
              })
            }
          >
            Delete {a.name}
          </button>
        </div>
      ))}
      <button
        disabled={!ready || saving}
        onClick={() => {
          setError("");
          setAsset("new");
        }}
      >
        Add property or vehicle
      </button>
      <h3 style={{ marginTop: 24 }}>Loans and debt</h3>
      {plan.liabilities.map((d) => (
        <div key={d.id} style={{ borderTop: "1px solid var(--surface-border)", padding: "12px 0" }}>
          <strong>{d.name}</strong>
          <ScenarioBadge rowId={d.id} /> · {compactCurrency(d.principal_balance)}
          <p style={{ fontSize: 12 }}>
            {d.interest_rate}% interest
            {d.linked_asset_id
              ? ` · ${plan.real_assets.find((a) => a.id === d.linked_asset_id)?.name ?? "Linked asset"}`
              : ""}
          </p>
          <button
            disabled={saving || !ready}
            onClick={() => {
              setError("");
              setDebt(d);
            }}
            data-sample-view
          >
            Edit {d.name} / schedule
          </button>{" "}
          <button
            disabled={saving}
            onClick={() =>
              void confirmDelete(d.name).then((confirmed) => {
                if (confirmed) void mutate(() => adapter.deleteLiability(plan.id, d.id));
              })
            }
          >
            Delete {d.name}
          </button>
        </div>
      ))}
      <button
        disabled={!ready || saving}
        onClick={() => {
          setError("");
          setDebt("new");
        }}
      >
        Add loan or debt
      </button>
      {error && !asset && !debt && <p role="alert">{error}</p>}
      <FormModal
        open={!!asset || !!debt}
        onClose={closeForm}
        title={asset ? "Property or vehicle" : "Loan or debt"}
      >
        <SaveErrorNotice message={error} />
        <fieldset
          disabled={saving}
          data-save-pending={saving || undefined}
          style={{ border: 0, padding: 0, minWidth: 0 }}
        >
          {asset && (
            <RealAssetForm
              initial={asset === "new" ? undefined : asset}
              accounts={accounts}
              onSubmit={saveAsset}
              onCancel={closeForm}
            />
          )}
          {debt && (
            <LiabilityForm
              initial={debt === "new" ? undefined : debt}
              planId={plan.id}
              milestones={plan.milestones}
              accounts={accounts}
              realAssets={plan.real_assets}
              onSubmit={saveDebt}
              onCancel={closeForm}
            />
          )}
        </fieldset>
        {saving && <p>Saving…</p>}
      </FormModal>
    </div>
  );
}
