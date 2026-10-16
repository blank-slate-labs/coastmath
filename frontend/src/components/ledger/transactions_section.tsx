import { useCallback, useEffect, useState } from "react";
import { ledger } from "@/api/ledger";
import { ledgerImports } from "@/api/ledger_imports";
import type { LedgerAccount, LedgerCategory, LedgerMonths, LedgerRule } from "@/api/ledger";
import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import LedgerAccounts from "./ledger_accounts";
import LedgerConnectPanel from "./ledger_connect_panel";
import LedgerImportPanel from "./ledger_import_panel";
import LedgerRules from "./ledger_rules";
import { errorMessage } from "@/utils/error_message";
import { stack } from "./ledger_format";
import MonthOverview from "./month_overview";
import SpendingFeedControl from "@/components/month_compare/spending_feed_control";
import TransactionReview from "./transaction_review";

interface LedgerState {
  categories: LedgerCategory[];
  accounts: LedgerAccount[];
  rules: LedgerRule[];
  months: LedgerMonths;
}

/** Transactions from every provider: accounts, month overview, review and rules. */
export default function TransactionsSection() {
  const planId = usePlanStore((s) => s.plan?.id);
  const { sample } = useStorage();
  const [state, setState] = useState<LedgerState | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  // Bumped only when an account is removed, so the import panel drops it from its lists.
  const [removals, setRemovals] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!planId) return;
    const [categories, accounts, rules, months] = await Promise.all([
      ledger.categories(),
      ledger.accounts(),
      ledger.rules(),
      ledger.months({ plan_id: planId }),
    ]);
    setState({ categories, accounts, rules, months });
  }, [planId]);

  useEffect(() => {
    if (sample) return;
    void load().catch((e) => setError(errorMessage(e)));
  }, [load, sample, refreshKey]);

  // Corrections can re-apply a plan's connected spending; reload the plan too.
  const changed = useCallback(() => {
    setRefreshKey((key) => key + 1);
    if (!planId) return;
    usePlanStore.setState({ simulation: null });
    void usePlanStore.getState().loadPlan(planId);
  }, [planId]);

  async function run(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
      changed();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (sample || !planId) return null;
  return (
    <section aria-label="Transactions" style={stack} data-save-pending={busy ? "true" : undefined}>
      {error && <p role="alert">{error}</p>}
      <LedgerImportPanel onChanged={changed} reloadKey={removals} />
      <LedgerConnectPanel onChanged={changed} />
      {!state && !error && <p role="status">Loading transactions…</p>}
      {state && (
        <>
          <LedgerAccounts
            accounts={state.accounts}
            busy={busy}
            onToggle={(account, include) =>
              void run(() =>
                ledger.updateAccount(account.id, {
                  include_in_spending: include === account.spending_eligible ? null : include,
                }),
              )
            }
            onRemove={(account) =>
              void run(async () => {
                await ledgerImports.deleteAccount(account.id);
                setRemovals((n) => n + 1);
              })
            }
          />
          {state.months.duplicates.map((d) => (
            <p role="status" key={d.source_ids.join()}>
              {d.source_ids
                .map((id) => state.months.sources.find((s) => s.id === id)?.name ?? "An account")
                .join(" and ")}{" "}
              share {d.matched} of {d.compared} transactions. Count only one.
            </p>
          ))}
          <SpendingFeedControl accounts={state.accounts} onChanged={changed} />
          <MonthOverview months={state.months.months} currency={state.months.currency} />
          <TransactionReview
            categories={state.categories}
            months={state.months.months.map((m) => m.month).reverse()}
            currency={state.months.currency}
            refreshKey={refreshKey}
            onChanged={changed}
          />
          <LedgerRules
            rules={state.rules}
            categories={state.categories}
            busy={busy}
            onUpdate={(rule, body) => void run(() => ledger.updateRule(rule.id, body))}
            onDelete={(rule) => void run(() => ledger.deleteRule(rule.id))}
          />
        </>
      )}
    </section>
  );
}
