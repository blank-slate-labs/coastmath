/**
 * Plan scenarios: a plan linked to a Main plan receives Main's changes on every
 * save of Main, except the values changed in the scenario itself.
 * Wire shapes of GET /plans/{id}/inheritance and its change routes.
 */

/** Row kinds have one item per scenario row and per removed Main row. */
export type ScenarioRowKind =
  | "spouse"
  | "milestone"
  | "income"
  | "expense"
  | "account"
  | "real_asset"
  | "liability"
  | "assumption_curve"
  | "charity";

/** Whole-list kinds appear once each, only for a scenario. */
export type ScenarioListKind = "priorities" | "drawdown" | "residency";

export type ScenarioItemKind = ScenarioRowKind | ScenarioListKind;

export type ScenarioItemState = "inherited" | "changed" | "removed" | "scenario_only";

/** One changed value; IDs are given in the scenario's own IDs where the referenced row is linked. */
export interface ScenarioFieldChange {
  field: string;
  value: unknown;
  parent_value: unknown;
}

export interface ScenarioItem {
  kind: ScenarioItemKind;
  /** Null for a removed Main row and for whole-list kinds. */
  row_id: string | null;
  /** Null for a scenario-only row and for whole-list kinds. */
  parent_row_id: string | null;
  name: string;
  state: ScenarioItemState;
  /** Only the changed fields; empty unless state is "changed" on a row kind. */
  fields: ScenarioFieldChange[];
}

/** A Main change the last sync could not apply; "plan" is a whole-plan problem (failed sync or projection check). */
export interface ScenarioSkipped {
  kind: ScenarioItemKind | "plan";
  parent_row_id: string | null;
  name: string;
  field: string | null;
  reason: string;
}

export interface PlanInheritance {
  plan_id: string;
  /** Null when the plan is not a scenario. */
  parent_plan_id: string | null;
  parent_name: string | null;
  status: "ok" | "needs_review";
  synced_at: string | null;
  plan_fields: ScenarioFieldChange[];
  items: ScenarioItem[];
  skipped: ScenarioSkipped[];
}

/** POST /plans/{id}/inheritance/reset. `fields` omitted resets every changed field of the row. */
export type InheritanceReset =
  | { kind: ScenarioRowKind; row_id: string; fields?: string[] | null }
  | { kind: "plan"; fields: string[] }
  | { kind: "priorities"; expected_revision: number }
  | { kind: "drawdown" | "residency" };

/** POST /plans/{id}/inheritance/restore: recreate a removed Main row. */
export interface InheritanceRestore {
  kind: ScenarioRowKind;
  parent_row_id: string;
}
