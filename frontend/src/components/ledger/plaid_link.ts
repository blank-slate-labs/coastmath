/**
 * Plaid Link, loaded only when a customer starts a connection
 * (https://plaid.com/docs/link/web/). The script comes from Plaid's CDN, which
 * the report-only CSP allows for scripts and frames.
 *
 * Institutions that sign in through OAuth leave the page and return to
 * `/plaid/oauth`; Link then resumes with the same token
 * (https://plaid.com/docs/link/oauth/), so the token is saved before Link opens.
 */
import { ledgerConnections } from "@/api/ledger_connections";
import type { LedgerConnection } from "@/api/ledger_connections";

export const PLAID_LINK_SCRIPT = "https://cdn.plaid.com/link/v2/stable/link-initialize.js";

export interface PlaidSuccessMetadata {
  institution?: { name?: string | null } | null;
}
export interface PlaidHandler {
  open: () => void;
  destroy?: () => void;
}
export interface PlaidCreateOptions {
  token: string;
  receivedRedirectUri?: string;
  onSuccess: (publicToken: string, metadata: PlaidSuccessMetadata) => void;
  onExit: (error: unknown) => void;
}
export interface PlaidGlobal {
  create: (options: PlaidCreateOptions) => PlaidHandler;
}
declare global {
  interface Window {
    Plaid?: PlaidGlobal;
  }
}

let loading: Promise<PlaidGlobal> | null = null;

/** Adds Link's script once; a failed load can be retried. */
export function loadPlaidLink(): Promise<PlaidGlobal> {
  if (window.Plaid) return Promise.resolve(window.Plaid);
  if (loading) return loading;
  loading = new Promise<PlaidGlobal>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = PLAID_LINK_SCRIPT;
    script.async = true;
    script.onload = () => {
      if (window.Plaid) resolve(window.Plaid);
      else {
        loading = null;
        script.remove();
        reject(new Error("Plaid Link did not load. Try again."));
      }
    };
    script.onerror = () => {
      loading = null;
      script.remove();
      reject(new Error("Plaid Link did not load. Try again."));
    };
    document.head.appendChild(script);
  });
  return loading;
}

export interface PlaidLinkResult {
  publicToken: string;
  institutionName: string | null;
}

/** Opens Link; resolves with the public token, or null when the customer leaves Link. */
export async function openPlaidLink(
  token: string,
  receivedRedirectUri?: string,
): Promise<PlaidLinkResult | null> {
  const plaid = await loadPlaidLink();
  return new Promise((resolve) => {
    let handler: PlaidHandler | null = null;
    const finish = (result: PlaidLinkResult | null) => {
      handler?.destroy?.();
      resolve(result);
    };
    handler = plaid.create({
      token,
      ...(receivedRedirectUri ? { receivedRedirectUri } : {}),
      onSuccess: (publicToken, metadata) =>
        finish({ publicToken, institutionName: metadata?.institution?.name ?? null }),
      onExit: () => finish(null),
    });
    handler.open();
  });
}

/** What the OAuth return page needs to resume Link. */
export interface PlaidSession {
  linkToken: string;
  connectionId: string | null;
  savedAt: number;
}
const SESSION_KEY = "coastmath.plaid_link";
// Link tokens last at most four hours; an older session cannot resume.
const SESSION_MAX_AGE_MS = 4 * 60 * 60 * 1000;

export function savePlaidSession(linkToken: string, connectionId: string | null): void {
  try {
    window.localStorage.setItem(
      SESSION_KEY,
      JSON.stringify({ linkToken, connectionId, savedAt: Date.now() }),
    );
  } catch {
    /* Storage blocked: OAuth institutions cannot resume, others still finish in place. */
  }
}

export function clearPlaidSession(): void {
  try {
    window.localStorage.removeItem(SESSION_KEY);
  } catch {
    /* nothing saved */
  }
}

/** The saved session, removed once read; null when missing, malformed or expired. */
export function takePlaidSession(now = Date.now()): PlaidSession | null {
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
  clearPlaidSession();
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<PlaidSession>;
    if (
      typeof value.linkToken !== "string" ||
      !value.linkToken ||
      typeof value.savedAt !== "number"
    )
      return null;
    if (now - value.savedAt > SESSION_MAX_AGE_MS) return null;
    return {
      linkToken: value.linkToken,
      connectionId: typeof value.connectionId === "string" ? value.connectionId : null,
      savedAt: value.savedAt,
    };
  } catch {
    return null;
  }
}

async function finish(
  result: PlaidLinkResult | null,
  connectionId: string | null,
): Promise<LedgerConnection | null> {
  if (!result) return null;
  // Update mode keeps the Item's access token: only the connection's reconnect state changes.
  return ledgerConnections.connectPlaid(
    connectionId
      ? { connection_id: connectionId }
      : { public_token: result.publicToken, institution_name: result.institutionName },
  );
}

/** Link for a new connection, or update mode for `connectionId`; null when the customer leaves Link. */
export async function startPlaidConnection(
  connectionId: string | null = null,
): Promise<LedgerConnection | null> {
  const { link_token: token } = await ledgerConnections.plaidLinkToken(connectionId ?? undefined);
  savePlaidSession(token, connectionId);
  try {
    return await finish(await openPlaidLink(token), connectionId);
  } finally {
    clearPlaidSession();
  }
}

/** Resumes Link after an OAuth institution redirects back with `href`. */
export async function resumePlaidConnection(
  session: PlaidSession,
  href: string,
): Promise<LedgerConnection | null> {
  return finish(await openPlaidLink(session.linkToken, href), session.connectionId);
}
