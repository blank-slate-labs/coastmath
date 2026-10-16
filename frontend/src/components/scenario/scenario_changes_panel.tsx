import { useEffect, useState } from "react";

import { FormModal } from "@/components/form_modal";
import { isSaveConflict } from "@/api/save_error";
import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import { reloadPlan, useScenarioStore } from "@/stores/scenario_store";
import type { PlanData } from "@/types/plan";
import { usePlanAccounts } from "@/utils/use_plan_accounts";
import type {
  InheritanceReset,
  PlanInheritance,
  ScenarioFieldChange,
  ScenarioItem,
  ScenarioRowKind,
} from "@/types/scenario";
import {
  WHOLE_LIST_ACTION,
  WHOLE_LIST_KINDS,
  fieldLabel,
  formatScenarioValue,
  groupChanges,
  type FormatContext,
} from "./scenario_format";
import "./scenario.css";

/** The allocation revision changed on the server: nothing was applied. */
export const PRIORITIES_CONFLICT =
  "Savings rules were not changed: income allocation changed since this plan opened. Review the latest saved rules, then try again.";

function errorText(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : "The change could not be made. Try again.";
}

/**
 * What a scenario changed relative to its Main plan, grouped by plan-builder
 * section, with the actions that use Main's values again, restore removed
 * items or make the scenario independent.
 */
