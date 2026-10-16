import { moneyLabel } from "@/utils/format";
import type { Income, PensionFormula } from "@/types/plan";
import MoneyInput from "@/components/money_input";

/** Blank means the pension pays the entered income amount. */
export type PensionKind = "" | PensionFormula["kind"];

/** Editable pension formula; numbers stay text until the form is saved. */
export interface PensionDraft {
  kind: PensionKind;
  linkedSalary: string;
  benefitPercent: string;
  priorService: string;
  averageYears: string;
  flatAmount: string;
  cola: string;
}

export function pensionDraft(formula: PensionFormula | null | undefined): PensionDraft {
  return {
    kind: formula?.kind ?? "",
    linkedSalary: formula?.linked_income_id ?? "",
    benefitPercent: String(formula?.benefit_percent_per_year ?? 1.5),
    priorService: String(formula?.years_of_service_before_plan ?? 0),
    averageYears: String(formula?.final_average_years ?? 3),
    flatAmount: String(formula?.flat_annual_amount ?? 0),
    cola: formula?.cola_percent?.toString() ?? "",
  };
}

interface PensionFormulaFieldsProps {
  draft: PensionDraft;
  onChange: (draft: PensionDraft) => void;
  /** The plan's incomes; the recipient's recurring salaries can drive the formula. */
  incomes: Income[];
  /** The income being edited, which cannot be its own linked salary. */
  incomeId?: string;
  owner: "self" | "spouse";
}

/** Formula, service and salary inputs of a qualified pension. */
export function PensionFormulaFields({
  draft,
  onChange,
  incomes,
  incomeId,
  owner,
}: PensionFormulaFieldsProps) {
  const set = (patch: Partial<PensionDraft>) => onChange({ ...draft, ...patch });
  return (
    <fieldset style={{ gridColumn: "1 / -1" }}>
      <legend>Pension benefit</legend>
      <label>
        Benefit formula
        <select value={draft.kind} onChange={(e) => set({ kind: e.target.value as PensionKind })}>
          <option value="">Entered income amount</option>
          <option value="flat">Flat annual benefit</option>
          <option value="final_average">Final average pay</option>
          <option value="career_average">Career average pay</option>
        </select>
      </label>
      {draft.kind && (
        <>
          {draft.kind === "flat" ? (
            <label>
              {moneyLabel("Flat annual benefit (today’s dollars)")}
              <MoneyInput
                min={0}
                value={draft.flatAmount}
                onValueChange={(flatAmount) => set({ flatAmount })}
              />
            </label>
          ) : (
            <>
              <label>
                Linked salary
                <select
                  required
                  value={draft.linkedSalary}
                  onChange={(e) => set({ linkedSalary: e.target.value })}
                >
                  <option value="">Choose salary</option>
                  {incomes
                    .filter(
                      (i) =>
                        i.id !== incomeId &&
                        i.owner === owner &&
                        i.frequency !== "once" &&
                        i.is_earned_income &&
                        !i.is_social_security,
                    )
                    .map((i) => (
                      <option key={i.id} value={i.id}>
                        {i.name}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                Benefit percent per service year
                <input
                  type="number"
                  min={0}
                  max={100}
                  step="any"
                  value={draft.benefitPercent}
                  onChange={(e) => set({ benefitPercent: e.target.value })}
                />
              </label>
              <label>
                Service years before plan
                <input
                  type="number"
                  min={0}
                  max={100}
                  step="any"
                  value={draft.priorService}
                  onChange={(e) => set({ priorService: e.target.value })}
                />
              </label>
              {draft.kind === "final_average" && (
                <label>
                  Final average years
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={draft.averageYears}
                    onChange={(e) => set({ averageYears: e.target.value })}
                  />
                </label>
              )}
              <p>
                Prior service uses plan-start salary where earlier pay is unknown. Benefit freezes
                when payments start.
              </p>
            </>
          )}
          <label>
            Pension COLA (%)
            <input
              type="number"
              min={-100}
              max={100}
              step="any"
              placeholder="No COLA"
              value={draft.cola}
              onChange={(e) => set({ cola: e.target.value })}
            />
          </label>
        </>
      )}
    </fieldset>
  );
}
