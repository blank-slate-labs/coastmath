import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AccountForm from "@/components/account_form";
import YearLedger, { usedTaxLines } from "@/components/year_ledger";
import YearItemized from "@/components/year_itemized";
import { usCoverage, planCountries } from "@/domain/intl_plan";
import type {
  PlanData,
  SimulationResult,
  TaxRegimeBenefitRule,
  TaxRegimeCountry,
  YearSnapshot,
} from "@/types/plan";
import { setDisplayCurrency } from "@/utils/format";
import { projectionReport, reportCsv } from "@/utils/projection_report";
import CustomRegimeEditor from "./custom_regime_editor";
import IntlBenefitsEditor from "./intl_benefits_editor";
import { paramFields } from "./param_schema";
import { makePlan } from "@/test_support/plan_builder";

const COUNTRIES: TaxRegimeCountry[] = [
  {
    code: "QZ",
    name: "Fixture country",
    currency: "EUR",
    filing_unit: "individual",
    regions: [],
    account_kinds: [
      {
        id: "QZ:pension_saver",
        label: "Pension saver",
        category: "tax_deferred",
        rules: ["Contributions are deductible; withdrawals are taxed."],
      },
      {
        id: "QZ:free_saver",
        label: "Free saver",
        category: "tax_free",
        rules: ["Withdrawals are tax free."],
      },
    ],
    benefit_rules: [],
    spec_years: [2026],
    approximations: [],
  },
  {
    code: "QX",
    name: "Sampleland",
    currency: "DKK",
    filing_unit: "individual",
    regions: [],
    account_kinds: [{ id: "QX:tax_free_saver", label: "Tax-free saver", category: "tax_free" }],
    benefit_rules: [],
    spec_years: [2026],
    approximations: [],
  },
];

describe("account kind picker", () => {
  const optionLabels = () =>
    within(screen.getByLabelText(/Account Type/))
      .getAllByRole("option")
      .map((o) => o.textContent);

  it("offers only the plan's countries' kinds and hides US types in an all-non-US plan", () => {
    const onSubmit = vi.fn();
    render(
      <AccountForm
        regimeCountries={COUNTRIES}
        planCountryCodes={["QZ"]}
        usCoverage="non_us"
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );
    const labels = optionLabels();
    expect(labels).toEqual(
      expect.arrayContaining([
        "Pension saver",
        "Free saver",
        "Checking",
        "Savings",
        "Taxable Brokerage",
        "Other",
      ]),
    );
    expect(labels).not.toContain("Tax-free saver");
    expect(labels).not.toContain("Roth IRA");
    expect(labels).not.toContain("Traditional 401(k)");

    fireEvent.change(screen.getByLabelText(/Account Type/), {
      target: { value: "intl:QZ:pension_saver" },
    });
    expect(
      screen.getByText(/Tax-deferred\. Contributions are deductible; withdrawals are taxed\./),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "My pension saver" } });
    fireEvent.click(screen.getByRole("button", { name: "Add Account" }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        account_type: "other",
        intl_account_kind: "QZ:pension_saver",
        roth_settings: null,
        inherited_year: null,
      }),
    );
  });

  it("keeps US types, marked as US rules, in a plan that moves", () => {
    render(
      <AccountForm
        regimeCountries={COUNTRIES}
        planCountryCodes={["US", "QX"]}
        usCoverage="mixed"
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(optionLabels()).toEqual(
      expect.arrayContaining(["Tax-free saver", "Roth IRA", "Traditional 401(k)"]),
    );
    expect(screen.getByRole("group", { name: "Employer plans (US rules)" })).toBeInTheDocument();
  });

  it("keeps a saved US type selectable and sends no kind for a US account", () => {
    const onSubmit = vi.fn();
    const initial = {
      id: "a",
      user_id: "u",
      name: "Old IRA",
      account_type: "roth_ira",
      balance: 10,
      owner: "self",
    } as const;
    render(
      <AccountForm
        initial={initial}
        regimeCountries={COUNTRIES}
        planCountryCodes={["QZ"]}
        usCoverage="non_us"
        onSubmit={onSubmit}
        onCancel={() => {}}
      />,
    );
    expect(optionLabels()).toContain("Roth IRA");
    expect(optionLabels()).not.toContain("Traditional IRA");
    fireEvent.click(screen.getByRole("button", { name: "Update Account" }));
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty("intl_account_kind");
  });

  it("leaves US plans' account form unchanged", () => {
    const onSubmit = vi.fn();
    render(<AccountForm onSubmit={onSubmit} onCancel={() => {}} />);
    expect(screen.queryByRole("group", { name: /Fixture country accounts/ })).toBeNull();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Cash" } });
    fireEvent.click(screen.getByRole("button", { name: "Add Account" }));
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty("intl_account_kind");
  });
});

