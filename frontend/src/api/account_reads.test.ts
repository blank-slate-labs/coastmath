import { afterEach, expect, it, vi } from "vitest";
import { AxiosHeaders, type InternalAxiosRequestConfig } from "axios";
import { api, fetchArchivedPlans, fetchPlans, listAccounts, listProgressPoints } from "./client";

const original = api.defaults.adapter;
afterEach(() => {
  api.defaults.adapter = original;
});

it("serves concurrent account reads from one request, and reads again after a write", async () => {
  const resolvers: (() => void)[] = [];
  const adapter = vi.fn(
    (config: InternalAxiosRequestConfig) =>
      new Promise((resolve) => {
        resolvers.push(() =>
          resolve({
            config,
            status: 200,
            statusText: "OK",
            headers: new AxiosHeaders(),
            data: config.method === "get" ? [{ id: "a" }] : {},
          }),
        );
      }),
  );
  api.defaults.adapter = adapter as never;
  const first = listAccounts("p");
  const second = listAccounts("p");
  const otherPlan = listAccounts("q");
  await Promise.resolve();
  await Promise.resolve();
  expect(adapter).toHaveBeenCalledTimes(2);
  // A write while a read is in flight: the next read must not reuse the older one.
  const write = api.put("/plans/p/accounts/a", {});
  // Request interceptors run on a later microtask; by then the write is on its way.
  for (let i = 0; i < 5; i++) await Promise.resolve();
  const third = listAccounts("p");
  await Promise.resolve();
  await Promise.resolve();
  expect(adapter).toHaveBeenCalledTimes(4);
  resolvers.forEach((resolve) => resolve());
  await Promise.all([first, second, otherPlan, write, third]);
  expect(await first).toBe(await second);
  // Settled reads are not cached.
  listAccounts("p");
  await Promise.resolve();
  await Promise.resolve();
  expect(adapter).toHaveBeenCalledTimes(5);
  resolvers.at(-1)!();
});

it("serves concurrent plan-list, archive and progress reads from one request each", async () => {
  const resolvers: (() => void)[] = [];
  const adapter = vi.fn(
    (config: InternalAxiosRequestConfig) =>
      new Promise((resolve) => {
        resolvers.push(() =>
          resolve({ config, status: 200, statusText: "OK", headers: new AxiosHeaders(), data: [] }),
        );
      }),
  );
  api.defaults.adapter = adapter as never;
  const reads = [
    fetchPlans(),
    fetchPlans(),
    fetchArchivedPlans(),
    fetchArchivedPlans(),
    listProgressPoints(),
    listProgressPoints(),
    listProgressPoints("2026-01-01"),
  ];
  for (let i = 0; i < 5; i++) await Promise.resolve();
  expect(
    adapter.mock.calls
      .map(
        ([config]) =>
          `${config.url}${config.params ? `?${new URLSearchParams(config.params)}` : ""}`,
      )
      .sort(),
  ).toEqual([
    "/plans/archived",
    "/plans/summaries",
    "/progress-points",
    "/progress-points?since=2026-01-01",
  ]);
  resolvers.forEach((resolve) => resolve());
  await Promise.all(reads);
});
