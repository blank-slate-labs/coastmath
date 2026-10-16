import { afterAll, beforeEach, expect, it, vi } from "vitest";
import axios, { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from "axios";
import { useSaveStore } from "@/stores/save_store";
import type { StorageAdapter } from "./adapter";

const originalAdapter = axios.defaults.adapter;
let response: unknown;
let failure: "network" | "contract" | null;
const requests: InternalAxiosRequestConfig[] = [];
axios.defaults.adapter = async (config) => {
  requests.push(config);
  if (failure === "network") throw new AxiosError("Network unavailable", "ERR_NETWORK", config);
  const reply = {
    data: response,
    status: 200,
    statusText: "OK",
    config,
    headers: new AxiosHeaders(),
  };
  if (failure === "contract")
    throw new AxiosError("Conflict", "ERR_BAD_REQUEST", config, undefined, {
      ...reply,
      status: 409,
      data: { error: { code: "CONFLICT", message: "Review latest saved rules", details: [] } },
    });
  return reply;
};
const { ApiStorageAdapter } = await import("./adapter");
const client = await import("@/api/client");
const adapter = new ApiStorageAdapter();
afterAll(() => {
  axios.defaults.adapter = originalAdapter;
  vi.useRealTimers();
});
beforeEach(() => {
  requests.length = 0;
  response = { id: "saved", name: "Saved by server" };
  failure = null;
  useSaveStore.setState({ pending: 0, failed: [], lastSavedAt: null });
});
const call = (method: keyof StorageAdapter, args: unknown[]) =>
  (adapter[method] as (...args: unknown[]) => Promise<unknown>)(...args);
const resources = [
  ["Plan", "Plans", "/plans", []],
  ["Account", "Accounts", "/accounts", []],
  ["Milestone", "Milestones", "/plans/p/milestones", ["p"]],
  ["Income", "Incomes", "/plans/p/incomes", ["p"]],
  ["Expense", "Expenses", "/plans/p/expenses", ["p"]],
  ["Assumption", "Assumptions", "/plans/p/assumptions", ["p"]],
  ["Charity", "Charities", "/plans/p/charities", ["p"]],
  ["RealAsset", "RealAssets", "/plans/p/real-assets", ["p"]],
  ["Liability", "Liabilities", "/plans/p/liabilities", ["p"]],
] as const;
for (const [singular, plural, path, scope] of resources) {
  for (const operation of ["list", "create", "update", "delete"] as const) {
    const method =
      `${operation === "list" && singular === "Plan" ? "fetch" : operation}${operation === "list" ? plural : singular}` as keyof StorageAdapter;
    const body = {
      name: "Draft",
      ...(singular === "Account" ? { account_type: "savings", balance: 1000 } : {}),
      ...(singular === "Plan" && operation === "create" ? { client_id: "owned-client" } : {}),
    };
    const args =
      operation === "list"
        ? [...scope]
        : operation === "create"
          ? [...scope, body]
          : operation === "update"
            ? [...scope, "item", body]
            : [...scope, "item"];
    it(`${method} preserves the HTTP contract and server response`, async () => {
      if (operation === "list") response = [{ id: "saved", name: "Server record" }];
      const result = await call(method, args);
      expect(result).toEqual(operation === "delete" ? undefined : response);
      expect(requests).toHaveLength(1);
      const request = requests[0];
      expect(request.url).toBe(
        path +
          (singular === "Plan" && operation === "list"
            ? "/summaries"
            : operation === "update" || operation === "delete"
              ? "/item"
              : ""),
      );
      expect(request.method).toBe(
        operation === "list"
          ? "get"
          : operation === "create"
            ? "post"
            : operation === "update"
              ? singular === "Charity"
                ? "patch"
                : "put"
              : "delete",
      );
      expect(request.baseURL).toBe("/api");
      expect(request.withCredentials).toBe(true);
      expect(request.headers.get("Content-Type")).toBe("application/json");
      if (operation === "create" || operation === "update")
        expect(JSON.parse(request.data)).toEqual(body);
    });
  }
}
const cases: [keyof StorageAdapter, unknown[], string, string, unknown?, unknown?][] = [
  ["fetchPlan", ["p"], "get", "/plans/p"],
  ["listPriorities", ["p"], "get", "/plans/p/priorities"],
  [
    "updatePriorities",
    ["p", [{ priority_rank: 1 }], 7],
    "put",
    "/plans/p/priorities",
    { items: [{ priority_rank: 1 }], expected_revision: 7 },
  ],
  ["listDrawdownOrder", ["p"], "get", "/plans/p/drawdown-order"],
  [
    "updateDrawdownOrder",
    ["p", [{ account_id: "a", drawdown_rank: 1 }]],
    "put",
    "/plans/p/drawdown-order",
    { items: [{ account_id: "a", drawdown_rank: 1 }] },
  ],
  ["listProgressPoints", [], "get", "/progress-points"],
  [
    "listProgressPoints",
    ["2026-01-01"],
    "get",
    "/progress-points",
    undefined,
    { since: "2026-01-01" },
  ],
  [
    "createProgressPoint",
    [{ date: "2026-01-01", net_worth: 123 }],
    "post",
    "/progress-points",
    { date: "2026-01-01", net_worth: 123 },
  ],
  ["deleteProgressPoint", ["point"], "delete", "/progress-points/point"],
  ["runSimulation", ["p"], "post", "/plans/p/simulate"],
  [
    "runStressTest",
    ["p", 1929],
    "post",
    "/plans/p/simulate",
    null,
    { historical_start_year: 1929 },
  ],
  ["fetchCompare", ["p", "base"], "post", "/plans/p/compare", { baseline_plan_id: "base" }],
  ["getMe", [], "get", "/auth/me"],
  ["logout", [], "post", "/auth/logout"],
  ["getAmortizationSchedule", ["p", "loan"], "get", "/plans/p/liabilities/loan/amortization"],
  ["duplicatePlan", ["p"], "post", "/plans/p/duplicate"],
  ["createScenario", ["p"], "post", "/plans/p/duplicate", { as_scenario: true }],
  [
    "createScenario",
    ["p", "Retire at 55"],
    "post",
    "/plans/p/duplicate",
    { as_scenario: true, name: "Retire at 55" },
  ],
  ["fetchInheritance", ["s"], "get", "/plans/s/inheritance"],
  [
    "resetInheritance",
    ["s", { kind: "income", row_id: "r", fields: ["annual_amount"] }],
    "post",
    "/plans/s/inheritance/reset",
    { kind: "income", row_id: "r", fields: ["annual_amount"] },
  ],
  [
    "resetInheritance",
    ["s", { kind: "plan", fields: ["life_expectancy"] }],
    "post",
    "/plans/s/inheritance/reset",
    { kind: "plan", fields: ["life_expectancy"] },
  ],
  [
    "resetInheritance",
    ["s", { kind: "priorities", expected_revision: 7 }],
    "post",
    "/plans/s/inheritance/reset",
    { kind: "priorities", expected_revision: 7 },
  ],
  [
    "restoreInheritance",
    ["s", { kind: "expense", parent_row_id: "m" }],
    "post",
    "/plans/s/inheritance/restore",
    { kind: "expense", parent_row_id: "m" },
  ],
  ["syncInheritance", ["s"], "post", "/plans/s/inheritance/sync"],
  ["detachScenario", ["s"], "post", "/plans/s/detach"],
  [
    "runMonteCarlo",
    ["p"],
    "post",
    "/plans/p/monte-carlo",
    { n_trials: 1000, block_size_min: 3, block_size_max: 7 },
  ],
  [
    "runMonteCarlo",
    ["p", 100, { block_size_min: 10, block_size_max: 12, seed: 42 }],
    "post",
    "/plans/p/monte-carlo",
    { n_trials: 100, block_size_min: 10, block_size_max: 12, seed: 42 },
  ],
  [
    "runMonteCarlo",
    ["p", 20, { seed: 42, calibrate_to_plan: false, failure_mode: "net_worth" }],
    "post",
    "/plans/p/monte-carlo",
    {
      n_trials: 20,
      block_size_min: 3,
      block_size_max: 7,
      seed: 42,
      calibrate_to_plan: false,
      failure_mode: "net_worth",
    },
  ],
];
it.each(cases)(
  "%s sends its computation/bulk/auth contract",
  async (method, args, verb, url, body, params) => {
    response =
      method === "listPriorities"
        ? { items: [{ id: "priority" }], revision: 8 }
        : { id: "result", revision: 8 };
    const result = await call(method, args);
    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({ method: verb, url });
    expect(requests[0].data === undefined ? undefined : JSON.parse(requests[0].data)).toEqual(body);
    expect(requests[0].params).toEqual(params);
    expect(result).toEqual(
      method === "logout" || verb === "delete"
        ? undefined
        : method === "listPriorities"
          ? { items: [{ id: "priority" }] }.items
          : response,
    );
  },
);
it.each(["network", "contract"] as const)(
  "propagates %s errors and retains failed save status until retry",
  async (kind) => {
    failure = kind;
    await expect(adapter.updatePriorities("p", [], 7)).rejects.toThrow(
      kind === "network" ? "Check saved values before retrying" : "Review latest saved rules",
    );
    expect(useSaveStore.getState().failed).toEqual(["put /plans/p/priorities"]);
    expect(useSaveStore.getState().pending).toBe(0);
    failure = null;
    response = { items: [], revision: 8 };
    expect(await adapter.updatePriorities("p", [], 7)).toEqual(response);
    expect(useSaveStore.getState().failed).toEqual([]);
    expect(JSON.parse(requests[1].data).expected_revision).toBe(7);
  },
);
it("tracks liability failures and recovery in the shared save indicator", async () => {
  failure = "contract";
  await expect(adapter.updateLiability("p", "loan", { principal_balance: 200 })).rejects.toThrow(
    "Review latest saved rules",
  );
  expect(useSaveStore.getState().failed).toEqual(["put /plans/p/liabilities/loan"]);
  failure = null;
  await adapter.updateLiability("p", "loan", { principal_balance: 200 });
  expect(useSaveStore.getState().failed).toEqual([]);
  expect(requests[1].headers.get("X-Client-Date")).toBe(client.localCalendarDate());
});
it("uses local calendar fields, including padded single digit months and days", () => {
  expect(client.localCalendarDate(new Date(2026, 0, 2, 23))).toBe("2026-01-02");
  expect(client.localCalendarDate(new Date(2026, 11, 31))).toBe("2026-12-31");
  expect(client.localCalendarDate()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
});

it("resolves personal ownership per session before creating an independent plan", async () => {
  await adapter.createPlan({ name: "Personal", birth_year: 1990 });
  expect(requests.map((r) => r.url)).toEqual(["/clients/personal", "/plans"]);
  expect(JSON.parse(requests[1].data)).toEqual({
    name: "Personal",
    birth_year: 1990,
    client_id: "saved",
  });
  requests.length = 0;
  response = { id: "another-workspace" };
  await adapter.createPlan({ name: "After sign-in", birth_year: 1990 });
  expect(JSON.parse(requests[1].data).client_id).toBe("another-workspace");
});
it("never falls back to legacy creation after workspace failure", async () => {
  failure = "network";
  await expect(adapter.createPlan({ name: "Personal", birth_year: 1990 })).rejects.toThrow();
  expect(requests.map((r) => r.url)).toEqual(["/clients/personal"]);
});
it("compares withdrawal strategies without changing the plan", async () => {
  const body = {
    methods: ["constant_dollar" as const],
    initial_rate: 0.04,
    start_milestone_id: "m",
    start_age: null,
    monte_carlo_trials: 0,
    seed: 42,
  };
  await adapter.compareWithdrawalStrategies("p", body);
  expect(requests.map((r) => [r.method, r.url])).toEqual([
    ["post", "/plans/p/withdrawal-strategies/compare"],
  ]);
  expect(JSON.parse(requests[0].data)).toEqual(body);
});
