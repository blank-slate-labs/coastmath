import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, it, expect, describe } from "vitest";
import EstateSettingsForm from "./estate_settings_form";
import { useSaveStore } from "@/stores/save_store";
import type { PlanData } from "@/types/plan";
import { makePlan } from "@/test_support/plan_builder";

function plan(overrides: Partial<PlanData> = {}): PlanData {
  return makePlan({
    id: "p1",
    user_id: "u",
    name: "Plan",
    birth_year: 1970,
    filing_status: "married_filing_jointly",
    life_expectancy: 90,
    created_at: "2026-01-01",
    estate_settings: {
      step_up_basis_on_death: true,
      filing_status_after_death: "single",
      federal_estate_exemption: 13_600_000,
      custom_federal_exemption_enabled: false,
      portability_election: true,
      state_estate_tax_enabled: true,
      state_estate_exemption: 2_000_000,
      state_estate_tax_rate: 0.16,
    },
    ...overrides,
  });
}

describe("EstateSettingsForm", () => {
  it("saves partner profile and estate settings with decimal rates in one update", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<EstateSettingsForm plan={plan()} onSave={save} />);
    expect(screen.getByLabelText(/State rate on the excess/)).toHaveValue(16);
    fireEvent.click(screen.getByLabelText("Plan includes a partner"));
    fireEvent.change(screen.getByLabelText(/Partner birth year/), { target: { value: "1972" } });
    fireEvent.change(screen.getByLabelText(/Partner life expectancy/), { target: { value: "88" } });
    fireEvent.click(screen.getByLabelText(/Override the federal estate exemption/));
    fireEvent.change(screen.getByLabelText(/Federal exemption at death/), {
      target: { value: "7000000" },
    });
    fireEvent.change(screen.getByLabelText(/State rate on the excess/), {
      target: { value: "12.5" },
    });
    fireEvent.change(screen.getByLabelText(/Settlement costs: fixed/), {
      target: { value: "15000" },
    });
    fireEvent.change(screen.getByLabelText(/Settlement costs: percent/), {
      target: { value: "2" },
    });
    fireEvent.change(screen.getByLabelText(/Heirs' income tax rate/), { target: { value: "22" } });
    fireEvent.click(screen.getByRole("button", { name: "Save estate settings" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved"));
    expect(save).toHaveBeenCalledWith("p1", {
      estate_settings: {
        step_up_basis_on_death: true,
        filing_status_after_death: "single",
        federal_estate_exemption: 7_000_000,
        custom_federal_exemption_enabled: true,
        portability_election: true,
        state_estate_tax_enabled: true,
        state_estate_exemption: 2_000_000,
        state_estate_tax_rate: 0.125,
        settlement_cost_fixed: 15000,
        settlement_cost_rate: 0.02,
        heir_income_tax_rate: 0.22,
      },
      spouse: { name: null, birth_year: 1972, life_expectancy: 88 },
    });
  });

  it("validates partner years and reports failed saves without losing edits", async () => {
    const save = vi.fn().mockRejectedValue(new Error("offline"));
    render(
      <EstateSettingsForm
        plan={plan({
          spouse: {
            id: "s",
            plan_id: "p1",
            name: "Sam",
            birth_year: 1971,
            life_expectancy: 85,
            income_streams: [],
            retirement_milestone_id: null,
          },
        })}
        onSave={save}
      />,
    );
    fireEvent.change(screen.getByLabelText(/Partner life expectancy/), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save estate settings" }));
    expect(screen.getByRole("alert")).toHaveTextContent("life expectancy");
    expect(save).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/Partner life expectancy/), { target: { value: "86" } });
    fireEvent.click(screen.getByRole("button", { name: "Save estate settings" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not save"));
    expect(save).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ spouse: { name: "Sam", birth_year: 1971, life_expectancy: 86 } }),
    );
    expect(screen.getByLabelText(/Partner life expectancy/)).toHaveValue(86);
  });

  it("removes the partner with an explicit null", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(
      <EstateSettingsForm
        plan={plan({
          spouse: {
            id: "s",
            plan_id: "p1",
            name: "Sam",
            birth_year: 1971,
            life_expectancy: 85,
            income_streams: [],
            retirement_milestone_id: null,
          },
        })}
        onSave={save}
      />,
    );
    fireEvent.click(screen.getByLabelText("Plan includes a partner"));
    fireEvent.click(screen.getByRole("button", { name: "Save estate settings" }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][1].spouse).toBeNull();
  });

  it("states the server's reason when it refuses to remove a partner who still owns items", async () => {
    const reason =
      "Save plan in “Plan” was not saved. Reassign or remove the partner's items first: Spouse Salary, Roth IRA (spouse).";
    const save = vi.fn().mockImplementation(async () => {
      useSaveStore.setState({
        failed: ["put /plans/p1"],
        failures: { "put /plans/p1": { message: reason, rejected: true } },
      });
      throw new Error(reason);
    });
    render(
      <EstateSettingsForm
        plan={plan({
          spouse: {
            id: "s",
            plan_id: "p1",
            name: "Sam",
            birth_year: 1971,
            life_expectancy: 85,
            income_streams: [],
            retirement_milestone_id: null,
          },
        })}
        onSave={save}
      />,
    );
    fireEvent.click(screen.getByLabelText("Plan includes a partner"));
    fireEvent.click(screen.getByRole("button", { name: "Save estate settings" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Spouse Salary, Roth IRA (spouse)"),
    );
    useSaveStore.setState(useSaveStore.getInitialState());
  });
});

it("saves an explicit household horizon and retains source-backed survivor settings", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  const source = plan({
    birth_month: 1,
    spouse: {
      id: "s",
      plan_id: "p1",
      name: "Sam",
      birth_year: 1972,
      birth_month: 4,
      life_expectancy: 90,
      income_streams: [],
      retirement_milestone_id: null,
    },
  });
  render(<EstateSettingsForm plan={source} onSave={save} />);
  fireEvent.change(screen.getByLabelText(/Plan ends/), {
    target: { value: "last_survivor_calendar_year_end" },
  });
  fireEvent.change(screen.getByLabelText(/Survivor Social Security policy/), {
    target: { value: "claimed_benefit_at_survivor_fra" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save estate settings" }));
  expect(screen.getByRole("alert")).toHaveTextContent("eligibility");
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText(/Survivor eligibility is confirmed/));
  fireEvent.change(screen.getByLabelText("Survivor eligibility note"), {
    target: { value: "Reviewed eligibility, marriage and claiming history." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save estate settings" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][1].estate_settings).toEqual(
    expect.objectContaining({
      household_lifecycle: "last_survivor_calendar_year_end",
      survivor_social_security_policy: "claimed_benefit_at_survivor_fra",
      survivor_social_security_eligibility_confirmed: true,
      survivor_social_security_eligibility_source:
        "Reviewed eligibility, marriage and claiming history.",
      state_estate_exemption: 2000000,
    }),
  );
});

it("blocks incompatible filing status and tracks birth-month-only edits", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(
    <EstateSettingsForm
      plan={plan({
        spouse: {
          id: "s",
          plan_id: "p1",
          name: "Sam",
          birth_year: 1972,
          birth_month: 4,
          life_expectancy: 90,
          income_streams: [],
          retirement_milestone_id: null,
        },
      })}
      onSave={save}
    />,
  );
  fireEvent.change(screen.getByLabelText(/Partner birth month/), { target: { value: "5" } });
  expect(screen.getByRole("status")).toHaveTextContent("Unsaved");
  fireEvent.change(screen.getByLabelText(/Plan ends/), {
    target: { value: "last_survivor_calendar_year_end" },
  });
  fireEvent.change(screen.getByLabelText(/Filing status after partner/), {
    target: { value: "married_filing_jointly" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save estate settings" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Single or Head");
  expect(save).not.toHaveBeenCalled();
});

it("saves and clears the amount to leave heirs without touching other estate keys", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  const saved = plan();
  const { unmount } = render(<EstateSettingsForm plan={saved} onSave={save} />);
  const heirs = screen.getByLabelText(/Leave to heirs/);
  expect(heirs).toHaveValue("");
  fireEvent.change(heirs, { target: { value: "500000" } });
  fireEvent.click(screen.getByRole("button", { name: "Save estate settings" }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(save.mock.calls[0][1].estate_settings).toMatchObject({
    legacy_target: 500000,
    state_estate_tax_rate: 0.16,
  });
  unmount();

  render(
    <EstateSettingsForm
      plan={plan({ estate_settings: { ...saved.estate_settings!, legacy_target: 500000 } })}
      onSave={save}
    />,
  );
  expect(screen.getByLabelText(/Leave to heirs/)).toHaveValue("500,000");
  fireEvent.change(screen.getByLabelText(/Leave to heirs/), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Save estate settings" }));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
  expect(save.mock.calls[1][1].estate_settings.legacy_target).toBeNull();
});

it("rejects a negative amount to leave heirs", () => {
  const save = vi.fn();
  render(<EstateSettingsForm plan={plan()} onSave={save} />);
  fireEvent.change(screen.getByLabelText(/Leave to heirs/), { target: { value: "-1" } });
  // Browsers block min={0} natively; the form still guards a submit that gets through.
  fireEvent.submit(screen.getByRole("button", { name: "Save estate settings" }).closest("form")!);
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Leave to heirs must be zero or a positive dollar amount.",
  );
  expect(save).not.toHaveBeenCalled();
});

it("saves legacy detail only once it is set", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<EstateSettingsForm plan={plan()} onSave={save} />);
  fireEvent.click(screen.getByLabelText(/Also step up joint taxable accounts/));
  fireEvent.change(screen.getByLabelText(/Selling costs on real assets/), {
    target: { value: "6" },
  });
  fireEvent.change(screen.getByLabelText(/Charitable bequest/), { target: { value: "10" } });
  fireEvent.click(screen.getByLabelText(/Step up cost basis on partner-owned/));
  fireEvent.change(screen.getByLabelText(/Heirs' capital gains rate/), { target: { value: "15" } });
  fireEvent.click(screen.getByRole("button", { name: "Save estate settings" }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(save.mock.calls[0][1].estate_settings).toMatchObject({
    step_up_basis_on_death: false,
    joint_account_step_up: true,
    heir_capital_gains_rate: 0.15,
    estate_selling_cost_percent: 6,
    charitable_bequest_percent: 10,
  });
});

describe("EstateSettingsForm in international plans", () => {
  const abroad = {
    id: "r1",
    plan_id: "p1",
    state_code: null,
    local_tax: null,
    country: "NZ",
    region: null,
    start_milestone_id: null,
    start_year: 2030,
  };
  it("shows the US estate exemptions without a note in a US plan", () => {
    render(<EstateSettingsForm plan={plan()} onSave={vi.fn()} />);
    expect(screen.getByLabelText(/Override the federal estate exemption/)).toBeInTheDocument();
    expect(
      screen.queryByText(/applies only to a death in a year you live in the US/),
    ).not.toBeInTheDocument();
  });
  it("hides the US estate exemptions in a plan with no US year and keeps their saved values", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(
      <EstateSettingsForm plan={plan({ tax_country: "NZ" } as Partial<PlanData>)} onSave={save} />,
    );
    expect(
      screen.queryByLabelText(/Override the federal estate exemption/),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Elect portability/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Apply a state estate tax/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Settlement costs: fixed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save estate settings" }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(save.mock.calls[0][1].estate_settings).toMatchObject({
      custom_federal_exemption_enabled: false,
      portability_election: true,
      state_estate_tax_enabled: true,
      state_estate_exemption: 2_000_000,
      state_estate_tax_rate: 0.16,
    });
  });
  it("keeps the exemptions in a plan that moves abroad, with a note about US years", () => {
    render(
      <EstateSettingsForm
        plan={plan({
          tax_country: "US",
          residency_periods: [abroad],
        } as unknown as Partial<PlanData>)}
        onSave={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/Override the federal estate exemption/)).toBeInTheDocument();
    expect(
      screen.getByText(
        /US estate tax, including the exemptions below, applies only to a death in a year you live in the US/,
      ),
    ).toBeInTheDocument();
  });
});