const PENSION: TaxRegimeBenefitRule = {
  id: "QZ:basic_pension",
  label: "Basic pension",
  params_schema: {
    type: "object",
    properties: {
      average_earnings_ratio: {
        title: "Average earnings ratio",
        type: "number",
        minimum: 0,
        maximum: 1,
        description: "Your earnings relative to the maximum.",
      },
      contributory_years: {
        anyOf: [{ type: "integer", minimum: 0 }, { type: "null" }],
        default: null,
        title: "Contributory years",
      },
      enhanced: { type: "boolean", title: "Include the enhancement", default: true },
      survivor_mode: { $ref: "#/$defs/SurvivorMode" },
    },
    required: ["average_earnings_ratio", "survivor_mode"],
    $defs: { SurvivorMode: { enum: ["combined", "none"], type: "string", title: "SurvivorMode" } },
  },
};

describe("benefits editor", () => {
  it("reads a Pydantic params schema, including Optional and enum references", () => {
    const fields = paramFields(PENSION.params_schema);
    expect(fields.map((f) => [f.key, f.kind, f.required])).toEqual([
      ["average_earnings_ratio", "number", true],
      ["contributory_years", "integer", false],
      ["enhanced", "boolean", false],
      ["survivor_mode", "enum", true],
    ]);
  });

  it("renders the rule's inputs, shows field errors, then saves the params", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <IntlBenefitsEditor
        benefits={[]}
        rules={[PENSION]}
        milestones={[]}
        hasPartner={false}
        onSave={onSave}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "+ Add benefit" }));
    expect(screen.getByLabelText("Include the enhancement")).toBeChecked();
    fireEvent.change(screen.getByLabelText(/Average earnings ratio/), { target: { value: "1.5" } });
    fireEvent.change(screen.getByLabelText(/Contributory years/), { target: { value: "2.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save benefits" }));
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText("Enter 1 or less.")).toBeInTheDocument();
    expect(screen.getByText("Enter a whole number.")).toBeInTheDocument();
    expect(screen.getByText("Choose survivor mode.")).toBeInTheDocument();
    expect(screen.getByText("Enter a whole start age from 0 to 120.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Average earnings ratio/), { target: { value: "0.8" } });
    fireEvent.change(screen.getByLabelText(/Contributory years/), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText(/Survivor mode/), { target: { value: "combined" } });
    fireEvent.change(screen.getByLabelText("Start age"), { target: { value: "65" } });
    fireEvent.click(screen.getByRole("button", { name: "Save benefits" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith([
        {
          rule: "QZ:basic_pension",
          owner: "self",
          start_age: 65,
          start_milestone_id: null,
          params: { average_earnings_ratio: 0.8, enhanced: true, survivor_mode: "combined" },
        },
      ]),
    );
    expect(screen.getByText("Benefits saved.")).toBeInTheDocument();
  });

  it("shows the server's rejection and keeps the draft", async () => {
    const onSave = vi
      .fn()
      .mockRejectedValue(
        new Error("Save plan was not saved. Intl settings: start age must be 60 to 70."),
      );
    const saved = [
      {
        rule: "QZ:basic_pension",
        owner: "self" as const,
        start_age: 75,
        start_milestone_id: null,
        params: { average_earnings_ratio: 0.5, survivor_mode: "none" },
      },
    ];
    render(
      <IntlBenefitsEditor
        benefits={saved}
        rules={[PENSION]}
        milestones={[]}
        hasPartner
        onSave={onSave}
      />,
    );
    fireEvent.change(screen.getByLabelText("Start age"), { target: { value: "72" } });
    fireEvent.click(screen.getByRole("button", { name: "Save benefits" }));
    await waitFor(() => expect(screen.getByText(/start age must be 60 to 70/)).toBeInTheDocument());
    expect(screen.getByLabelText("Start age")).toHaveValue(72);
    expect(screen.getByText("Unsaved benefit changes.")).toBeInTheDocument();
  });
});

