import { useState } from "react";
import type { Milestone, PlanType } from "@/types/plan";
import { MilestoneWindowFields } from "@/components/milestone_window_fields";

interface IncomeTimingFieldsProps {
  milestones: Milestone[];
  isSocialSecurity: boolean;
  /** "Now" plans label the default start "Now"; fixed-date plans keep "Plan start". */
  planType: PlanType;
  claimingAge: number | null;
  /** Calendar year the recipient reaches the claiming age. */
  claimYear: number | null;
  startMilestoneId: string;
  onStartMilestoneChange: (id: string) => void;
  endMilestoneId: string;
  onEndMilestoneChange: (id: string) => void;
  startMonth: number | null;
  onStartMonthChange: (month: number | null) => void;
  endMonth: number | null;
  onEndMonthChange: (month: number | null) => void;
  startMilestone?: Milestone;
  /** Year the start milestone resolves to, when known without a projection. */
  startYear: number | null;
  windowError: string | null;
  windowWarning: string | null;
}

/** When an income starts and ends, summarised in words above the milestone and month choices. */
export function IncomeTimingFields({
  milestones,
  isSocialSecurity,
  planType,
  claimingAge,
  claimYear,
  startMilestoneId,
  onStartMilestoneChange,
  endMilestoneId,
  onEndMilestoneChange,
  startMonth,
  onStartMonthChange,
  endMonth,
  onEndMonthChange,
  startMilestone,
  startYear,
  windowError,
  windowWarning,
}: IncomeTimingFieldsProps) {
  // Wage timing sits behind its summary; a saved window that needs fixing opens it.
  const [timingOpen, setTimingOpen] = useState(Boolean(windowError));
  // Months are rarely needed; a saved month opens them.
  const [monthsOpen, setMonthsOpen] = useState(startMonth != null || endMonth != null);

  // Social Security keeps its plan-relative wording; wages read as "now" in a Now plan.
  const wageNow = !isSocialSecurity && planType === "NOW";
  const startSummary = startMilestoneId
    ? `Starts at ${startMilestone?.name ?? "the selected milestone"}${startYear != null ? ` (${startYear})` : "; year depends on the projection"}`
    : isSocialSecurity && claimingAge != null
      ? `Starts at claiming age ${claimingAge}${claimYear != null ? ` (${claimYear})` : ""}`
      : wageNow
        ? "Starts now"
        : "Starts when this plan begins";
  const endSummary = endMilestoneId
    ? `ends at ${milestones.find((m) => m.id === endMilestoneId)?.name ?? "the selected milestone"}`
    : isSocialSecurity
      ? "continues through plan end"
      : "continues to end of plan";
  const timingSummary = `${startSummary}; ${endSummary}`;

  const timingControls = (
    <MilestoneWindowFields
      milestones={milestones}
      start={{
        label: "Start milestone",
        placeholder:
          isSocialSecurity && claimingAge != null
            ? `Claiming age ${claimingAge}`
            : wageNow
              ? "Now"
              : "Plan start",
        value: startMilestoneId,
        onChange: onStartMilestoneChange,
      }}
      end={{
        label: "End milestone",
        placeholder: isSocialSecurity ? "Through plan end" : "End of plan",
        value: endMilestoneId,
        onChange: onEndMilestoneChange,
      }}
      startMonth={{
        label: "Start month",
        placeholder:
          startMilestoneId || (isSocialSecurity && claimingAge != null)
            ? "Default: Jan"
            : "Not applied",
        value: startMonth,
        onChange: onStartMonthChange,
      }}
      endMonth={{
        label: "End month",
        placeholder: endMilestoneId ? "Default: Dec" : "Not applied",
        value: endMonth,
        onChange: onEndMonthChange,
      }}
      windowError={windowError}
      windowWarning={windowWarning}
      claimingAge={isSocialSecurity ? claimingAge : null}
      monthsDisclosure={{
        className: "form-advanced income-months",
        summary: "Start and end months",
        open: monthsOpen,
        onToggle: setMonthsOpen,
      }}
    />
  );

  return isSocialSecurity ? (
    <fieldset className="income-timing form-field-group">
      <legend>When you receive this income</legend>
      <p className="form-group-summary">{timingSummary}.</p>
      {timingControls}
    </fieldset>
  ) : (
    <details
      className="form-advanced income-timing"
      open={timingOpen}
      onToggle={(e) => setTimingOpen(e.currentTarget.open)}
    >
      <summary>{timingSummary}</summary>
      <div className="form-field-group">{timingControls}</div>
    </details>
  );
}
