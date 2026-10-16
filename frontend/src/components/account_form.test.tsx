import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import AccountForm from "./account_form";
import type { Account } from "@/types/plan";

function makeAccount(overrides: Partial<Account> = {}): Account {
  return {
    id: "a1",
    user_id: "u1",
    name: "Brokerage",
    account_type: "taxable_brokerage",
    balance: 250000,
    owner: "self",
    ...overrides,
  };
}

describe("AccountForm — cost_basis", () => {
  it("shows the cost_basis input for taxable_brokerage", () => {
    render(<AccountForm initial={makeAccount()} onSubmit={() => {}} onCancel={() => {}} />);
    expect(screen.getByLabelText(/cost basis/i)).toBeInTheDocument();
  });

  it("does NOT show cost_basis input for checking accounts", () => {
    render(
      <AccountForm
        initial={makeAccount({
          account_type: "checking",
          name: "Bank",
          balance: 5000,
        })}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.queryByLabelText(/cost basis/i)).toBeNull();
  });

  it("submits cost_basis=150000 when entered on a taxable_brokerage", () => {
    const handleSubmit = vi.fn();
    render(<AccountForm initial={makeAccount()} onSubmit={handleSubmit} onCancel={() => {}} />);

    const input = screen.getByLabelText(/cost basis/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "150000" } });
    fireEvent.click(screen.getByText("Update Account"));

    expect(handleSubmit).toHaveBeenCalledTimes(1);
    expect(handleSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        account_type: "taxable_brokerage",
        cost_basis: 150000,
      }),
    );
  });

  it("submits 529 contributions as its basis only when entered", () => {
    const handleSubmit = vi.fn();
    render(
      <AccountForm
        initial={makeAccount({ account_type: "five_twenty_nine", name: "529" })}
        onSubmit={handleSubmit}
        onCancel={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("Update Account"));
    expect(handleSubmit.mock.calls[0][0]).not.toHaveProperty("cost_basis");
    fireEvent.change(screen.getByLabelText("529 contributions"), { target: { value: "60000" } });
    fireEvent.click(screen.getByText("Update Account"));
    expect(handleSubmit.mock.calls[1][0]).toMatchObject({
      account_type: "five_twenty_nine",
      cost_basis: 60000,
    });
  });

  it("pre-fills cost_basis input when editing an account with a preset value", () => {
    render(
      <AccountForm
        initial={makeAccount({ cost_basis: 150000 })}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    const input = screen.getByLabelText(/cost basis/i) as HTMLInputElement;
    expect(input.value).toBe("150,000");
  });

  it("submits cost_basis=null when the input is cleared on a taxable_brokerage (explicit unset)", () => {
    const handleSubmit = vi.fn();
    render(
      <AccountForm
        initial={makeAccount({ cost_basis: 150000 })}
        onSubmit={handleSubmit}
        onCancel={() => {}}
      />,
    );

    const input = screen.getByLabelText(/cost basis/i) as HTMLInputElement;
    expect(input.value).toBe("150,000");
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.click(screen.getByText("Update Account"));

    expect(handleSubmit).toHaveBeenCalledTimes(1);
    const payload = handleSubmit.mock.calls[0][0];
    expect(payload).toHaveProperty("cost_basis", null);
  });

  it("omits cost_basis entirely for non-taxable account types", () => {
    const handleSubmit = vi.fn();
    render(
      <AccountForm
        initial={makeAccount({ account_type: "checking", name: "Bank" })}
        onSubmit={handleSubmit}
        onCancel={() => {}}
      />,
    );

    fireEvent.click(screen.getByText("Update Account"));
    expect(handleSubmit).toHaveBeenCalledTimes(1);
    const payload = handleSubmit.mock.calls[0][0];
    expect(payload).not.toHaveProperty("cost_basis");
  });

  it("enforces min=0 on the cost_basis input", () => {
    render(<AccountForm initial={makeAccount()} onSubmit={() => {}} onCancel={() => {}} />);
    const input = screen.getByLabelText(/cost basis/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "-5" } });
    expect(input.validationMessage).toBe("Enter 0 or more.");
  });
});