describe("custom regime editor", () => {
  it("validates brackets and rates, then saves the regime document", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<CustomRegimeEditor document={null} baseYear={2026} currency="EUR" onSave={onSave} />);
    fireEvent.change(screen.getByLabelText("Rate (%)"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "+ Add bracket" }));
    const bracket2 = screen.getByRole("group", { name: "Bracket 2" });
    fireEvent.change(within(bracket2).getByLabelText(/Income from/), { target: { value: "0" } });
    fireEvent.change(within(bracket2).getByLabelText("Rate (%)"), { target: { value: "130" } });
    fireEvent.click(screen.getByRole("button", { name: "Save tax rules" }));
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText("Each bracket starts above the one before.")).toBeInTheDocument();
    expect(screen.getByText("Enter a rate from 0 to 100%.")).toBeInTheDocument();

    fireEvent.change(within(bracket2).getByLabelText(/Income from/), {
      target: { value: "40000" },
    });
    fireEvent.change(within(bracket2).getByLabelText(/^Rate \(%\)/), { target: { value: "30" } });
    fireEvent.change(screen.getByLabelText(/Tax-free allowance/), { target: { value: "12000" } });
    fireEvent.change(screen.getByLabelText("Capital gains"), {
      target: { value: "ordinary_inclusion" },
    });
    fireEvent.change(screen.getByLabelText("Share of gains taxed (%)"), {
      target: { value: "50" },
    });
    fireEvent.change(screen.getByLabelText("Dividends"), { target: { value: "flat" } });
    fireEvent.change(screen.getByLabelText("Dividend rate (%)"), { target: { value: "15" } });
    fireEvent.click(screen.getByLabelText("Tax net worth each year"));
    fireEvent.change(screen.getByLabelText(/Tax-free amount/), { target: { value: "1000000" } });
    fireEvent.change(screen.getByLabelText("Wealth tax rate (%)"), { target: { value: "1" } });
    fireEvent.click(screen.getByLabelText("Tax trades in taxable accounts"));
    fireEvent.change(screen.getByLabelText("Transaction tax rate (%)"), {
      target: { value: "0.2" },
    });
    fireEvent.change(screen.getByLabelText("Charged on"), { target: { value: "both" } });
    fireEvent.click(screen.getByRole("button", { name: "Save tax rules" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0]).toEqual({
      meta: {
        country: "XX",
        name: "Custom",
        base_year: 2026,
        currency: "EUR",
        filing_unit: "individual",
        default_indexing: "inflation",
      },
      national: [
        {
          id: "income_tax",
          label: "Income tax",
          category: "income_national",
          allowance: { amount: 12000 },
          brackets: [
            { lower: 0, upper: 40000, rate: 0.1 },
            { lower: 40000, upper: null, rate: 0.3 },
          ],
        },
      ],
      capital_gains: { mode: "ordinary_inclusion", inclusion_rate: 0.5 },
      dividends: { qualified: { mode: "flat", rate: 0.15 }, other: { mode: "flat", rate: 0.15 } },
      interest: { mode: "ordinary" },
      wealth_tax: { unit: "person", base: "net_worth", allowance: 1000000, rate: 0.01 },
      transaction_tax: { rate: 0.002, applies_to: "both", account_categories: ["taxable"] },
    });
  });

  it("reopens a saved document and shows the server's rejection without losing the draft", async () => {
    const saved = {
      meta: {
        country: "XX",
        name: "Custom",
        base_year: 2026,
        currency: "USD",
        filing_unit: "joint",
        default_indexing: "none",
      },
      national: [
        {
          id: "income_tax",
          label: "Income tax",
          category: "income_national",
          brackets: [{ lower: 0, upper: null, rate: 0.2 }],
        },
      ],
      capital_gains: { mode: "exempt" },
      dividends: {
        qualified: { mode: "capital_gains_rates" },
        other: { mode: "capital_gains_rates" },
      },
      interest: { mode: "exempt" },
    };
    const onSave = vi
      .fn()
      .mockRejectedValue(
        new Error("Save plan was not saved. Intl settings: brackets must be contiguous."),
      );
    render(<CustomRegimeEditor document={saved} baseYear={2026} currency="USD" onSave={onSave} />);
    expect(screen.getByLabelText("Taxed as")).toHaveValue("joint");
    expect(screen.getByLabelText("Index thresholds with inflation")).not.toBeChecked();
    expect(screen.getByLabelText("Capital gains")).toHaveValue("exempt");
    expect(screen.getByLabelText("Dividends")).toHaveValue("capital_gains_rates");
    expect(screen.getByLabelText("Interest")).toHaveValue("exempt");
    expect(screen.getByLabelText("Rate (%)")).toHaveValue(20);
    fireEvent.change(screen.getByLabelText("Rate (%)"), { target: { value: "25" } });
    fireEvent.click(screen.getByRole("button", { name: "Save tax rules" }));
    await waitFor(() =>
      expect(screen.getByText(/brackets must be contiguous/)).toBeInTheDocument(),
    );
    expect(screen.getByLabelText("Rate (%)")).toHaveValue(25);
  });
});

