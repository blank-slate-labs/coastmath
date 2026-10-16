import { useState } from "react";
import type { ConnectionAccount, LedgerLinkInput } from "@/api/ledger_connections";
import { usePlanStore } from "@/stores/plan_store";
import type { Account, AccountCreate, Liability, LiabilityCreate } from "@/types/plan";
import AccountForm from "../account_form";
import LiabilityForm from "../liability_form";
import { money, muted, row, stack } from "./ledger_format";

/** Type and subtype pairs a synced account can be confirmed as. */
export const ACCOUNT_KINDS: {
  key: string;
  label: string;
  account_type: string;
  subtype: string | null;
}[] = [
  { key: "checking", label: "Checking", account_type: "DEPOSITORY", subtype: "CHECKING" },
  { key: "savings", label: "Savings", account_type: "DEPOSITORY", subtype: "SAVINGS" },
  { key: "credit_card", label: "Credit card", account_type: "CREDIT", subtype: "CREDIT_CARD" },
  { key: "mortgage", label: "Mortgage", account_type: "LOAN", subtype: "MORTGAGE" },
  { key: "loan", label: "Other loan", account_type: "LOAN", subtype: null },
  { key: "brokerage", label: "Brokerage", account_type: "INVESTMENT", subtype: "BROKERAGE" },
  { key: "401k", label: "401(k)", account_type: "INVESTMENT", subtype: "PLAN_401K" },
  { key: "ira", label: "Traditional IRA", account_type: "INVESTMENT", subtype: "IRA" },
  { key: "roth", label: "Roth IRA", account_type: "INVESTMENT", subtype: "ROTH" },
  { key: "hsa", label: "HSA", account_type: "INVESTMENT", subtype: "HSA" },
  { key: "other", label: "Other", account_type: "OTHER", subtype: null },
];

function kindOf(account: ConnectionAccount): string {
  if (!account.type_confirmed) return "";
  return (
    ACCOUNT_KINDS.find(
      (k) => k.account_type === account.account_type && k.subtype === account.subtype,
    )?.key ??
    ACCOUNT_KINDS.find((k) => k.account_type === account.account_type)?.key ??
    ""
  );
}

export interface ConnectionAccountProps {
  account: ConnectionAccount;
  planId: string;
  sharedPlan: boolean;
  planAccounts: Account[];
  planDebts: Liability[];
  busy: boolean;
  onConfirmType: (account: ConnectionAccount, accountType: string, subtype: string | null) => void;
  onLink: (account: ConnectionAccount, body: LedgerLinkInput) => void;
  onUnlink: (linkId: string) => void;
}

