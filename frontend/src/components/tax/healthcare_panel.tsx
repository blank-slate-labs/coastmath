import type { YearSnapshot } from "@/types/plan";
import { compactCurrency, fullCurrency, moneyLabel } from "@/utils/format";

interface HealthcarePanelProps {
  snapshots: YearSnapshot[];
  configured: boolean;
  /** Opens the Health coverage editor. */
  onEdit?: () => void;
}

/** Year-by-year health coverage costs from the projection engine. */
export function HealthcarePanel({ snapshots, configured, onEdit }: HealthcarePanelProps) {
  const rows = snapshots.filter(
    (s) =>
      (s.healthcare && s.healthcare.total > 0) ||
      (s.healthcare && (s.healthcare.aca_covered_adults > 0 || s.healthcare.medicare_persons > 0)),
  );
  if (!configured) {
    return (
      <div>
        <h3 style={{ marginTop: 0 }}>Health coverage</h3>
        <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
          Health coverage is off.
          {onEdit && (
            <>
              {" "}
              <button type="button" className="btn-ghost" onClick={onEdit}>
                Edit health coverage
              </button>
            </>
          )}
        </p>
      </div>
    );
  }
  const lifetimeGross = rows.reduce((sum, s) => sum + (s.healthcare?.aca_gross_premium ?? 0), 0);
  const lifetimeCredit = rows.reduce((sum, s) => sum + (s.healthcare?.aca_credit ?? 0), 0);
  const lifetimeMedicare = rows.reduce(
    (sum, s) =>
      sum +
      (s.healthcare?.medicare_part_b ?? 0) +
      (s.healthcare?.medicare_irmaa_part_b ?? 0) +
      (s.healthcare?.medicare_irmaa_part_d ?? 0) +
      (s.healthcare?.medicare_part_d_plan ?? 0) +
      (s.healthcare?.medicare_supplement ?? 0),
    0,
  );
  const irmaaYears = rows.filter((s) => (s.healthcare?.medicare_tier ?? 0) > 0).length;
  const cliffYears = rows.filter(
    (s) => s.healthcare && s.healthcare.aca_covered_adults > 0 && !s.healthcare.aca_eligible,
  );
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <h3 style={{ margin: 0 }}>Health coverage</h3>
      <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
        {moneyLabel("Nominal dollars")} from the projection. The premium tax credit uses each year's
        projected modified AGI; IRMAA uses income from two years earlier.
      </p>
      <dl style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8, margin: 0 }}>
        <dt>Marketplace premiums before credits</dt>
        <dd style={{ margin: 0, textAlign: "right" }}>{compactCurrency(lifetimeGross)}</dd>
        <dt>Premium tax credits</dt>
        <dd style={{ margin: 0, textAlign: "right" }}>{compactCurrency(lifetimeCredit)}</dd>
        <dt>Medicare premiums and surcharges</dt>
        <dd style={{ margin: 0, textAlign: "right" }}>{compactCurrency(lifetimeMedicare)}</dd>
        <dt>Years with IRMAA surcharges</dt>
        <dd style={{ margin: 0, textAlign: "right" }}>{irmaaYears}</dd>
      </dl>
      {cliffYears.length > 0 && (
        <p role="note" style={{ margin: 0, fontSize: 13, color: "var(--color-danger)" }}>
          No premium tax credit in {cliffYears.length} marketplace year
          {cliffYears.length === 1 ? "" : "s"} ({cliffYears[0].healthcare?.aca_reason}). Managing
          income below 400% of the poverty line in those years would restore it.
        </p>
      )}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", fontSize: 13 }} aria-label="Health coverage by year">
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}>Year</th>
              <th>Age</th>
              <th style={{ textAlign: "right" }}>Income vs FPL</th>
              <th style={{ textAlign: "right" }}>Marketplace premium</th>
              <th style={{ textAlign: "right" }}>Credit</th>
              <th style={{ textAlign: "right" }}>Medicare B + D</th>
              <th style={{ textAlign: "right" }}>IRMAA</th>
              <th style={{ textAlign: "right" }}>Total cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const h = s.healthcare!;
              const irmaa = h.medicare_irmaa_part_b + h.medicare_irmaa_part_d;
              return (
                <tr key={s.year}>
                  <td>{s.year}</td>
                  <td style={{ textAlign: "center" }}>{s.age}</td>
                  <td style={{ textAlign: "right" }}>
                    {h.aca_covered_adults > 0 ? `${Math.round(h.aca_fpl_ratio * 100)}%` : "—"}
                  </td>
                  <td style={{ textAlign: "right" }} title={fullCurrency(h.aca_gross_premium)}>
                    {h.aca_covered_adults > 0 ? compactCurrency(h.aca_gross_premium) : "—"}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {h.aca_covered_adults > 0
                      ? h.aca_eligible
                        ? `−${compactCurrency(h.aca_credit)}`
                        : "none"
                      : "—"}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {h.medicare_persons > 0
                      ? compactCurrency(
                          h.medicare_part_b + h.medicare_part_d_plan + h.medicare_supplement,
                        )
                      : "—"}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {h.medicare_persons > 0
                      ? irmaa > 0
                        ? `${compactCurrency(irmaa)} (tier ${h.medicare_tier})`
                        : "none"
                      : "—"}
                  </td>
                  <td style={{ textAlign: "right", fontWeight: 600 }}>
                    {compactCurrency(h.total)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && (
        <p style={{ margin: 0, fontSize: 13, color: "var(--text-tertiary)" }}>
          No coverage years in this projection.
        </p>
      )}
    </div>
  );
}

export default HealthcarePanel;
