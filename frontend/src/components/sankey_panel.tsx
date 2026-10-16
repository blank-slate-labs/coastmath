import { ChartHeader } from "@/components/chart_chrome";
import SankeyChart from "@/components/sankey_chart";
import SurplusAllocationSummary from "@/components/surplus_allocation_summary";
import { usePlanStore } from "@/stores/plan_store";

/**
 * One year's cash flow: the Sankey on the left, and beside it where the surplus
 * went (or which accounts covered a deficit). The year comes from the
 * dashboard's shared selection, set on the hero chart or the pinned age bar.
 * Amounts are nominal for that year, including the actual partial first-year
 * period.
 */
export default function SankeyPanel({
  year,
  onEditAllocation,
}: {
  year: number;
  onEditAllocation: (rank?: number) => void;
}) {
  const plan = usePlanStore((s) => s.plan);
  const simulation = usePlanStore((s) => s.simulation);
  const currencyMode = usePlanStore((s) => s.currencyMode);

  if (!simulation || !plan) {
    return (
      <div
        style={{ padding: 40, textAlign: "center", color: "var(--text-tertiary)", fontSize: 14 }}
      >
        No projection yet.
      </div>
    );
  }

  const snapshots = simulation.yearly_snapshots;
  const snapshot = snapshots.find((point) => point.year === year) ?? null;
  const age = snapshot?.age ?? year - plan.birth_year;
  // A partial first year is labelled once, in the year panel beside this diagram.
  const basis = currencyMode === "inflation_adjusted" ? " · nominal" : "";
  const breakdown = snapshot?.cash_flow ?? null;

  return (
    <div className="dash-split">
      <div className="dash-main" style={{ display: "grid", gap: 12 }}>
        <ChartHeader title="Cash flow" subtitle={`${year} · age ${age}${basis}`} />
        {breakdown ? (
          <SankeyChart breakdown={breakdown} selectedYear={year} height={400} />
        ) : (
          <div
            style={{
              height: 400,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--text-tertiary)",
              fontSize: 14,
              borderRadius: 18,
              background: "var(--gray-50)",
            }}
          >
            No cash flow breakdown available for {year}.
          </div>
        )}
      </div>
      <SurplusAllocationSummary
        snapshot={snapshot ?? undefined}
        jointFiling={plan.filing_status === "married_filing_jointly"}
        onEdit={onEditAllocation}
      />
    </div>
  );
}
