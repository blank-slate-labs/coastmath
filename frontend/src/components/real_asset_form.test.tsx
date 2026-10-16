import { it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import RealAssetForm from "./real_asset_form";

it("preserves appreciation and saves adjusted basis and sale timing", () => {
  const submit = vi.fn();
  render(
    <RealAssetForm
      accounts={[]}
      onSubmit={submit}
      onCancel={() => {}}
      initial={{
        id: "a",
        plan_id: "p",
        name: "Home",
        current_value: 400000,
        annual_appreciation_rate: 0.03,
        is_primary_residence: true,
        auto_liquidate_on_depletion: false,
        liquidation_target_account_id: null,
        annual_property_tax: 0,
        annual_maintenance: 0,
        property_tax_rate: null,
        maintenance_rate: null,
        insurance_rate: null,
        sale_year: null,
        sale_month: 1,
      }}
    />,
  );
  fireEvent.change(screen.getByLabelText(/Adjusted tax basis/), { target: { value: "250000" } });
  fireEvent.change(screen.getByLabelText(/Planned sale year/), { target: { value: "2030" } });
  fireEvent.change(screen.getByLabelText(/Sale month/), { target: { value: "7" } });
  fireEvent.submit(screen.getByLabelText("Name").closest("form")!);
  expect(submit).toHaveBeenCalledWith(
    expect.objectContaining({
      annual_appreciation_rate: 0.03,
      adjusted_basis: 250000,
      sale_year: 2030,
      sale_month: 7,
    }),
  );
});

it("defaults new vehicles to personal use and submits investment treatment only when selected", () => {
  const submit = vi.fn();
  render(<RealAssetForm accounts={[]} onSubmit={submit} onCancel={() => {}} />);
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Car" } });
  expect(screen.getByText(/Losses not deductible; gains taxable/)).toBeTruthy();
  fireEvent.submit(screen.getByLabelText("Name").closest("form")!);
  expect(submit).toHaveBeenLastCalledWith(
    expect.objectContaining({ tax_treatment: "personal_use" }),
  );
  fireEvent.change(screen.getByLabelText("Sale tax treatment"), {
    target: { value: "investment" },
  });
  expect(screen.getByText(/depreciation recapture/)).toBeTruthy();
  fireEvent.submit(screen.getByLabelText("Name").closest("form")!);
  expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ tax_treatment: "investment" }));
  fireEvent.click(screen.getByLabelText("Primary residence"));
  fireEvent.submit(screen.getByLabelText("Name").closest("form")!);
  expect(submit).toHaveBeenLastCalledWith(
    expect.objectContaining({ tax_treatment: "personal_use", is_primary_residence: true }),
  );
});

it("asks for review when editing an unclassified legacy property", () => {
  const submit = vi.fn();
  render(
    <RealAssetForm
      accounts={[]}
      onSubmit={submit}
      onCancel={() => {}}
      initial={{
        id: "a",
        plan_id: "p",
        name: "Car",
        current_value: 24000,
        annual_appreciation_rate: -0.1,
        is_primary_residence: false,
        auto_liquidate_on_depletion: false,
        liquidation_target_account_id: null,
        annual_property_tax: 0,
        annual_maintenance: 0,
        property_tax_rate: null,
        maintenance_rate: null,
        insurance_rate: null,
        sale_year: 2028,
        sale_month: 1,
      }}
    />,
  );
  expect(
    screen.getByText(/Until reviewed, gains are taxed and losses are not deducted/),
  ).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Sale tax treatment"), {
    target: { value: "personal_use" },
  });
  fireEvent.submit(screen.getByLabelText("Name").closest("form")!);
  expect(submit).toHaveBeenCalledWith(
    expect.objectContaining({ tax_treatment: "personal_use", sale_year: 2028 }),
  );
});

