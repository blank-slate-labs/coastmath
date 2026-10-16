import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { SEPPCalculator } from "./sepp_calculator";
import type { YearSnapshot, PlanData, Account, SEPPPreviewResponse } from "@/types/plan";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";

const mockUpdatePlan = vi.fn();
let mockPlan: PlanData | null = null;

vi.mock("@/stores/plan_store", () => ({
  usePlanStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({ plan: mockPlan, updatePlan: mockUpdatePlan }),
}));

const mockListAccounts = vi.fn<() => Promise<Account[]>>();
const mockPreviewSepp = vi.fn<(body: unknown) => Promise<SEPPPreviewResponse>>();
vi.mock("@/api/client", () => ({
  previewSepp: (body: unknown) => mockPreviewSepp(body),
}));
// One stable storage value, as the provider memoizes it.
const adapter = makeAdapter({ listAccounts: mockListAccounts });
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);

const accounts: Account[] = [
  {
    id: "trad-1",
    user_id: "u1",
    name: "Trad IRA",
    account_type: "traditional_ira",
    balance: 500000,
    owner: "self",
  },
  {
    id: "roth-1",
    user_id: "u1",
    name: "Roth IRA",
    account_type: "roth_ira",
    balance: 50000,
    owner: "self",
  },
  {
    id: "check-1",
    user_id: "u1",
    name: "Checking",
    account_type: "checking",
    balance: 10000,
    owner: "self",
  },
] as Account[];

const basePlan = makePlan({
  id: "plan-1",
  user_id: "u1",
  name: "Test Plan",
  birth_year: 1980,
  created_at: "2025-01-01",
});

const preview: SEPPPreviewResponse = {
  single_life_divisor: 36.2,
  end_age: 59.5,
  payment_years: 11,
  methods: [
    {
      method: "rmd_method",
      first_year_amount: 13812,
      schedule: [{ age: 50, year: 2030, withdrawal: 13812, remaining: 486188 }],
    },
    {
      method: "fixed_amortization",
      first_year_amount: 30185,
      schedule: [
        { age: 50, year: 2030, withdrawal: 30185, remaining: 469815 },
        { age: 51, year: 2031, withdrawal: 30185, remaining: 463120 },
      ],
    },
  ],
  notes: ["Payments must continue for five years or until age 59 1/2, whichever is later."],
};

const snapshots: YearSnapshot[] = [
  { year: 2026, age: 46, accounts: {} } as unknown as YearSnapshot,
];

