import type { MilestoneDistribution } from "@/types/plan";

/** A milestone every trial reaches in the same year (a fixed date) has no spread to show. */
const isFixed = (item: MilestoneDistribution) =>
  item.reach_rate === 1 &&
  item.unreached_trials === 0 &&
  item.p10_year != null &&
  item.p10_year === item.median_year &&
  item.median_year === item.p90_year;

export default function MilestoneOutcomes({
  outcomes: all,
}: {
  outcomes: MilestoneDistribution[];
}) {
  const outcomes = all.filter((item) => !isFixed(item));
  if (!outcomes.length) return null;
  return (
    <section className="card" aria-labelledby="mc_milestone_heading">
      <h3 id="mc_milestone_heading">Milestone timing</h3>
      <p>Years cover trials that reached the milestone; unreached trials are counted separately.</p>
      <div style={{ overflowX: "auto" }}>
        <table
          style={{
            width: "100%",
            textAlign: "left",
            borderSpacing: "16px 12px",
            fontVariantNumeric: "tabular-nums",
          }}
        >
          <thead>
            <tr>
              <th scope="col">Milestone</th>
              <th scope="col">Reached</th>
              <th scope="col">Not reached</th>
              <th scope="col">10th percentile year</th>
              <th scope="col">Median year</th>
              <th scope="col">90th percentile year</th>
            </tr>
          </thead>
          <tbody>
            {outcomes.map((item) => (
              <tr key={item.id}>
                <th scope="row">{item.name}</th>
                <td>
                  {item.reach_rate == null ? "Unknown" : `${(item.reach_rate * 100).toFixed(1)}%`} (
                  {item.reached_trials} {item.reached_trials === 1 ? "trial" : "trials"})
                  {item.unreported_trials > 0 && `; ${item.unreported_trials} unreported`}
                </td>
                <td>{item.unreached_trials}</td>
                <td>{item.p10_year ?? "—"}</td>
                <td>{item.median_year ?? "—"}</td>
                <td>{item.p90_year ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
