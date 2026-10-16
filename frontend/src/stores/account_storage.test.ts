import { afterEach, expect, it } from "vitest";
import { clearAccountStorage } from "./account_storage";

const keys = () =>
  Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i)).sort();
afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

it("forgets account and plan storage but keeps device preferences", () => {
  for (const key of [
    "coastmath:theme",
    "coastmath:currency_mode",
    "coastmath:active-plan:user-1",
    "coastmath:metrics:plan-1",
    "coastmath:fi_estimate_hidden:plan-1",
    "coastmath:builder:plan-1:Income",
    "coastmath.email_for_signin",
    "coastmath.email_link_request",
    "unrelated",
  ])
    localStorage.setItem(key, "value");
  sessionStorage.setItem("allocation-draft:v1:user-1:plan-1", "{}");
  clearAccountStorage();
  expect(keys()).toEqual(["coastmath:currency_mode", "coastmath:theme", "unrelated"]);
  expect(sessionStorage.length).toBe(0);
});
