import { describe, expect, it } from "vitest";
import { withdrawalLockLabel } from "./withdrawal_lock";

describe("withdrawalLockLabel", () => {
  const milestones = [{ id: "m1", name: "Leave employer" }];
  it.each([
    [null, null],
    [{ unlock: "age" as const, age: 62 }, "Locked until age 62"],
    [{ unlock: "age" as const, age: 59.5 }, "Locked until age 59.5"],
    [{ unlock: "year" as const, year: 2031 }, "Locked until 2031"],
    [{ unlock: "milestone" as const, milestone_id: "m1" }, "Locked until Leave employer"],
    [
      { unlock: "milestone" as const, milestone_id: "gone" },
      "Locked until a milestone in another plan",
    ],
  ])("labels %j", (lock, expected) => {
    expect(withdrawalLockLabel(lock, milestones)).toBe(expected);
  });
});
