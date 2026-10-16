import { useEffect, useState } from "react";
import { ledger } from "@/api/ledger";
import type { LedgerCategory, LedgerTransaction, TransactionChanges } from "@/api/ledger";
import { errorMessage } from "@/utils/error_message";
import { downloadReport } from "@/utils/projection_report";
import { money, monthLabel, muted, row, stack } from "./ledger_format";
import SuggestionBar from "./suggestion_bar";

const PAGE = 100;
// Keeps neighboring columns apart when a narrow screen squeezes the table.
const cell: React.CSSProperties = { padding: "4px" };

/** Review and correct transactions: category, exclusion and one-time flags. */
export default function TransactionReview({
  categories,
  months,
  currency,
  refreshKey,
  onChanged,
}: {
  categories: LedgerCategory[];
  months: string[];
  currency: string;
  refreshKey: number;
  onChanged: () => void;
}) {
  const [month, setMonth] = useState("");
  const [category, setCategory] = useState("");
  const [uncategorized, setUncategorized] = useState(false);
  const [similar, setSimilar] = useState(false);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<{ transactions: LedgerTransaction[]; total: number } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    ledger
      .transactions({
        month: month || undefined,
        category: category || undefined,
        uncategorized: uncategorized || undefined,
        limit: PAGE,
        offset,
      })
      .then((next) => {
        if (active) {
          setPage(next);
          setError(null);
        }
      })
      .catch((e) => {
        if (active) setError(errorMessage(e));
      });
    return () => {
      active = false;
    };
  }, [month, category, uncategorized, offset, refreshKey]);

  async function change(txn: LedgerTransaction, body: TransactionChanges, applyToSimilar = false) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await ledger.updateTransaction(
        txn.id,
        applyToSimilar ? { ...body, apply_to_similar: true } : body,
      );
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const filter = (update: () => void) => {
    update();
    setOffset(0);
  };
  const total = page?.total ?? 0;
  const paged = total > PAGE;
  const pager = (label: string) => (
    <div role="group" aria-label={label} style={row}>
      <button
        type="button"
        disabled={offset === 0}
        onClick={() => setOffset(Math.max(0, offset - PAGE))}
      >
        Newer
      </button>
      <span style={muted}>
        {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
      </span>
      <button
        type="button"
        disabled={offset + PAGE >= total}
        onClick={() => setOffset(offset + PAGE)}
      >
        Older
      </button>
    </div>
  );
  async function download() {
    if (downloading) return;
    setDownloading(true);
    setError(null);
    try {
      downloadReport(
        await ledger.exportTransactions(),
        "transactions.csv",
        "text/csv;charset=utf-8",
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setDownloading(false);
    }
  }

  // The export holds every retained transaction, whatever the filters show.
  const hasTransactions = !!page && (page.total > 0 || !!month || !!category || uncategorized);
  return (
    <section
      aria-label="Transaction review"
      style={stack}
      data-save-pending={busy ? "true" : undefined}
    >
      <div style={{ ...row, justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Transactions</h3>
        {hasTransactions && (
          <button type="button" disabled={downloading} onClick={() => void download()}>
            Download CSV
          </button>
        )}
      </div>
      <div style={row}>
        <label>
          Month{" "}
          <select value={month} onChange={(e) => filter(() => setMonth(e.target.value))}>
            <option value="">All</option>
            {months.map((key) => (
              <option key={key} value={key}>
                {monthLabel(key)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Category{" "}
          <select value={category} onChange={(e) => filter(() => setCategory(e.target.value))}>
            <option value="">All</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={uncategorized}
            onChange={(e) => filter(() => setUncategorized(e.target.checked))}
          />{" "}
          Uncategorized only
        </label>
        <label>
          <input type="checkbox" checked={similar} onChange={(e) => setSimilar(e.target.checked)} />{" "}
          Apply category to similar
        </label>
      </div>
      <SuggestionBar
        transactions={page?.transactions ?? []}
        refreshKey={refreshKey}
        onChanged={onChanged}
      />
      {error && <p role="alert">{error}</p>}
      {!page && !error && <p role="status">Loading transactions…</p>}
      {page && page.transactions.length === 0 && <p style={muted}>No transactions yet.</p>}
      {page && paged && pager("Transaction pages")}
      {page && page.transactions.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr>
              <th align="left" style={cell}>
                Date
              </th>
              <th align="left" style={cell}>
                Description
              </th>
              <th align="right" style={cell}>
                Amount
              </th>
              <th align="left" style={cell}>
                Category
              </th>
              <th style={cell}>Exclude</th>
              <th style={cell}>One-time</th>
            </tr>
          </thead>
          <tbody>
            {page.transactions.map((txn) => (
              <tr key={txn.id} data-kind={txn.kind}>
                <td style={cell}>{txn.date}</td>
                <td style={cell}>
                  {txn.merchant_name ?? txn.description}
                  <div style={muted}>
                    {txn.source_name}
                    {txn.status === "PENDING" ? " · pending" : ""}
                  </div>
                </td>
                <td align="right" style={cell}>
                  {money(-txn.amount, txn.currency ?? currency)}
                </td>
                <td style={cell}>
                  <select
                    aria-label={`Category for ${txn.description}`}
                    value={txn.category}
                    disabled={busy}
                    onChange={(e) => void change(txn, { category: e.target.value }, similar)}
                  >
                    {categories.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                  {txn.category_override && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void change(txn, { category: null })}
                    >
                      Reset
                    </button>
                  )}
                  {txn.category_source === "llm" && (
                    <>
                      <span style={muted}> Suggested </span>
                      <button
                        type="button"
                        disabled={busy}
                        aria-label={`Accept suggestion for ${txn.description}`}
                        onClick={() => void change(txn, { category: txn.category })}
                      >
                        Accept
                      </button>
                    </>
                  )}
                </td>
                <td align="center" style={cell}>
                  <input
                    type="checkbox"
                    aria-label={`Exclude ${txn.description}`}
                    checked={txn.excluded}
                    disabled={busy}
                    onChange={(e) => void change(txn, { excluded: e.target.checked })}
                  />
                </td>
                <td align="center" style={cell}>
                  <input
                    type="checkbox"
                    aria-label={`One-time ${txn.description}`}
                    checked={txn.one_time}
                    disabled={busy}
                    onChange={(e) => void change(txn, { one_time: e.target.checked })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {page && paged && pager("Transaction pages, end of list")}
    </section>
  );
}
