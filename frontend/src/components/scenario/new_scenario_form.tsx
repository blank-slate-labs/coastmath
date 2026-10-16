import { useState } from "react";

import { usePlanStore } from "@/stores/plan_store";
import type { PlanData, PlanSummary } from "@/types/plan";

/**
 * The plan a new scenario follows: the open plan itself, or the open
 * scenario's Main (a scenario can't have scenarios of its own).
 */
export function scenarioSource(plan: PlanData, plans: PlanSummary[]): { id: string; name: string } {
  if (!plan.parent_plan_id) return { id: plan.id, name: plan.name };
  return {
    id: plan.parent_plan_id,
    name: plans.find((p) => p.id === plan.parent_plan_id)?.name ?? "Main plan",
  };
}

/** Names and creates a scenario of `source`, then opens it. */
export function NewScenarioForm({
  source,
  onDone,
}: {
  source: { id: string; name: string };
  onDone: () => void;
}) {
  const createScenario = usePlanStore((s) => s.createScenario);
  const error = usePlanStore((s) => s.error);
  const [name, setName] = useState(`${source.name} (scenario)`);
  const [busy, setBusy] = useState(false);
  const trimmed = name.trim();

  return (
    <form
      className="new-scenario"
      style={{ display: "grid", gap: 12 }}
      onSubmit={async (event) => {
        event.preventDefault();
        if (!trimmed || busy) return;
        setBusy(true);
        const created = await createScenario(source.id, trimmed);
        setBusy(false);
        if (created) onDone();
      }}
    >
      <p style={{ margin: 0 }}>
        “{source.name}” stays the Main plan. The scenario starts identical and receives each change
        saved to “{source.name}”, except values you change in the scenario.
      </p>
      <label style={{ display: "grid", gap: 6 }}>
        Scenario name
        <input
          value={name}
          maxLength={255}
          required
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={busy || !trimmed} aria-busy={busy}>
        {busy ? "Creating…" : "Create scenario"}
      </button>
    </form>
  );
}
