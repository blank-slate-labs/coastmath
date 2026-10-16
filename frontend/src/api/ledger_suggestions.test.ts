import { afterEach, expect, it } from "vitest";
import type { InternalAxiosRequestConfig } from "axios";
import { api } from "./client";
import { ledgerSuggestions } from "./ledger_suggestions";

const original = api.defaults.adapter;
afterEach(() => {
  api.defaults.adapter = original;
});

it("routes status and run to the suggestion endpoints", async () => {
  const calls: InternalAxiosRequestConfig[] = [];
  const status = { offered: true, running: false, pending: 2, last_run: null };
  api.defaults.adapter = async (config) => {
    calls.push(config);
    return { data: status, status: 200, statusText: "OK", headers: {}, config };
  };
  expect(await ledgerSuggestions.status()).toEqual(status);
  expect(await ledgerSuggestions.run()).toEqual(status);
  expect(calls.map((call) => [call.method, call.url])).toEqual([
    ["get", "/ledger/suggestions/status"],
    ["post", "/ledger/suggestions/run"],
  ]);
});
