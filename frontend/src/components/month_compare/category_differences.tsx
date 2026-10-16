import type { SpendingOutcome } from "@/api/spending_models";
import { money } from "@/components/ledger/ledger_format";
import { categoryDifferences } from "./month_format";

/** The categories whose monthly spending differs most between two month variants. */
export default function CategoryDifferences({
  a,
  b,
  labels,
  currency,
}: {
  a: SpendingOutcome;
  b: SpendingOutcome;
  labels: Record<string, string>;
  currency: string;
}) {
  const rows = categoryDifferences(a.by_category ?? {}, b.by_category ?? {});
  return (
    <section aria-label="Category differences" className="card" style={{ display: "grid", gap: 8 }}>
      <h3 style={{ margin: 0 }}>
        {a.label} vs {b.label}
      </h3>
      {rows.length === 0 ? (
        <p style={{ margin: 0 }}>No category differences.</p>
      ) : (
        <table className="chart-table" style={{ width: "100%" }}>
          <thead>
            <tr>
              <th scope="col">Category / mo</th>
              <th scope="col" className="num">
                {a.label}
              </th>
              <th scope="col" className="num">
                {b.label}
              </th>
              <th scope="col" className="num">
                Difference
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <th scope="row" style={{ textAlign: "left", fontWeight: 500 }}>
                  {labels[row.key] ?? row.key}
                </th>
                <td className="num">{money(row.a, currency)}</td>
                <td className="num">{money(row.b, currency)}</td>
                <td className="num">
                  {row.difference > 0 ? "+" : ""}
                  {money(row.difference, currency)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
