import { afterEach, expect, it } from "vitest";
import type { AxiosAdapter, InternalAxiosRequestConfig } from "axios";
import { api } from "./client";
import { ledgerConnections } from "./ledger_connections";

const original = api.defaults.adapter;
afterEach(() => {
  api.defaults.adapter = original;
});

function capture(calls: InternalAxiosRequestConfig[]): AxiosAdapter {
  return async (config) => {
    calls.push(config);
    return { data: { marker: "server" }, status: 200, statusText: "OK", headers: {}, config };
  };
}

it("routes every connection call to its path and passes bodies unchanged", async () => {
  const calls: InternalAxiosRequestConfig[] = [];
  api.defaults.adapter = capture(calls);
  expect(await ledgerConnections.providers()).toEqual({ marker: "server" });
  await ledgerConnections.list();
  await ledgerConnections.connectSimpleFIN("token-1");
  await ledgerConnections.connectSimpleFIN("token-2", "c1");
  await ledgerConnections.sync("c1");
  expect(await ledgerConnections.disconnect("c1", true)).toBeUndefined();
  await ledgerConnections.link("s1", {
    plan_id: "p1",
    source_revision: 2,
    account_id: "a1",
    expected_balance: 10,
  });
  expect(await ledgerConnections.unlink("l1")).toBeUndefined();
  expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
    "get /ledger/providers",
    "get /ledger/connections",
    "post /ledger/connections/simplefin",
    "post /ledger/connections/simplefin",
    "post /ledger/connections/c1/sync",
    "delete /ledger/connections/c1",
    "post /ledger/accounts/s1/link",
    "delete /ledger/links/l1",
  ]);
  expect(JSON.parse(calls[2].data)).toEqual({ setup_token: "token-1" });
  expect(JSON.parse(calls[3].data)).toEqual({ setup_token: "token-2", connection_id: "c1" });
  expect(calls[5].params).toEqual({ remove_data: true });
  expect(JSON.parse(calls[6].data)).toEqual({
    plan_id: "p1",
    source_revision: 2,
    account_id: "a1",
    expected_balance: 10,
  });
});

it("routes Plaid Link calls", async () => {
  const calls: InternalAxiosRequestConfig[] = [];
  api.defaults.adapter = capture(calls);
  await ledgerConnections.plaidLinkToken();
  await ledgerConnections.plaidLinkToken("c1");
  await ledgerConnections.connectPlaid({
    public_token: "public-1",
    institution_name: "Synthetic Bank",
  });
  await ledgerConnections.connectPlaid({ connection_id: "c1" });
  expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
    "post /ledger/connections/plaid/link-token",
    "post /ledger/connections/plaid/link-token",
    "post /ledger/connections/plaid",
    "post /ledger/connections/plaid",
  ]);
  expect(calls.map((c) => JSON.parse(c.data))).toEqual([
    {},
    { connection_id: "c1" },
    { public_token: "public-1", institution_name: "Synthetic Bank" },
    { connection_id: "c1" },
  ]);
});
