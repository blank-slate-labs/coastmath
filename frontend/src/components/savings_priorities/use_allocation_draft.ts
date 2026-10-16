import { useEffect, useState } from "react";
import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import { useSaveStore } from "@/stores/save_store";
import { isSaveConflict } from "@/api/save_error";
import { usePlanAccounts } from "@/utils/use_plan_accounts";
import { usCoverage } from "@/domain/intl_plan";
import type { CashFlowPriority, CashFlowPriorityCreate, PlanData } from "@/types/plan";
import { allocationProblem, priorityPayload, rankedPayload } from "./rules";

interface StoredDraft {
  items: CashFlowPriorityCreate[];
  baseline: CashFlowPriority[];
  revision: number;
}

function readDraft(draftKey: string): StoredDraft | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(draftKey) ?? "null");
    return value &&
      Array.isArray(value.items) &&
      Array.isArray(value.baseline) &&
      Number.isInteger(value.revision)
      ? (value as StoredDraft)
      : null;
  } catch {
    return null;
  }
}

/**
 * The editor's draft of a plan's allocation rules: recovered from and kept in sessionStorage
 * until saved, checked against the saved revision, and reviewed against the latest saved rules
 * when they move on underneath it.
 */
export function useAllocationDraft(plan: PlanData) {
  const draftKey = `allocation-draft:v1:${plan.user_id}:${plan.id}`;
  const [recovery] = useState(() => readDraft(draftKey));
  const [baseline, setBaseline] = useState(recovery?.baseline ?? plan.priorities);
  const [revision, setRevision] = useState(recovery?.revision ?? plan.priorities_revision ?? 0);
  const [latest, setLatest] = useState<PlanData | null>(null);
  const [storageError, setStorageError] = useState(false);
  const [recovered, setRecovered] = useState(!!recovery);
  const { adapter } = useStorage();
  const [items, setItems] = useState(() => recovery?.items ?? rankedPayload(plan.priorities));
  const [dirty, setDirty] = useState(!!recovery);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [accountRetry, setAccountRetry] = useState(0);
  const { accounts, status: accountStatus } = usePlanAccounts(adapter, plan.id, {
    refreshKey: accountRetry,
  });
  useEffect(() => {
    if (saving) return;
    if (!dirty) {
      setItems(rankedPayload(plan.priorities));
      setBaseline(plan.priorities);
      setRevision(plan.priorities_revision ?? 0);
    } else if ((plan.priorities_revision ?? 0) !== revision) setLatest(plan);
  }, [plan, dirty, saving, revision]);
  useEffect(() => {
    try {
      if (dirty) sessionStorage.setItem(draftKey, JSON.stringify({ items, baseline, revision }));
      else sessionStorage.removeItem(draftKey);
      setStorageError(false);
    } catch {
      setStorageError(true);
    }
  }, [items, baseline, revision, dirty, draftKey]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(() => {
    if (accountStatus === "error")
      setError("Could not load accounts. Retry to continue; your edits are retained.");
  }, [accountStatus]);
  async function reviewLatest(afterFailure = false) {
    try {
      const current = await adapter.fetchPlan(plan.id);
      if (!afterFailure || (current.priorities_revision ?? 0) !== revision) setLatest(current);
    } catch {
      if (!afterFailure)
        setError("Could not load the latest rules. Your draft is retained; retry when connected.");
    }
  }
  function reconcile(keepDraft: boolean) {
    if (!latest) return;
    setBaseline(latest.priorities);
    setRevision(latest.priorities_revision ?? 0);
    if (!keepDraft) setItems(rankedPayload(latest.priorities));
    // Only a retained draft needs submission; latest rules are already saved.
    setLatest(null);
    setDirty(keepDraft);
    setError("");
    setRecovered(false);
    setSaved(false);
    if (!keepDraft) useSaveStore.getState().discardRejected(`put /plans/${plan.id}/priorities`);
    if (usePlanStore.getState().plan?.id === plan.id) usePlanStore.setState({ plan: latest });
  }
  function change(next: CashFlowPriorityCreate[]) {
    setItems(next);
    setDirty(true);
    setSaved(false);
    setError("");
  }
  function edit(i: number, update: Partial<CashFlowPriorityCreate>) {
    change(items.map((p, j) => (i === j ? { ...p, ...update } : p)));
  }
  function retryAccounts() {
    setError("");
    setAccountRetry((n) => n + 1);
  }
  async function save() {
    if (latest) {
      setError("Review the changed rules before saving.");
      return;
    }
    const problem = allocationProblem(items, baseline, {
      accounts,
      liabilities: plan.liabilities ?? [],
      incomes: plan.income_streams,
      coverage: usCoverage(plan),
    });
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    setError("");
    try {
      const result = await adapter.updatePriorities(
        plan.id,
        items.map((p, i) => ({ ...p, priority_rank: i + 1 })),
        revision,
      );
      const priorities = result.items;
      setBaseline(priorities);
      setRevision(result.revision);
      setRecovered(false);
      try {
        sessionStorage.removeItem(draftKey);
      } catch {
        setStorageError(true);
      }
      setItems(priorityPayload(priorities));
      setDirty(false);
      setSaved(true);
      if (usePlanStore.getState().plan?.id === plan.id) {
        usePlanStore.setState((s) => ({
          plan: s.plan ? { ...s.plan, priorities, priorities_revision: result.revision } : null,
          simulation: null,
        }));
        await usePlanStore.getState().runSimulation(plan.id);
      }
    } catch (err) {
      setError(
        isSaveConflict(err)
          ? "These rules changed in another tab or device. Review them below before saving."
          : `Could not save allocation. ${err instanceof Error ? err.message : "Check the accounts and values."} Your edits are retained; correct the issue or review the latest rules.`,
      );
      await reviewLatest(true);
    } finally {
      setSaving(false);
    }
  }
  return {
    items,
    latest,
    dirty,
    saving,
    saved,
    error,
    storageError,
    recovered,
    accounts,
    accountsReady: accountStatus === "ready",
    change,
    edit,
    reviewLatest,
    reconcile,
    retryAccounts,
    save,
  };
}
