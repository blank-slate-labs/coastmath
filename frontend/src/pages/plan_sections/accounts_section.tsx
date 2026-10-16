import { useState } from "react";

import AccountForm from "@/components/account_form";
import { withdrawalLockLabel } from "@/domain/withdrawal_lock";
import { accountTypeLabel } from "@/domain/account_types";
import { ownerSuffix } from "@/domain/person_labels";
import { FormModal } from "@/components/form_modal";
import { useStorage } from "@/storage/context";
import { useTaxRegimes } from "@/components/intl/use_tax_regimes";
import { findAccountKind, planCountries, usCoverage } from "@/domain/intl_plan";
import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import { usePlanAccounts } from "@/utils/use_plan_accounts";
import { useFailedSaveGuard } from "@/components/use_failed_save_guard";
import { confirmDelete } from "@/components/confirm_dialog";
import SaveErrorNotice from "@/components/save_error_notice";
import { ScenarioBadge } from "@/components/scenario/scenario_badge";
import {
  CollapsibleSection,
  EmptyState,
  actionBtnStyle,
  addBtnStyle,
  deleteBtnStyle,
} from "@/pages/plan_setup_shared";
import {
  actionGroupStyle,
  compactCurrency,
  itemDetailStyle,
  itemNameStyle,
  itemStackStyle,
  listItemStyle,
} from "@/pages/plan_sections/shared";
import type { Account, AccountCreate } from "@/types/plan";

const ZERO_GROWTH_TYPES = new Set(["checking", "savings"]);

export function AccountsSection() {
  const { adapter } = useStorage();
  const plan = usePlanStore((s) => s.plan);
  const saveAccount = usePlanStore((s) => s.saveAccount);
  const deleteAccount = usePlanStore((s) => s.deleteAccount);
  const regimes = useTaxRegimes(adapter);
  const { accounts, status: accountStatus } = usePlanAccounts(adapter, plan?.id);
  const loading = accountStatus === "loading";
  const loadError =
    accountStatus === "error" ? "Could not load accounts. Reopen this section to retry." : null;
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const accountPath = plan ? `/plans/${plan.id}/accounts` : "/accounts";
  const saveKey = editing ? `put ${accountPath}/${editing.id}` : `post ${accountPath}`;
  const closeForm = useFailedSaveGuard(saveKey, saving, saveError, () => {
    setShowForm(false);
    setEditing(null);
    setSaveError(null);
  });

  const marketReturnCurve = plan?.assumption_curves?.find(
    (c: { curve_type: string }) => c.curve_type === "market_return",
  );
  const estimatedReturn =
    marketReturnCurve?.fixed_rate != null
      ? `${(marketReturnCurve.fixed_rate * 100).toFixed(1)}% est. return`
      : null;

  async function handleSubmit(data: AccountCreate) {
    if (saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      if (editing) {
        const changes = Object.fromEntries(
          Object.entries(data).filter(([key, value]) => value !== editing[key as keyof Account]),
        ) as Partial<AccountCreate>;
        if (Object.keys(changes).length > 0) {
          await saveAccount(editing.id, changes);
        }
      } else {
        await saveAccount(null, data);
      }
      useSaveStore.getState().discardRejected(saveKey);
      setShowForm(false);
      setEditing(null);
    } catch (error) {
      setSaveError(
        useSaveStore.getState().failures[saveKey]?.message ??
          (error instanceof Error
            ? error.message
            : "The account save could not be confirmed. Keep your draft and check saved values before retrying."),
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    // A shared household account leaves every plan that uses it.
    const confirmed = await confirmDelete(
      accounts.find((account) => account.id === id)?.name ?? "this account",
      plan?.client_id ? undefined : "It is removed from every plan that shares it.",
    );
    if (!confirmed) return;
    setDeleteError(null);
    setDeleting(true);
    try {
      await deleteAccount(id);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Could not delete account. Please retry.";
      setDeleteError(
        /priorit|waterfall|drawdown/i.test(message)
          ? `${message} Remove this account from Income allocation and Drawdown order, save those changes, then retry deletion.`
          : message,
      );
    } finally {
      setDeleting(false);
    }
  }

  return (
    <CollapsibleSection
      title={
        plan?.client_id ? "Accounts · this plan" : "Household accounts · shared across your plans"
      }
      // An older plan shares its accounts: an edit or deletion here changes every such plan.
      sheetNote={
        plan?.client_id
          ? undefined
          : "Shared across your plans: an edit or deletion changes each of them."
      }
      count={loading || loadError ? undefined : accounts.length}
      defaultOpen={false}
      action={
        !loading && !loadError && !showForm && !editing ? (
          <button
            className="btn-ghost plan-add-btn"
            style={addBtnStyle}
            onClick={() => setShowForm(true)}
          >
            <span style={{ fontSize: "15px", lineHeight: 1 }}>+</span> Add account
          </button>
        ) : undefined
      }
    >
      {loading && <p role="status">Loading accounts…</p>}
      {loadError && <p role="alert">{loadError}</p>}
      {deleteError && <p role="alert">{deleteError}</p>}
      {!loading && !loadError && accounts.length === 0 && !showForm && !editing && (
        <EmptyState message="No accounts yet." />
      )}

      {accounts.map((account) => (
        <div key={account.id} className="plan-list-item" style={listItemStyle}>
          <span style={itemStackStyle}>
            <span style={itemNameStyle}>
              {account.name}
              <ScenarioBadge rowId={account.id} />
            </span>
            <span style={itemDetailStyle}>
              {findAccountKind(regimes.countries, account.intl_account_kind)?.label ??
                accountTypeLabel(account.account_type)}{" "}
              · {compactCurrency.format(account.balance)}
              {account.owner && ownerSuffix(account.owner, plan?.spouse != null)}
            </span>
            {account.withdrawal_lock && (
              <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
                {withdrawalLockLabel(account.withdrawal_lock, plan?.milestones)}
              </span>
            )}
            {estimatedReturn && !ZERO_GROWTH_TYPES.has(account.account_type) && (
              <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>
                {account.investment_settings &&
                Object.values(account.investment_settings).some((value) => value != null)
                  ? "Custom investment assumptions"
                  : estimatedReturn}
              </span>
            )}
          </span>
          <span style={actionGroupStyle}>
            <button
              className="plan-action-btn"
              style={actionBtnStyle}
              onClick={() => setEditing(account)}
              data-sample-view
            >
              Edit
            </button>
            <button
              className="plan-delete-btn"
              style={deleteBtnStyle}
              onClick={() => handleDelete(account.id)}
              disabled={deleting}
            >
              Delete
            </button>
          </span>
        </div>
      ))}

      <FormModal
        open={showForm || editing !== null}
        onClose={closeForm}
        title={editing ? "Edit Account" : "Add Account"}
      >
        <SaveErrorNotice message={saveError} />
        <fieldset
          disabled={saving}
          data-save-pending={saving || undefined}
          style={{ border: 0, padding: 0, minWidth: 0 }}
        >
          <AccountForm
            independent={Boolean(plan?.client_id)}
            planAssumptions={plan}
            milestones={plan?.milestones}
            regimeCountries={regimes.countries}
            planCountryCodes={planCountries(plan)}
            usCoverage={usCoverage(plan)}
            initial={editing ?? undefined}
            onSubmit={handleSubmit}
            onCancel={closeForm}
          />
        </fieldset>
        {saving && <p>Saving…</p>}
      </FormModal>
    </CollapsibleSection>
  );
}
