import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import MilestoneForm, { availablePresets, circularReferenceIds } from "./milestone_form";
import type { Milestone } from "@/types/plan";

function ms(id: string, name: string, extra: Partial<Milestone> = {}): Milestone {
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
    ...extra,
  };
}

describe("MilestoneForm", () => {
  it("submits a financial-independence milestone with metric and multiple", () => {
    const onSubmit = vi.fn();
    render(<MilestoneForm onSubmit={onSubmit} onCancel={() => {}} />);
    fireEvent.click(screen.getByRole("radio", { name: "Custom" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "FI" } });
    fireEvent.change(screen.getByLabelText("Trigger Type"), {
      target: { value: "expense_multiple" },
    });
    fireEvent.change(screen.getByLabelText(/Multiple of annual expenses/), {
      target: { value: "30" },
    });
    fireEvent.change(screen.getByLabelText("Balance measured"), { target: { value: "net_worth" } });
    fireEvent.click(screen.getByText("Add Milestone"));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        trigger_type: "expense_multiple",
        expense_multiple: 30,
        metric: "net_worth",
        trigger_value: null,
        relative_to_id: null,
      }),
    );
  });

  it("submits a relative milestone and hides circular references", () => {
    const fi = ms("fi", "FI", { trigger_type: "expense_multiple", expense_multiple: 25 });
    const retire = ms("retire", "Retire", {
      trigger_type: "relative",
      relative_to_id: "fi",
      offset_years: 2,
    });
    const move = ms("move", "Move", {
      trigger_type: "relative",
      relative_to_id: "retire",
      offset_years: 1,
    });
    const other = ms("other", "Other");
    expect(circularReferenceIds("fi", [fi, retire, move, other])).toEqual(
      new Set(["fi", "retire", "move"]),
    );

    const onSubmit = vi.fn();
    render(
      <MilestoneForm
        initial={fi}
        milestones={[fi, retire, move, other]}
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText("Trigger Type"), { target: { value: "relative" } });
    const options = Array.from(screen.getByLabelText(/Relative to/).querySelectorAll("option")).map(
      (o) => o.textContent,
    );
    expect(options).toEqual(["— Choose a milestone —", "Other"]);
    fireEvent.click(screen.getByText("Update Milestone"));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose the milestone");
    fireEvent.change(screen.getByLabelText(/Relative to/), { target: { value: "other" } });
    fireEvent.change(screen.getByLabelText(/Offset/), { target: { value: "-3" } });
    fireEvent.click(screen.getByText("Update Milestone"));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        trigger_type: "relative",
        relative_to_id: "other",
        offset_years: -3,
        expense_multiple: null,
        metric: null,
      }),
    );
  });

  it("clears fields that do not apply when the trigger type changes", () => {
    const onSubmit = vi.fn();
    render(
      <MilestoneForm
        initial={ms("r", "Retire", {
          trigger_type: "relative",
          relative_to_id: "x",
          offset_years: 2,
        })}
        milestones={[ms("x", "X")]}
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText("Trigger Type"), { target: { value: "age" } });
    fireEvent.change(screen.getByLabelText("Age"), { target: { value: "60" } });
    fireEvent.click(screen.getByText("Update Milestone"));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        trigger_type: "age",
        trigger_value: 60,
        relative_to_id: null,
        offset_years: 0,
      }),
    );
  });

  it("starts a new milestone on the Retirement preset, asking only for the age", () => {
    const onSubmit = vi.fn();
    render(
      <MilestoneForm milestones={[]} birthYear={1990} onSubmit={onSubmit} onCancel={() => {}} />,
    );
    expect(screen.getByRole("radio", { name: "Retirement" })).toBeChecked();
    expect(screen.queryByRole("radio", { name: "Partner retirement" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Trigger Type")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Add Milestone"));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Enter an age between 0 and 130.");
    fireEvent.change(screen.getByLabelText("Age"), { target: { value: "62" } });
    fireEvent.click(screen.getByText("Add Milestone"));
    expect(onSubmit).toHaveBeenCalledExactlyOnceWith({
      name: "Retirement",
      trigger_type: "age",
      trigger_value: 62,
      trigger_date: null,
      metric: null,
      expense_multiple: null,
      relative_to_id: null,
      offset_years: 0,
    });
  });

  it("saves Partner retirement at the owner's age for the year the partner reaches it", () => {
    const onSubmit = vi.fn();
    render(
      <MilestoneForm
        milestones={[ms("r", "Retirement")]}
        birthYear={1980}
        spouseBirthYear={1983}
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );
    expect(screen.queryByRole("radio", { name: "Retirement" })).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Partner retirement" })).toBeChecked();
    fireEvent.change(screen.getByLabelText("Partner's age"), { target: { value: "65" } });
    expect(screen.getByText("Saved as the primary person's age 68.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Add Milestone"));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Partner retirement",
        trigger_type: "age",
        trigger_value: 68,
      }),
    );
  });

  it("keeps the custom form when every preset already exists, and for edits", () => {
    expect(
      availablePresets([ms("a", " retirement "), ms("b", "Partner Retirement")], 1980, 1983),
    ).toEqual([]);
    expect(availablePresets([], 1980, null)).toEqual(["retirement"]);
    const { unmount } = render(
      <MilestoneForm
        milestones={[ms("a", "Retirement")]}
        birthYear={1980}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("");
    unmount();
    render(
      <MilestoneForm
        initial={ms("x", "Sabbatical")}
        milestones={[]}
        birthYear={1980}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("Sabbatical");
  });

  it("reopens a Partner retirement with the partner's age and saves it unchanged", () => {
    const onSubmit = vi.fn();
    render(
      <MilestoneForm
        initial={ms("pr", "Partner retirement", { trigger_value: 66 })}
        milestones={[ms("r", "Retirement"), ms("pr", "Partner retirement", { trigger_value: 66 })]}
        birthYear={1980}
        spouseBirthYear={1983}
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByRole("radio", { name: "Partner retirement" })).toBeChecked();
    expect(screen.getByLabelText(/^Partner's age/)).toHaveValue(63);
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
    expect(screen.getByText("Saved as the primary person's age 66.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Update Milestone"));
    expect(onSubmit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        name: "Partner retirement",
        trigger_type: "age",
        trigger_value: 66,
      }),
    );
    expect(onSubmit.mock.lastCall![0]).not.toHaveProperty("is_active");
  });

  it("converts an edited Partner retirement to the primary person's age when switched to Custom", () => {
    const onSubmit = vi.fn();
    render(
      <MilestoneForm
        initial={ms("pr", "Partner retirement", { trigger_value: 66 })}
        birthYear={1980}
        spouseBirthYear={1983}
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Custom" }));
    expect(screen.getByLabelText("Name")).toHaveValue("Partner retirement");
    expect(screen.getByLabelText(/^Age/)).toHaveValue(66);
    fireEvent.click(screen.getByRole("radio", { name: "Partner retirement" }));
    expect(screen.getByLabelText(/^Partner's age/)).toHaveValue(63);
    fireEvent.click(screen.getByText("Update Milestone"));
    expect(onSubmit).toHaveBeenLastCalledWith(expect.objectContaining({ trigger_value: 66 }));
  });

  it("edits a Partner retirement as a custom age milestone without a partner birth year", () => {
    render(
      <MilestoneForm
        initial={ms("pr", "Partner retirement", { trigger_value: 66 })}
        birthYear={1980}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("Partner retirement");
    expect(screen.getByLabelText(/^Age/)).toHaveValue(66);
  });
});

it("builds combined metric conditions and a deadline without discarding edited values", () => {
  const submit = vi.fn();
  render(
    <MilestoneForm
      initial={ms("goal", "Goal", {
        trigger_type: "conditions",
        conditions: {
          combinator: "all",
          items: [{ kind: "age", owner: "self", age: 50 }],
        },
      })}
      accounts={[{ id: "cash", name: "Cash" }]}
      onSubmit={submit}
      onCancel={() => {}}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Add condition" }));
  const row = within(screen.getByRole("group", { name: "Condition 2" }));
  fireEvent.change(row.getByLabelText("Kind"), { target: { value: "metric" } });
  fireEvent.change(row.getByLabelText("Metric"), { target: { value: "account_balance" } });
  fireEvent.change(row.getByLabelText("Account"), { target: { value: "cash" } });
  fireEvent.change(row.getByLabelText("Unit"), { target: { value: "multiple_of_metric" } });
  fireEvent.change(row.getByLabelText("Value"), { target: { value: "25" } });
  fireEvent.change(row.getByLabelText("Average years"), { target: { value: "3" } });
  fireEvent.click(screen.getByLabelText("Set a deadline"));
  fireEvent.change(screen.getByLabelText("At deadline"), { target: { value: "miss" } });
  fireEvent.click(screen.getByRole("button", { name: "Update Milestone" }));
  expect(submit).toHaveBeenCalledWith(
    expect.objectContaining({
      conditions: {
        combinator: "all",
        items: [
          { kind: "age", owner: "self", age: 50 },
          {
            kind: "metric",
            metric: "account_balance",
            account_id: "cash",
            comparator: ">=",
            value: 25,
            value_unit: "multiple_of_metric",
            other_metric: "annual_spending",
            average_years: 3,
          },
        ],
        deadline: { kind: "age", value: 60, owner: "self", action: "miss" },
      },
    }),
  );
});

it("requires an account and clears old conditions when switching trigger type", () => {
  const submit = vi.fn();
  render(
    <MilestoneForm
      initial={ms("goal", "Goal", {
        trigger_type: "conditions",
        conditions: {
          combinator: "all",
          items: [
            {
              kind: "metric",
              metric: "account_balance",
              value: 100,
              comparator: ">=",
              value_unit: "dollars",
            },
          ],
        },
      })}
      onSubmit={submit}
      onCancel={() => {}}
    />,
  );
  fireEvent.submit(screen.getByRole("button", { name: "Update Milestone" }).closest("form")!);
  expect(submit).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("Choose an account");
  fireEvent.change(screen.getByLabelText("Trigger Type"), { target: { value: "age" } });
  fireEvent.click(screen.getByRole("button", { name: "Update Milestone" }));
  expect(submit).toHaveBeenCalledWith(
    expect.objectContaining({ conditions: null, trigger_type: "age", trigger_value: 65 }),
  );
});

it("switches a milestone off without changing its trigger and omits an unchanged switch", () => {
  const submit = vi.fn();
  const move = ms("move", "Move", { trigger_value: 60 });
  const { unmount } = render(
    <MilestoneForm initial={move} onSubmit={submit} onCancel={() => {}} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Update Milestone" }));
  expect(submit.mock.calls[0][0]).not.toHaveProperty("is_active");
  fireEvent.click(screen.getByLabelText(/^Active/));
  fireEvent.click(screen.getByRole("button", { name: "Update Milestone" }));
  expect(submit).toHaveBeenLastCalledWith(
    expect.objectContaining({ is_active: false, trigger_type: "age", trigger_value: 60 }),
  );
  unmount();
  render(
    <MilestoneForm initial={{ ...move, is_active: false }} onSubmit={submit} onCancel={() => {}} />,
  );
  expect(screen.getByLabelText(/^Active/)).not.toBeChecked();
  fireEvent.click(screen.getByLabelText(/^Active/));
  fireEvent.click(screen.getByRole("button", { name: "Update Milestone" }));
  expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ is_active: true }));
});
