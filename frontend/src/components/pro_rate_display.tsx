const SHORT_MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

interface ProRateDisplayProps {
  startMonth: number | null; // 1-12
  endMonth: number | null; // 1-12
  hasStartMilestone: boolean;
  hasEndMilestone: boolean;
  claimingAge?: number | null;
}

export function ProRateDisplay({
  startMonth,
  endMonth,
  hasStartMilestone,
  hasEndMilestone,
  claimingAge = null,
}: ProRateDisplayProps) {
  if (startMonth === null && endMonth === null) return null;

  // Boundary years may differ or depend on the forecast. Months alone cannot
  // determine a modeled dollar amount (including a partial first plan year).
  return (
    <div
      role="status"
      style={{ fontSize: "12px", color: "var(--text-tertiary)", padding: "4px 0" }}
    >
      {startMonth !== null && (
        <div>
          {hasStartMilestone
            ? `Starts in ${SHORT_MONTHS[startMonth - 1]} in the year the Start Milestone is reached.`
            : claimingAge !== null
              ? `Starts in ${SHORT_MONTHS[startMonth - 1]} in the year the income recipient reaches claiming age ${claimingAge}.`
              : "Requires a Start Milestone."}
        </div>
      )}
      {endMonth !== null && (
        <div>
          {hasEndMilestone
            ? `Ends after ${SHORT_MONTHS[endMonth - 1]} in the year the End Milestone is reached.`
            : "Requires an End Milestone."}
        </div>
      )}
      <div>Months apply to boundary years only, not a seasonal schedule.</div>
    </div>
  );
}
