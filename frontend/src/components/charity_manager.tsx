import { useState, useEffect, useCallback } from "react";
import type { Account, Milestone } from "@/types/plan";
import type {
  CharityEntity,
  CharityEntityCreate,
  CharityFunding,
  CharityType,
} from "@/types/charity";
import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import { milestoneWindowError, resolveMilestoneYear } from "@/utils/milestone_window";
import { dollarsOr, moneyLabel } from "@/utils/format";
import { ScenarioBadge } from "@/components/scenario/scenario_badge";
import MoneyInput from "@/components/money_input";
import { confirmDelete } from "./confirm_dialog";
import { formStyle } from "./form_styles";

interface CharityManagerProps {
  planId: string;
  milestones: Milestone[];
}

const TYPE_LABELS: Record<CharityType, string> = {
  qcd: "QCD from IRA",
  daf: "Donor-advised fund",
  direct: "Direct cash gift",
};

const TYPE_NOTES: Record<CharityType, string> = {
  qcd: "Requires IRA owner age 70½; capped at the indexed annual limit.",
  daf: "Paid from checking, then taxable brokerage. Itemized up to 60% of AGI with five-year carryforward; 0.5% AGI floor from 2026.",
  direct:
    "Paid from checking, then taxable brokerage. Itemized up to 60% of AGI (0.5% floor from 2026) or $1,000/$2,000 non-itemizer deduction. No carryforward.",
};

const SHARES_NOTE =
  "Gives shares from a taxable brokerage account at market value, so their gain is never taxed. " +
  "Itemized up to 30% of AGI with five-year carryforward; cash gifts then share the 60% limit. " +
  "If the account runs short, the rest is paid in cash.";

const helpStyle: React.CSSProperties = {
  gridColumn: "1 / -1",
  fontSize: 12,
  color: "var(--text-secondary)",
  textTransform: "none",
  letterSpacing: "normal",
};

