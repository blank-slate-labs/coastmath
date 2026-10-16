import { useState } from "react";
import type { PlanData, TaxSettings, HSACoverage, StatePayrollCoverage } from "@/types/plan";
import { moneyLabel } from "@/utils/format";
import MoneyInput from "./money_input";
import { DEFAULT_TAX_SETTINGS } from "@/domain/tax_settings_defaults";

const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
type Period = HSACoverage | StatePayrollCoverage;
function PeriodFields({ row, change }: { row: Period; change: (patch: Partial<Period>) => void }) {
  return (
    <>
      <label>
        Person
        <select
          value={row.owner}
          onChange={(e) => change({ owner: e.target.value as Period["owner"] })}
        >
          <option value="self">Primary person</option>
          <option value="spouse">Partner</option>
        </select>
      </label>
      <label>
        First year
        <input
          required
          type="number"
          min="2025"
          max="2300"
          value={row.start_year}
          onChange={(e) => change({ start_year: Number(e.target.value) })}
        />
      </label>
      <label>
        Last year (blank means ongoing)
        <input
          type="number"
          min={row.start_year}
          max="2300"
          value={row.end_year ?? ""}
          onChange={(e) => change({ end_year: e.target.value ? Number(e.target.value) : null })}
        />
      </label>
    </>
  );
}

