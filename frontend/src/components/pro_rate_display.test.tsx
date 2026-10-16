import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProRateDisplay } from "./pro_rate_display";

describe("ProRateDisplay", () => {
  it("explains inactive month overrides without promising dollar proration", () => {
    render(
      <ProRateDisplay
        startMonth={7}
        endMonth={6}
        hasStartMilestone={false}
        hasEndMilestone={false}
      />,
    );
    expect(screen.getByText(/Requires a Start Milestone/)).toBeInTheDocument();
    expect(screen.getByText(/Requires an End Milestone/)).toBeInTheDocument();
    expect(screen.getByRole("status")).not.toHaveTextContent("$");
  });

  it("describes separate milestone boundary years instead of a combined seasonal amount", () => {
    render(<ProRateDisplay startMonth={12} endMonth={1} hasStartMilestone hasEndMilestone />);
    expect(
      screen.getByText(/Starts in Dec in the year the Start Milestone is reached/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Ends after Jan in the year the End Milestone is reached/),
    ).toBeInTheDocument();
    expect(screen.getByText(/not a seasonal schedule/)).toBeInTheDocument();
    expect(screen.getByRole("status")).not.toHaveTextContent("$");
  });

  it("handles each boundary independently and updates when a milestone is removed", () => {
    const { rerender } = render(
      <ProRateDisplay startMonth={7} endMonth={6} hasStartMilestone hasEndMilestone={false} />,
    );
    expect(screen.getByText(/Starts in Jul/)).toBeInTheDocument();
    expect(screen.getByText(/Requires an End Milestone/)).toBeInTheDocument();
    rerender(
      <ProRateDisplay startMonth={7} endMonth={6} hasStartMilestone={false} hasEndMilestone />,
    );
    expect(screen.getByText(/Requires a Start Milestone/)).toBeInTheDocument();
    expect(screen.getByText(/Ends after Jun/)).toBeInTheDocument();
    expect(screen.queryByText(/Starts in Jul/)).not.toBeInTheDocument();
  });

  it("returns null when neither month is overridden", () => {
    const { container } = render(
      <ProRateDisplay startMonth={null} endMonth={null} hasStartMilestone hasEndMilestone />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("also explains explicit January and December selections without milestones", () => {
    render(
      <ProRateDisplay
        startMonth={1}
        endMonth={12}
        hasStartMilestone={false}
        hasEndMilestone={false}
      />,
    );
    expect(screen.getByText(/Requires a Start Milestone/)).toBeInTheDocument();
    expect(screen.getByText(/Requires an End Milestone/)).toBeInTheDocument();
  });
});
