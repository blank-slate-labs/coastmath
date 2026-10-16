import { afterEach, expect, it } from "vitest";
import { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from "axios";
import { api } from "./client";
import { ledger } from "./ledger";

const original = api.defaults.adapter;
afterEach(() => {
  api.defaults.adapter = original;
});

function capture(
  calls: InternalAxiosRequestConfig[],
  data: unknown = { marker: "server" },
): AxiosAdapter {
  return async (config) => {
    calls.push(config);
    return { data, status: 200, statusText: "OK", headers: {}, config };
  };
}

it("routes every ledger call to its path and passes bodies unchanged", async () => {
  const calls: InternalAxiosRequestConfig[] = [];
  api.defaults.adapter = capture(calls);
  await ledger.categories();
  await ledger.accounts();
  await ledger.updateAccount("a1", { include_in_spending: null });
  await ledger.transactions({ month: "2026-08", uncategorized: true });
  await ledger.transactions();
  await ledger.updateTransaction("t1", { category: "dining", apply_to_similar: true });
  await ledger.bulkUpdate(["t1", "t2"], { excluded: true });
  await ledger.rules();
  await ledger.createRule({ match_field: "merchant", pattern: "synthetic", category: "dining" });
  await ledger.updateRule("r1", { category: "groceries" });
  expect(await ledger.deleteRule("r1")).toBeUndefined();
  await ledger.months({ plan_id: "p1" });
  expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
    "get /ledger/categories",
    "get /ledger/accounts",
    "patch /ledger/accounts/a1",
    "get /ledger/transactions",
    "get /ledger/transactions",
    "patch /ledger/transactions/t1",
    "post /ledger/transactions/bulk",
    "get /ledger/rules",
    "post /ledger/rules",
    "patch /ledger/rules/r1",
    "delete /ledger/rules/r1",
    "get /ledger/months",
  ]);
  expect(JSON.parse(calls[2].data)).toEqual({ include_in_spending: null });
  expect(calls[3].params).toEqual({ month: "2026-08", uncategorized: true });
  expect(JSON.parse(calls[6].data)).toEqual({ excluded: true, ids: ["t1", "t2"] });
  expect(calls[11].params).toEqual({ plan_id: "p1" });
});

it("repeats month source IDs without brackets", async () => {
  const calls: InternalAxiosRequestConfig[] = [];
  api.defaults.adapter = capture(calls, { months: [] });
  await ledger.months({ source_ids: ["a", "b"] });
  expect(api.getUri(calls[0])).toContain("source_ids=a&source_ids=b");
  await ledger.months();
  expect(calls[1].params).toEqual({});
});

it("fetches the transaction export as text", async () => {
  const calls: InternalAxiosRequestConfig[] = [];
  api.defaults.adapter = capture(calls, "date,amount\r\n");
  expect(await ledger.exportTransactions()).toBe("date,amount\r\n");
  expect(`${calls[0].method} ${calls[0].url}`).toBe("get /ledger/transactions/export");
  expect(calls[0].responseType).toBe("text");
});

it("passes failures through to callers", async () => {
  api.defaults.adapter = async (config) => {
    throw new AxiosError("Unavailable", "ERR_NETWORK", config);
  };
  await expect(ledger.updateRule("r1", {})).rejects.toThrow("Unavailable");
});
