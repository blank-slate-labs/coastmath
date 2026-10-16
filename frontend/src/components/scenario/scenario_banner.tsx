import { useState } from "react";

import { useStorage } from "@/storage/context";
import { usePlanStore } from "@/stores/plan_store";
import { changeCount, useInheritanceSync, useScenarioStore } from "@/stores/scenario_store";
import { ScenarioChangesPanel } from "./scenario_changes_panel";
import "./scenario.css";

/**
 * Shown above the planner while a scenario is open: which plan it follows, how
 * many values it changed, and anything from Main the last sync couldn't apply.
 * A failed read leaves the planner usable and offers a retry.
 */
export function ScenarioBanner() {
  const { adapter } = useStorage();
  useInheritanceSync(adapter);
  const plan = usePlanStore((s) => s.plan);
  const plans = usePlanStore((s) => s.plans);
  const baselinePlanId = usePlanStore((s) => s.baselinePlanId);
  const setBaselinePlan = usePlanStore((s) => s.setBaselinePlan);
  const entry = useScenarioStore((s) => (plan ? s.byPlan[plan.id] : undefined));
  const load = useScenarioStore((s) => s.load);
  const change = useScenarioStore((s) => s.change);
  const [panelOpen, setPanelOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);

  const parentId = plan?.parent_plan_id;
  if (!plan || !parentId) return null;
  const data = entry?.data?.plan_id === plan.id ? entry.data : null;
  const mainName = data?.parent_name ?? plans.find((p) => p.id === parentId)?.name ?? "Main plan";
  const count = data ? changeCount(data) : null;

  async function syncNow() {
    if (!plan) return;
    setSyncing(true);
    setSyncError(null);
    try {
      await change(plan.id, () => adapter.syncInheritance(plan.id));
    } catch (err) {
      setSyncError(err instanceof Error && err.message ? err.message : "Sync failed. Try again.");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <section className="scenario-banner" aria-label="Scenario">
      <div className="scenario-banner-row">
        <p>
          <strong>Scenario of {mainName}</strong>
          {count !== null && ` · ${count} ${count === 1 ? "change" : "changes"}`}
        </p>
        <span className="scenario-actions">
          <button
            type="button"
            className="btn-quiet"
            disabled={!data}
            onClick={() => setPanelOpen(true)}
          >
            View changes
          </button>
          <button
            type="button"
            className="btn-quiet"
            disabled={baselinePlanId === parentId}
            onClick={() => void setBaselinePlan(parentId)}
          >
            Compare with {mainName}
          </button>
        </span>
      </div>
      {entry?.failed && (
        <p role="alert">
          Couldn’t load what this scenario changed.{" "}
          <button type="button" className="btn-quiet" onClick={() => void load(adapter, plan.id)}>
            Retry
          </button>
        </p>
      )}
      {data?.status === "needs_review" && (
        <div className="scenario-review" role="status">
          <p>Some changes from {mainName} weren’t applied to this scenario:</p>
          {data.skipped.length > 0 && (
            <ul>
              {data.skipped.map((skip, index) => (
                <li key={`${skip.parent_row_id ?? skip.name}-${skip.field ?? ""}-${index}`}>
                  <strong>{skip.name}</strong>: {skip.reason}
                </li>
              ))}
            </ul>
          )}
          <span className="scenario-actions">
            <button
              type="button"
              disabled={syncing}
              aria-busy={syncing}
              onClick={() => void syncNow()}
            >
              {syncing ? "Syncing…" : "Sync now"}
            </button>
          </span>
          {syncError && <p role="alert">{syncError}</p>}
        </div>
      )}
      {data && (
        <ScenarioChangesPanel
          open={panelOpen}
          onClose={() => setPanelOpen(false)}
          plan={plan}
          data={data}
          mainName={mainName}
        />
      )}
    </section>
  );
}