it("submits a planned rental purchase with a loan, selling costs and depreciation inputs", () => {
  const submit = vi.fn();
  render(
    <RealAssetForm
      accounts={[{ id: "acct", name: "Checking", account_type: "checking" } as never]}
      onSubmit={submit}
      onCancel={() => {}}
    />,
  );
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Duplex" } });
  fireEvent.click(screen.getByLabelText("Planned purchase"));
  fireEvent.change(screen.getByLabelText("Purchase year"), { target: { value: "2028" } });
  fireEvent.change(screen.getByLabelText("Purchase month"), { target: { value: "4" } });
  fireEvent.change(screen.getByLabelText(/Purchase price/), { target: { value: "350000" } });
  fireEvent.change(screen.getByLabelText(/Closing costs/), { target: { value: "7000" } });
  fireEvent.change(screen.getByLabelText("Pay from"), { target: { value: "acct" } });
  fireEvent.change(screen.getByLabelText(/Loan rate/), { target: { value: "6.5" } });
  fireEvent.change(screen.getByLabelText(/Loan term/), { target: { value: "360" } });
  fireEvent.change(screen.getByLabelText("Down payment value"), { target: { value: "25" } });
  fireEvent.change(screen.getByLabelText(/Selling costs/), { target: { value: "6" } });
  fireEvent.change(screen.getByLabelText("Sale tax treatment"), { target: { value: "rental" } });
  fireEvent.change(screen.getByLabelText(/Annual rent/), { target: { value: "30000" } });
  fireEvent.change(screen.getByLabelText("Operating expenses basis"), {
    target: { value: "percent" },
  });
  fireEvent.change(screen.getByLabelText("Operating expenses value"), { target: { value: "10" } });
  fireEvent.change(screen.getByLabelText(/Land value/), { target: { value: "20" } });
  fireEvent.click(screen.getByLabelText(/trade or business/));
  fireEvent.submit(screen.getByLabelText("Name").closest("form")!);
  expect(submit).toHaveBeenCalledWith(
    expect.objectContaining({
      tax_treatment: "rental",
      current_value: 350000,
      purchase_year: 2028,
      purchase_month: 4,
      purchase_price: 350000,
      closing_costs: 7000,
      purchase_funding_account_id: "acct",
      purchase_loan_rate: 6.5,
      purchase_loan_term_months: 360,
      down_payment_rate: 0.25,
      down_payment_amount: null,
      selling_cost_rate: 0.06,
      rental_income: 30000,
      rental_expense_rate: 0.1,
      rental_expenses: null,
      land_value_rate: 0.2,
      rental_property_class: "residential",
      qbi_eligible: true,
      rental_active_participation: true,
    }),
  );
});

it("saves home sale exclusion dates for a primary residence and clears rental fields", () => {
  const submit = vi.fn();
  render(<RealAssetForm accounts={[]} onSubmit={submit} onCancel={() => {}} />);
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Home" } });
  fireEvent.change(screen.getByLabelText(/Current value/), { target: { value: "500000" } });
  fireEvent.click(screen.getByLabelText("Primary residence"));
  fireEvent.change(screen.getByLabelText("Owned since (year)"), { target: { value: "2019" } });
  fireEvent.change(screen.getByLabelText("Owned since (month)"), { target: { value: "6" } });
  fireEvent.submit(screen.getByLabelText("Name").closest("form")!);
  expect(submit).toHaveBeenCalledWith(
    expect.objectContaining({
      is_primary_residence: true,
      owned_since_year: 2019,
      owned_since_month: 6,
      primary_residence_since_year: null,
      rental_income: null,
      purchase_year: null,
    }),
  );
});

