import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { IncomeTimingFields } from "./income_timing_fields";
import type { Milestone } from "@/types/plan";

const retirement: Milestone = {
  id: "ret",
  plan_id: "p",
  name: "Retirement",
  trigger_type: "age",
  trigger_value: 65,
  trigger_date: null,
  metric: null,
  expense_multiple: null,
  relative_to_id: null,
  offset_years: 0,
  sort_order: 0,
};

function renderFields(overrides: Partial<React.ComponentProps<typeof IncomeTimingFields>> = {}) {
  return render(
    <IncomeTimingFields
      milestones={[retirement]}
      isSocialSecurity={false}
      planType="NOW"
      claimingAge={67}
      claimYear={2033}
      startMilestoneId=""
      onStartMilestoneChange={vi.fn()}
      endMilestoneId="ret"
      onEndMilestoneChange={vi.fn()}
      startMonth={null}
      onStartMonthChange={vi.fn()}
      endMonth={null}
      onEndMonthChange={vi.fn()}
      startYear={null}
      windowError={null}
      windowWarning={null}
      {...overrides}
    />,
  );
}

describe("IncomeTimingFields", () => {
  it("folds wage timing behind a summary of the window", () => {
    const { container } = renderFields();
    const timing = container.querySelector("details.income-timing") as HTMLDetailsElement;
    expect(timing.open).toBe(false);
    expect(timing.querySelector("summary")).toHaveTextContent("Starts now; ends at Retirement");
    expect((screen.getByLabelText("Start milestone") as HTMLSelectElement).options[0].text).toBe(
      "Now",
    );
    const months = container.querySelector("details.income-months") as HTMLDetailsElement;
    expect(months.open).toBe(false);
  });

  it("opens on a saved window error and on saved months", () => {
    const { container } = renderFields({
      windowError: "The end milestone comes before the start.",
      startMonth: 4,
    });
    expect((container.querySelector("details.income-timing") as HTMLDetailsElement).open).toBe(
      true,
    );
    expect((container.querySelector("details.income-months") as HTMLDetailsElement).open).toBe(
      true,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The end milestone comes before the start.",
    );
  });

  it("keeps Social Security timing visible with claiming-age wording", () => {
    const { container } = renderFields({ isSocialSecurity: true, endMilestoneId: "" });
    expect(container.querySelector("details.income-timing")).toBeNull();
    expect(screen.getByText("When you receive this income")).toBeInTheDocument();
    expect(
      screen.getByText("Starts at claiming age 67 (2033); continues through plan end."),
    ).toBeInTheDocument();
    expect((screen.getByLabelText("Start milestone") as HTMLSelectElement).options[0].text).toBe(
      "Claiming age 67",
    );
    expect((screen.getByLabelText("End milestone") as HTMLSelectElement).options[0].text).toBe(
      "Through plan end",
    );
  });
});
