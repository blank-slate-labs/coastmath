import { beforeEach, expect, it } from "vitest";
import { AxiosError, AxiosHeaders, type AxiosAdapter } from "axios";
import { api } from "./client";
import { useSaveStore } from "@/stores/save_store";
import { usePlanStore } from "@/stores/plan_store";
import { makePlan } from "@/test_support/plan_builder";

beforeEach(() => useSaveStore.setState(useSaveStore.getInitialState()));
const success: AxiosAdapter = async (config) => ({
  config,
  status: 200,
  statusText: "OK",
  headers: new AxiosHeaders(),
  data: {},
});

it("confirms a save only after its response and ignores computations", async () => {
  let finish!: () => void;
  const request = api.put(
    "/plans/p/expenses/e",
    {},
    {
      adapter: async (config) => {
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
        return success(config);
      },
    },
  );
  await Promise.resolve();
  await Promise.resolve();
  expect(useSaveStore.getState().pending).toBe(1);
  expect(useSaveStore.getState().lastSavedAt).toBeNull();
  await api.post("/plans/p/simulate", {}, { adapter: success });
  expect(useSaveStore.getState().pending).toBe(1);
  expect(useSaveStore.getState().lastSavedAt).toBeNull();
  finish();
  await request;
  expect(useSaveStore.getState().pending).toBe(0);
  expect(useSaveStore.getState().lastSavedAt).not.toBeNull();
});

it("keeps failed writes visible until that write is retried successfully", async () => {
  await expect(
    api.put(
      "/accounts/a",
      {},
      {
        adapter: async (config) => {
          throw new AxiosError("offline", "ERR_NETWORK", config);
        },
      },
    ),
  ).rejects.toThrow("Check saved values before retrying");
  await api.put("/plans/p", {}, { adapter: success });
  expect(useSaveStore.getState().failed).toEqual(["put /accounts/a"]);
  await api.put("/accounts/a", {}, { adapter: success });
  expect(useSaveStore.getState().failed).toEqual([]);
  expect(useSaveStore.getState().pending).toBe(0);
});

it("preserves the backend name validation reason", async () => {
  await expect(
    api.put(
      "/plans/p/incomes/i",
      { name: "UX income " + "A".repeat(250) },
      {
        adapter: async (config) => {
          throw new AxiosError("Request failed", "ERR_BAD_REQUEST", config, undefined, {
            config,
            status: 422,
            statusText: "Unprocessable Entity",
            headers: new AxiosHeaders(),
            data: {
              error: {
                code: "VALIDATION_ERROR",
                message: "Validation failed",
                details: [{ field: "name", reason: "String should have at most 255 characters" }],
              },
            },
          });
        },
      },
    ),
  ).rejects.toThrow(/Name: String should have at most 255 characters/);
});

it.each(["incomes/i", "accounts/a", "liabilities/d"])(
  "an older successful %s response cannot erase a newer failed save",
  async (resource) => {
    let finish!: () => void;
    const older = api.put(
      `/plans/p/${resource}`,
      { name: "Older" },
      {
        adapter: async (config) => {
          await new Promise<void>((resolve) => {
            finish = resolve;
          });
          return success(config);
        },
      },
    );
    await Promise.resolve();
    await Promise.resolve();
    await expect(
      api.put(
        `/plans/p/${resource}`,
        { name: "Newer" },
        {
          adapter: async (config) => {
            throw new AxiosError("offline", "ERR_NETWORK", config);
          },
        },
      ),
    ).rejects.toThrow();
    finish();
    await older;
    expect(useSaveStore.getState().failed).toEqual([`put /plans/p/${resource}`]);
  },
);

it("a late failure keeps its original plan identity and survives another plan's save", async () => {
  usePlanStore.setState({
    plan: makePlan({ id: "a", name: "Plan A", income_streams: [{ id: "i", name: "Salary A" }] }),
  });
  let reject!: () => void;
  const pending = api.put(
    "/plans/a/incomes/i",
    { name: "Draft A" },
    {
      adapter: (config) =>
        new Promise((_resolve, fail) => {
          reject = () => fail(new AxiosError("offline", "ERR_NETWORK", config));
        }),
    },
  );
  const failure = expect(pending).rejects.toThrow("Save income “Salary A” in “Plan A”");
  await Promise.resolve();
  await Promise.resolve();
  usePlanStore.setState({ plan: makePlan({ id: "b", name: "Plan B" }) });
  await api.put("/plans/b", { name: "Plan B" }, { adapter: success });
  reject();
  await failure;
  expect(useSaveStore.getState().failed).toEqual(["put /plans/a/incomes/i"]);
  expect(useSaveStore.getState().failures["put /plans/a/incomes/i"].message).not.toContain(
    "Plan B",
  );
  usePlanStore.setState({ plan: null });
});