it("does not resend unchanged inherited elections or Roth history on an unrelated edit", () => {
  const submit = vi.fn();
  const history = {
    contribution_basis: 60000,
    first_contribution_year: 2010,
    conversions: [{ year: 2024, taxable_basis: 10000, nontaxable_basis: 2000 }],
  };
  const inheritance = {
    distribution_method: "life_expectancy" as const,
    decedent_birth_year: 1940,
    decedent_died_after_rbd: true,
  };
  render(
    <AccountForm
      initial={makeAccount({
        account_type: "roth_ira",
        inherited_year: 2024,
        beneficiary_type: "spouse",
        inheritance_settings: inheritance,
        roth_settings: history,
      })}
      onSubmit={submit}
      onCancel={() => {}}
    />,
  );
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Renamed Roth" } });
  fireEvent.click(screen.getByText("Update Account"));
  expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ name: "Renamed Roth" }));
  const data = submit.mock.lastCall![0];
  for (const key of [
    "inherited_year",
    "beneficiary_type",
    "inheritance_settings",
    "roth_settings",
  ]) {
    expect(data).not.toHaveProperty(key);
  }
  expect(screen.getByLabelText("Undistributed regular contributions ($)")).toHaveValue("60,000");
});

it("submits explicit Roth basis and dated taxable versus nontaxable conversion principal", () => {
  const submit = vi.fn();
  render(
    <AccountForm
      initial={makeAccount({ account_type: "roth_ira" })}
      onSubmit={submit}
      onCancel={() => {}}
    />,
  );
  fireEvent.click(screen.getByLabelText(/Enter Roth contribution/));
  fireEvent.change(screen.getByLabelText(/Undistributed regular/), { target: { value: "60000" } });
  fireEvent.change(screen.getByLabelText(/First Roth contribution/), { target: { value: "2010" } });
  fireEvent.click(screen.getByText("Add past conversion"));
  fireEvent.change(screen.getByLabelText("Conversion tax year"), { target: { value: "2024" } });
  fireEvent.change(screen.getByLabelText(/Previously taxable conversion/), {
    target: { value: "10000" },
  });
  fireEvent.change(screen.getByLabelText(/Nontaxable conversion/), { target: { value: "2000" } });
  fireEvent.click(screen.getByText("Update Account"));
  expect(submit).toHaveBeenLastCalledWith(
    expect.objectContaining({
      roth_settings: {
        contribution_basis: 60000,
        first_contribution_year: 2010,
        conversions: [{ year: 2024, taxable_basis: 10000, nontaxable_basis: 2000 }],
      },
    }),
  );
  fireEvent.change(screen.getByLabelText("Account Type"), { target: { value: "checking" } });
  fireEvent.click(screen.getByText("Update Account"));
  expect(submit).toHaveBeenLastCalledWith(
    expect.objectContaining({
      inherited_year: null,
      inheritance_settings: null,
      roth_settings: null,
    }),
  );
});

it("submits fixed investment overrides as decimal rates", () => {
  const submit = vi.fn();
  render(<AccountForm initial={makeAccount()} onSubmit={submit} onCancel={() => {}} />);

  fireEvent.click(screen.getByLabelText("Use fixed settings for this account"));
  fireEvent.change(screen.getByLabelText("Stock price growth (%)"), { target: { value: "5" } });
  fireEvent.change(screen.getByLabelText("Stock dividend yield (%)"), { target: { value: "1.5" } });
  fireEvent.change(screen.getByLabelText("Bond allocation (%)"), { target: { value: "40" } });
  fireEvent.click(screen.getByText("Update Account"));

  expect(submit).toHaveBeenLastCalledWith(
    expect.objectContaining({
      investment_settings: {
        stock_growth_rate: 0.05,
        dividend_yield: 0.015,
        bond_allocation: 0.4,
        // Untouched income-composition fields keep the legacy treatment.
        qualified_dividend_ratio: null,
        bond_income_yield: null,
        bond_income_mix: null,
        municipal_state_exempt: null,
        annual_fee_rate: null,
      },
    }),
  );
});