function CharityForm({
  initial,
  milestones,
  accounts,
  onSubmit,
  onCancel,
}: {
  initial?: CharityEntity;
  milestones: Milestone[];
  accounts: Account[];
  onSubmit: (data: CharityEntityCreate) => void | Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [entityType, setEntityType] = useState<CharityType>(initial?.entity_type ?? "direct");
  const [annualAmount, setAnnualAmount] = useState(initial?.annual_amount?.toString() ?? "");
  const [startMilestoneId, setStartMilestoneId] = useState(initial?.start_milestone_id ?? "");
  const [endMilestoneId, setEndMilestoneId] = useState(initial?.end_milestone_id ?? "");
  const [sourceAccountId, setSourceAccountId] = useState(initial?.source_account_id ?? "");
  const [funding, setFunding] = useState<CharityFunding>(initial?.funding ?? "cash");
  const givesShares = entityType !== "qcd" && funding === "appreciated_shares";
  const brokerageAccounts = accounts.filter((a) => a.account_type === "taxable_brokerage");
  const [error, setError] = useState<string | null>(null);
  const birthYear = usePlanStore((state) => state.plan?.birth_year);
  const startYear = resolveMilestoneYear(
    milestones.find((m) => m.id === startMilestoneId),
    milestones,
    birthYear,
  );
  const endYear = resolveMilestoneYear(
    milestones.find((m) => m.id === endMilestoneId),
    milestones,
    birthYear,
  );
  const windowError =
    milestoneWindowError(startMilestoneId, endMilestoneId, milestones, birthYear) ??
    (startMilestoneId &&
    endMilestoneId &&
    (startMilestoneId === endMilestoneId || (startYear != null && startYear === endYear))
      ? "Giving must end in a later year than it starts; the end year is excluded."
      : null);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (windowError) {
      setError(windowError);
      return;
    }
    const amount = Number(annualAmount);
    if (annualAmount.trim() === "" || !Number.isFinite(amount) || amount <= 0) {
      setError(moneyLabel("Enter a positive annual amount in today's nominal dollars."));
      return;
    }
    if (givesShares && !brokerageAccounts.some((a) => a.id === sourceAccountId)) {
      setError("Choose the taxable brokerage account the shares come from.");
      return;
    }
    const data: CharityEntityCreate = {
      name: name.trim(),
      entity_type: entityType,
      annual_amount: amount,
      start_milestone_id: startMilestoneId || null,
      end_milestone_id: endMilestoneId || null,
      source_account_id: entityType === "qcd" || givesShares ? sourceAccountId || null : null,
    };
    // Cash gifts omit the field unless they switch back from shares.
    if (givesShares) data.funding = "appreciated_shares";
    else if (initial?.funding === "appreciated_shares") data.funding = "cash";
    void onSubmit(data);
  }

  return (
    <form onSubmit={handleSubmit} style={formStyle}>
      <label>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <label>
        Giving type
        <select value={entityType} onChange={(e) => setEntityType(e.target.value as CharityType)}>
          <option value="direct">Direct cash gift</option>
          <option value="daf">Donor-advised fund contribution</option>
          <option value="qcd">Qualified charitable distribution (IRA)</option>
        </select>
      </label>
      <p style={helpStyle}>{givesShares ? SHARES_NOTE : TYPE_NOTES[entityType]}</p>
      {entityType !== "qcd" && (
        <label>
          Paid with
          <select value={funding} onChange={(e) => setFunding(e.target.value as CharityFunding)}>
            <option value="cash">Cash</option>
            <option value="appreciated_shares">Appreciated shares</option>
          </select>
        </label>
      )}
      {givesShares && (
        <label>
          Shares from
          <select value={sourceAccountId} onChange={(e) => setSourceAccountId(e.target.value)}>
            <option value="">Choose a brokerage account</option>
            {brokerageAccounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {entityType === "qcd" && (
        <label>
          IRA payer
          <select value={sourceAccountId} onChange={(e) => setSourceAccountId(e.target.value)}>
            <option value="">Automatic allocation</option>
            {accounts
              .filter(
                (a) => a.account_type === "traditional_ira" && ["self", "spouse"].includes(a.owner),
              )
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            {sourceAccountId &&
              !accounts.some(
                (a) =>
                  a.id === sourceAccountId &&
                  a.account_type === "traditional_ira" &&
                  ["self", "spouse"].includes(a.owner),
              ) && <option value={sourceAccountId}>Missing IRA</option>}
          </select>
        </label>
      )}
      <label>
        {moneyLabel("Annual amount ($, nominal)")}
        <MoneyInput value={annualAmount} onValueChange={setAnnualAmount} min="0" step="0.01" />
        <span style={{ ...helpStyle, display: "block" }}>
          {dollarsOr("Same dollar amount", "Same amount")} every active year; it is not
          inflation-adjusted.
        </span>
      </label>
      <label>
        Start milestone
        <select value={startMilestoneId} onChange={(e) => setStartMilestoneId(e.target.value)}>
          <option value="">— From the start —</option>
          {milestones.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        End milestone
        <select value={endMilestoneId} onChange={(e) => setEndMilestoneId(e.target.value)}>
          <option value="">— Until the end —</option>
          {milestones.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </label>
      <span style={helpStyle}>
        Whole years: full amount in the start milestone year, none in the end milestone year.
      </span>
      {error && (
        <div
          role="alert"
          style={{ gridColumn: "1 / -1", color: "var(--color-danger)", fontSize: 13 }}
        >
          {error}
        </div>
      )}
      <div
        style={{
          gridColumn: "1 / -1",
          display: "flex",
          gap: 8,
          justifyContent: "flex-end",
          flexWrap: "wrap",
        }}
      >
        <button type="button" onClick={onCancel} data-sample-view>
          Cancel
        </button>
        <button type="submit">{initial ? "Update" : "Add"} giving</button>
      </div>
    </form>
  );
}

/**
 * Manages a plan's charitable giving entities and re-runs the projection after
 * each change so QCD, DAF and direct-gift effects show up immediately.
 */
export default function CharityManager({ planId, milestones }: CharityManagerProps) {
  const { adapter } = useStorage();
  const [charities, setCharities] = useState<CharityEntity[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<CharityEntity | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [giving, available] = await Promise.all([
        adapter.listCharities(planId),
        adapter.listAccounts(planId),
      ]);
      setCharities(giving);
      const plan = usePlanStore.getState().plan;
      const snapshot =
        plan?.id === planId && plan.plan_type === "FIXED_DATE" ? plan.snapshot_conditions : null;
      setAccounts(
        snapshot && Object.keys(snapshot).length
          ? Object.entries(snapshot).map(([id, a]) => ({ ...(a as Omit<Account, "id">), id }))
          : available,
      );
    } catch {
      setError("Could not load charitable giving for this plan.");
    } finally {
      setLoading(false);
    }
  }, [adapter, planId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function afterChange() {
    await load();
    const store = usePlanStore.getState();
    if (store.plan?.id === planId) await store.runSimulation(planId);
  }

  async function handleCreate(data: CharityEntityCreate) {
    try {
      setError(null);
      await adapter.createCharity(planId, data);
      setShowForm(false);
      await afterChange();
    } catch {
      setError("Could not save this giving entry. Your edits are retained; try again.");
    }
  }

  async function handleUpdate(data: CharityEntityCreate) {
    if (!editing) return;
    try {
      setError(null);
      await adapter.updateCharity(planId, editing.id, data);
      setEditing(null);
      await afterChange();
    } catch {
      setError("Could not update this giving entry. Your edits are retained; try again.");
    }
  }

  async function handleDelete(charity: CharityEntity) {
    if (!(await confirmDelete(charity.name))) return;
    try {
      setError(null);
      await adapter.deleteCharity(planId, charity.id);
      await afterChange();
    } catch {
      setError("Could not delete this giving entry.");
    }
  }

  function milestoneName(id: string | null): string | null {
    if (!id) return null;
    return milestones.find((ms) => ms.id === id)?.name ?? "missing milestone";
  }

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
        {moneyLabel("Amounts are nominal dollars per active year.")}
      </p>
      {loading && (
        <p role="status" style={{ margin: 0, fontSize: 13 }}>
          Loading charitable giving…
        </p>
      )}
      {error && (
        <div role="alert" style={{ color: "var(--color-danger)", fontSize: 13 }}>
          {error}
        </div>
      )}

      {!loading && !showForm && !editing && charities.length === 0 && (
        <p style={{ margin: 0, fontSize: 13, color: "var(--text-tertiary)" }}>
          No charitable giving planned yet.
        </p>
      )}

      {!loading &&
        charities.map((c) => (
          <div
            key={c.id}
            className="plan-list-item"
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span style={{ display: "grid", gap: 2, minWidth: 0 }}>
              <span style={{ fontWeight: 600 }}>
                {c.name}
                <ScenarioBadge rowId={c.id} />
              </span>
              <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                {TYPE_LABELS[c.entity_type]}
                {c.funding === "appreciated_shares" ? " (shares)" : ""} · $
                {c.annual_amount.toLocaleString()}/yr
                {c.source_account_id &&
                  ` · ${accounts.find((a) => a.id === c.source_account_id)?.name ?? (c.funding === "appreciated_shares" ? "Missing account" : "Missing IRA")}`}
                {milestoneName(c.start_milestone_id) &&
                  ` · from ${milestoneName(c.start_milestone_id)}`}
                {milestoneName(c.end_milestone_id) &&
                  ` · until ${milestoneName(c.end_milestone_id)}`}
              </span>
            </span>
            <span style={{ display: "flex", gap: 6, flexShrink: 0 }}>
              <button
                type="button"
                className="plan-action-btn"
                onClick={() => {
                  setShowForm(false);
                  setEditing(c);
                }}
                data-sample-view
              >
                Edit
              </button>
              <button
                type="button"
                className="plan-delete-btn"
                onClick={() => void handleDelete(c)}
              >
                Delete
              </button>
            </span>
          </div>
        ))}

      {showForm && (
        <CharityForm
          milestones={milestones}
          accounts={accounts}
          onSubmit={handleCreate}
          onCancel={() => setShowForm(false)}
        />
      )}
      {editing && (
        <CharityForm
          key={editing.id}
          initial={editing}
          milestones={milestones}
          accounts={accounts}
          onSubmit={handleUpdate}
          onCancel={() => setEditing(null)}
        />
      )}
      {!showForm && !editing && (
        <button type="button" className="btn-ghost plan-add-btn" onClick={() => setShowForm(true)}>
          + Add giving
        </button>
      )}
    </div>
  );
}
