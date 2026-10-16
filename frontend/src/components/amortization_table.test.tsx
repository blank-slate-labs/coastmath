import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import AmortizationTable from "./amortization_table";

const mockSchedule = [
  {
    year: 1,
    principal_paid: 8000,
    interest_paid: 6000,
    remaining_balance: 92000,
    cumulative_interest: 6000,
  },
  {
    year: 2,
    principal_paid: 8500,
    interest_paid: 5500,
    remaining_balance: 83500,
    cumulative_interest: 11500,
  },
  {
    year: 3,
    principal_paid: 9000,
    interest_paid: 5000,
    remaining_balance: 74500,
    cumulative_interest: 16500,
  },
  {
    year: 4,
    principal_paid: 74500,
    interest_paid: 4000,
    remaining_balance: 0,
    cumulative_interest: 20500,
  },
];

vi.mock("@/api/liabilities", () => ({
  getAmortizationSchedule: vi.fn(() => Promise.resolve({ schedule: mockSchedule })),
}));

vi.mock("@/stores/plan_store", () => ({
  usePlanStore: vi.fn((selector: (s: { currencyMode: string }) => string) =>
    selector({ currencyMode: "nominal" }),
  ),
}));

const defaultProps = {
  planId: "p1",
  liabilityId: "l1",
  inflationRate: 0.03,
  extraPayment: 0,
  principalBalance: 100000,
  interestRate: 6,
  termMonths: 360,
  monthlyPayment: null,
};

describe("AmortizationTable", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders all schedule rows", async () => {
    render(<AmortizationTable {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByText("Year")).toBeInTheDocument();
    });

    // Should have 4 data rows
    const rows = screen.getAllByRole("row");
    // header + 4 data + 1 summary = 6
    expect(rows.length).toBe(6);
  });

  it("highlights the payoff year row", async () => {
    render(<AmortizationTable {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByTestId("payoff-row")).toBeInTheDocument();
    });

    const payoffRow = screen.getByTestId("payoff-row");
    expect(payoffRow).toHaveStyle({ background: "#c8e6c9" });
  });

  it("renders a summary row with totals", async () => {
    render(<AmortizationTable {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByTestId("summary-row")).toBeInTheDocument();
    });

    const summaryRow = screen.getByTestId("summary-row");
    // Total principal: 8000+8500+9000+74500 = 100000
    expect(summaryRow).toHaveTextContent("$100,000");
    // Total interest: 6000+5500+5000+4000 = 20500
    expect(summaryRow).toHaveTextContent("$20,500");
    // Last column is cumulative interest, not principal plus interest.
    expect(summaryRow.lastElementChild).toHaveTextContent("$20,500");
  });

  it("shows extra payment comparison when extra_payment > 0", async () => {
    render(<AmortizationTable {...defaultProps} extraPayment={500} monthlyPayment={599.55} />);

    await waitFor(() => {
      expect(screen.getByTestId("extra-payment-comparison")).toBeInTheDocument();
    });

    const comparison = screen.getByTestId("extra-payment-comparison");
    expect(comparison).toHaveTextContent("Payoff with extra payments: Year 4");
    expect(comparison).toHaveTextContent("saving");
  });

  it("does not show comparison when extra_payment = 0", async () => {
    render(<AmortizationTable {...defaultProps} extraPayment={0} />);

    await waitFor(() => {
      expect(screen.getByText("Year")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("extra-payment-comparison")).not.toBeInTheDocument();
  });

  it("shows loading state", () => {
    render(<AmortizationTable {...defaultProps} />);
    expect(screen.getByText("Loading amortization schedule...")).toBeInTheDocument();
  });
});

it("describes accrued interest and growing principal without calling them cash paid", async () => {
  const { getAmortizationSchedule } = await import("@/api/liabilities");
  vi.mocked(getAmortizationSchedule).mockResolvedValueOnce({
    schedule: [
      {
        year: 1,
        principal_paid: -1395.08,
        interest_paid: 1515.08,
        remaining_balance: 13395.08,
        cumulative_interest: 1515.08,
      },
    ],
  });
  render(
    <AmortizationTable
      {...defaultProps}
      principalBalance={12000}
      interestRate={12}
      monthlyPayment={10}
    />,
  );
  expect(await screen.findByRole("columnheader", { name: "Interest paid" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Principal reduction" })).toBeInTheDocument();
  expect(
    screen.getByText(/Negative principal reduction means unpaid interest/),
  ).toBeInTheDocument();
  expect(screen.queryByRole("columnheader", { name: "Interest Paid" })).not.toBeInTheDocument();
  expect(screen.getAllByRole("row")[1]).toHaveTextContent("$-1,395$1,515$13,395");
});

it("keeps the current liability's schedule when an earlier request answers last", async () => {
  const { getAmortizationSchedule } = await import("@/api/liabilities");
  type Reply = Awaited<ReturnType<typeof getAmortizationSchedule>>;
  const pending: Record<
    string,
    { resolve: (reply: Reply) => void; reject: (error: Error) => void }
  > = {};
  vi.mocked(getAmortizationSchedule).mockImplementation(
    (_planId, liabilityId) =>
      new Promise<Reply>((resolve, reject) => {
        pending[liabilityId] = { resolve, reject };
      }),
  );
  const row = (remaining: number) => ({
    year: 1,
    principal_paid: 1000,
    interest_paid: 500,
    remaining_balance: remaining,
    cumulative_interest: 500,
  });

  const { rerender } = render(<AmortizationTable {...defaultProps} liabilityId="old" />);
  rerender(<AmortizationTable {...defaultProps} liabilityId="current" />);
  await act(async () => pending.current.resolve({ schedule: [row(55555)] }));
  expect(await screen.findByText("$55,555")).toBeInTheDocument();

  await act(async () => pending.old.resolve({ schedule: [row(11111)] }));
  expect(screen.getByText("$55,555")).toBeInTheDocument();
  expect(screen.queryByText("$11,111")).not.toBeInTheDocument();
});

it("ignores a failure from a liability no longer shown", async () => {
  const { getAmortizationSchedule } = await import("@/api/liabilities");
  type Reply = Awaited<ReturnType<typeof getAmortizationSchedule>>;
  const pending: Record<
    string,
    { resolve: (reply: Reply) => void; reject: (error: Error) => void }
  > = {};
  vi.mocked(getAmortizationSchedule).mockImplementation(
    (_planId, liabilityId) =>
      new Promise<Reply>((resolve, reject) => {
        pending[liabilityId] = { resolve, reject };
      }),
  );

  const { rerender } = render(<AmortizationTable {...defaultProps} liabilityId="old" />);
  rerender(<AmortizationTable {...defaultProps} liabilityId="current" />);
  await act(async () => pending.old.reject(new Error("Old schedule failed")));
  expect(screen.getByText("Loading amortization schedule...")).toBeInTheDocument();
  expect(screen.queryByText("Old schedule failed")).not.toBeInTheDocument();
});