describe("AccountForm — dividend and bond income composition", () => {
  const composed = {
    stock_growth_rate: null,
    dividend_yield: null,
    bond_allocation: 0.4,
    qualified_dividend_ratio: 0.7,
    bond_income_yield: 0.035,
    bond_income_mix: { treasury: 0.5, municipal: 0.3, other: 0.2 },
    municipal_state_exempt: true,
    annual_fee_rate: null,
  };

  it("submits percent inputs as 0-1 fractions", () => {
    const submit = vi.fn();
    render(<AccountForm initial={makeAccount()} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.click(screen.getByLabelText("Use fixed settings for this account"));
    fireEvent.change(screen.getByLabelText("Qualified dividends (%)"), { target: { value: "70" } });
    fireEvent.change(screen.getByLabelText("Bond income yield (%)"), { target: { value: "3.5" } });
    fireEvent.change(screen.getByLabelText("Treasury bond income (%)"), {
      target: { value: "60" },
    });
    fireEvent.change(screen.getByLabelText("Municipal bond income (%)"), {
      target: { value: "40" },
    });
    fireEvent.click(screen.getByLabelText(/In-state municipal bonds/));
    fireEvent.click(screen.getByText("Update Account"));

    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        investment_settings: {
          stock_growth_rate: null,
          dividend_yield: null,
          bond_allocation: null,
          qualified_dividend_ratio: 0.7,
          bond_income_yield: 0.035,
          // A blank share counts as zero once any share is entered.
          bond_income_mix: { treasury: 0.6, municipal: 0.4, other: 0 },
          municipal_state_exempt: true,
          annual_fee_rate: null,
        },
      }),
    );
  });

  it("blocks a mix that does not add up to 100%", () => {
    const submit = vi.fn();
    render(<AccountForm initial={makeAccount()} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.click(screen.getByLabelText("Use fixed settings for this account"));
    fireEvent.change(screen.getByLabelText("Treasury bond income (%)"), {
      target: { value: "50" },
    });
    fireEvent.change(screen.getByLabelText("Other bond income (%)"), { target: { value: "30" } });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Treasury, municipal and other must add up to 100% (now 80%).",
    );
    expect(screen.getByLabelText("Treasury bond income (%)")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Municipal bond income (%)"), {
      target: { value: "20" },
    });
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("shows saved fractions as percents and leaves unchanged settings unsent", () => {
    const submit = vi.fn();
    render(
      <AccountForm
        initial={makeAccount({ investment_settings: composed })}
        onSubmit={submit}
        onCancel={() => {}}
      />,
    );
    expect(
      screen.getByText("Advanced: how dividends and bond income are taxed").closest("details"),
    ).toHaveAttribute("open");
    expect(screen.getByLabelText("Qualified dividends (%)")).toHaveValue(70);
    expect(screen.getByLabelText("Bond income yield (%)")).toHaveValue(3.5);
    expect(screen.getByLabelText("Treasury bond income (%)")).toHaveValue(50);
    expect(screen.getByLabelText("Municipal bond income (%)")).toHaveValue(30);
    expect(screen.getByLabelText("Other bond income (%)")).toHaveValue(20);
    expect(screen.getByLabelText(/In-state municipal bonds/)).toBeChecked();
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit.mock.calls[0][0]).not.toHaveProperty("investment_settings");
  });

  it("is offered only for taxable brokerage accounts and cleared for other types", () => {
    const submit = vi.fn();
    render(
      <AccountForm
        initial={makeAccount({ investment_settings: composed })}
        onSubmit={submit}
        onCancel={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText("Account Type"), {
      target: { value: "traditional_ira" },
    });
    expect(screen.queryByLabelText("Qualified dividends (%)")).toBeNull();
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        investment_settings: expect.objectContaining({
          bond_allocation: 0.4,
          qualified_dividend_ratio: null,
          bond_income_yield: null,
          bond_income_mix: null,
          municipal_state_exempt: null,
        }),
      }),
    );
  });
});

