import { usePlanStore } from "@/stores/plan_store";

export default function CompareSelector() {
  const plan = usePlanStore((s) => s.plan);
  const plans = usePlanStore((s) => s.plans);
  const baselinePlanId = usePlanStore((s) => s.baselinePlanId);
  const isComparing = usePlanStore((s) => s.isComparing);
  const compareMode = usePlanStore((s) => s.compareMode);
  const setBaselinePlan = usePlanStore((s) => s.setBaselinePlan);

  const otherPlans = (plans ?? []).filter((p) => p.id !== plan?.id);

  if (otherPlans.length === 0) return null;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
      <label
        htmlFor="compare-select"
        style={{ fontSize: "12px", color: "var(--text-tertiary)", whiteSpace: "nowrap", margin: 0 }}
      >
        Compare to:
      </label>
      <select
        id="compare-select"
        value={baselinePlanId ?? ""}
        onChange={(e) => setBaselinePlan(e.target.value || null)}
        disabled={isComparing}
        style={{
          padding: "5px 28px 5px 10px",
          fontSize: "12px",
          minWidth: "120px",
          opacity: isComparing ? 0.6 : 1,
        }}
      >
        <option value="">None</option>
        {otherPlans.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      {isComparing && (
        <span style={{ fontSize: "12px", color: "var(--text-tertiary)" }}>Loading...</span>
      )}
      {compareMode && !isComparing && (
        <button
          className="nav-item"
          onClick={() => setBaselinePlan(null)}
          style={{
            padding: "4px 12px",
            fontSize: "12px",
            borderRadius: "var(--radius-sm)",
            cursor: "pointer",
            background: "var(--color-danger-light)",
            color: "var(--color-danger)",
            border: "1px solid rgba(239, 68, 68, 0.2)",
            fontWeight: 500,
          }}
        >
          Clear
        </button>
      )}
    </div>
  );
}
