import { useState } from "react";
import type { LedgerAccount } from "@/api/ledger";
import { muted, row, stack } from "./ledger_format";

/** Every ledger account with its spending toggle; file accounts can be removed after one confirmation. */
export default function LedgerAccounts({
  accounts,
  busy,
  onToggle,
  onRemove,
}: {
  accounts: LedgerAccount[];
  busy: boolean;
  onToggle: (account: LedgerAccount, include: boolean) => void;
  onRemove: (account: LedgerAccount) => void;
}) {
  const [confirming, setConfirming] = useState<string | null>(null);
  return (
    <section aria-label="Transaction accounts" style={stack}>
      <h3 style={{ margin: 0 }}>Accounts</h3>
      {accounts.length === 0 ? (
        <p style={muted}>No accounts yet.</p>
      ) : (
        <ul style={{ ...stack, listStyle: "none", padding: 0, margin: 0 }}>
          {accounts.map((account) => (
            <li
              key={account.id}
              className="card"
              style={{
                display: "flex",
                gap: 12,
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <div>
                <strong>
                  {account.name}
                  {account.mask ? ` ··${account.mask}` : ""}
                </strong>
                <div style={muted}>
                  {account.institution_name} ·{" "}
                  {(account.subtype ?? account.account_type).replace(/_/g, " ").toLowerCase()} ·{" "}
                  {account.transaction_count} transactions
                </div>
              </div>
              <div style={row}>
                <label>
                  <input
                    type="checkbox"
                    checked={account.counts_toward_spending}
                    disabled={busy}
                    onChange={(e) => onToggle(account, e.target.checked)}
                  />{" "}
                  Count spending
                </label>
                {/* Only imported accounts: synced ones leave through their connection. */}
                {account.provider === "file" && confirming !== account.id && (
                  <button
                    type="button"
                    disabled={busy}
                    aria-label={`Remove ${account.name}`}
                    onClick={() => setConfirming(account.id)}
                  >
                    Remove
                  </button>
                )}
              </div>
              {account.provider === "file" && confirming === account.id && (
                <div
                  style={{ ...row, flexBasis: "100%" }}
                  role="group"
                  aria-label={`Confirm removing ${account.name}`}
                >
                  <span>
                    Deletes its imports, its rules and {account.transaction_count} transactions.
                    This can’t be undone.
                  </span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      setConfirming(null);
                      onRemove(account);
                    }}
                  >
                    Remove account
                  </button>
                  <button type="button" onClick={() => setConfirming(null)}>
                    Cancel
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