it("states the tax assumption only for 529 and other accounts", () => {
  render(
    <AccountForm
      initial={makeAccount({ account_type: "five_twenty_nine", name: "College" })}
      onSubmit={() => {}}
      onCancel={() => {}}
    />,
  );
  expect(screen.getByRole("combobox", { name: /account type/i })).toHaveAccessibleDescription(
    "Withdrawals are tax free up to the year’s qualified education expenses; beyond them, earnings are taxed plus 10%.",
  );
  fireEvent.change(screen.getByRole("combobox", { name: /account type/i }), {
    target: { value: "other" },
  });
  expect(screen.getByText("Growth and withdrawals are treated as untaxed.")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: /account type/i }), {
    target: { value: "hsa" },
  });
  expect(screen.queryByText(/treated as/)).toBeNull();
  expect(screen.getByRole("combobox", { name: /account type/i })).not.toHaveAttribute(
    "aria-describedby",
  );
});

describe("AccountForm — annual fee", () => {
  it("submits the percent input as a 0-1 fraction next to the dividend yield", () => {
    const submit = vi.fn();
    render(
      <AccountForm
        initial={makeAccount({ account_type: "traditional_ira" })}
        onSubmit={submit}
        onCancel={() => {}}
      />,
    );
    fireEvent.click(screen.getByLabelText("Use fixed settings for this account"));
    const fee = screen.getByLabelText("Annual fee (%)");
    expect(fee).toHaveAttribute("min", "0");
    expect(fee).toHaveAttribute("max", "5");
    fireEvent.change(fee, { target: { value: "1.25" } });
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        investment_settings: expect.objectContaining({
          annual_fee_rate: 0.0125,
          dividend_yield: null,
        }),
      }),
    );
  });

  it("shows a saved fee as a percent and leaves an unchanged fee unsent", () => {
    const submit = vi.fn();
    const saved = {
      stock_growth_rate: null,
      dividend_yield: null,
      bond_allocation: null,
      qualified_dividend_ratio: null,
      bond_income_yield: null,
      bond_income_mix: null,
      municipal_state_exempt: null,
      annual_fee_rate: 0.0075,
    };
    render(
      <AccountForm
        initial={makeAccount({ investment_settings: saved })}
        onSubmit={submit}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByLabelText("Annual fee (%)")).toHaveValue(0.75);
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit.mock.calls[0][0]).not.toHaveProperty("investment_settings");
  });

  it("sends null for a blank fee and is not offered for cash accounts", () => {
    const submit = vi.fn();
    render(<AccountForm initial={makeAccount()} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.click(screen.getByLabelText("Use fixed settings for this account"));
    fireEvent.change(screen.getByLabelText("Bond allocation (%)"), { target: { value: "40" } });
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        investment_settings: expect.objectContaining({ annual_fee_rate: null }),
      }),
    );
    fireEvent.change(screen.getByLabelText("Account Type"), { target: { value: "checking" } });
    expect(screen.queryByLabelText("Annual fee (%)")).toBeNull();
  });
});

