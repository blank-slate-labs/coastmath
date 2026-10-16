import type { ForgivenessExclusionBasis, LiabilityForgiveness, Milestone } from "@/types/plan";
import { moneyLabel } from "@/utils/format";
import MoneyInput from "@/components/money_input";

export type ForgivenessDraft = {
  enabled: boolean;
  trigger: "year" | "milestone";
  year: string;
  milestoneId: string;
  amount: string;
  treatment: "taxable" | "declared_exclusion";
  basis: ForgivenessExclusionBasis | "";
  excludedAmount: string;
};

export const BASIS_LABELS: Record<ForgivenessExclusionBasis, string> = {
  bankruptcy: "Discharged in a bankruptcy case",
  insolvency: "Insolvent immediately before the cancellation",
  qualified_farm_debt: "Qualified farm debt",
  qualified_real_property_business_debt: "Qualified real property business debt",
  qualified_principal_residence: "Qualified principal residence debt",
  other_declared: "Other exclusion I have confirmed with a tax professional",
};

export function forgivenessDraft(saved: LiabilityForgiveness | null | undefined): ForgivenessDraft {
  return {
    enabled: !!saved,
    trigger: saved?.milestone_id ? "milestone" : "year",
    year: saved?.year != null ? String(saved.year) : "",
    milestoneId: saved?.milestone_id ?? "",
    amount: saved?.amount != null ? String(saved.amount) : "",
    treatment: saved?.tax_treatment ?? "taxable",
    basis: saved?.exclusion_basis ?? "",
    excludedAmount: saved?.excluded_amount != null ? String(saved.excluded_amount) : "",
  };
}

/** The first problem with the draft, or null. */
export function forgivenessProblem(d: ForgivenessDraft): string | null {
  if (!d.enabled) return null;
  if (
    d.trigger === "year" &&
    !(
      Number.isInteger(Number(d.year)) &&
      Number(d.year) >= 1900 &&
      Number(d.year) <= 2200 &&
      d.year.trim() !== ""
    )
  )
    return "Enter the year the debt is forgiven (1900 to 2200).";
  if (d.trigger === "milestone" && !d.milestoneId)
    return "Choose the milestone that triggers the forgiveness.";
  if (d.amount.trim() !== "" && !(Number(d.amount) > 0))
    return "The forgiven amount must be more than zero, or blank for the whole balance.";
  if (d.treatment === "declared_exclusion") {
    if (!d.basis) return "Choose the basis for the exclusion you are declaring.";
    if (d.excludedAmount.trim() !== "" && !(Number(d.excludedAmount) >= 0))
      return "The excluded amount cannot be negative.";
    if (
      d.amount.trim() !== "" &&
      d.excludedAmount.trim() !== "" &&
      Number(d.excludedAmount) > Number(d.amount)
    )
      return "The excluded amount cannot exceed the forgiven amount.";
  }
  return null;
}

/** The wire shape for a draft, null when forgiveness is off. */
export function forgivenessPayload(d: ForgivenessDraft): LiabilityForgiveness | null {
  if (!d.enabled) return null;
  const out: LiabilityForgiveness = {
    year: d.trigger === "year" ? Number(d.year) : null,
    milestone_id: d.trigger === "milestone" ? d.milestoneId : null,
    amount: d.amount.trim() === "" ? null : Number(d.amount),
    tax_treatment: d.treatment,
  };
  if (d.treatment === "declared_exclusion") {
    out.exclusion_basis = d.basis || null;
    out.excluded_amount = d.excludedAmount.trim() === "" ? null : Number(d.excludedAmount);
  }
  return out;
}

type Props = {
  value: ForgivenessDraft;
  onChange: (value: ForgivenessDraft) => void;
  milestones: Milestone[];
};

export default function LiabilityForgivenessFields({ value, onChange, milestones }: Props) {
  const set = (patch: Partial<ForgivenessDraft>) => onChange({ ...value, ...patch });
  const problem = forgivenessProblem(value);
  return (
    <fieldset style={{ display: "grid", gap: 8 }}>
      <legend>Debt forgiveness</legend>
      <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          type="checkbox"
          checked={value.enabled}
          onChange={(e) => set({ enabled: e.target.checked })}
        />
        Part or all of this loan is forgiven once
      </label>
      {value.enabled && (
        <>
          <label>
            Forgiven when
            <select
              value={value.trigger}
              onChange={(e) => set({ trigger: e.target.value as ForgivenessDraft["trigger"] })}
              style={{ display: "block", width: "100%" }}
            >
              <option value="year">A calendar year</option>
              <option value="milestone">A milestone</option>
            </select>
          </label>
          {value.trigger === "year" ? (
            <label>
              Forgiveness year
              <input
                type="number"
                min={1900}
                max={2200}
                step={1}
                value={value.year}
                onChange={(e) => set({ year: e.target.value })}
                style={{ display: "block", width: "100%" }}
              />
            </label>
          ) : (
            <label>
              Forgiveness milestone
              <select
                value={value.milestoneId}
                onChange={(e) => set({ milestoneId: e.target.value })}
                style={{ display: "block", width: "100%" }}
              >
                <option value="">— Choose —</option>
                {milestones.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            {moneyLabel("Amount forgiven ($; blank forgives the whole remaining balance)")}
            <MoneyInput
              min="0.01"
              step="0.01"
              value={value.amount}
              onValueChange={(amount) => set({ amount })}
              style={{ display: "block", width: "100%" }}
            />
          </label>
          <label>
            Tax treatment
            <select
              value={value.treatment}
              onChange={(e) => set({ treatment: e.target.value as ForgivenessDraft["treatment"] })}
              style={{ display: "block", width: "100%" }}
            >
              <option value="taxable">Taxable cancellation-of-debt income</option>
              <option value="declared_exclusion">I declare an exclusion</option>
            </select>
          </label>
          {value.treatment === "declared_exclusion" && (
            <>
              <label>
                Basis for the exclusion
                <select
                  value={value.basis}
                  onChange={(e) => set({ basis: e.target.value as ForgivenessDraft["basis"] })}
                  style={{ display: "block", width: "100%" }}
                >
                  <option value="">— Choose —</option>
                  {(Object.keys(BASIS_LABELS) as ForgivenessExclusionBasis[]).map((b) => (
                    <option key={b} value={b}>
                      {BASIS_LABELS[b]}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {moneyLabel("Excluded amount ($; blank excludes all of it)")}
                <MoneyInput
                  min="0"
                  step="0.01"
                  value={value.excludedAmount}
                  onValueChange={(excludedAmount) => set({ excludedAmount })}
                  style={{ display: "block", width: "100%" }}
                />
              </label>
            </>
          )}
          <small>
            No cash arrives. The loan balance drops once. Forgiven debt is taxable income unless an
            exclusion applies to you; the plan records the exclusion you declare and does not decide
            whether you qualify.
          </small>
          {problem && (
            <span role="alert" style={{ fontSize: 12, color: "var(--color-danger)" }}>
              {problem}
            </span>
          )}
        </>
      )}
    </fieldset>
  );
}
