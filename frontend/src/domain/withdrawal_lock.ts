import type { Milestone, WithdrawalLock } from "@/types/plan";

/** Short account-row status for a withdrawal lock, or null when there is none. */
export function withdrawalLockLabel(
  lock: WithdrawalLock | null | undefined,
  milestones: Pick<Milestone, "id" | "name">[] = [],
): string | null {
  if (!lock) return null;
  if (lock.unlock === "age" && lock.age != null) return `Locked until age ${lock.age}`;
  if (lock.unlock === "year" && lock.year != null) return `Locked until ${lock.year}`;
  if (lock.unlock === "milestone") {
    const milestone = milestones.find((item) => item.id === lock.milestone_id);
    // Household accounts are shared; another plan's milestone does not apply here.
    return milestone
      ? `Locked until ${milestone.name}`
      : "Locked until a milestone in another plan";
  }
  return null;
}
