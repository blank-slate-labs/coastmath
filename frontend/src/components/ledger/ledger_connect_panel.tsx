import { useCallback, useEffect, useId, useRef, useState } from "react";
import { ledger } from "@/api/ledger";
import { ledgerConnections } from "@/api/ledger_connections";
import type {
  ConnectionAccount,
  LedgerConnection,
  LedgerLinkInput,
  LedgerProvider,
} from "@/api/ledger_connections";
import { extensions } from "@/extensions";
import { useStorage } from "@/storage/context";
import { useAuthStore } from "@/stores/auth_store";
import { usePlanStore } from "@/stores/plan_store";
import type { Account, Liability } from "@/types/plan";
import { FormModal } from "../form_modal";
import LedgerConnectionAccount from "./ledger_connection_account";
import { errorMessage } from "@/utils/error_message";
import { muted, row, stack } from "./ledger_format";
import { startPlaidConnection } from "./plaid_link";

export interface LedgerPanelProps {
  onChanged: () => void;
}

const POLL_MS = 15000;
const PENDING = new Set(["NEW", "SYNCING"]);

function statusText(connection: LedgerConnection): string {
  switch (connection.status) {
    case "NEW":
      return "Waiting for first sync";
    case "SYNCING":
      return "Syncing";
    case "RETRYING":
      return "Retrying";
    case "PAYMENT_REQUIRED":
      return "Payment needed at your bridge";
    case "RECONNECT_REQUIRED":
      return "Reconnect needed";
    default:
      return connection.last_success_at
        ? `Synced ${new Date(connection.last_success_at).toLocaleString()}`
        : "Synced";
  }
}

