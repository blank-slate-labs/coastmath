import { useEffect, useState } from "react";
import { ledger } from "@/api/ledger";
import type { LedgerTransaction } from "@/api/ledger";
import { ledgerSuggestions } from "@/api/ledger_suggestions";
import type { SuggestionStatus } from "@/api/ledger_suggestions";
import { errorMessage } from "@/utils/error_message";
import { row } from "./ledger_format";

/** Run LLM suggestions (when the deployment offers them) and accept every visible suggestion. */
export default function SuggestionBar({
  transactions,
  refreshKey,
  onChanged,
}: {
  transactions: LedgerTransaction[];
  refreshKey: number;
  onChanged: () => void;
}) {
  const [status, setStatus] = useState<SuggestionStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    // Suggestions are optional: an unavailable status simply hides the run button.
    ledgerSuggestions
      .status()
      .then((next) => {
        if (active) setStatus(next);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [refreshKey]);

  const suggested = transactions.filter((txn) => txn.category_source === "llm");

  async function act(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const run = () =>
    act(async () => {
      setRunning(true);
      const next = await ledgerSuggestions.run().finally(() => setRunning(false));
      setStatus(next);
      if (next.last_run?.status === "failed") setError(next.last_run.message);
      if (next.last_run?.suggested) onChanged();
    });

  const acceptAll = () =>
    act(async () => {
      const byCategory = new Map<string, string[]>();
      for (const txn of suggested)
        byCategory.set(txn.category, [...(byCategory.get(txn.category) ?? []), txn.id]);
      for (const [category, ids] of byCategory) await ledger.bulkUpdate(ids, { category });
      onChanged();
    });

  if (!status?.offered && suggested.length === 0) return null;
  return (
    <div style={row} data-save-pending={busy ? "true" : undefined}>
      {status?.offered && (
        <button
          type="button"
          disabled={busy || status.running || !status.pending}
          onClick={() => void run()}
        >
          {running ? "Suggesting…" : `Suggest categories (${status.pending ?? 0})`}
        </button>
      )}
      {suggested.length > 0 && (
        <button type="button" disabled={busy} onClick={() => void acceptAll()}>
          Accept {suggested.length} suggested
        </button>
      )}
      {error && <span role="alert">{error}</span>}
    </div>
  );
}
