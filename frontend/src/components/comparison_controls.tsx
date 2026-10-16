import { usePlanStore } from "@/stores/plan_store";

/** Baseline capture and saved-plan comparison, sized to sit in a chart header. */
export default function ComparisonControls() {
  const {
    plan,
    plans,
    simulation,
    baselineSimulation,
    baselinePlanId,
    isComparing,
    isSimulating,
    saveBaseline,
    clearBaseline,
    setBaselinePlan,
  } = usePlanStore();
  if (!plan) return null;
  const otherPlans = plans.filter((p) => p.id !== plan.id);
  return (
    <div className="compare-controls">
      <button
        type="button"
        className="btn-quiet"
        disabled={!simulation || isSimulating || isComparing}
        onClick={saveBaseline}
        title="Comparison clears on reload or plan switch."
      >
        {baselineSimulation ? "Update comparison forecast" : "Keep forecast for comparison"}
      </button>
      {otherPlans.length > 0 && (
        <select
          data-sample-view
          aria-label="Compare with saved plan"
          className="compare-select"
          disabled={isComparing}
          value={baselinePlanId ?? ""}
          onChange={(e) => setBaselinePlan(e.target.value || null)}
        >
          <option value="">Compare with another plan…</option>
          {otherPlans.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      )}
      {(baselineSimulation || isComparing) && (
        <button type="button" className="btn-quiet" onClick={clearBaseline}>
          Stop comparing
        </button>
      )}
      <span role="status" className="compare-status">
        {isComparing
          ? "Loading comparison…"
          : baselineSimulation
            ? `${baselinePlanId ? `Comparing with ${otherPlans.find((p) => p.id === baselinePlanId)?.name ?? "the selected plan"}.` : "Baseline captured."} Clears on reload or plan switch.`
            : ""}
      </span>
    </div>
  );
}
