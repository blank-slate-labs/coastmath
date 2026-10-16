import type { Milestone } from "@/types/plan";
import { MonthPicker } from "@/components/month_picker";
import { ProRateDisplay } from "@/components/pro_rate_display";

interface MilestoneChoice {
  label: string;
  /** Text of the blank option, which means plan start or plan end. */
  placeholder: string;
  value: string;
  onChange: (milestoneId: string) => void;
}

interface MonthChoice {
  label: string;
  placeholder?: string;
  value: number | null;
  onChange: (month: number | null) => void;
}

interface MilestoneWindowFieldsProps {
  milestones: Milestone[];
  start: MilestoneChoice;
  end: MilestoneChoice;
  startMonth: MonthChoice;
  endMonth: MonthChoice;
  /** From `milestoneWindowError`; marks the end select invalid. */
  windowError: string | null;
  /** From `milestoneWindowWarning`. */
  windowWarning: string | null;
  /** A Social Security claiming age, which sets the start month's default year. */
  claimingAge?: number | null;
  /** Folds the month pickers into a disclosure whose open state the caller keeps. */
  monthsDisclosure?: {
    className: string;
    summary: string;
    open: boolean;
    onToggle: (open: boolean) => void;
  };
}

/** Start and end milestones with their month pickers and the pro-rated months they imply. */
export function MilestoneWindowFields({
  milestones,
  start,
  end,
  startMonth,
  endMonth,
  windowError,
  windowWarning,
  claimingAge,
  monthsDisclosure,
}: MilestoneWindowFieldsProps) {
  const milestoneOptions = milestones.map((m) => (
    <option key={m.id} value={m.id}>
      {m.name}
    </option>
  ));
  const monthPickers = (
    <div
      style={
        monthsDisclosure
          ? { display: "flex", gap: 16, flexWrap: "wrap", marginTop: 8 }
          : { display: "flex", gap: 16, flexWrap: "wrap" }
      }
    >
      <div style={{ flex: 1 }}>
        <MonthPicker
          label={startMonth.label}
          placeholder={startMonth.placeholder}
          value={startMonth.value}
          onChange={startMonth.onChange}
        />
      </div>
      <div style={{ flex: 1 }}>
        <MonthPicker
          label={endMonth.label}
          placeholder={endMonth.placeholder}
          value={endMonth.value}
          onChange={endMonth.onChange}
        />
      </div>
    </div>
  );
  const proRate = (
    <ProRateDisplay
      startMonth={startMonth.value}
      endMonth={endMonth.value}
      hasStartMilestone={!!start.value}
      hasEndMilestone={!!end.value}
      claimingAge={claimingAge}
    />
  );

  return (
    <>
      <label>
        {start.label}
        <select value={start.value} onChange={(e) => start.onChange(e.target.value)}>
          <option value="">{start.placeholder}</option>
          {milestoneOptions}
        </select>
      </label>

      <label>
        {end.label}
        <select
          value={end.value}
          onChange={(e) => end.onChange(e.target.value)}
          aria-invalid={windowError ? true : undefined}
        >
          <option value="">{end.placeholder}</option>
          {milestoneOptions}
        </select>
        {windowError && (
          <span
            role="alert"
            style={{ display: "block", fontSize: 12, color: "var(--color-danger)" }}
          >
            {windowError}
          </span>
        )}
        {windowWarning && (
          <span
            role="status"
            style={{ display: "block", fontSize: 12, color: "var(--color-warning, #b45309)" }}
          >
            {windowWarning}
          </span>
        )}
      </label>

      {monthsDisclosure ? (
        <details
          className={monthsDisclosure.className}
          open={monthsDisclosure.open}
          onToggle={(e) => monthsDisclosure.onToggle(e.currentTarget.open)}
        >
          <summary>{monthsDisclosure.summary}</summary>
          {monthPickers}
          {proRate}
        </details>
      ) : (
        <>
          {monthPickers}
          <div style={{ gridColumn: "1 / -1" }}>{proRate}</div>
        </>
      )}
    </>
  );
}
