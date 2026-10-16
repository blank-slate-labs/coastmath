import { useEffect, useState } from "react";

import type { StorageAdapter } from "@/storage/adapter";
import { usePlanStore } from "@/stores/plan_store";
import type { Account } from "@/types/plan";

export type PlanAccountsStatus = "loading" | "ready" | "error";

export interface PlanAccounts {
  accounts: Account[];
  status: PlanAccountsStatus;
}

const NO_ACCOUNTS: Account[] = [];

/** The last read that settled, with the inputs it was made for. */
interface Settled {
  adapter: StorageAdapter;
  planId: string | undefined;
  revision: number;
  refreshKey: number | undefined;
  accounts: Account[];
  failed: boolean;
}

/**
 * The plan's accounts (the user's own accounts when `planId` is undefined),
 * read again whenever the plan store's `accountsRevision` or `refreshKey`
 * changes. The list starts empty for each plan, so a section never shows
 * another plan's accounts. A failed read keeps the plan's last list and
 * reports `error`; `status` is `loading` until the read for the current inputs
 * settles. `enabled: false` defers the read, for example until a panel opens.
 */
export function usePlanAccounts(
  adapter: StorageAdapter,
  planId: string | undefined,
  { enabled = true, refreshKey }: { enabled?: boolean; refreshKey?: number } = {},
): PlanAccounts {
  const revision = usePlanStore((s) => s.accountsRevision);
  const [settled, setSettled] = useState<Settled | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    const settle = (accounts: Account[] | null) => {
      if (!active) return;
      setSettled((prev) => {
        const samePlan = prev?.adapter === adapter && prev.planId === planId;
        const kept = samePlan ? prev.accounts : NO_ACCOUNTS;
        return {
          adapter,
          planId,
          revision,
          refreshKey,
          accounts: accounts ?? kept,
          failed: accounts === null,
        };
      });
    };
    adapter.listAccounts(planId).then(settle, () => settle(null));
    return () => {
      active = false;
    };
  }, [adapter, planId, revision, refreshKey, enabled]);

  if (!settled || settled.adapter !== adapter || settled.planId !== planId)
    return { accounts: NO_ACCOUNTS, status: "loading" };
  const current = settled.revision === revision && settled.refreshKey === refreshKey;
  return {
    accounts: settled.accounts,
    status: !current ? "loading" : settled.failed ? "error" : "ready",
  };
}