describe("SEPPCalculator", () => {
  beforeEach(() => {
    mockUpdatePlan.mockReset().mockResolvedValue(undefined);
    mockListAccounts.mockResolvedValue(accounts);
    mockPreviewSepp.mockReset().mockResolvedValue(preview);
    mockPlan = { ...basePlan };
  });

  it("renders nothing when plan is null", () => {
    mockPlan = null;
    const { container } = render(<SEPPCalculator snapshots={snapshots} />);
    expect(container.firstChild).toBeNull();
  });

  it("lists only pre-tax accounts and previews engine amounts for the chosen inputs", async () => {
    render(<SEPPCalculator snapshots={snapshots} />);
    fireEvent.click(screen.getByLabelText("Enabled"));
    const select = await screen.findByLabelText(/Source account/);
    const options = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
    expect(options.some((t) => t?.includes("Trad IRA"))).toBe(true);
    expect(options.some((t) => t?.includes("Roth IRA"))).toBe(false);
    fireEvent.change(select, { target: { value: "trad-1" } });
    await waitFor(() =>
      expect(mockPreviewSepp).toHaveBeenCalledWith({
        balance: 500000,
        start_age: 50,
        interest_rate: 0.05,
        birth_year: 1980,
        birth_month: null,
      }),
    );
    expect((await screen.findAllByText("$30,185")).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/11 annual payments/)).toBeInTheDocument();
    expect(screen.getByText(/Single Life factor at start:/)).toHaveTextContent("36.2");
  });

  it("blocks a start age at or after 59.5 and saves valid settings in decimal rate units", async () => {
    render(<SEPPCalculator snapshots={snapshots} />);
    fireEvent.click(screen.getByLabelText("Enabled"));
    const select = await screen.findByLabelText(/Source account/);
    fireEvent.change(select, { target: { value: "trad-1" } });
    fireEvent.change(screen.getByLabelText("Start age"), { target: { value: "60" } });
    expect(screen.getByRole("alert")).toHaveTextContent("cannot begin at 59½");
    expect(screen.getByRole("button", { name: "Save SEPP settings" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Start age"), { target: { value: "52" } });
    fireEvent.change(screen.getByLabelText(/Interest rate/), { target: { value: "4.5" } });
    fireEvent.click(screen.getByLabelText(/Required-minimum-distribution method/));
    fireEvent.click(screen.getByRole("button", { name: "Save SEPP settings" }));
    await waitFor(() =>
      expect(mockUpdatePlan).toHaveBeenCalledWith("plan-1", {
        sepp_settings: {
          enabled: true,
          source_account_id: "trad-1",
          method: "rmd_method",
          start_age: 52,
          interest_rate: 0.045,
        },
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("saved");
  });

  it("warns when the rate exceeds the 5% safe harbor and disables a saved series without losing it", async () => {
    mockPlan = {
      ...basePlan,
      sepp_settings: {
        enabled: true,
        source_account_id: "trad-1",
        method: "fixed_amortization",
        start_age: 50,
        interest_rate: 0.05,
      },
    };
    render(<SEPPCalculator snapshots={snapshots} />);
    await screen.findByLabelText(/Source account/);
    fireEvent.change(screen.getByLabelText(/Interest rate/), { target: { value: "6" } });
    expect(
      screen
        .getAllByRole("alert")
        .some((el) => el.textContent?.includes("120% of the federal mid-term rate")),
    ).toBe(true);
    fireEvent.click(screen.getByLabelText("Enabled"));
    fireEvent.click(screen.getByRole("button", { name: "Save SEPP settings" }));
    await waitFor(() =>
      expect(mockUpdatePlan).toHaveBeenCalledWith("plan-1", {
        sepp_settings: {
          enabled: false,
          source_account_id: "trad-1",
          method: "fixed_amortization",
          start_age: 50,
          interest_rate: 0.05,
        },
      }),
    );
  });

  it("compares a rate above 5% with the ceiling the preview returns for the start month", async () => {
    mockPreviewSepp.mockResolvedValue({ ...preview, rate_ceiling: 0.0554 });
    mockPlan = {
      ...basePlan,
      sepp_settings: {
        enabled: true,
        source_account_id: "trad-1",
        method: "fixed_amortization",
        start_age: 50,
        interest_rate: 0.055,
      },
    };
    render(<SEPPCalculator snapshots={snapshots} />);
    expect(
      await screen.findByText(
        /120% of the federal mid-term rate before the first payment is 5.54%/,
      ),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Interest rate/), { target: { value: "6" } });
    await waitFor(() =>
      expect(
        screen
          .getAllByRole("alert")
          .some((el) => el.textContent?.includes("above the 5.54% allowed")),
      ).toBe(true),
    );
  });

  it("previews a partner-owned IRA with the partner's birth date and age", async () => {
    mockListAccounts.mockResolvedValue([
      ...accounts,
      {
        id: "partner-ira",
        user_id: "u1",
        name: "Partner IRA",
        account_type: "traditional_ira",
        balance: 400000,
        owner: "spouse",
      } as Account,
    ]);
    mockPlan = makePlan({
      ...basePlan,
      spouse: {
        id: "s1",
        plan_id: "plan-1",
        name: "Partner",
        birth_year: 1985,
        birth_month: 4,
        life_expectancy: 95,
      },
    });
    render(<SEPPCalculator snapshots={snapshots} />);
    fireEvent.click(screen.getByLabelText("Enabled"));
    fireEvent.change(await screen.findByLabelText(/Source account/), {
      target: { value: "partner-ira" },
    });
    fireEvent.change(screen.getByLabelText(/Start age/), { target: { value: "40" } });
    await waitFor(() =>
      expect(mockPreviewSepp).toHaveBeenLastCalledWith({
        balance: 400000,
        start_age: 40,
        interest_rate: 0.05,
        birth_year: 1985,
        birth_month: 4,
      }),
    );
    expect(screen.getByText("Ages are your partner's, who owns this account.")).toBeInTheDocument();
    // 2026 - 1985 = 41, the partner's age in the projection's first year.
    expect(
      screen
        .getAllByRole("alert")
        .some((el) => el.textContent?.includes("before your partner's current age 41")),
    ).toBe(true);
  });

  it("sends a custom yearly payment to the preview, shows when it does not qualify, and saves it", async () => {
    mockPreviewSepp.mockResolvedValue({
      ...preview,
      custom: {
        annual_amount: 40000,
        qualifies: false,
        approved_amount: 30185,
        message:
          "This amount is not an IRS-approved payment, so it is treated as an ordinary early withdrawal.",
      },
    });
    render(<SEPPCalculator snapshots={snapshots} />);
    fireEvent.click(screen.getByLabelText("Enabled"));
    fireEvent.change(await screen.findByLabelText(/Source account/), {
      target: { value: "trad-1" },
    });
    fireEvent.change(screen.getByLabelText(/Custom yearly payment/), {
      target: { value: "40000" },
    });
    await waitFor(() =>
      expect(mockPreviewSepp).toHaveBeenLastCalledWith({
        balance: 500000,
        start_age: 50,
        interest_rate: 0.05,
        birth_year: 1980,
        birth_month: null,
        annual_amount: 40000,
      }),
    );
    expect(await screen.findByText(/is not an IRS-approved payment/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save SEPP settings" }));
    await waitFor(() =>
      expect(mockUpdatePlan).toHaveBeenCalledWith("plan-1", {
        sepp_settings: {
          enabled: true,
          source_account_id: "trad-1",
          method: "fixed_amortization",
          start_age: 50,
          interest_rate: 0.05,
          annual_amount: 40000,
        },
      }),
    );
  });

  it("rejects a non-positive custom payment", async () => {
    render(<SEPPCalculator snapshots={snapshots} />);
    fireEvent.click(screen.getByLabelText("Enabled"));
    fireEvent.change(await screen.findByLabelText(/Source account/), {
      target: { value: "trad-1" },
    });
    fireEvent.change(screen.getByLabelText(/Custom yearly payment/), { target: { value: "-5" } });
    expect(
      screen
        .getAllByRole("alert")
        .some((el) => el.textContent?.includes("custom payment must be more than zero")),
    ).toBe(true);
    expect(screen.getByRole("button", { name: "Save SEPP settings" })).toBeDisabled();
  });
});