export function ScenarioChangesPanel({
  open,
  onClose,
  plan,
  data,
  mainName,
}: {
  open: boolean;
  onClose: () => void;
  plan: PlanData;
  data: PlanInheritance;
  mainName: string;
}) {
  const { adapter } = useStorage();
  const change = useScenarioStore((s) => s.change);
  const load = useScenarioStore((s) => s.load);
  const clear = useScenarioStore((s) => s.clear);
  const detachScenario = usePlanStore((s) => s.detachScenario);
  // Account names for changed account links; the panel still works without them.
  const { accounts } = usePlanAccounts(adapter, plan.id, { enabled: open });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDetach, setConfirmDetach] = useState(false);

  useEffect(() => {
    if (!open) {
      setError(null);
      setConfirmDetach(false);
    }
  }, [open]);

  const ctx: FormatContext = { plan, accounts };
  const groups = groupChanges(data);

  async function run(action: () => Promise<PlanInheritance>, priorities = false) {
    setBusy(true);
    setError(null);
    try {
      await change(plan.id, action);
    } catch (err) {
      if (priorities && isSaveConflict(err)) {
        setError(PRIORITIES_CONFLICT);
        // Show the latest saved rules; nothing was applied.
        await Promise.all([reloadPlan(plan.id), load(adapter, plan.id)]);
      } else {
        setError(errorText(err));
      }
    } finally {
      setBusy(false);
    }
  }

  const reset = (body: InheritanceReset) =>
    run(() => adapter.resetInheritance(plan.id, body), body.kind === "priorities");
  const restore = (kind: ScenarioRowKind, parentRowId: string) =>
    run(() => adapter.restoreInheritance(plan.id, { kind, parent_row_id: parentRowId }));

  async function detach() {
    setBusy(true);
    setError(null);
    const ok = await detachScenario(plan.id);
    setBusy(false);
    if (ok) {
      clear(plan.id);
      onClose();
    } else
      setError(
        usePlanStore.getState().error ?? "This scenario could not be made independent. Try again.",
      );
  }

  function fieldRow(field: ScenarioFieldChange, owner: string, onReset: () => void, kind?: string) {
    const label = fieldLabel(field.field, kind);
    return (
      <div key={field.field} className="scenario-field">
        <span>
          <strong>{label}</strong>{" "}
          <span className="scenario-field-values">
            Main: {formatScenarioValue(field.field, field.parent_value, ctx)} · This scenario:{" "}
            {formatScenarioValue(field.field, field.value, ctx)}
          </span>
        </span>
        <button
          type="button"
          className="btn-quiet"
          disabled={busy}
          aria-label={`Use Main’s value for ${label} of ${owner}`}
          onClick={onReset}
        >
          Use Main’s value
        </button>
      </div>
    );
  }

  function itemRow(item: ScenarioItem) {
    const key = `${item.kind}-${item.row_id ?? item.parent_row_id ?? item.name}`;
    if (WHOLE_LIST_KINDS.has(item.kind)) {
      const action = WHOLE_LIST_ACTION[item.kind] ?? "Use Main’s values";
      const body: InheritanceReset =
        item.kind === "priorities"
          ? { kind: "priorities", expected_revision: plan.priorities_revision ?? 0 }
          : { kind: item.kind as "drawdown" | "residency" };
      return (
        <li key={key} className="scenario-change">
          <span className="scenario-change-name">{item.name}</span>
          <span className="scenario-change-state">Changed in this scenario</span>
          <span className="scenario-actions">
            <button
              type="button"
              disabled={busy}
              aria-label={`${action}: ${item.name}`}
              onClick={() => void reset(body)}
            >
              {action}
            </button>
          </span>
        </li>
      );
    }
    const kind = item.kind as ScenarioRowKind;
    if (item.state === "removed") {
      return (
        <li key={key} className="scenario-change">
          <span className="scenario-change-name">{item.name}</span>
          <span className="scenario-change-state">Removed in this scenario</span>
          <span className="scenario-actions">
            <button
              type="button"
              disabled={busy || !item.parent_row_id}
              aria-label={`Restore ${item.name}`}
              onClick={() => item.parent_row_id && void restore(kind, item.parent_row_id)}
            >
              Restore
            </button>
          </span>
        </li>
      );
    }
    if (item.state === "scenario_only") {
      return (
        <li key={key} className="scenario-change">
          <span className="scenario-change-name">{item.name}</span>
          <span className="scenario-change-state">Only in this scenario</span>
        </li>
      );
    }
    const rowId = item.row_id;
    return (
      <li key={key} className="scenario-change">
        <span className="scenario-change-name">{item.name}</span>
        <span className="scenario-change-state">Changed in this scenario</span>
        {rowId &&
          item.fields.map((field) =>
            fieldRow(
              field,
              item.name,
              () => void reset({ kind, row_id: rowId, fields: [field.field] }),
            ),
          )}
        {/* One changed field has its own button; the whole-item button is for two or more. */}
        {rowId && item.fields.length !== 1 && (
          <span className="scenario-actions">
            <button
              type="button"
              disabled={busy}
              aria-label={`Use Main’s values for ${item.name}`}
              onClick={() => void reset({ kind, row_id: rowId })}
            >
              Use Main’s values
            </button>
          </span>
        )}
      </li>
    );
  }

  return (
    <FormModal
      open={open}
      onClose={() => {
        if (!busy) onClose();
      }}
      title="Changes in this scenario"
    >
      <div className="scenario-changes">
        <p>
          Values listed here were changed in “{plan.name}” and stay as they are when “{mainName}” is
          saved. Everything else follows “{mainName}”.
        </p>
        {error && <p role="alert">{error}</p>}
        {groups.length === 0 && <p role="status">This scenario follows “{mainName}” everywhere.</p>}
        {groups.map((group) => (
          <section key={group.section} aria-label={group.section}>
            <h3>{group.section}</h3>
            <ul>
              {group.planFields.length > 0 && (
                <li className="scenario-change">
                  <span className="scenario-change-name">Plan settings</span>
                  {group.planFields.map((field) =>
                    fieldRow(
                      field,
                      "plan settings",
                      () => void reset({ kind: "plan", fields: [field.field] }),
                      "plan",
                    ),
                  )}
                  {group.planFields.length > 1 && (
                    <span className="scenario-actions">
                      <button
                        type="button"
                        disabled={busy}
                        aria-label="Use Main’s values for plan settings"
                        onClick={() =>
                          void reset({
                            kind: "plan",
                            fields: group.planFields.map((field) => field.field),
                          })
                        }
                      >
                        Use Main’s values
                      </button>
                    </span>
                  )}
                </li>
              )}
              {group.items.map(itemRow)}
            </ul>
          </section>
        ))}
        {busy && <p role="status">Updating…</p>}
        <span className="scenario-actions">
          {/* Catches up after a restore from the archive or a skipped sync. */}
          <button
            type="button"
            className="btn-quiet"
            disabled={busy}
            onClick={() => void run(() => adapter.syncInheritance(plan.id))}
          >
            Sync now
          </button>
        </span>
        <div className="scenario-detach">
          {confirmDetach ? (
            <>
              <p>
                “{plan.name}” keeps its current values and stops receiving changes from “{mainName}
                ”. It can’t be linked again.
              </p>
              <span className="scenario-actions">
                <button
                  type="button"
                  className="btn-danger"
                  disabled={busy}
                  onClick={() => void detach()}
                >
                  Make independent
                </button>
                <button
                  type="button"
                  className="btn-quiet"
                  disabled={busy}
                  onClick={() => setConfirmDetach(false)}
                >
                  Cancel
                </button>
              </span>
            </>
          ) : (
            <span className="scenario-actions">
              <button
                type="button"
                className="btn-quiet"
                disabled={busy}
                onClick={() => setConfirmDetach(true)}
              >
                Make independent…
              </button>
            </span>
          )}
        </div>
      </div>
    </FormModal>
  );
}
