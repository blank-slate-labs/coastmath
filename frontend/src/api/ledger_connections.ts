import { api } from "./client";
import type { AccountCreate, LiabilityCreate } from "@/types/plan";
import type { LedgerAccount } from "./ledger";

/** Provider connections and neutral balance links (backend `app/routers/ledger_connections.py`). */
export type LinkFlow = "file" | "token" | "widget";
export interface LedgerProvider {
  key: string;
  label: string;
  link_flow: LinkFlow;
  capabilities: string[];
  offered: boolean;
  reason: string | null;
  history_days: number | null;
}

export interface LedgerLink {
  id: string;
  source_id: string;
  plan_id: string;
  account_id: string | null;
  liability_id: string | null;
  last_applied_balance: number;
  error: string | null;
}
export interface ConnectionAccount extends LedgerAccount {
  balance: number | null;
  balance_updated_at: string | null;
  revision: number;
  type_confirmed: boolean;
  blocked_reason: string | null;
  suggested_account_type: string | null;
  links: LedgerLink[];
}
export type ConnectionStatus =
  | "NEW"
  | "SYNCING"
  | "ACTIVE"
  | "RETRYING"
  | "PAYMENT_REQUIRED"
  | "RECONNECT_REQUIRED"
  | "DISCONNECTED";
export interface LedgerConnection {
  id: string;
  provider: string;
  label: string;
  institution_name: string;
  status: ConnectionStatus;
  error: string | null;
  last_success_at: string | null;
  next_check_at: string | null;
  created_at: string;
  accounts: ConnectionAccount[];
}
/**
 * Links one plan record: an existing account or debt (`expected_balance` is its saved balance when
 * reviewed), or a new one created from the synced balance.
 */
export interface LedgerLinkInput {
  plan_id: string;
  source_revision: number;
  account_id?: string;
  liability_id?: string;
  expected_balance?: number;
  new_account?: AccountCreate;
  new_liability?: LiabilityCreate;
  acknowledge_shared_accounts?: boolean;
  acknowledge_duplicate_risk?: boolean;
}

export interface PlaidLinkToken {
  link_token: string;
  expiration: string | null;
}
/** A new connection from Link's public token, or `connection_id` once update mode succeeded. */
export type PlaidConnectInput =
  { public_token: string; institution_name?: string | null } | { connection_id: string };

const path = "/ledger";
export const ledgerConnections = {
  providers: (): Promise<LedgerProvider[]> => api.get(`${path}/providers`).then((r) => r.data),
  list: (): Promise<LedgerConnection[]> => api.get(`${path}/connections`).then((r) => r.data),
  /** With `connectionId`, replaces that connection's access (reconnect). */
  connectSimpleFIN: (setupToken: string, connectionId?: string): Promise<LedgerConnection> =>
    api
      .post(`${path}/connections/simplefin`, {
        setup_token: setupToken,
        ...(connectionId ? { connection_id: connectionId } : {}),
      })
      .then((r) => r.data),
  /** With `connectionId`, a token for Link's update mode on that connection. */
  plaidLinkToken: (connectionId?: string): Promise<PlaidLinkToken> =>
    api
      .post(
        `${path}/connections/plaid/link-token`,
        connectionId ? { connection_id: connectionId } : {},
      )
      .then((r) => r.data),
  connectPlaid: (body: PlaidConnectInput): Promise<LedgerConnection> =>
    api.post(`${path}/connections/plaid`, body).then((r) => r.data),
  sync: (id: string): Promise<LedgerConnection> =>
    api.post(`${path}/connections/${id}/sync`).then((r) => r.data),
  disconnect: (id: string, removeData: boolean): Promise<void> =>
    api
      .delete(`${path}/connections/${id}`, { params: { remove_data: removeData } })
      .then(() => undefined),
  link: (sourceId: string, body: LedgerLinkInput): Promise<LedgerLink> =>
    api.post(`${path}/accounts/${sourceId}/link`, body).then((r) => r.data),
  unlink: (linkId: string): Promise<void> =>
    api.delete(`${path}/links/${linkId}`).then(() => undefined),
};