it("saves a mixed-use home as a rental with a rented share and yearly steps", () => {
  const submit = vi.fn();
  render(<RealAssetForm accounts={[]} onSubmit={submit} onCancel={() => {}} />);
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Duplex" } });
  fireEvent.click(screen.getByLabelText("Primary residence"));
  fireEvent.click(screen.getByLabelText("Part of the home is rented out"));
  fireEvent.change(screen.getByLabelText(/Annual rent/), { target: { value: "40000" } });
  const form = screen.getByLabelText("Name").closest("form")!;
  fireEvent.submit(form);
  expect(screen.getByRole("alert")).toHaveTextContent("rented share");
  expect(submit).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText(/Rented share of the property/), {
    target: { value: "50" },
  });
  fireEvent.click(screen.getByText("Add a year"));
  fireEvent.change(screen.getByLabelText("From year"), { target: { value: "2030" } });
  fireEvent.change(screen.getByLabelText("Rented share (%)"), { target: { value: "0" } });
  fireEvent.submit(form);
  expect(submit).toHaveBeenLastCalledWith(
    expect.objectContaining({
      is_primary_residence: true,
      tax_treatment: "rental",
      rental_income: 40000,
      rental_use_rate: 0.5,
      rental_use_schedule: [{ year: 2030, rate: 0 }],
    }),
  );
});

it("keeps the rented share of an existing rental and clears it for personal use", () => {
  const submit = vi.fn();
  render(
    <RealAssetForm
      accounts={[]}
      onSubmit={submit}
      onCancel={() => {}}
      initial={{
        id: "a",
        plan_id: "p",
        name: "Cabin",
        current_value: 300000,
        annual_appreciation_rate: 0.03,
        is_primary_residence: false,
        tax_treatment: "rental",
        auto_liquidate_on_depletion: false,
        liquidation_target_account_id: null,
        annual_property_tax: 0,
        annual_maintenance: 0,
        property_tax_rate: null,
        maintenance_rate: null,
        insurance_rate: null,
        sale_year: null,
        sale_month: 1,
        rental_use_rate: 0.4,
        rental_use_schedule: [{ year: 2031, rate: 1 }],
      }}
    />,
  );
  expect(screen.getByLabelText(/Rented share of the property/)).toHaveValue(40);
  const form = screen.getByLabelText("Name").closest("form")!;
  fireEvent.submit(form);
  expect(submit).toHaveBeenLastCalledWith(
    expect.objectContaining({
      tax_treatment: "rental",
      rental_use_rate: 0.4,
      rental_use_schedule: [{ year: 2031, rate: 1 }],
    }),
  );
  fireEvent.change(screen.getByLabelText("Sale tax treatment"), {
    target: { value: "personal_use" },
  });
  fireEvent.submit(form);
  expect(submit).toHaveBeenLastCalledWith(
    expect.objectContaining({
      tax_treatment: "personal_use",
      rental_use_rate: null,
      rental_use_schedule: null,
    }),
  );
});

it.each([350, 6])(
  "keeps a %i-month purchase loan term valid through a name-only edit",
  (months) => {
    const submit = vi.fn();
    render(
      <RealAssetForm
        accounts={[]}
        onSubmit={submit}
        onCancel={() => {}}
        initial={{
          id: "a",
          plan_id: "p",
          name: "Condo",
          current_value: 300000,
          annual_appreciation_rate: 0.03,
          is_primary_residence: false,
          tax_treatment: "investment",
          auto_liquidate_on_depletion: false,
          liquidation_target_account_id: null,
          annual_property_tax: 0,
          annual_maintenance: 0,
          property_tax_rate: null,
          maintenance_rate: null,
          insurance_rate: null,
          sale_year: null,
          sale_month: 1,
          purchase_year: 2030,
          purchase_month: 1,
          purchase_price: 300000,
          purchase_loan_rate: 6,
          purchase_loan_term_months: months,
          down_payment_rate: 0.2,
        }}
      />,
    );
    const term = screen.getByLabelText("Loan term (months)") as HTMLInputElement;
    expect(term.value).toBe(String(months));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Renamed condo" } });
    const form = screen.getByLabelText("Name").closest("form")!;
    expect(form.checkValidity()).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Update real asset" }));
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Renamed condo",
        purchase_loan_rate: 6,
        purchase_loan_term_months: months,
      }),
    );
  },
);
