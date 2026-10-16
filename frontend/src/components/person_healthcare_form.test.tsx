import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import HealthcareForm, { defaultHealthcareSettings } from "./healthcare_form";
import { personHealthcareDraft, readPersonHealthcare } from "./person_healthcare_form";
import type { PersonHealthcareSettings } from "@/types/plan";
import { makePlan } from "@/test_support/plan_builder";

const partner: PersonHealthcareSettings = {
  owner: "spouse",
  mode: "coverage",
  aca_enabled: false,
  out_of_pocket_annual: null,
  medicare_start_age: 67,
  long_term_care: {
    monthly_cost: 4500,
    duration_months: 28,
    months_before_longevity: 28,
    covered_fraction: 0.25,
    amount_reference_year: 2026,
  },
};
const plan = makePlan({
  id: "plan",
  spouse: { name: "Sam" },
  healthcare_settings: {
    ...defaultHealthcareSettings,
    enabled: true,
    persons: [partner],
    magi_two_years_prior_filing_status: "married_filing_jointly",
  },
});

it("preserves an untouched partner budget and unknown OOP while editing shared settings", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<HealthcareForm plan={plan} onSave={save} />);
  fireEvent.change(screen.getByLabelText(/^Medical cost inflation/), { target: { value: "4" } });
  fireEvent.click(screen.getByRole("button", { name: "Save health coverage" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][1].persons).toEqual([partner]);
  expect(save.mock.calls[0][1].magi_two_years_prior_filing_status).toBe("married_filing_jointly");
});

it("retains new person drafts after failed save, then reloads exact submitted data", async () => {
  const save = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(undefined);
  const view = render(<HealthcareForm plan={plan} onSave={save} />);
  fireEvent.change(screen.getByLabelText("Primary person medical cost method"), {
    target: { value: "itemized" },
  });
  fireEvent.change(screen.getByLabelText("Primary person Itemized medical cost ($ per year)"), {
    target: { value: "1200" },
  });
  expect(screen.getByText(/Unsaved health coverage/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Save health coverage" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("retained"));
  expect(screen.getByLabelText("Primary person Itemized medical cost ($ per year)")).toHaveValue(
    "1,200",
  );
  fireEvent.click(screen.getByRole("button", { name: "Save health coverage" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved"));
  const settings = save.mock.calls[1][1];
  view.unmount();
  render(<HealthcareForm plan={{ ...plan, healthcare_settings: settings }} onSave={save} />);
  expect(screen.getByLabelText("Primary person Itemized medical cost ($ per year)")).toHaveValue(
    "1,200",
  );
  expect(screen.queryByText(/Unsaved health coverage/)).not.toBeInTheDocument();
  expect(settings.persons[1]).toEqual(partner);
});

it("distinguishes inherited, off, unknown and zero without adding budgets", () => {
  const draft = personHealthcareDraft();
  expect(readPersonHealthcare(draft, "self")).toBeUndefined();
  draft.mode = "off";
  expect(readPersonHealthcare(draft, "self")?.mode).toBe("off");
  draft.mode = "coverage";
  expect(readPersonHealthcare(draft, "self")?.out_of_pocket_annual).toBeNull();
  draft.numbers.out_of_pocket_annual = "0";
  expect(readPersonHealthcare(draft, "self")?.out_of_pocket_annual).toBe(0);
});

it("requires explicit itemized and LTC inputs and converts covered share exactly", () => {
  const draft = personHealthcareDraft();
  draft.mode = "itemized";
  expect(() => readPersonHealthcare(draft, "self")).toThrow(/itemized/);
  draft.numbers.itemized_annual_amount = "0";
  draft.ltc = true;
  expect(() => readPersonHealthcare(draft, "self")).toThrow(/LTC/);
  Object.assign(draft.numbers, {
    monthly_cost: "5000",
    duration_months: "24",
    start_year: "2050",
    start_month: "7",
    covered_fraction: "30",
  });
  expect(readPersonHealthcare(draft, "self")?.long_term_care).toEqual(
    expect.objectContaining({
      monthly_cost: 5000,
      duration_months: 24,
      start_year: 2050,
      start_month: 7,
      covered_fraction: 0.3,
      months_before_longevity: null,
    }),
  );
  draft.ltcStart = "longevity";
  draft.numbers.months_before_longevity = "28";
  expect(readPersonHealthcare(draft, "self")?.long_term_care).toEqual(
    expect.objectContaining({ start_year: null, start_month: 1, months_before_longevity: 28 }),
  );
});

it("reads Medicare-covered quarters as a whole number and blank as none", () => {
  const draft = personHealthcareDraft({ owner: "self", mode: "coverage" });
  expect(readPersonHealthcare(draft, "self")?.medicare_part_a_quarters ?? null).toBeNull();
  const reduced = { ...draft, numbers: { ...draft.numbers, medicare_part_a_quarters: "34" } };
  expect(readPersonHealthcare(reduced, "self")?.medicare_part_a_quarters).toBe(34);
  expect(
    personHealthcareDraft(readPersonHealthcare(reduced, "self")).numbers.medicare_part_a_quarters,
  ).toBe("34");
  const fractional = { ...draft, numbers: { ...draft.numbers, medicare_part_a_quarters: "34.5" } };
  expect(() => readPersonHealthcare(fractional, "self")).toThrow(/whole number/);
});
