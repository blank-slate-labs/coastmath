import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MilestoneWindowFields } from "./milestone_window_fields";
import type { Milestone } from "@/types/plan";

function ms(id: string, name: string): Milestone {
  return {
    id,
    plan_id: "p",
    name,
    trigger_type: "age",
    trigger_value: 65,
    trigger_date: null,
    metric: null,
    expense_multiple: null,
    relative_to_id: null,
    offset_years: 0,
    sort_order: 0,
  };
}

const milestones = [ms("m1", "Retirement"), ms("m2", "Age 70")];

// The alert and status sit inside the end label, so its accessible name carries their text.
const endSelect = () => screen.getAllByRole("combobox")[1];

function renderFields(overrides: Partial<React.ComponentProps<typeof MilestoneWindowFields>> = {}) {
  const handlers = {
    start: vi.fn(),
    end: vi.fn(),
    startMonth: vi.fn(),
    endMonth: vi.fn(),
  };
  const utils = render(
    <MilestoneWindowFields
      milestones={milestones}
      start={{
        label: "Start",
        placeholder: "From plan start",
        value: "",
        onChange: handlers.start,
      }}
      end={{ label: "End", placeholder: "Through plan end", value: "", onChange: handlers.end }}
      startMonth={{ label: "Start month", value: null, onChange: handlers.startMonth }}
      endMonth={{ label: "End month", value: null, onChange: handlers.endMonth }}
      windowError={null}
      windowWarning={null}
      {...overrides}
    />,
  );
  return { ...utils, handlers };
}

describe("MilestoneWindowFields", () => {
  it("lists the milestones after each placeholder and reports the chosen ids", () => {
    const { handlers } = renderFields();
    const start = screen.getByLabelText("Start") as HTMLSelectElement;
    const end = screen.getByLabelText("End") as HTMLSelectElement;
    expect(Array.from(start.options).map((o) => o.text)).toEqual([
      "From plan start",
      "Retirement",
      "Age 70",
    ]);
    expect(end.options[0].text).toBe("Through plan end");
    fireEvent.change(start, { target: { value: "m1" } });
    fireEvent.change(end, { target: { value: "m2" } });
    expect(handlers.start).toHaveBeenCalledWith("m1");
    expect(handlers.end).toHaveBeenCalledWith("m2");
  });

  it("shows the window error as an alert and marks the end select invalid", () => {
    renderFields({ windowError: "The end milestone comes before the start." });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The end milestone comes before the start.",
    );
    expect(endSelect()).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Start")).not.toHaveAttribute("aria-invalid");
  });

  it("shows a warning as a status without marking the end select invalid", () => {
    renderFields({ windowWarning: "The order depends on the projection." });
    expect(screen.getByRole("status")).toHaveTextContent("The order depends on the projection.");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(endSelect()).not.toHaveAttribute("aria-invalid");
  });

  it("passes month choices to their setters and shows the pro-rated months", () => {
    const { handlers, rerender } = renderFields();
    fireEvent.change(screen.getByLabelText("Start month"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("End month"), { target: { value: "" } });
    expect(handlers.startMonth).toHaveBeenCalledWith(4);
    expect(handlers.endMonth).toHaveBeenCalledWith(null);
    expect(screen.queryByRole("status")).toBeNull();

    rerender(
      <MilestoneWindowFields
        milestones={milestones}
        start={{ label: "Start", placeholder: "-", value: "", onChange: handlers.start }}
        end={{ label: "End", placeholder: "-", value: "", onChange: handlers.end }}
        startMonth={{ label: "Start month", value: 4, onChange: handlers.startMonth }}
        endMonth={{ label: "End month", value: null, onChange: handlers.endMonth }}
        windowError={null}
        windowWarning={null}
      />,
    );
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("folds the month pickers into a disclosure when asked", () => {
    const onToggle = vi.fn();
    const { container } = renderFields({
      startMonth: {
        label: "Start month",
        placeholder: "Default: Jan",
        value: null,
        onChange: vi.fn(),
      },
      monthsDisclosure: {
        className: "form-advanced months",
        summary: "Start and end months",
        open: false,
        onToggle,
      },
    });
    const details = container.querySelector("details.months") as HTMLDetailsElement;
    expect(details).not.toBeNull();
    expect(details.open).toBe(false);
    expect(details.querySelector("summary")).toHaveTextContent("Start and end months");
    expect(details).toContainElement(screen.getByLabelText("Start month"));
    expect((screen.getByLabelText("Start month") as HTMLSelectElement).options[0].text).toBe(
      "Default: Jan",
    );
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect(onToggle).toHaveBeenCalledWith(true);
  });
});
