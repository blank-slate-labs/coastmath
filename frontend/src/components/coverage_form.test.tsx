import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { vi, expect, it } from "vitest";
import CoverageForm from "./coverage_form";
import { makePlan } from "@/test_support/plan_builder";
const plan = makePlan({
  id: "a",
  start_date: "2026-01-01",
  tax_settings: { mode: "flat", ordinary_income_tax_rate: 0.2 },
});
it("preserves explicit Ohio eligibility when editing unrelated coverage", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(
    <CoverageForm
      plan={{
        ...plan,
        tax_settings: {
          ...plan.tax_settings!,
          oh_exemption_eligible_owners: ["self"],
          oh_dependents_by_year: { "2026": 1, "2027": 0 },
        },
      }}
      onSave={save}
    />,
  );
  fireEvent.click(screen.getByText("Health savings & work coverage"));
  fireEvent.change(screen.getByLabelText("Primary person earlier state wages ($)"), {
    target: { value: "50500" },
  });
  fireEvent.click(screen.getByText("Save coverage"));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        oh_exemption_eligible_owners: ["self"],
        oh_dependents_by_year: { "2026": 1, "2027": 0 },
        state_payroll_wages_year_to_date: { self: 50500 },
      }),
    ),
  );
});
it("retains an explicit payroll start month when editing another period field", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(
    <CoverageForm
      plan={{
        ...plan,
        tax_settings: {
          ...plan.tax_settings!,
          state_payroll_coverage: [
            { owner: "self", start_year: 2029, start_month: 6, state_code: "CA", ca_sdi: true },
          ],
        },
      }}
      onSave={save}
    />,
  );
  fireEvent.click(screen.getByText("Health savings & work coverage"));
  fireEvent.change(screen.getByLabelText("Last year (blank means ongoing)"), {
    target: { value: "2040" },
  });
  fireEvent.click(screen.getByText("Save coverage"));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        state_payroll_coverage: [expect.objectContaining({ start_month: 6, end_year: 2040 })],
      }),
    ),
  );
});
it("preserves unknown and explicit zero, existing settings, and independent plans", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  const view = render(<CoverageForm key="a" plan={plan} onSave={save} />);
  fireEvent.click(screen.getByText("Health savings & work coverage"));
  fireEvent.click(screen.getByText("Save coverage"));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        mode: "flat",
        ca_exemption_eligible_owners: null,
        hsa_coverage: [],
      }),
    ),
  );
  fireEvent.change(screen.getByLabelText("Eligibility"), { target: { value: "known" } });
  fireEvent.change(screen.getByLabelText("California SDI already paid ($)"), {
    target: { value: "0" },
  });
  fireEvent.click(screen.getByText("Save coverage"));
  await waitFor(() =>
    expect(save).toHaveBeenLastCalledWith(
      expect.objectContaining({
        ca_exemption_eligible_owners: [],
        state_payroll_paid_year_to_date: { "California SDI": 0 },
      }),
    ),
  );
  view.rerender(
    <CoverageForm key="b" plan={{ ...plan, id: "b", tax_settings: null }} onSave={save} />,
  );
  fireEvent.click(screen.getByText("Health savings & work coverage"));
  expect(screen.getByLabelText("Eligibility")).toHaveValue("unknown");
});
it("reloads periods and retains corrected draft after server validation errors", async () => {
  const save = vi
    .fn()
    .mockRejectedValue(new Error("Coverage periods for an owner must not overlap."));
  render(
    <CoverageForm
      plan={{
        ...plan,
        tax_settings: {
          ...plan.tax_settings!,
          hsa_coverage: [
            { owner: "spouse", start_year: 2026, coverage: "family", eligible_months: [1, 6] },
          ],
        },
      }}
      onSave={save}
    />,
  );
  fireEvent.click(screen.getByText("Health savings & work coverage"));
  const group = screen.getByRole("group", { name: "HSA period 1" });
  expect(within(group).getByLabelText("Person")).toHaveValue("spouse");
  expect(within(group).getByLabelText("Jan")).toBeChecked();
  expect(within(group).getByLabelText("Feb")).not.toBeChecked();
  fireEvent.change(within(group).getByLabelText("Last year (blank means ongoing)"), {
    target: { value: "2027" },
  });
  fireEvent.click(screen.getByText("Save coverage"));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("must not overlap"));
  expect(within(group).getByLabelText("Last year (blank means ongoing)")).toHaveValue(2027);
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({
      hsa_coverage: [
        expect.objectContaining({ owner: "spouse", eligible_months: [1, 6], end_year: 2027 }),
      ],
    }),
  );
});
it("keeps missing months unsaved and saves explicit dependent years after correction", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<CoverageForm plan={plan} onSave={save} />);
  fireEvent.click(screen.getByText("Health savings & work coverage"));
  fireEvent.click(screen.getByText("Add HSA period"));
  fireEvent.change(screen.getByLabelText("Health coverage"), { target: { value: "family" } });
  fireEvent.click(screen.getByText("Save coverage"));
  expect(screen.getByRole("status")).toHaveTextContent("at least one eligible HSA month");
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText("Jan"));
  fireEvent.change(screen.getByLabelText("Primary person earlier state wages ($)"), {
    target: { value: "50500" },
  });
  fireEvent.click(screen.getByText("Add dependent year"));
  fireEvent.change(screen.getByLabelText("Qualifying dependents in 2026"), {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByText("Save coverage"));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        ca_dependents_by_year: { "2026": 2 },
        state_payroll_wages_year_to_date: { self: 50500 },
      }),
    ),
  );
});
