import { afterEach, expect, it } from "vitest";
import type { AxiosAdapter, InternalAxiosRequestConfig } from "axios";
import { api } from "./client";
import { fileToBase64, ledgerImports } from "./ledger_imports";

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

it("routes every import call to its path and passes bodies unchanged", async () => {
  const calls: InternalAxiosRequestConfig[] = [];
  api.defaults.adapter = capture(calls);
  const file = { filename: "a.csv", content_base64: "QQ==" };
  expect(await ledgerImports.preview({ ...file, source_id: "a1" })).toEqual({ marker: "server" });
  await ledgerImports.commit({ ...file, new_account: { name: "Card", account_type: "CREDIT" } });
  await ledgerImports.list();
  await ledgerImports.list("a1");
  await ledgerImports.revert("i1");
  await ledgerImports.revert("i2", { removeAccount: true });
  expect(await ledgerImports.deleteAccount("a1")).toBeUndefined();
  expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
    "post /ledger/imports/preview",
    "post /ledger/imports",
    "get /ledger/imports",
    "get /ledger/imports",
    "delete /ledger/imports/i1",
    "delete /ledger/imports/i2",
    "delete /ledger/accounts/a1",
  ]);
  expect(JSON.parse(calls[0].data)).toEqual({ ...file, source_id: "a1" });
  expect(calls[2].params).toEqual({});
  expect(calls[3].params).toEqual({ source_id: "a1" });
  expect(calls[4].params).toEqual({});
  expect(calls[5].params).toEqual({ remove_account: true });
});

it("encodes file bytes as base64", async () => {
  const bytes = new Uint8Array(70000).map((_, i) => i % 251);
  const encoded = await fileToBase64(new Blob([bytes]));
  expect(Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0))).toEqual(bytes);
  expect(await fileToBase64(new Blob(["Date,Amount\n"]))).toBe(btoa("Date,Amount\n"));
});

it("reports an unreadable file", async () => {
  const original = window.FileReader;
  class Failing {
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    readAsDataURL() {
      this.onerror?.();
    }
  }
  window.FileReader = Failing as unknown as typeof FileReader;
  try {
    await expect(fileToBase64(new Blob(["x"]))).rejects.toThrow("could not be read");
  } finally {
    window.FileReader = original;
  }
});
