import { useState } from "react";
import type { LedgerImport } from "@/api/ledger_imports";
import { muted, row, stack } from "./ledger_format";
import { rangeLabel } from "./import_format";

/** Committed and reverted imports; reverting asks once before removing rows. */
export default function ImportHistory({
  imports,
  busy,
  onRevert,
}: {
  imports: LedgerImport[];
  busy: boolean;
  onRevert: (item: LedgerImport) => void;
}) {
  const [confirming, setConfirming] = useState<string | null>(null);
  return (
    <section aria-label="Import history" style={stack}>
      <h4 style={{ margin: 0 }}>Imports</h4>
      {imports.length === 0 ? (
        <p style={muted}>No imports yet.</p>
      ) : (
        <ul style={{ ...stack, listStyle: "none", padding: 0, margin: 0 }}>
          {imports.map((item) => (
            <li key={item.id} className="card" style={{ ...row, justifyContent: "space-between" }}>
              <div>
                <strong>{item.filename}</strong>
                <div style={muted}>
                  {item.source_name} · {rangeLabel(item.date_from, item.date_to)} ·{" "}
                  {item.imported_count} added
                  {item.duplicate_count ? ` · ${item.duplicate_count} already there` : ""}
                  {item.skipped_count ? ` · ${item.skipped_count} skipped` : ""}
                </div>
              </div>
              {item.status === "reverted" ? (
                <span style={muted}>Reverted</span>
              ) : confirming === item.id ? (
                <div style={row} role="group" aria-label="Confirm revert">
                  <span>
                    Removes up to {item.transaction_count} transactions no other import covers.
                    {item.revert_removes_account && ` This also removes ${item.source_name}.`} This
                    can’t be undone.
                  </span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setConfirming(null);
                      onRevert(item);
                    }}
                  >
                    Remove
                  </button>
                  <button type="button" onClick={() => setConfirming(null)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <button type="button" disabled={busy} onClick={() => setConfirming(item.id)}>
                  Revert
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
