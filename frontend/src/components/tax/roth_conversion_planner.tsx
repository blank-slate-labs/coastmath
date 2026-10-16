import { useEffect, useState } from "react";
import { usePlanStore } from "@/stores/plan_store";
import { useStorage } from "@/storage/context";
import { priorityPayload } from "../savings_priorities_panel";
import type { CashFlowPriority, CashFlowPriorityCreate, YearSnapshot } from "@/types/plan";
import { ROTH_TYPES, TRADITIONAL_RETIREMENT_TYPES } from "@/domain/account_types";
import { ownerLabel, ownerSuffix } from "@/domain/person_labels";
import { moneyLabel } from "@/utils/format";
import { usePlanAccounts } from "@/utils/use_plan_accounts";
import MoneyInput from "@/components/money_input";
import { STALE_RATE_NOTE, isStaleConversionCeiling } from "@/domain/federal_bracket_rates";
import { confirmDelete } from "@/components/confirm_dialog";

/**
 * Switch a conversion or harvest rule to the plan tax target, or back. A
 * rule sized by the target is a targeted ("fill_bracket") rule; switching back
 * keeps its own bracket, or returns a conversion without one to a fixed cap
 * and a harvest without one to the 0% capital-gains bracket.
 */
export function withPlanTarget(
  items: CashFlowPriority[],
  id: string,
  useTarget: boolean,
): CashFlowPriorityCreate[] {
  return priorityPayload(
    items.map((item) => {
      if (item.id !== id) return item;
      if (useTarget) return { ...item, conversion_mode: "fill_bracket", use_plan_tax_target: true };
      const changed: CashFlowPriority = { ...item, use_plan_tax_target: false };
      if (item.bracket_ceiling_rate == null) {
        if (item.priority_type === "gain_harvest") changed.bracket_ceiling_rate = 0;
        else changed.conversion_mode = "fixed";
      }
      return changed;
    }),
  );
}

function PlanTargetToggle({
  rule,
  onChange,
}: {
  rule: CashFlowPriority;
  onChange: (useTarget: boolean) => void;
}) {
  return (
    <label style={{ display: "inline-flex", gap: 4, alignItems: "center", marginInline: 8 }}>
      <input
        type="checkbox"
        checked={rule.use_plan_tax_target ?? false}
        onChange={(e) => onChange(e.target.checked)}
      />
      Use plan tax target
    </label>
  );
}

