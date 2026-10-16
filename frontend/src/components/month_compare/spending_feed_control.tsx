import { useCallback, useEffect, useState } from "react";
import type { LedgerAccount } from "@/api/ledger";
import { spendingFeeds } from "@/api/spending_models";
import type { SpendingFeedState } from "@/api/spending_models";
import { money, muted, row, stack } from "@/components/ledger/ledger_format";
import { errorMessage } from "@/utils/error_message";
import { usePlanStore } from "@/stores/plan_store";
import { monthsText } from "./month_format";

function accountName(account: LedgerAccount): string {
  return `${account.name}${account.mask ? ` ··${account.mask}` : ""}`;
}

/** Turn the plan's spending from transactions on or off and choose its accounts. */
export default function SpendingFeedControl({
  accounts,
  onChanged,
}: {
  accounts: LedgerAccount[];
  onChanged: () => void;
}) {
  const planId = usePlanStore((s) => s.plan?.id);
  const currency = usePlanStore((s) => s.plan?.currency) ?? "USD";
  const planType = usePlanStore((s) => s.plan?.plan_type);
  const hasExpenses = usePlanStore((s) => (s.plan?.expenses?.length ?? 0) > 0);
  const [feed, setFeed] = useState<SpendingFeedState | null>(null);
  const [chosen, setChosen] = useState<string[] | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!planId) return;
    setFeed(await spendingFeeds.get(planId));
  }, [planId]);

  useEffect(() => {
    setFeed(null);
    setChosen(null);
    setError(null);
    void load().catch((e) => setError(errorMessage(e)));
  }, [load]);

  if (!planId) return null;
  if (!feed) return error ? <p role="alert">{error}</p> : null;

  const listed = accounts.filter((a) => a.counts_toward_spending || feed.source_ids.includes(a.id));
  const selected =
    chosen ??
    (feed.active
      ? feed.source_ids
      : listed.filter((a) => a.counts_toward_spending).map((a) => a.id));
  const needsAck = !feed.active && hasExpenses;

  async function run(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
      setChosen(null);
      await load();
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-label="Plan spending"
      className="card"
      style={stack}
      data-save-pending={busy ? "true" : undefined}
    >
      <h3 style={{ margin: 0 }}>Plan spending</h3>
      {planType && planType !== "NOW" && <p style={muted}>Updates Now plans only.</p>}
      {feed.active && (
        <dl style={{ ...row, gap: 24, margin: 0 }}>
          <div>
            <dt style={muted}>Basis</dt>
            <dd style={{ margin: 0 }}>
              {feed.basis === "months" ? monthsText(feed.basis_months) : "Recent months"}
            </dd>
          </div>
          <div>
            <dt style={muted}>Essential / yr</dt>
            <dd style={{ margin: 0 }}>
              {feed.annual_essential == null ? "—" : money(feed.annual_essential, currency)}
            </dd>
          </div>
          <div>
            <dt style={muted}>Discretionary / yr</dt>
            <dd style={{ margin: 0 }}>
              {feed.annual_discretionary == null ? "—" : money(feed.annual_discretionary, currency)}
            </dd>
          </div>
        </dl>
      )}
      {feed.error && <p role="alert">{feed.error}</p>}
      {error && <p role="alert">{error}</p>}
      <fieldset
        style={{ ...stack, gap: 4, border: 0, padding: 0, margin: 0 }}
        disabled={busy || planType !== "NOW"}
      >
        <legend style={muted}>Accounts</legend>
        {listed.length === 0 && <p style={{ ...muted, margin: 0 }}>No spending accounts yet.</p>}
        {listed.map((account) => (
          <label key={account.id}>
            <input
              type="checkbox"
              checked={selected.includes(account.id)}
              onChange={(e) =>
                setChosen(
                  e.target.checked
                    ? [...selected, account.id]
                    : selected.filter((id) => id !== account.id),
                )
              }
            />{" "}
            {accountName(account)}
          </label>
        ))}
        {needsAck && (
          <label>
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
            />{" "}
            This plan’s existing expenses won’t double-count this spending.
          </label>
        )}
        <div style={row}>
          <button
            type="button"
            className="btn-primary"
            disabled={selected.length === 0 || (needsAck && !acknowledged)}
            onClick={() =>
              void run(() =>
                spendingFeeds.put(planId, {
                  source_ids: selected,
                  acknowledge_existing_expenses: acknowledged,
                  basis: feed.basis,
                  months: feed.basis === "months" ? feed.basis_months : [],
                }),
              )
            }
          >
            {feed.active ? "Update accounts" : "Use for plan spending"}
          </button>
          {feed.active && (
            <button type="button" onClick={() => void run(() => spendingFeeds.stop(planId))}>
              Turn off
            </button>
          )}
        </div>
        {feed.active && <p style={muted}>Turning off keeps both expenses at their last amounts.</p>}
      </fieldset>
    </section>
  );
}