describe("US-only gating", () => {
  const plan = (overrides: Partial<PlanData>) => makePlan({ tax_country: "US", ...overrides });
  const period = (country: string | null, start_year: number | null) => ({
    id: "r",
    plan_id: "p",
    state_code: null,
    country,
    region: null,
    start_milestone_id: null,
    end_milestone_id: null,
    start_year,
    end_year: null,
    rank: 0,
  });

  it("treats saved plans without a country as US plans", () => {
    expect(usCoverage(plan({ tax_country: undefined }))).toBe("us");
  });
  it("is all-non-US when the plan and its periods are abroad", () => {
    expect(usCoverage(plan({ tax_country: "ZZ", residency_periods: [period("QY", 2030)] }))).toBe(
      "non_us",
    );
    // A period from the plan's start replaces the plan's own country.
    expect(usCoverage(plan({ tax_country: "US", residency_periods: [period("ZZ", null)] }))).toBe(
      "non_us",
    );
  });
  it("is mixed when the plan moves between the US and another country", () => {
    expect(usCoverage(plan({ tax_country: "US", residency_periods: [period("ZZ", 2030)] }))).toBe(
      "mixed",
    );
    expect(
      planCountries(
        plan({ tax_country: "ZZ", residency_periods: [period("US", 2030), period(null, 2040)] }),
      ),
    ).toEqual(["ZZ", "US"]);
  });
});