describe("AccountForm — inherited plan assumptions", () => {
  const plan = {
    assumption_curves: [
      {
        id: "c1",
        plan_id: "p1",
        curve_type: "market_return" as const,
        mode: "fixed" as const,
        fixed_rate: 0.065,
        control_points: [],
      },
      {
        id: "c2",
        plan_id: "p1",
        curve_type: "bond_allocation" as const,
        mode: "curve" as const,
        fixed_rate: null,
        control_points: [
          { x: 40, y: 0.2 },
          { x: 70, y: 0.6 },
        ],
      },
    ],
    assumption_defaults: { market_return: 0.07, dividend_yield: 0.015, bond_allocation: 0 },
  };

  it("lists the plan values an account inherits and uses them as placeholders", () => {
    render(
      <AccountForm
        initial={makeAccount()}
        planAssumptions={plan}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    const inherited = screen.getByLabelText("Plan investment assumptions");
    expect(inherited).toHaveTextContent("Stock price growth6.5%");
    expect(inherited).toHaveTextContent("Dividend yield1.5%");
    expect(inherited).toHaveTextContent("Bond allocationCurve");
    fireEvent.click(screen.getByLabelText("Use fixed settings for this account"));
    expect(screen.queryByLabelText("Plan investment assumptions")).toBeNull();
    expect(screen.getByLabelText("Stock price growth (%)")).toHaveAttribute("placeholder", "6.5");
    expect(screen.getByLabelText("Stock dividend yield (%)")).toHaveAttribute("placeholder", "1.5");
    expect(screen.getByLabelText("Bond allocation (%)")).toHaveAttribute(
      "placeholder",
      "Plan curve",
    );
  });
});

describe("AccountForm — joint owner", () => {
  it.each(["roth_ira", "traditional_401k", "hsa"])(
    "drops a joint owner when the type changes to %s",
    (type) => {
      const submit = vi.fn();
      render(
        <AccountForm
          initial={makeAccount({ owner: "joint" })}
          onSubmit={submit}
          onCancel={() => {}}
        />,
      );
      expect(screen.getByRole("option", { name: "Joint" })).toBeInTheDocument();
      fireEvent.change(screen.getByLabelText("Account Type"), { target: { value: type } });
      expect(screen.queryByRole("option", { name: "Joint" })).toBeNull();
      fireEvent.click(screen.getByText("Update Account"));
      expect(submit).toHaveBeenLastCalledWith(
        expect.objectContaining({ account_type: type, owner: "self" }),
      );
    },
  );

  it("shows a legacy joint IRA's owner for review and keeps it on unrelated edits", () => {
    const submit = vi.fn();
    render(
      <AccountForm
        initial={makeAccount({ account_type: "traditional_ira", owner: "joint" })}
        onSubmit={submit}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByLabelText("Owner")).toHaveDisplayValue(
      "joint (existing value — review owner)",
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Renamed IRA" } });
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ name: "Renamed IRA", owner: "joint" }),
    );
  });
});

describe("AccountForm — employer plan types", () => {
  it("groups the account types by category, with the new employer plans", () => {
    render(<AccountForm onSubmit={() => {}} onCancel={() => {}} />);
    const groups = screen.getAllByRole("group").filter((group) => group.tagName === "OPTGROUP");
    expect(groups.map((group) => group.getAttribute("label"))).toEqual([
      "Employer plans",
      "IRAs",
      "Taxable and cash",
      "Other",
    ]);
    const employer = Array.from(groups[0].querySelectorAll("option")).map(
      (option) => option.textContent,
    );
    expect(employer).toEqual([
      "Traditional 401(k)",
      "Roth 401(k)",
      "Traditional 403(b)",
      "Roth 403(b)",
      "Traditional 457(b)",
      "Roth 457(b)",
      "401(a)",
    ]);
  });

  it.each(["traditional_403b", "roth_457b", "traditional_401a"])(
    "drops a joint owner and saves %s",
    (type) => {
      const submit = vi.fn();
      render(
        <AccountForm
          initial={makeAccount({ owner: "joint" })}
          onSubmit={submit}
          onCancel={() => {}}
        />,
      );
      fireEvent.change(screen.getByLabelText("Account Type"), { target: { value: type } });
      expect(screen.queryByRole("option", { name: "Joint" })).toBeNull();
      fireEvent.click(screen.getByText("Update Account"));
      expect(submit).toHaveBeenLastCalledWith(
        expect.objectContaining({ account_type: type, owner: "self" }),
      );
    },
  );

  it("keeps inherited history for a 457(b) and explains its treatment", () => {
    const submit = vi.fn();
    render(
      <AccountForm
        initial={makeAccount({ account_type: "traditional_457b", inherited_year: 2023 })}
        onSubmit={submit}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByText(/governmental 457\(b\)/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Year original owner died/)).toHaveValue(2023);
    // The type note is inside the label, so match the label's start.
    fireEvent.change(screen.getByLabelText(/^Account Type/), { target: { value: "roth_403b" } });
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({ account_type: "roth_403b", inherited_year: 2023 }),
    );
  });

  it("notes that a 401(a) is employer-funded", () => {
    render(
      <AccountForm
        initial={makeAccount({ account_type: "traditional_401a" })}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(
      screen.getByText("Employer contributions only; no employee deferrals."),
    ).toBeInTheDocument();
  });
});

