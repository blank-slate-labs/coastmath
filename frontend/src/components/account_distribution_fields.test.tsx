import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import AccountForm from "./account_form";
import { cleanDistributionSettings } from "./account_distribution_fields";
import type { Account } from "@/types/plan";

const account = (overrides: Partial<Account> = {}): Account => ({
  id: "a1",
  user_id: "u1",
  name: "Work 401(k)",
  account_type: "traditional_401k",
  balance: 400000,
  owner: "self",
  ...overrides,
});
const setup = (initial: Account) => {
  const onSubmit = vi.fn();
  render(<AccountForm initial={initial} onSubmit={onSubmit} onCancel={() => {}} />);
  return onSubmit;
};

describe("account distribution rules", () => {
  it("offers the separation year for a workplace plan and saves it", () => {
    const onSubmit = setup(account());
    fireEvent.change(screen.getByLabelText(/Year you left this plan's employer/), {
      target: { value: "2031" },
    });
    fireEvent.click(screen.getByRole("button", { name: /update|save/i }));
    expect(onSubmit.mock.calls[0][0].distribution_settings).toEqual({ separation_year: 2031 });
  });

  it("never offers a separation year for an IRA, only the spouse-beneficiary election", () => {
    const onSubmit = setup(account({ account_type: "traditional_ira", name: "IRA" }));
    expect(screen.queryByLabelText(/Year you left this plan's employer/)).toBeNull();
    fireEvent.click(screen.getByLabelText(/Spouse is the sole beneficiary/));
    fireEvent.click(screen.getByRole("button", { name: /update|save/i }));
    expect(onSubmit.mock.calls[0][0].distribution_settings).toEqual({
      spouse_sole_beneficiary: true,
    });
  });

  it("shows no distribution rules for a Roth IRA or a brokerage account", () => {
    setup(account({ account_type: "roth_ira", name: "Roth" }));
    expect(screen.queryByText("Distribution rules")).toBeNull();
  });

  it("leaves distribution settings out of an unchanged payload and clears a saved one", () => {
    const untouched = setup(account());
    fireEvent.click(screen.getByRole("button", { name: /update|save/i }));
    expect(untouched.mock.calls[0][0]).not.toHaveProperty("distribution_settings");
  });

  it("drops settings that do not fit the account", () => {
    expect(
      cleanDistributionSettings("traditional_ira", "self", false, {
        separation_year: 2030,
        spouse_sole_beneficiary: true,
      }),
    ).toEqual({ spouse_sole_beneficiary: true });
    expect(
      cleanDistributionSettings("traditional_401k", "self", true, { separation_year: 2030 }),
    ).toBeNull();
    expect(
      cleanDistributionSettings("traditional_401k", "joint", false, {
        spouse_sole_beneficiary: true,
      }),
    ).toBeNull();
  });
});