export function RothConversionPlanner({ snapshots }: { snapshots: YearSnapshot[] }) {
  const plan = usePlanStore((s) => s.plan);
  const { adapter } = useStorage();
  const { accounts, status: accountStatus } = usePlanAccounts(adapter, plan?.id);
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [amount, setAmount] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (accountStatus === "error") setError("Could not load accounts. Reopen tax tools to retry.");
  }, [accountStatus]);
  if (!plan) return null;
  const currentPlan = plan;
  const hasPartner = plan.spouse != null;
  const sources = accounts.filter((a) => TRADITIONAL_RETIREMENT_TYPES.has(a.account_type));
  const selectedSource = sources.find((a) => a.id === source);
  const targets = accounts.filter(
    (a) =>
      ROTH_TYPES.has(a.account_type) && (a.owner ?? "self") === (selectedSource?.owner ?? "self"),
  );
  async function save(items: CashFlowPriorityCreate[]) {
    setSaving(true);
    setError("");
    try {
      await adapter.updatePriorities(currentPlan.id, items, currentPlan.priorities_revision ?? 0);
      if (usePlanStore.getState().plan?.id === currentPlan.id)
        await usePlanStore.getState().loadPlan(currentPlan.id);
      setAmount("");
    } catch (err) {
      setError(
        `Could not save conversions. ${err instanceof Error ? err.message : ""} Your inputs are retained. Reload the latest plan before retrying.`,
      );
    } finally {
      setSaving(false);
    }
  }
  return (
    <section data-sample-editor>
      <h3>Manual Roth conversions</h3>
      <p style={{ color: "var(--text-secondary)", fontSize: 13 }}>
        Annual conversions up to the cap. Assumes pre-tax balances; after-tax IRA basis and
        workplace eligibility are not modeled.
      </p>
      <p style={{ fontSize: 13 }}>
        First-year marginal rate in the current projection:{" "}
        {((snapshots[0]?.marginal_rate ?? 0) * 100).toFixed(1)}%. The cost of a conversion must be
        evaluated by recalculating the full plan.
      </p>
      <fieldset disabled={saving} style={{ border: 0, padding: 0, minWidth: 0 }}>
        {plan.priorities
          .filter((p) => p.priority_type === "roth_conversion")
          .map((p) => (
            <div
              key={p.id}
              style={{ padding: "10px 0", borderTop: "1px solid var(--surface-border)" }}
            >
              {accounts.find((a) => a.id === p.source_account_id)?.name ?? "Source"} →{" "}
              {accounts.find((a) => a.id === p.target_account_id)?.name ?? "Roth"} ·{" "}
              {p.use_plan_tax_target
                ? `fill the plan tax target${p.max_annual_amount != null ? `, up to $${p.max_annual_amount.toLocaleString()}` : ""}`
                : p.conversion_mode === "fill_bracket"
                  ? `fill to the ${Math.round((p.bracket_ceiling_rate ?? 0) * 100)}% bracket${isStaleConversionCeiling(p, plan.tax_settings) ? ` ${STALE_RATE_NOTE}` : ""}${p.magi_cap != null ? `, MAGI ≤ $${p.magi_cap.toLocaleString()}` : ""}`
                  : p.max_annual_amount == null
                    ? "Available balance"
                    : `$${p.max_annual_amount.toLocaleString()}`}{" "}
              / year{" "}
              <PlanTargetToggle
                rule={p}
                onChange={(useTarget) =>
                  void save(withPlanTarget(plan.priorities, p.id, useTarget))
                }
              />{" "}
              <button
                onClick={() =>
                  void confirmDelete(
                    `${accounts.find((a) => a.id === p.source_account_id)?.name ?? "Source"} → ${accounts.find((a) => a.id === p.target_account_id)?.name ?? "Roth"} conversion`,
                  ).then((confirmed) => {
                    if (confirmed)
                      void save(
                        priorityPayload(plan.priorities.filter((item) => item.id !== p.id)),
                      );
                  })
                }
              >
                Remove conversion
              </button>
            </div>
          ))}
        {plan.priorities
          .filter((p) => p.priority_type === "gain_harvest")
          .map((p) => (
            <div
              key={p.id}
              style={{ padding: "10px 0", borderTop: "1px solid var(--surface-border)" }}
            >
              Harvest gains in{" "}
              {accounts.find((a) => a.id === p.source_account_id)?.name ?? "taxable account"}{" "}
              {p.use_plan_tax_target ? (
                "to fill the plan tax target"
              ) : (
                <>
                  to fill the {Math.round((p.bracket_ceiling_rate ?? 0) * 100)}% capital-gains
                  bracket{p.magi_cap != null ? `, MAGI ≤ $${p.magi_cap.toLocaleString()}` : ""}
                </>
              )}{" "}
              <PlanTargetToggle
                rule={p}
                onChange={(useTarget) =>
                  void save(withPlanTarget(plan.priorities, p.id, useTarget))
                }
              />{" "}
              <button
                onClick={() =>
                  void save(priorityPayload(plan.priorities.filter((item) => item.id !== p.id)))
                }
              >
                Remove rule
              </button>
            </div>
          ))}
        {!plan.tax_settings?.tax_target && plan.priorities.some((p) => p.use_plan_tax_target) && (
          <p role="status">
            Rules using the plan tax target convert or harvest nothing until a tax target is set
            under Plan details › Tax target.
          </p>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (
              !selectedSource ||
              !targets.some((a) => a.id === target) ||
              !Number.isFinite(Number(amount)) ||
              Number(amount) <= 0
            ) {
              setError("Select accounts for the same person and enter a positive annual cap.");
              return;
            }
            void save([
              ...priorityPayload(plan.priorities),
              {
                priority_rank: plan.priorities.length + 1,
                priority_type: "roth_conversion",
                source_account_id: source,
                target_account_id: target,
                max_annual_amount: Number(amount),
              },
            ]);
          }}
          style={{ display: "grid", gap: 12 }}
        >
          <label>
            Traditional source
            <select
              required
              value={source}
              onChange={(e) => {
                setSource(e.target.value);
                setTarget("");
              }}
            >
              <option value="">Choose account</option>
              {sources.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                  {ownerSuffix(a.owner, hasPartner)}
                </option>
              ))}
            </select>
          </label>
          <p className="allocation-help">Source and Roth destination must have the same owner.</p>
          <label>
            Roth destination
            <select
              required
              disabled={!selectedSource || !targets.length}
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value="">
                {!selectedSource
                  ? "Choose a source first"
                  : !targets.length
                    ? "No eligible Roth account"
                    : "Choose account"}
              </option>
              {selectedSource &&
                targets.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                    {ownerSuffix(a.owner, hasPartner)}
                  </option>
                ))}
            </select>
          </label>
          {selectedSource && !targets.length && (
            <p role="status">
              No Roth account belongs to the {ownerLabel(selectedSource.owner).toLowerCase()}. Add a
              Roth account for the same person under Accounts in the plan builder.
            </p>
          )}
          <label>
            {moneyLabel("Annual conversion cap ($)")}
            <MoneyInput required min="0.01" step="0.01" value={amount} onValueChange={setAmount} />
          </label>
          <button type="submit" disabled={!selectedSource || !targets.some((a) => a.id === target)}>
            {saving ? "Saving…" : "Add conversion rule"}
          </button>
        </form>
      </fieldset>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