/** One synced account: its type confirmation and its balance link into this plan. */
export default function LedgerConnectionAccount(props: ConnectionAccountProps) {
  const { account, planId, sharedPlan, planAccounts, planDebts, busy } = props;
  const [kind, setKind] = useState(kindOf(account));
  const [linking, setLinking] = useState(false);
  const chosen = ACCOUNT_KINDS.find((k) => k.key === kind);
  const link = account.links.find((l) => l.plan_id === planId);
  const debt = account.account_type === "CREDIT" || account.account_type === "LOAN";
  const targets = debt ? planDebts : planAccounts;
  const targetName =
    link &&
    (planAccounts.find((a) => a.id === link.account_id)?.name ??
      planDebts.find((d) => d.id === link.liability_id)?.name);
  return (
    <li className="card" style={stack}>
      <div>
        <strong>{account.name}</strong>
        <div style={muted}>
          {account.institution_name}
          {account.balance != null ? ` · ${money(account.balance, account.currency ?? "USD")}` : ""}
          {account.type_confirmed ? "" : " · Type not confirmed"}
        </div>
      </div>
      <div style={row}>
        <label>
          Account type{" "}
          <select
            aria-label={`Account type for ${account.name}`}
            value={kind}
            disabled={busy}
            onChange={(e) => setKind(e.target.value)}
          >
            <option value="">Choose…</option>
            {ACCOUNT_KINDS.map((k) => (
              <option key={k.key} value={k.key}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        {chosen && kind !== kindOf(account) && (
          <button
            type="button"
            disabled={busy}
            onClick={() => props.onConfirmType(account, chosen.account_type, chosen.subtype)}
          >
            Confirm type
          </button>
        )}
      </div>
      {link ? (
        <div style={row}>
          <span style={muted}>Balance updates {targetName ?? "a planning record"}.</span>
          {link.error && <span role="alert">{link.error}</span>}
          <button type="button" disabled={busy} onClick={() => props.onUnlink(link.id)}>
            Unlink balance
          </button>
        </div>
      ) : (
        account.type_confirmed &&
        (account.blocked_reason ? (
          <p style={muted}>{account.blocked_reason}</p>
        ) : linking ? (
          <LinkForm
            account={account}
            debt={debt}
            targets={targets}
            planAccounts={planAccounts}
            planId={planId}
            sharedPlan={sharedPlan}
            busy={busy}
            onCancel={() => setLinking(false)}
            onSubmit={(body) => props.onLink(account, body)}
          />
        ) : (
          <button type="button" disabled={busy} onClick={() => setLinking(true)}>
            Link balance
          </button>
        ))
      )}
    </li>
  );
}

const NEW = "new";

/**
 * Choose an existing plan record, or create one with the editor's own form. Server refusals
 * show in the panel above while this form keeps its draft.
 */
function LinkForm({
  account,
  debt,
  targets,
  planAccounts,
  planId,
  sharedPlan,
  busy,
  onCancel,
  onSubmit,
}: {
  account: ConnectionAccount;
  debt: boolean;
  targets: (Account | Liability)[];
  planAccounts: Account[];
  planId: string;
  sharedPlan: boolean;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (body: LedgerLinkInput) => void;
}) {
  const plan = usePlanStore((s) => s.plan);
  // Capture the reviewed values; a background reload must not approve a newer balance.
  const [choices] = useState(targets);
  const [balance] = useState(account.balance);
  const [selection, setSelection] = useState("");
  const [shared, setShared] = useState(false);
  const [duplicate, setDuplicate] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const target = choices.find((c) => c.id === selection);
  const saved = target ? ("balance" in target ? target.balance : target.principal_balance) : null;
  const canCreate = balance != null && plan?.id === planId;
  const creating = canCreate && selection === NEW;
  const needsShared = sharedPlan && !debt;
  const needsDuplicate = creating && choices.length > 0;
  const acknowledged = (!needsShared || shared) && (!needsDuplicate || duplicate);
  const base = {
    plan_id: planId,
    source_revision: account.revision,
    acknowledge_shared_accounts: shared,
    acknowledge_duplicate_risk: duplicate,
  };
  if (!choices.length && !canCreate)
    return <p style={muted}>No {debt ? "debts" : "accounts"} in this plan yet.</p>;

  function createAccount(data: AccountCreate) {
    // The server refuses a taxable account without basis; say so before sending.
    if (data.account_type === "taxable_brokerage" && data.cost_basis == null) {
      setProblem("Enter the cost basis for a taxable account.");
      return;
    }
    setProblem(null);
    onSubmit({ ...base, new_account: { ...data, balance: balance! } });
  }

  return (
    <div style={stack} data-unsaved-changes="true">
      <label>
        Planning record{" "}
        <select
          aria-label="Planning record"
          value={selection}
          disabled={busy}
          onChange={(e) => {
            setSelection(e.target.value);
            setProblem(null);
          }}
        >
          <option value="">Choose…</option>
          {choices.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
          {canCreate && <option value={NEW}>New {debt ? "debt" : "account"}</option>}
        </select>
      </label>
      {saved != null && (
        <p style={muted}>
          {money(saved)} → {money(balance ?? 0)}
        </p>
      )}
      {needsShared && (
        <label>
          <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />{" "}
          Update this account in every household plan
        </label>
      )}
      {needsDuplicate && (
        <label>
          <input
            type="checkbox"
            checked={duplicate}
            onChange={(e) => setDuplicate(e.target.checked)}
          />{" "}
          This {debt ? "debt" : "account"} isn’t already in the plan
        </label>
      )}
      {problem && <p role="alert">{problem}</p>}
      {creating && plan ? (
        <fieldset
          aria-label={debt ? "New debt" : "New account"}
          disabled={busy || !acknowledged}
          style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}
        >
          {debt ? (
            <LiabilityForm
              connectedBalance={balance!}
              milestones={plan.milestones}
              accounts={planAccounts}
              realAssets={plan.real_assets}
              onCancel={onCancel}
              onSubmit={(data: LiabilityCreate) =>
                onSubmit({ ...base, new_liability: { ...data, principal_balance: balance! } })
              }
            />
          ) : (
            <AccountForm
              independent={!sharedPlan}
              planAssumptions={plan}
              milestones={plan.milestones}
              initial={
                {
                  id: "",
                  user_id: "",
                  name: account.name,
                  account_type: account.suggested_account_type ?? "other",
                  balance: balance!,
                  owner: "self",
                  beneficiary_type: "non_edb",
                  cost_basis: null,
                } as Account
              }
              connectedBalance={balance!}
              submitLabel="Add Account"
              onCancel={onCancel}
              onSubmit={createAccount}
            />
          )}
        </fieldset>
      ) : (
        <div style={row}>
          <button
            type="button"
            disabled={busy || saved == null || (needsShared && !shared)}
            onClick={() =>
              onSubmit({
                plan_id: planId,
                source_revision: account.revision,
                expected_balance: saved!,
                acknowledge_shared_accounts: shared,
                ...(debt ? { liability_id: selection } : { account_id: selection }),
              })
            }
          >
            Link
          </button>
          <button type="button" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