describe("AccountForm — withdrawals available", () => {
  const milestones = [
    { id: "m1", name: "Leave employer" },
    { id: "m2", name: "Retire" },
  ];
  const submit = (onSubmit = vi.fn(), props: Partial<Parameters<typeof AccountForm>[0]> = {}) => {
    render(
      <AccountForm milestones={milestones} onSubmit={onSubmit} onCancel={() => {}} {...props} />,
    );
    return onSubmit;
  };

  it("defaults to any time and sends no lock for a new account", () => {
    const onSubmit = submit();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Cash" } });
    expect((screen.getByLabelText("Withdrawals available") as HTMLSelectElement).value).toBe("any");
    fireEvent.click(screen.getByText("Add Account"));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ withdrawal_lock: null }));
  });

  it.each([
    ["age", "Unlock age", "59.5", { unlock: "age", age: 59.5, milestone_id: null, year: null }],
    ["year", "Unlock year", "2031", { unlock: "year", age: null, milestone_id: null, year: 2031 }],
    [
      "milestone",
      "Unlock milestone",
      "m2",
      { unlock: "milestone", age: null, milestone_id: "m2", year: null },
    ],
  ])("sends a %s lock with exactly that field", (kind, label, value, expected) => {
    const onSubmit = submit();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Deferred comp" } });
    fireEvent.change(screen.getByLabelText("Withdrawals available"), { target: { value: kind } });
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByText("Add Account"));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ withdrawal_lock: expected }));
  });

  it("blocks saving a lock without its value", () => {
    const onSubmit = submit();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "CD" } });
    fireEvent.change(screen.getByLabelText("Withdrawals available"), { target: { value: "year" } });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter the year withdrawals become available.",
    );
    fireEvent.click(screen.getByText("Add Account"));
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Unlock year"), { target: { value: "2031.5" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a year from 1900 to 2200.");
  });

  it("leaves an unchanged saved lock out of an edit and can clear it", () => {
    const saved = { unlock: "milestone" as const, age: null, milestone_id: "m1", year: null };
    const onSubmit = submit(vi.fn(), { initial: makeAccount({ withdrawal_lock: saved }) });
    expect((screen.getByLabelText("Unlock milestone") as HTMLSelectElement).value).toBe("m1");
    fireEvent.click(screen.getByText("Update Account"));
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty("withdrawal_lock");
    fireEvent.change(screen.getByLabelText("Withdrawals available"), { target: { value: "any" } });
    fireEvent.click(screen.getByText("Update Account"));
    expect(onSubmit.mock.calls[1][0]).toEqual(expect.objectContaining({ withdrawal_lock: null }));
  });

  it("keeps another plan's milestone selectable on a shared account", () => {
    const saved = {
      unlock: "milestone" as const,
      age: null,
      milestone_id: "elsewhere",
      year: null,
    };
    const onSubmit = submit(vi.fn(), { initial: makeAccount({ withdrawal_lock: saved }) });
    expect(screen.getByRole("option", { name: "A milestone in another plan" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Renamed" } });
    fireEvent.click(screen.getByText("Update Account"));
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty("withdrawal_lock");
  });

  it("starts an age lock at 59½ where the 10% additional tax applies and follows the type", () => {
    submit();
    const type = screen.getByLabelText("Account Type");
    fireEvent.change(type, { target: { value: "roth_ira" } });
    fireEvent.change(screen.getByLabelText("Withdrawals available"), { target: { value: "age" } });
    const age = screen.getByLabelText("Unlock age") as HTMLInputElement;
    expect(age.value).toBe("59.5");
    fireEvent.change(type, { target: { value: "traditional_457b" } });
    expect(age.value).toBe("");
    fireEvent.change(type, { target: { value: "traditional_401k" } });
    expect(age.value).toBe("59.5");
    fireEvent.change(age, { target: { value: "62" } });
    fireEvent.change(type, { target: { value: "roth_401k" } });
    expect(age.value).toBe("62");
  });

  it("labels the age by the account owner", () => {
    submit(vi.fn(), {
      initial: makeAccount({
        owner: "spouse",
        withdrawal_lock: { unlock: "age", age: 62, milestone_id: null, year: null },
      }),
    });
    expect(screen.getByText("Partner's age")).toBeInTheDocument();
    expect((screen.getByLabelText("Unlock age") as HTMLInputElement).value).toBe("62");
  });
});

describe("AccountForm — state_taxed_basis", () => {
  it("shows the field for traditional retirement accounts only", () => {
    const { unmount } = render(
      <AccountForm
        initial={makeAccount({ account_type: "traditional_ira", name: "IRA" })}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByLabelText(/contributions your state already taxed/i)).toBeInTheDocument();
    unmount();
    render(
      <AccountForm
        initial={makeAccount({ account_type: "roth_ira", name: "Roth" })}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.queryByLabelText(/contributions your state already taxed/i)).toBeNull();
  });

  it("submits the entered amount and omits an unchanged blank", () => {
    const handleSubmit = vi.fn();
    const { unmount } = render(
      <AccountForm
        initial={makeAccount({ account_type: "traditional_403b", name: "403(b)" })}
        onSubmit={handleSubmit}
        onCancel={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("Update Account"));
    expect(handleSubmit.mock.calls[0][0]).not.toHaveProperty("state_taxed_basis");
    unmount();
    render(
      <AccountForm
        initial={makeAccount({ account_type: "traditional_403b", name: "403(b)" })}
        onSubmit={handleSubmit}
        onCancel={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText(/contributions your state already taxed/i), {
      target: { value: "42000" },
    });
    fireEvent.click(screen.getByText("Update Account"));
    expect(handleSubmit.mock.calls[1][0]).toMatchObject({ state_taxed_basis: 42000 });
  });
});

describe("AccountForm — bond glide path", () => {
  const saved = {
    stock_growth_rate: null,
    dividend_yield: null,
    bond_allocation: null,
    qualified_dividend_ratio: null,
    bond_income_yield: null,
    bond_income_mix: null,
    municipal_state_exempt: null,
    annual_fee_rate: null,
    bond_allocation_glide: [
      { year: null, age: 50, bond_allocation: 0.3 },
      { year: null, age: 65, bond_allocation: 0.6 },
    ],
  };

  it("submits age points as fractions and omits the key when there are none", () => {
    const submit = vi.fn();
    render(<AccountForm initial={makeAccount()} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.click(screen.getByLabelText("Use fixed settings for this account"));
    fireEvent.change(screen.getByLabelText("Bond allocation (%)"), { target: { value: "40" } });
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit.mock.calls[0][0].investment_settings).not.toHaveProperty("bond_allocation_glide");

    fireEvent.change(screen.getByLabelText("Glide path points by"), { target: { value: "age" } });
    fireEvent.click(screen.getByText("Add glide path point"));
    fireEvent.change(screen.getByLabelText("Glide path age 1"), { target: { value: "55" } });
    fireEvent.change(screen.getByLabelText("Glide path bonds 1 (%)"), { target: { value: "35" } });
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        investment_settings: expect.objectContaining({
          bond_allocation_glide: [{ year: null, age: 55, bond_allocation: 0.35 }],
        }),
      }),
    );
  });

  it("blocks an incomplete row", () => {
    const submit = vi.fn();
    render(<AccountForm initial={makeAccount()} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.click(screen.getByLabelText("Use fixed settings for this account"));
    fireEvent.click(screen.getByText("Add glide path point"));
    fireEvent.change(screen.getByLabelText("Glide path year 1"), { target: { value: "2030" } });
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Fill in or remove each glide path row.");
  });

  it("leaves an unchanged saved path unsent and clears a removed one with an empty list", () => {
    const submit = vi.fn();
    render(
      <AccountForm
        initial={makeAccount({ investment_settings: saved })}
        onSubmit={submit}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByLabelText("Glide path age 2")).toHaveValue(65);
    expect(screen.getByLabelText("Glide path bonds 1 (%)")).toHaveValue(30);
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit.mock.calls[0][0]).not.toHaveProperty("investment_settings");

    fireEvent.click(screen.getByLabelText("Remove glide path point 2"));
    fireEvent.click(screen.getByLabelText("Remove glide path point 1"));
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        investment_settings: expect.objectContaining({ bond_allocation_glide: [] }),
      }),
    );
  });
});