export default function CoverageForm({
  plan,
  onSave,
}: {
  plan: PlanData;
  onSave: (settings: TaxSettings) => Promise<void>;
}) {
  const [hsa, setHsa] = useState(plan.tax_settings?.hsa_coverage ?? []);
  const [payroll, setPayroll] = useState(plan.tax_settings?.state_payroll_coverage ?? []);
  const [exempt, setExempt] = useState(plan.tax_settings?.ca_exemption_eligible_owners ?? null);
  const [paid, setPaid] = useState(plan.tax_settings?.state_payroll_paid_year_to_date ?? {});
  const [stateWages, setStateWages] = useState(
    plan.tax_settings?.state_payroll_wages_year_to_date ?? {},
  );
  const [dependents, setDependents] = useState(plan.tax_settings?.ca_dependents_by_year ?? {});
  const [dependentYear, setDependentYear] = useState(
    Number(plan.start_date?.slice(0, 4)) || new Date().getFullYear(),
  );
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const year = Math.max(2025, Number(plan.start_date?.slice(0, 4)) || new Date().getFullYear());
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setStatus("");
    setSaving(true);
    try {
      if (hsa.some((row) => row.coverage !== "ineligible" && row.eligible_months?.length === 0)) {
        throw new Error("Select at least one eligible HSA month, or choose Not eligible.");
      }
      for (const periods of [hsa, payroll]) {
        if (
          periods.some((row, i) =>
            periods
              .slice(0, i)
              .some(
                (other) =>
                  row.owner === other.owner &&
                  Math.max(row.start_year, other.start_year) <=
                    Math.min(row.end_year ?? 2300, other.end_year ?? 2300),
              ),
          )
        ) {
          throw new Error(
            "Coverage periods for the same person must not overlap. Adjust the first or last year.",
          );
        }
      }
      await onSave({
        ...DEFAULT_TAX_SETTINGS,
        ...plan.tax_settings,
        hsa_coverage: hsa,
        state_payroll_coverage: payroll,
        ca_exemption_eligible_owners: exempt,
        state_payroll_paid_year_to_date: paid,
        ca_dependents_by_year: dependents,
        state_payroll_wages_year_to_date: stateWages,
      });
      setStatus("Coverage saved");
    } catch (error) {
      setStatus(
        error instanceof Error
          ? error.message
          : "Could not save coverage. Your entries are retained.",
      );
    } finally {
      setSaving(false);
    }
  }
  return (
    <details style={{ marginTop: 16 }}>
      <summary>Health savings & work coverage</summary>
      <p>Unknown coverage uses existing estimates.</p>
      <form onSubmit={save}>
        <fieldset disabled={saving} style={{ border: 0, padding: 0 }}>
          <h4>HSA eligibility</h4>
          <p>Enter eligible HSA months for each year in the period.</p>
          {hsa.length === 0 && <p>HSA eligibility unknown.</p>}
          {hsa.map((row, i) => {
            const change = (patch: Partial<HSACoverage>) =>
              setHsa(hsa.map((r, n) => (n === i ? { ...r, ...patch } : r)));
            return (
              <fieldset key={i}>
                <legend>HSA period {i + 1}</legend>
                <PeriodFields row={row} change={change} />
                <label>
                  Health coverage
                  <select
                    value={row.coverage}
                    onChange={(e) =>
                      change({ coverage: e.target.value as HSACoverage["coverage"] })
                    }
                  >
                    <option value="self_only">Self-only HDHP</option>
                    <option value="family">Family HDHP</option>
                    <option value="ineligible">Not eligible for HSA contributions</option>
                  </select>
                </label>
                <label>
                  Employee HSA funding
                  <select
                    value={row.payroll_funding ?? ""}
                    onChange={(e) =>
                      change({
                        payroll_funding: e.target.value
                          ? (e.target.value as "cafeteria" | "direct")
                          : null,
                      })
                    }
                  >
                    <option value="">Unknown</option>
                    <option value="cafeteria">Section 125 salary reduction through work</option>
                    <option value="direct">Direct / after-tax contribution</option>
                  </select>
                </label>
                <p>
                  Enter salary before HSA deductions; opening tax-history wages after section 125
                  deductions. Employer HSA funding goes in Income allocation.
                </p>
                {row.coverage !== "ineligible" && (
                  <div role="group" aria-label="Eligible months">
                    {months.map((m, index) => {
                      const selected = row.eligible_months ?? months.map((_, n) => n + 1);
                      return (
                        <label key={m} style={{ display: "inline-flex", margin: 8 }}>
                          <input
                            type="checkbox"
                            checked={selected.includes(index + 1)}
                            onChange={(e) =>
                              change({
                                eligible_months: e.target.checked
                                  ? [...selected, index + 1].sort((a, b) => a - b)
                                  : selected.filter((n) => n !== index + 1),
                              })
                            }
                          />
                          {m}
                        </label>
                      );
                    })}
                  </div>
                )}
                <button type="button" onClick={() => setHsa(hsa.filter((_, n) => n !== i))}>
                  Remove HSA period {i + 1}
                </button>
              </fieldset>
            );
          })}
          <button
            type="button"
            onClick={() =>
              setHsa([
                ...hsa,
                {
                  owner: "self",
                  start_year: year,
                  end_year: year,
                  coverage: "ineligible",
                  eligible_months: [],
                },
              ])
            }
          >
            Add HSA period
          </button>
          <h4>California personal exemption</h4>
          <p>Select people who cannot be claimed as dependents.</p>
          <label>
            Eligibility
            <select
              value={exempt === null ? "unknown" : "known"}
              onChange={(e) => setExempt(e.target.value === "unknown" ? null : [])}
            >
              <option value="unknown">Unknown</option>
              <option value="known">I know who is eligible</option>
            </select>
          </label>
          {exempt !== null &&
            (["self", "spouse"] as const).map((owner) => (
              <label key={owner} style={{ display: "block" }}>
                <input
                  type="checkbox"
                  checked={exempt.includes(owner)}
                  onChange={(e) =>
                    setExempt(
                      e.target.checked ? [...exempt, owner] : exempt.filter((o) => o !== owner),
                    )
                  }
                />
                {owner === "self" ? "Primary person eligible" : "Partner eligible"}
              </label>
            ))}
          {exempt?.length === 0 && <p>Explicitly no eligible personal exemptions.</p>}
          <h4>California dependents</h4>
          <p>
            Dependent counts apply to each listed year only. Blank means unknown; zero means none.
          </p>
          {Object.entries(dependents)
            .sort()
            .map(([year, count]) => (
              <div key={year}>
                <label>
                  Qualifying dependents in {year}
                  <input
                    type="number"
                    required
                    min="0"
                    max="30"
                    step="1"
                    value={count}
                    onChange={(e) =>
                      setDependents({ ...dependents, [year]: Number(e.target.value) })
                    }
                  />
                </label>
                <button
                  type="button"
                  onClick={() =>
                    setDependents(
                      Object.fromEntries(
                        Object.entries(dependents).filter(([key]) => key !== year),
                      ),
                    )
                  }
                >
                  Remove {year}
                </button>
              </div>
            ))}
          <label>
            Dependent tax year
            <input
              type="number"
              min="2025"
              max="2300"
              step="1"
              value={dependentYear}
              onChange={(e) => setDependentYear(Number(e.target.value))}
            />
          </label>
          <button
            type="button"
            disabled={
              dependentYear < 2025 || dependentYear > 2300 || !Number.isInteger(dependentYear)
            }
            onClick={() =>
              setDependents({ ...dependents, [dependentYear]: dependents[dependentYear] ?? 0 })
            }
          >
            Add dependent year
          </button>
          <h4>Employee state programs</h4>
          <p>
            Applies to all W-2 wages in the selected work state. Split-state wages and
            self-employment are unsupported. Premiums appear under spending.
          </p>
          {payroll.length === 0 && <p>Employee coverage unknown.</p>}
          {payroll.map((row, i) => {
            const change = (patch: Partial<StatePayrollCoverage>) =>
              setPayroll(payroll.map((r, n) => (n === i ? { ...r, ...patch } : r)));
            return (
              <fieldset key={i}>
                <legend>Work coverage period {i + 1}</legend>
                <PeriodFields row={row} change={change} />
                <label>
                  Work state
                  <select
                    value={row.state_code}
                    onChange={(e) =>
                      change({
                        state_code: e.target.value as "CA" | "WA",
                        ca_sdi: false,
                        wa_paid_leave: false,
                        wa_cares: false,
                      })
                    }
                  >
                    <option value="CA">California</option>
                    <option value="WA">Washington</option>
                  </select>
                </label>
                {(row.state_code === "CA"
                  ? [["ca_sdi", "California SDI"]]
                  : [
                      ["wa_paid_leave", "Washington Paid Leave"],
                      ["wa_cares", "Washington Cares"],
                    ]
                ).map(([key, label]) => (
                  <label key={key} style={{ display: "block" }}>
                    <input
                      type="checkbox"
                      checked={!!row[key as "ca_sdi"]}
                      onChange={(e) => change({ [key]: e.target.checked })}
                    />
                    {label}
                  </label>
                ))}
                <label>
                  Employer pays this share of your required premium (%)
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="any"
                    required
                    value={(row.employer_pays_fraction ?? 0) * 100}
                    onChange={(e) =>
                      change({ employer_pays_fraction: Number(e.target.value) / 100 })
                    }
                  />
                </label>
                {(row.employer_pays_fraction ?? 0) > 0 && (
                  <p>
                    Includes only your share; any taxable-wage effect of employer-paid premiums is
                    not modeled.
                  </p>
                )}
                <p>Leave every program unchecked only if this person is explicitly not covered.</p>
                <button type="button" onClick={() => setPayroll(payroll.filter((_, n) => n !== i))}>
                  Remove work period {i + 1}
                </button>
              </fieldset>
            );
          })}
          <button
            type="button"
            onClick={() =>
              setPayroll([
                ...payroll,
                { owner: "self", start_year: year, end_year: year, state_code: "CA" },
              ])
            }
          >
            Add work coverage period
          </button>
          <h4>State wages before this plan starts</h4>
          <p>Opening-year state-program wages. Blank uses W-2 tax history; zero means none.</p>
          {(["self", "spouse"] as const).map((owner) => (
            <label key={owner}>
              {owner === "self" ? "Primary person" : "Partner"}{" "}
              {moneyLabel("earlier state wages ($)")}
              <MoneyInput
                min="0"
                step="0.01"
                value={stateWages[owner] ?? ""}
                onValueChange={(amount) =>
                  setStateWages({
                    ...stateWages,
                    [owner]: amount === "" ? undefined : Number(amount),
                  })
                }
              />
            </label>
          ))}
          <h4>Premiums paid before this plan starts</h4>
          <p>Opening tax year only. Blank means unpaid.</p>
          {(["California SDI", "Washington Paid Leave", "Washington Cares"] as const).map(
            (name) => (
              <label key={name} style={{ display: "block" }}>
                {name} {moneyLabel("already paid ($)")}
                <MoneyInput
                  min="0"
                  step="0.01"
                  value={paid[name] ?? ""}
                  onValueChange={(amount) =>
                    setPaid({ ...paid, [name]: amount === "" ? undefined : Number(amount) })
                  }
                />
              </label>
            ),
          )}
          <button type="submit">{saving ? "Saving…" : "Save coverage"}</button>
          <p role="status">{status}</p>
        </fieldset>
      </form>
    </details>
  );
}