/** Synced providers (SimpleFIN, Plaid): connect, sync, reconnect, disconnect, confirm types and link balances. */
export default function LedgerConnectPanel({ onChanged }: LedgerPanelProps) {
  const plan = usePlanStore((s) => s.plan);
  const { adapter } = useStorage();
  // An access policy may limit linking, reconnecting and syncing; reads and disconnects stay available.
  const access = extensions.access;
  const linkingLocked = useAuthStore((s) => !!access?.locked(s.user, "bank_linking"));
  const [providers, setProviders] = useState<LedgerProvider[]>([]);
  const [connections, setConnections] = useState<LedgerConnection[]>([]);
  const [planAccounts, setPlanAccounts] = useState<Account[]>([]);
  const [planDebts, setPlanDebts] = useState<Liability[]>([]);
  const [token, setToken] = useState("");
  const [reconnecting, setReconnecting] = useState<LedgerConnection | null>(null);
  const [removing, setRemoving] = useState<LedgerConnection | null>(null);
  const [removeData, setRemoveData] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A refused setup token, shown under its field.
  const [tokenError, setTokenError] = useState<string | null>(null);
  const tokenErrorId = useId();
  const busyRef = useRef(false);
  const planId = plan?.id;

  const load = useCallback(async () => {
    if (!planId) return;
    const [offered, saved] = await Promise.all([
      ledgerConnections.providers(),
      ledgerConnections.list(),
    ]);
    setProviders(offered);
    setConnections(saved);
    if (!saved.length) return;
    // Plan records are only needed to link balances.
    const [accounts, debts] = await Promise.all([
      adapter.listAccounts(planId),
      adapter.listLiabilities(planId),
    ]);
    setPlanAccounts(accounts);
    setPlanDebts(debts);
  }, [planId, adapter]);

  useEffect(() => {
    void load().catch((e) => setError(errorMessage(e)));
  }, [load]);

  const pending = connections.some((c) => PENDING.has(c.status));
  const wasPending = useRef(false);
  useEffect(() => {
    // A finished sync brings new transactions: refresh the section once.
    if (wasPending.current && !pending) onChanged();
    wasPending.current = pending;
    if (!pending) return;
    const timer = window.setInterval(() => {
      void load().catch((e) => setError(errorMessage(e)));
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [pending, load, onChanged]);

  async function run(
    action: () => Promise<unknown>,
    changesPlan = false,
    report: (message: string) => void = setError,
  ) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    setTokenError(null);
    try {
      await action();
      await load();
      if (changesPlan) onChanged();
    } catch (e) {
      if (!extensions.api?.isExplained?.(e)) report(errorMessage(e));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  /** Runs a linking action, or explains why the account may not. */
  function link(action: () => void) {
    if (linkingLocked) access?.explain("bank_linking");
    else action();
  }
  const lock =
    linkingLocked && access ? (
      <>
        <access.LockGlyph size={13} />{" "}
      </>
    ) : null;

  const simplefin = providers.find((p) => p.key === "simplefin");
  const plaid = providers.find((p) => p.key === "plaid");
  if (!plan || (!simplefin?.offered && !plaid?.offered && connections.length === 0)) return null;
  const submitToken = () =>
    run(
      async () => {
        await ledgerConnections.connectSimpleFIN(token.trim(), reconnecting?.id);
        setToken("");
        setReconnecting(null);
      },
      false,
      setTokenError,
    );

  return (
    <section
      aria-label="Synced accounts"
      style={stack}
      data-save-pending={busy ? "true" : undefined}
    >
      <h3 style={{ margin: 0 }}>Synced accounts</h3>
      {error && <p role="alert">{error}</p>}
      {linkingLocked && access && (plaid?.offered || simplefin?.offered) && (
        <access.LockedFeature feature="bank_linking" />
      )}
      {!linkingLocked && plaid?.offered && (
        <div style={row}>
          <button
            type="button"
            disabled={busy}
            onClick={() => void run(() => startPlaidConnection())}
          >
            Connect with Plaid
          </button>
        </div>
      )}
      {!linkingLocked && simplefin?.offered && (
        <form
          style={row}
          onSubmit={(e) => {
            e.preventDefault();
            if (token.trim()) void submitToken();
          }}
        >
          <label>
            {reconnecting
              ? `New setup token for ${reconnecting.institution_name}`
              : "SimpleFIN setup token"}{" "}
            <input
              type="password"
              autoComplete="off"
              value={token}
              disabled={busy}
              aria-invalid={tokenError ? true : undefined}
              aria-describedby={tokenError ? tokenErrorId : undefined}
              onChange={(e) => {
                setToken(e.target.value);
                setTokenError(null);
              }}
            />
          </label>
          <button type="submit" disabled={busy || !token.trim()}>
            {reconnecting ? "Reconnect" : "Connect"}
          </button>
          {reconnecting && (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setReconnecting(null);
                setToken("");
                setTokenError(null);
              }}
            >
              Cancel
            </button>
          )}
          {tokenError && (
            <p
              id={tokenErrorId}
              role="alert"
              className="field-error"
              style={{ margin: 0, flexBasis: "100%" }}
            >
              {tokenError}
            </p>
          )}
        </form>
      )}
      {connections.map((connection) => (
        <article
          key={connection.id}
          className="card"
          style={stack}
          aria-label={`${connection.label}: ${connection.institution_name}`}
        >
          <div style={{ ...row, justifyContent: "space-between" }}>
            <div>
              <strong>{connection.institution_name}</strong>
              <div style={muted}>
                {connection.label} · {statusText(connection)}
              </div>
            </div>
            <div style={row}>
              {connection.status !== "RECONNECT_REQUIRED" && (
                <button
                  type="button"
                  disabled={busy || PENDING.has(connection.status)}
                  onClick={() => link(() => void run(() => ledgerConnections.sync(connection.id)))}
                >
                  {lock}Sync now
                </button>
              )}
              {connection.provider === "simplefin" && simplefin?.offered && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    link(() => {
                      setReconnecting(connection);
                      setToken("");
                      setTokenError(null);
                    })
                  }
                >
                  {lock}Reconnect
                </button>
              )}
              {connection.provider === "plaid" &&
                plaid?.offered &&
                connection.status === "RECONNECT_REQUIRED" && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => link(() => void run(() => startPlaidConnection(connection.id)))}
                  >
                    {lock}Reconnect
                  </button>
                )}
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setRemoving(connection);
                  setRemoveData(false);
                }}
              >
                Disconnect
              </button>
            </div>
          </div>
          {connection.error && (
            <p role="status" style={muted}>
              {connection.error}
            </p>
          )}
          {connection.accounts.length > 0 && (
            <ul style={{ ...stack, listStyle: "none", padding: 0, margin: 0 }}>
              {connection.accounts.map((account) => (
                <LedgerConnectionAccount
                  key={`${account.id}:${account.revision}`}
                  account={account}
                  planId={plan.id}
                  sharedPlan={!plan.client_id}
                  planAccounts={planAccounts}
                  planDebts={planDebts}
                  busy={busy}
                  onConfirmType={(item: ConnectionAccount, accountType, subtype) =>
                    void run(
                      () => ledger.updateAccount(item.id, { account_type: accountType, subtype }),
                      true,
                    )
                  }
                  onLink={(item: ConnectionAccount, body: LedgerLinkInput) =>
                    void run(() => ledgerConnections.link(item.id, body), true)
                  }
                  onUnlink={(linkId) => void run(() => ledgerConnections.unlink(linkId), true)}
                />
              ))}
            </ul>
          )}
        </article>
      ))}
      <FormModal
        open={!!removing}
        title="Disconnect?"
        onClose={() => {
          if (!busy) setRemoving(null);
        }}
      >
        <p>
          Syncing stops and the saved access is deleted. Linked balances keep their last values.
        </p>
        <label>
          <input
            type="checkbox"
            checked={removeData}
            disabled={busy}
            onChange={(e) => setRemoveData(e.target.checked)}
          />{" "}
          Also delete these accounts and their transactions
        </label>
        {removeData && <p role="alert">Deleted transactions cannot be restored.</p>}
        <div style={row}>
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                if (removing) await ledgerConnections.disconnect(removing.id, removeData);
                setRemoving(null);
              }, true)
            }
          >
            Disconnect
          </button>
          <button type="button" disabled={busy} onClick={() => setRemoving(null)}>
            Cancel
          </button>
        </div>
      </FormModal>
    </section>
  );
}