function snapshot(overrides: Partial<YearSnapshot>): YearSnapshot {
  return {
    year: 2030,
    age: 50,
    gross_income: 100000,
    taxes: 22000,
    federal_tax: 0,
    state_tax: 0,
    capital_gains_tax: 0,
    fica_tax: 0,
    expenses: 50000,
    net_cash_flow: 28000,
    accounts: {},
    real_assets_value: 0,
    liabilities_balance: 0,
    net_worth: 500000,
    effective_rate: 0.22,
    marginal_rate: 0.3,
    deduction_used: "",
    deduction_amount: 0,
    standard_deduction: 0,
    flex_spending_reduction: 0,
    investment_growth: 0,
    milestones_triggered: [],
    transfers: [],
    cash_flow: {
      income_sources: [],
      gross_income: 100000,
      tax_withheld: 22000,
      payroll_deductions: 0,
      net_pay: 78000,
      tax_delta: 0,
      expenses: [],
      contributions: [],
      transfers: [],
      drawdowns: [],
    },
    ...overrides,
  } as YearSnapshot;
}

const ABROAD_YEAR = snapshot({
  tax_country: "FR",
  national_income_tax: 20500,
  social_contributions: 1500,
  wealth_tax: 0,
  intl_tax_lines: [
    {
      code: "income_tax",
      label: "Income tax",
      category: "income_national",
      person: "self",
      amount: 20500,
    },
    {
      code: "social",
      label: "Social contribution",
      category: "social_contribution",
      person: "self",
      amount: 1500,
    },
  ],
});
const US_YEAR = snapshot({
  year: 2029,
  tax_country: "US",
  federal_tax: 15000,
  state_tax: 7000,
  intl_tax_lines: [],
  national_income_tax: 0,
});

describe("results", () => {
  afterEach(() => setDisplayCurrency(null));

  it("lists the country's totals in the ledger's tax breakdown, in the plan's currency", () => {
    setDisplayCurrency("MXN");
    expect(usedTaxLines([US_YEAR, ABROAD_YEAR])).toEqual([
      "federal_tax",
      "state_tax",
      "national_income_tax",
      "social_contributions",
    ]);
    render(
      <YearLedger
        snapshot={ABROAD_YEAR}
        previous={null}
        isFirstYear={false}
        taxLines={usedTaxLines([ABROAD_YEAR])}
      />,
    );
    const breakdown = screen.getByText("Tax breakdown").closest("details")!;
    expect(within(breakdown).getByText("Tax rules").nextSibling).toHaveTextContent("France");
    expect(
      within(breakdown).getByText("National income tax").closest(".ledger-row"),
    ).toHaveTextContent("$20,500");
    expect(
      within(breakdown).getByText("Social contributions").closest(".ledger-row"),
    ).toHaveTextContent("$1,500");
    expect(within(breakdown).queryByText("Federal income tax")).toBeNull();
  });

  it("itemizes the year's tax lines under the country's name", () => {
    render(<YearItemized snapshot={ABROAD_YEAR} />);
    const group = screen.getByRole("group", { name: "France tax lines" });
    expect(within(group).getByText("Social contribution (Primary person)")).toBeInTheDocument();
    render(<YearItemized snapshot={US_YEAR} />);
    expect(screen.getAllByRole("group", { name: /tax lines/ })).toHaveLength(1);
  });

  it("adds country columns to reports only when a year is taxed abroad", () => {
    const plan = makePlan({ birth_year: 1980 });
    const sim = (snaps: YearSnapshot[]) =>
      ({ yearly_snapshots: snaps, metadata: { start_year: 2029 } }) as unknown as SimulationResult;
    const usRows = projectionReport(plan, sim([US_YEAR]), "nominal");
    expect(Object.keys(usRows[0])).not.toContain("tax_country");
    expect(reportCsv(usRows, "nominal", 2029)).not.toContain("national_income_tax");
    const rows = projectionReport(plan, sim([US_YEAR, ABROAD_YEAR]), "nominal");
    expect(rows.map((r) => [r.tax_country, r.national_income_tax, r.social_contributions])).toEqual(
      [
        ["US", 0, 0],
        ["FR", 20500, 1500],
      ],
    );
  });
});
