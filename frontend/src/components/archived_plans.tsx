import { useId, useState } from "react";

import { extensions } from "@/extensions";
import { useAuthStore } from "@/stores/auth_store";
import { usePlanStore } from "@/stores/plan_store";
import type { ArchivedPlanSummary } from "@/types/plan";
import { localDay } from "@/utils/format";

/** Delete permanently, behind an explicit confirmation: it cannot be undone. */
function DeleteArchived({ plan }: { plan: ArchivedPlanSummary }) {
  const deleteArchivedPlan = usePlanStore((s) => s.deleteArchivedPlan);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const promptId = useId();
  if (!confirming) {
    return (
      <button type="button" className="btn-quiet" onClick={() => setConfirming(true)}>
        Delete permanently
      </button>
    );
  }
  return (
    <div className="archived-plan-confirm" role="group" aria-labelledby={promptId}>
      <p id={promptId}>Delete “{plan.name}” permanently? This cannot be undone.</p>
      <button
        type="button"
        className="btn-danger"
        disabled={busy}
        aria-busy={busy}
        onClick={async () => {
          setBusy(true);
          if (!(await deleteArchivedPlan(plan.id))) setBusy(false);
        }}
      >
        {busy ? "Deleting…" : "Delete permanently"}
      </button>
      <button
        type="button"
        className="btn-quiet"
        disabled={busy}
        onClick={() => setConfirming(false)}
      >
        Cancel
      </button>
    </div>
  );
}

/**
 * Archived plans in the sidebar, by name and archive date. Each can be
 * opened, restored or deleted permanently. An access policy may lock opening
 * and restoring them; the server enforces it.
 */
export function ArchivedPlans() {
  const archived = usePlanStore((s) => s.archivedPlans);
  const loadPlan = usePlanStore((s) => s.loadPlan);
  const restorePlan = usePlanStore((s) => s.restorePlan);
  const openPlanId = usePlanStore((s) => s.plan?.id);
  const access = extensions.access;
  const locked = useAuthStore((s) => !!access?.locked(s.user, "archived_plans"));
  const [restoring, setRestoring] = useState<string | null>(null);
  if (!archived.length) return null;

  return (
    <details className="archived-plans">
      <summary>Archived plans · {archived.length}</summary>
      {locked && access && <access.LockedFeature feature="archived_plans" />}
      <ul>
        {archived.map((plan) => (
          <li key={plan.id} className="archived-plan">
            <span className="archived-plan-name">{plan.name}</span>
            <span className="archived-plan-date">Archived {localDay(plan.archived_at)}</span>
            <div className="archived-plan-actions">
              {!locked && (
                <>
                  <button
                    type="button"
                    className="btn-quiet"
                    disabled={openPlanId === plan.id}
                    onClick={() => void loadPlan(plan.id)}
                  >
                    Open
                  </button>
                  <button
                    type="button"
                    className="btn-quiet"
                    disabled={restoring !== null}
                    aria-busy={restoring === plan.id}
                    onClick={async () => {
                      setRestoring(plan.id);
                      const restored = await restorePlan(plan.id);
                      setRestoring(null);
                      if (restored && openPlanId !== plan.id) void loadPlan(plan.id);
                    }}
                  >
                    {restoring === plan.id ? "Restoring…" : "Restore"}
                  </button>
                </>
              )}
              <DeleteArchived plan={plan} />
            </div>
          </li>
        ))}
      </ul>
    </details>
  );
}
