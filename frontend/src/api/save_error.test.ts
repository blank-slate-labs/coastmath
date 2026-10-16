import { expect, it, vi } from "vitest";
import { isSaveConflict, saveFailure, saveAction } from "./save_error";
import { useSaveStore } from "@/stores/save_store";
import { makePlan } from "@/test_support/plan_builder";

it.each([
  [401, "session expired", true],
  [403, "permission", true],
  [404, "no longer available", true],
  [409, "conflicts with saved data", true],
  [422, "server did not identify a field", true],
  [429, "too many requests", true],
  [500, "could not be confirmed", false],
])(
  "explains status %s without inventing a field or pretending it saved",
  (status, text, rejected) => {
    const result = saveFailure({ response: { status } }, "Save income Salary");
    expect(result.message).toContain(text);
    expect(result.message).toContain("Save income Salary");
    expect(result.rejected).toBe(rejected);
  },
);
it("distinguishes timeout, offline and unspecified connection failure", () => {
  expect(saveFailure({ code: "ETIMEDOUT" }, "Save income").message).toContain("timed out");
  const offline = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
  expect(saveFailure({}, "Save income").message).toContain("while offline");
  offline.mockRestore();
  expect(saveFailure({}, "Save income").message).toContain("connection was interrupted");
});
it("suppresses raw technical error details but retains a safe known validation reason", () => {
  const failure = saveFailure(
    {
      response: {
        status: 422,
        data: {
          error: {
            message: "SQL SELECT password FROM users",
            details: [
              null,
              { field: "name", reason: "String should have at most 255 characters" },
              { field: "name", reason: "https://secret.test/api/token" },
            ],
          },
        },
      },
    },
    "Save income",
  );
  expect(failure.message).toContain("Name: String should have at most 255 characters.");
  expect(failure.message).not.toMatch(/SQL|password|secret|https:/);
});
it("uses the saved name rather than the rejected rename", () => {
  const plan = makePlan({ id: "p", name: "Plan A", income_streams: [{ id: "i", name: "Salary" }] });
  expect(saveAction("put", "/plans/p/incomes/i", { name: "Bad draft" }, plan)).toBe(
    "Save income “Salary” in “Plan A”",
  );
});
it("discard never acknowledges a write with an unknown outcome", () => {
  useSaveStore.setState(useSaveStore.getInitialState());
  const store = useSaveStore.getState();
  const key = "put /plans/p/incomes/i";
  store.finish(key, false, store.begin(key), saveFailure({ code: "ETIMEDOUT" }, "Save income"));
  store.discardRejected(key);
  expect(useSaveStore.getState().failed).toEqual([key]);
});
it.each([
  ["liabilities", "debt", "liabilities", "UX Loan"],
  ["real-assets", "property", "real_assets", "UX Cabin"],
])(
  "keeps %s saved identity on a blank rename and unrelated completion",
  (resource, label, collection, name) => {
    const plan = makePlan({ id: "p", name: "Plan A", [collection]: [{ id: "i", name }] });
    const action = saveAction("put", `/plans/p/${resource}/i`, { name: "   " }, plan);
    expect(action).toBe(`Save ${label} “${name}” in “Plan A”`);
    const failure = saveFailure(
      {
        response: {
          status: 422,
          data: {
            error: {
              details: [
                {
                  field: "name",
                  reason: "Enter a name containing at least one non-space character",
                },
              ],
            },
          },
        },
      },
      action,
    );
    useSaveStore.setState(useSaveStore.getInitialState());
    const store = useSaveStore.getState();
    const key = `put /plans/p/${resource}/i`;
    const older = store.begin(key);
    store.finish(key, false, store.begin(key), failure);
    store.finish(key, true, older);
    store.finish("put /plans/other/incomes/j", true, store.begin("put /plans/other/incomes/j"));
    expect(useSaveStore.getState().failures[key]?.message).toContain(
      `“${name}” in “Plan A” was not saved. Name:`,
    );
    expect(useSaveStore.getState().failures[key]?.message).toContain("was not saved. Name:");
    store.finish(key, true, store.begin(key));
    expect(useSaveStore.getState().failed).toEqual([]);
  },
);
it("shows the connected-expense refusal as a rejected save that keeps the draft", () => {
  // The backend's own 409 code for connected spending; the web explains it by status and message.
  const failure = saveFailure(
    {
      response: {
        status: 409,
        data: {
          error: {
            code: "CONNECTED_EXPENSE",
            details: [],
            message:
              "This expense follows your transactions. Turn off Plan spending in Transactions before changing its amount or deleting it.",
          },
        },
      },
    },
    "Save expense “Everyday spending (connected)”",
  );
  expect(failure.rejected).toBe(true);
  expect(failure.message).toContain("conflicts with saved data");
  expect(failure.message).toContain("Turn off Plan spending in Transactions");
});
it("names what still uses a milestone when its delete is refused", () => {
  const plan = makePlan({ id: "p", name: "Plan A", milestones: [{ id: "m", name: "Retirement" }] });
  const action = saveAction("delete", "/plans/p/milestones/m", undefined, plan);
  const failure = saveFailure(
    {
      response: {
        status: 409,
        data: {
          error: {
            code: "CONFLICT",
            details: [],
            message:
              "Salary, Rent and 2 more use this milestone. Point them at another milestone before deleting this one.",
          },
        },
      },
    },
    action,
  );
  expect(failure.rejected).toBe(true);
  expect(failure.message).toBe(
    "Delete milestone “Retirement” in “Plan A” was not saved because it conflicts with saved data. " +
      "Salary, Rent and 2 more use this milestone. Point them at another milestone before deleting this one.",
  );
});
it("rewrites validator bounds as the value to enter and keeps a whole-message reason unlabelled", () => {
  const bound = saveFailure(
    {
      response: {
        status: 422,
        data: {
          error: {
            message: "Validation failed",
            details: [
              { field: "birth_year", reason: "Input should be greater than or equal to 1900" },
              {
                field: "annual_amount",
                reason: "Input should be less than or equal to 1000000000000",
              },
            ],
          },
        },
      },
    },
    "Save plan",
  );
  expect(bound.message).toBe(
    "Save plan was not saved. Birth year: Enter 1900 or more. Annual amount: Enter 1,000,000,000,000 or less.",
  );
  const sentence = "Reassign or remove the partner's items first: Spouse Salary.";
  const whole = saveFailure(
    {
      response: {
        status: 422,
        data: { error: { message: sentence, details: [{ field: "spouse", reason: sentence }] } },
      },
    },
    "Save plan",
  );
  expect(whole.message).toBe(`Save plan was not saved. ${sentence}`);
});
it("explains an allocation conflict without the revision bookkeeping", () => {
  const conflict = saveFailure(
    {
      response: {
        status: 409,
        data: {
          error: {
            message:
              "Allocation changed since you started editing. Review the latest rules before saving; your draft has not been applied.",
            details: [{ field: "expected_revision", reason: "stale allocation revision" }],
          },
        },
      },
    },
    "Save income allocation",
  );
  expect(conflict.message).not.toMatch(/revision/i);
  expect(conflict.message).toContain("Allocation changed since you started editing.");
});
it("recognises a 409 from the client's save error and from a raw Axios error", () => {
  expect(isSaveConflict(Object.assign(new Error("conflict"), { status: 409 }))).toBe(true);
  expect(isSaveConflict({ response: { status: 409 } })).toBe(true);
  expect(
    isSaveConflict(Object.assign(new Error("invalid"), { status: 422, response: { status: 422 } })),
  ).toBe(false);
  expect(isSaveConflict({ response: null })).toBe(false);
  expect(isSaveConflict(new Error("network"))).toBe(false);
  expect(isSaveConflict(null)).toBe(false);
  expect(isSaveConflict(undefined)).toBe(false);
  expect(isSaveConflict("409")).toBe(false);
});
