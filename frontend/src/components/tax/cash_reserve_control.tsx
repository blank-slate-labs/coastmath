import { useCallback, useEffect, useRef, useState } from "react";
import { usePlanStore } from "@/stores/plan_store";
import { useStorage } from "@/storage/context";
import type { Account } from "@/types/plan";
import { fullCurrency, moneyLabel } from "@/utils/format";
import MoneyInput from "@/components/money_input";
import { helpTextStyle } from "../form_styles";

const warningStyle: React.CSSProperties = {
  padding: "8px 10px",
  background: "var(--color-danger-light, rgba(220, 38, 38, 0.08))",
  borderRadius: "var(--radius-md, 6px)",
  fontSize: 13,
  color: "var(--color-danger)",
};

/**
 * Opt-in protected cash reserve. The reserve accounts keep a set amount that the
 * normal withdrawal order skips; it is spent only when nothing else can cover a
 * shortfall, in the order the accounts are listed here.
 */
export default function CashReserveControl() {
  const plan = usePlanStore((s) => s.plan);
  const updatePlan = usePlanStore((s) => s.updatePlan);
  const { adapter } = useStorage();
  const saved = plan?.cash_reserve_settings;
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [enabled, setEnabled] = useState(saved?.enabled ?? false);
  const [ids, setIds] = useState<string[]>(saved?.account_ids ?? []);
  const [amount, setAmount] = useState(saved?.reserve_amount ? String(saved.reserve_amount) : "");
  const [sweep, setSweep] = useState(saved?.sweep_excess ?? false);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);
  // Edited since the last save; switching tabs or reloading asks first.
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useRef(0);
  const planId = plan?.id;
  const loadAccounts = useCallback(async () => {
    const request = ++load.current;
    try {
      const items = await adapter.listAccounts(planId);
      if (load.current === request)
        setAccounts(
          items.filter((a) => a.account_type === "checking" || a.account_type === "savings"),
        );
    } catch {
      /* accounts may not be loaded yet */
    }
  }, [adapter, planId]);
  useEffect(() => {
    void loadAccounts();
    return () => {
      load.current += 1;
    };
  }, [loadAccounts]);
  if (!plan) return null;
  const parsed = Number(amount);
  const amountInvalid = enabled && !(amount.trim() !== "" && Number.isFinite(parsed) && parsed > 0);
  const accountsInvalid = enabled && ids.length === 0;
  const touch = () => {
    setDone(false);
    setError(null);
    setDirty(true);
  };
  const toggle = (id: string, on: boolean) => {
    touch();
    setIds(on ? [...ids, id] : ids.filter((x) => x !== id));
  };
  const move = (i: number, direction: number) => {
    const j = i + direction;
    if (j < 0 || j >= ids.length) return;
    const next = [...ids];
    [next[i], next[j]] = [next[j], next[i]];
    touch();
    setIds(next);
  };
  async function save() {
    if (!plan || amountInvalid || accountsInvalid) return;
    setSaving(true);
    setDone(false);
    setError(null);
    try {
      await updatePlan(plan.id, {
        cash_reserve_settings: enabled
          ? // The sweep is sent only when on, so existing settings keep their shape.
            {
              enabled: true,
              account_ids: ids,
              reserve_amount: parsed,
              ...(sweep ? { sweep_excess: true } : {}),
            }
          : plan.cash_reserve_settings
            ? { ...plan.cash_reserve_settings, enabled: false }
            : null,
      });
      setDone(true);
      setDirty(false);
    } catch {
      setError("Could not save the cash reserve. Your edits are retained; try again.");
    } finally {
      setSaving(false);
    }
  }
  const name = (id: string) => accounts.find((a) => a.id === id)?.name ?? "Account";
  return (
    <div
      style={{ display: "grid", gap: 10 }}
      data-sample-editor
      data-unsaved-changes={dirty || undefined}
      data-save-pending={saving || undefined}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <h3 style={{ margin: 0 }}>Cash reserve</h3>
        <label
          style={{ fontSize: 13, cursor: "pointer", display: "flex", alignItems: "center", gap: 6 }}
        >
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => {
              setEnabled(e.target.checked);
              touch();
            }}
          />
          Enabled
        </label>
      </div>
      <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
        Off by default. When on, withdrawals leave the reserve alone and draw on it last, only to
        cover what other accounts cannot.
      </p>
      {enabled && (
        <fieldset
          disabled={saving}
          style={{ border: 0, padding: 0, minWidth: 0, display: "grid", gap: 10 }}
        >
          <label>
            {moneyLabel("Reserve amount ($, in today's dollars)")}
            <MoneyInput
              min={0.01}
              step={0.01}
              value={amount}
              onValueChange={(value) => {
                setAmount(value);
                touch();
              }}
              aria-invalid={amountInvalid || undefined}
            />
          </label>
          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend style={{ fontSize: 13, marginBottom: 4 }}>
              Reserve accounts (checking or savings)
            </legend>
            {accounts.length === 0 && (
              <span style={helpTextStyle}>
                No checking or savings accounts found. Add one in Accounts first.
              </span>
            )}
            {accounts.map((a) => (
              <label
                key={a.id}
                style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}
              >
                <input
                  type="checkbox"
                  checked={ids.includes(a.id)}
                  onChange={(e) => toggle(a.id, e.target.checked)}
                />
                {a.name} · {fullCurrency(a.balance)}
              </label>
            ))}
          </fieldset>
          {ids.length > 1 && (
            <ol
              aria-label="Reserve spending order"
              style={{ margin: 0, paddingLeft: 20, fontSize: 13 }}
            >
              {ids.map((id, i) => (
                <li key={id}>
                  {name(id)}{" "}
                  <button
                    type="button"
                    disabled={i === 0}
                    aria-label={`Spend ${name(id)} earlier`}
                    onClick={() => move(i, -1)}
                  >
                    Earlier
                  </button>{" "}
                  <button
                    type="button"
                    disabled={i === ids.length - 1}
                    aria-label={`Spend ${name(id)} later`}
                    onClick={() => move(i, 1)}
                  >
                    Later
                  </button>
                </li>
              ))}
            </ol>
          )}
          {ids.length > 1 && (
            <span style={helpTextStyle}>Reserve accounts are spent in the order listed.</span>
          )}
          <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13 }}>
            <input
              type="checkbox"
              checked={sweep}
              onChange={(e) => {
                setSweep(e.target.checked);
                touch();
              }}
            />
            <span>
              Invest cash above the reserve each year
              <span style={{ ...helpTextStyle, display: "block" }}>
                At year end, cash in the reserve accounts beyond the reserve amount fills your
                allocation rules in order, within their annual maximums and contribution limits.
                Moving cash is not taxed; locked accounts are never drawn.
              </span>
            </span>
          </label>
          {accountsInvalid && (
            <div role="alert" style={warningStyle}>
              Choose at least one reserve account.
            </div>
          )}
          {amountInvalid && (
            <div role="alert" style={warningStyle}>
              Enter a reserve amount above zero.
            </div>
          )}
        </fieldset>
      )}
      {error && (
        <div role="alert" style={warningStyle}>
          {error}
        </div>
      )}
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving || amountInvalid || accountsInvalid}
        >
          {saving ? "Saving…" : "Save cash reserve"}
        </button>
        {done && (
          <span role="status" style={{ fontSize: 13 }}>
            Cash reserve saved.
          </span>
        )}
      </div>
    </div>
  );
}
