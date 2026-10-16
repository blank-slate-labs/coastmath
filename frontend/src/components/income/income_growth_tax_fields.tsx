import { moneyLabel } from "@/utils/format";
import MoneyInput from "@/components/money_input";
import { GrowthScheduleEditor, type SegmentRow } from "@/components/income_growth_schedule_editor";

interface IncomeGrowthTaxFieldsProps {
  /** Opens the section, as when the form shows a validation error. */
  forceOpen: boolean;
  isActive: boolean;
  onActiveChange: (active: boolean) => void;
  growthRate: string;
  onGrowthRateChange: (rate: string) => void;
  growthCap: string;
  onGrowthCapChange: (cap: string) => void;
  growthCapInflationLinked: boolean;
  onGrowthCapInflationLinkedChange: (linked: boolean) => void;
  /** Year-segment growth, offered when `scheduleAllowed`. */
  segmentRows: SegmentRow[];
  onSegmentRowsChange: (rows: SegmentRow[]) => void;
  scheduleAllowed: boolean;
  isSocialSecurity: boolean;
  /** Other income, which the user marks earned or not. */
  isOther: boolean;
  isEarnedIncome: boolean;
  onEarnedIncomeChange: (earned: boolean) => void;
  /** Whether the income counts as earned: a salary, or Other marked earned. */
  earned: boolean;
  isSelfEmployed: boolean;
  onSelfEmployedChange: (selfEmployed: boolean) => void;
  withholdingPercent: string;
  onWithholdingPercentChange: (percent: string) => void;
}

/** The collapsed "Growth and tax settings" section of the income form. */
export function IncomeGrowthTaxFields({
  forceOpen,
  isActive,
  onActiveChange,
  growthRate,
  onGrowthRateChange,
  growthCap,
  onGrowthCapChange,
  growthCapInflationLinked,
  onGrowthCapInflationLinkedChange,
  segmentRows,
  onSegmentRowsChange,
  scheduleAllowed,
  isSocialSecurity,
  isOther,
  isEarnedIncome,
  onEarnedIncomeChange,
  earned,
  isSelfEmployed,
  onSelfEmployedChange,
  withholdingPercent,
  onWithholdingPercentChange,
}: IncomeGrowthTaxFieldsProps) {
  return (
    <details className="form-advanced" open={forceOpen || !isActive ? true : undefined}>
      <summary>Growth and tax settings</summary>
      <div className="form-field-group">
        <label style={{ gridColumn: "1 / -1" }}>
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => onActiveChange(e.target.checked)}
          />{" "}
          Include in projection
        </label>

        <label>
          Growth rate (% per year)
          <input
            type="number"
            step="0.1"
            min="-100"
            max="100"
            value={growthRate}
            onChange={(e) => onGrowthRateChange(e.target.value)}
            placeholder="e.g. 3.0"
          />
        </label>
        <div style={{ gridColumn: "1 / -1", color: "var(--text-secondary)", fontSize: 12 }}>
          {moneyLabel(
            "Enter the amount in today's dollars. Growth compounds from the plan's start year even if this income begins later.",
          )}
          {earned
            ? " A blank rate follows the Wage growth assumption. Use 0 for a fixed nominal amount."
            : isSocialSecurity
              ? " A blank rate follows the Social Security COLA assumption. Use 0 for a fixed nominal amount."
              : " A blank rate keeps a fixed nominal amount."}
        </div>
        <label>
          {moneyLabel("Growth cap ($ per year, optional)")}
          <MoneyInput
            min="0"
            step="0.01"
            value={growthCap}
            onValueChange={onGrowthCapChange}
            placeholder="No cap"
          />
        </label>
        {growthCap.trim() !== "" && (
          <label style={{ gridColumn: "1 / -1" }}>
            <input
              type="checkbox"
              checked={growthCapInflationLinked}
              onChange={(e) => onGrowthCapInflationLinkedChange(e.target.checked)}
            />{" "}
            {moneyLabel("Cap rises with inflation (entered in today's dollars)")}
          </label>
        )}
        {scheduleAllowed && (
          <GrowthScheduleEditor
            rows={segmentRows}
            onChange={onSegmentRowsChange}
            defaultStartYear={new Date().getFullYear() + 1}
          />
        )}
        {isOther && (
          <label style={{ gridColumn: "1 / -1" }}>
            <input
              type="checkbox"
              checked={isEarnedIncome}
              onChange={(e) => onEarnedIncomeChange(e.target.checked)}
            />{" "}
            Earned income (wages or self-employment; affects payroll tax and retirement contribution
            eligibility)
          </label>
        )}
        {earned && (
          <label style={{ gridColumn: "1 / -1" }}>
            <input
              type="checkbox"
              checked={isSelfEmployed}
              onChange={(e) => onSelfEmployedChange(e.target.checked)}
            />{" "}
            Self-employed (self-employment tax instead of employee FICA; eligible for the QBI
            deduction)
          </label>
        )}
        {earned && isSelfEmployed && (
          <div style={{ gridColumn: "1 / -1", color: "var(--text-secondary)", fontSize: 12 }}>
            Enter net business profit after business expenses, before self-employment tax. The
            projection applies the ordinary Schedule SE earnings adjustment automatically.
          </div>
        )}

        <label>
          Tax withholding (% of gross)
          <input
            type="number"
            min="0"
            max="100"
            step="0.5"
            value={withholdingPercent}
            onChange={(e) => onWithholdingPercentChange(e.target.value)}
            placeholder="0"
          />
          <span style={{ display: "block", fontSize: 12, color: "var(--text-secondary)" }}>
            Withheld during the year and credited against the actual tax bill. Leave blank to settle
            the full liability at tax time.
          </span>
        </label>
      </div>
    </details>
  );
}
