import type { UsCoverage } from "@/domain/intl_plan";

const noteStyle: React.CSSProperties = {
  gridColumn: "1 / -1",
  margin: 0,
  fontSize: 12,
  color: "var(--text-secondary)",
};

/** Says that a US-only setting applies only in the plan's US years; nothing in all-US plans. */
export default function UsOnlyNote({
  coverage,
  what = "These settings",
}: {
  coverage: UsCoverage;
  what?: string;
}) {
  if (coverage !== "mixed") return null;
  return (
    <p className="us-only-note" style={noteStyle}>
      {what} apply only in the years you live in the US.
    </p>
  );
}
