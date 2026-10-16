import type { StorageAdapter } from "@/storage/adapter";
import type { StrategyPlanChange, StrategySearchCandidate, TaxSettings } from "@/types/plan";
import { priorityPayload } from "../savings_priorities_panel";
import { DEFAULT_TAX_SETTINGS } from "@/domain/tax_settings_defaults";
import { isSaveConflict } from "@/api/save_error";

export type ApplyStep = "rules" | "tax_settings" | "drawdown_order";

export const APPLY_STEP_LABELS: Record<ApplyStep, string> = {
  rules: "allocation rules",
  tax_settings: "tax target settings",
  drawdown_order: "withdrawal order",
};

/** The saved plan no longer matches what the search ran against. Nothing further was written. */
export class StrategyApplyConflict extends Error {
  constructor(
    message: string,
    readonly done: ApplyStep[],
  ) {
    super(message);
  }
}

/** A later step failed after earlier steps saved. Retrying writes only the remaining ones. */
export class StrategyApplyPartial extends Error {
  constructor(
    message: string,
    readonly done: ApplyStep[],
    readonly remaining: ApplyStep[],
  ) {
    super(message);
  }
}

/** Drops null, undefined and false members so a saved target compares equal however the server spells defaults. */
export function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, v]) => v !== null && v !== undefined && v !== false)
        .map(([k, v]) => [k, canonical(v)])
        .sort(([a], [b]) => String(a).localeCompare(String(b))),
    );
  }
  return value;
}
const same = (a: unknown, b: unknown) =>
  JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));

export const stepsFor = (candidate: StrategySearchCandidate): ApplyStep[] => {
  const steps: ApplyStep[] = [];
  if (candidate.proposal.priorities_to_add.length) steps.push("rules");
  if (candidate.proposal.tax_settings) steps.push("tax_settings");
  if (candidate.proposal.drawdown_order) steps.push("drawdown_order");
  return steps;
};

const changeOf = (changes: StrategyPlanChange[], target: StrategyPlanChange["target"]) =>
  changes.find((c) => c.target === target);

/**
 * Applies a searched candidate: allocation rules (revision-checked), tax settings, then withdrawal order.
 * Everything that can be checked is checked before the first write. A 409 or a changed
 * saved value stops the apply with a StrategyApplyConflict and leaves the rest unwritten;
 * nothing is merged or retried automatically. `done` lists steps already saved by an earlier attempt.
 */
export async function applyStrategyCandidate(
  adapter: Pick<
    StorageAdapter,
    | "fetchPlan"
    | "updatePriorities"
    | "updatePlan"
    | "listDrawdownOrder"
    | "updateDrawdownOrder"
    | "createMilestone"
  >,
  planId: string,
  candidate: StrategySearchCandidate,
  expectedRevision: number,
  done: ApplyStep[] = [],
): Promise<ApplyStep[]> {
  const steps = stepsFor(candidate);
  const pending = steps.filter((s) => !done.includes(s));
  const { proposal, changes } = candidate;
  const completed = [...done];
  const latest = await adapter.fetchPlan(planId);

  const stale = (what: string) =>
    new StrategyApplyConflict(
      `${what} changed since the search ran. Nothing more was applied. Review the saved plan and search again.`,
      completed,
    );
  if (pending.includes("rules") && (latest.priorities_revision ?? 0) !== expectedRevision)
    throw stale("The allocation rules");
  if (pending.includes("tax_settings")) {
    const target = changeOf(changes, "tax_target");
    if (target && !same(latest.tax_settings?.tax_target ?? null, target.before ?? null))
      throw stale("The saved tax target");
    const blend = changeOf(changes, "blend_drawdown");
    if (
      blend &&
      Boolean(latest.tax_settings?.blend_drawdown_to_tax_target) !== Boolean(blend.before)
    )
      throw stale("Withdrawal blending");
  }
  if (pending.includes("drawdown_order")) {
    const saved = (await adapter.listDrawdownOrder(planId))
      .sort((a, b) => a.rank - b.rank)
      .map((e) => e.source_account_id)
      .filter((id): id is string => Boolean(id));
    const before = (changeOf(changes, "drawdown_order")?.before as string[] | undefined) ?? [];
    if (JSON.stringify(saved) !== JSON.stringify(before)) throw stale("The withdrawal order");
  }

  const remaining = () => steps.filter((s) => !completed.includes(s));
  const run = async (step: ApplyStep, write: () => Promise<unknown>) => {
    if (completed.includes(step)) return;
    try {
      await write();
    } catch (error) {
      if (isSaveConflict(error)) {
        throw new StrategyApplyConflict(
          `The ${APPLY_STEP_LABELS[step]} changed in another session. Nothing more was applied. Review the saved plan and search again.`,
          completed,
        );
      }
      const detail = error instanceof Error && error.message ? ` ${error.message}` : "";
      throw new StrategyApplyPartial(
        `Could not save the ${APPLY_STEP_LABELS[step]}.${detail}`,
        completed,
        remaining(),
      );
    }
    completed.push(step);
  };

  if (pending.includes("rules")) {
    await run("rules", async () => {
      // A year or age window's milestones come first. A matching active
      // milestone (saved by an earlier attempt, or already in the plan) is
      // reused; a switched-off one never fires, so the window gets a new one.
      const ids = new Map<string, string>();
      for (const wanted of proposal.milestones_to_add ?? []) {
        const existing = (latest.milestones ?? []).find(
          (m) =>
            m.trigger_type === wanted.trigger_type &&
            m.is_active !== false &&
            !m.conditions &&
            !m.relative_to_id &&
            !m.offset_years &&
            (wanted.trigger_type === "age"
              ? m.trigger_value != null && m.trigger_value === wanted.trigger_value
              : m.trigger_date != null &&
                wanted.trigger_date != null &&
                m.trigger_date.slice(0, 10) === wanted.trigger_date.slice(0, 10)),
        );
        const saved =
          existing ??
          (await adapter.createMilestone(planId, {
            name: wanted.name,
            trigger_type: wanted.trigger_type,
            trigger_value: wanted.trigger_value,
            trigger_date: wanted.trigger_date,
          } as Parameters<typeof adapter.createMilestone>[1]));
        ids.set(wanted.id, saved.id);
      }
      const resolve = (id: string | null | undefined) =>
        id != null && ids.has(id) ? ids.get(id)! : (id ?? null);
      const items = priorityPayload(latest.priorities ?? []);
      for (const added of proposal.priorities_to_add) {
        items.push({
          ...added,
          ...(ids.size
            ? {
                start_milestone_id: resolve(added.start_milestone_id),
                end_milestone_id: resolve(added.end_milestone_id),
              }
            : {}),
          priority_rank: items.length + 1,
        });
      }
      return adapter.updatePriorities(planId, items, expectedRevision);
    });
  }
  if (pending.includes("tax_settings")) {
    await run("tax_settings", () =>
      adapter.updatePlan(planId, {
        tax_settings: {
          ...DEFAULT_TAX_SETTINGS,
          ...latest.tax_settings,
          ...proposal.tax_settings,
        } as TaxSettings,
      }),
    );
  }
  if (pending.includes("drawdown_order")) {
    await run("drawdown_order", () =>
      adapter.updateDrawdownOrder(planId, proposal.drawdown_order ?? []),
    );
  }
  return completed;
}