describe("AccountForm — fee types and paid-out income", () => {
  it("submits a flat fee, a fee on gains and paid-out income for a brokerage account", () => {
    const submit = vi.fn();
    render(<AccountForm initial={makeAccount()} onSubmit={submit} onCancel={() => {}} />);
    fireEvent.click(screen.getByLabelText("Use fixed settings for this account"));
    fireEvent.change(screen.getByLabelText("Annual fee ($)"), { target: { value: "250" } });
    fireEvent.change(screen.getByLabelText("Fee on gains (%)"), { target: { value: "10" } });
    fireEvent.click(screen.getByLabelText("Reinvest dividends and interest"));
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        investment_settings: expect.objectContaining({
          annual_fee_amount: 250,
          fee_percent_of_earnings: 0.1,
          reinvest_income: false,
        }),
      }),
    );
  });

  it("keeps older unchanged settings unsent and offers reinvestment only for brokerage accounts", () => {
    const submit = vi.fn();
    const saved = {
      stock_growth_rate: null,
      dividend_yield: null,
      bond_allocation: null,
      qualified_dividend_ratio: null,
      bond_income_yield: null,
      bond_income_mix: null,
      municipal_state_exempt: null,
      annual_fee_rate: 0.005,
    };
    render(
      <AccountForm
        initial={makeAccount({ account_type: "traditional_ira", investment_settings: saved })}
        onSubmit={submit}
        onCancel={() => {}}
      />,
    );
    expect(screen.queryByLabelText("Reinvest dividends and interest")).toBeNull();
    fireEvent.click(screen.getByText("Update Account"));
    expect(submit.mock.calls[0][0]).not.toHaveProperty("investment_settings");
  });

  it("shows saved new settings", () => {
    const saved = {
      stock_growth_rate: null,
      dividend_yield: null,
      bond_allocation: null,
      qualified_dividend_ratio: null,
      bond_income_yield: null,
      bond_income_mix: null,
      municipal_state_exempt: null,
      annual_fee_rate: null,
      annual_fee_amount: 120,
      fee_percent_of_earnings: 0.2,
      reinvest_income: false,
    };
    render(
      <AccountForm
        initial={makeAccount({ investment_settings: saved })}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByLabelText("Annual fee ($)")).toHaveValue("120");
    expect(screen.getByLabelText("Fee on gains (%)")).toHaveValue(20);
    expect(screen.getByLabelText("Reinvest dividends and interest")).not.toBeChecked();
  });
});
