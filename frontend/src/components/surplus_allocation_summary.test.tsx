import { fireEvent, render, screen } from "@testing-library/react";
import { vi, expect, it } from "vitest";
import SurplusAllocationSummary from "./surplus_allocation_summary";
import type { YearSnapshot } from "@/types/plan";

it("shows named surplus destinations, limiting caps and a working edit action", () => {
  const edit = vi.fn();
  const snapshot = {
    year: 2026,
    net_cash_flow: 10000,
    cash_flow: {
      contributions: [
        {
          account_id: "a",
          account_name: "Vanguard",
          amount: 7500,
          source: "priority",
          priority_rank: 1,
          limited_by: ["annual maximum"],
        },
        { account_id: "b", account_name: "Chase", amount: 2500, source: "default_sink" },
        { account_id: "c", account_name: "Work plan", amount: 24500, source: "payroll" },
      ],
    },
  } as unknown as YearSnapshot;
  render(<SurplusAllocationSummary snapshot={snapshot} onEdit={edit} />);
  expect(screen.getByText("Vanguard")).toBeVisible();
  expect(screen.getByText("Chase")).toBeVisible();
  expect(screen.getByText(/Limited by annual maximum/)).toBeVisible();
  expect(screen.queryByText("Work plan")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Edit income allocation" }));
  expect(edit).toHaveBeenCalledOnce();
});

it("explains deficit years without suggesting money was allocated", () => {
  render(
    <SurplusAllocationSummary
      snapshot={{ year: 2026, net_cash_flow: -100 } as YearSnapshot}
      onEdit={() => {}}
    />,
  );
  expect(screen.getByText(/No surplus in 2026/)).toBeVisible();
});

it("uses engine reasons for zero funding and navigates to that rule without guessing", () => {
  const edit = vi.fn();
  render(
    <SurplusAllocationSummary
      snapshot={
        {
          year: 2026,
          cash_flow: {
            contributions: [
              {
                account_name: "IRA",
                source: "priority",
                priority_rank: 3,
                amount: 0,
                funding_reasons: ["income_eligibility"],
              },
              {
                account_name: "Brokerage",
                source: "priority",
                priority_rank: 4,
                amount: 0,
                funding_reasons: ["earlier_rules"],
              },
              { account_name: "Old result", source: "priority", priority_rank: 5, amount: 0 },
            ],
          },
        } as unknown as YearSnapshot
      }
      onEdit={edit}
    />,
  );
  expect(screen.getByText(/Modeled income is above/)).toBeVisible();
  expect(screen.getByText(/Earlier allocation rules used/)).toBeVisible();
  expect(screen.getByText(/No funding explanation is available/)).toBeVisible();
  // Shown numbers follow the order the rules ran; navigation still uses the saved rank.
  fireEvent.click(screen.getByRole("button", { name: "Review rule 1" }));
  expect(edit).toHaveBeenCalledWith(3);
});

it("says once that earlier rules used the surplus", () => {
  render(
    <SurplusAllocationSummary
      snapshot={
        {
          year: 2026,
          net_cash_flow: 500,
          cash_flow: {
            contributions: [
              { account_name: "Roth IRA", source: "priority", priority_rank: 1, amount: 500 },
              {
                account_name: "Brokerage",
                source: "priority",
                priority_rank: 2,
                amount: 0,
                funding_reasons: ["earlier_rules"],
              },
              {
                account_name: "HSA",
                source: "priority",
                priority_rank: 3,
                amount: 0,
                funding_reasons: ["earlier_rules"],
              },
            ],
          },
        } as unknown as YearSnapshot
      }
      onEdit={() => {}}
    />,
  );
  expect(screen.getAllByText(/Earlier allocation rules used/)).toHaveLength(1);
});

it("explains a partly funded withdraw-if-short rule", () => {
  render(
    <SurplusAllocationSummary
      snapshot={
        {
          year: 2026,
          net_cash_flow: 500,
          cash_flow: {
            contributions: [
              {
                account_name: "Brokerage",
                source: "priority",
                priority_rank: 2,
                amount: 1500,
                funding_reasons: ["withdrawal_shortfall"],
                limited_by: ["available withdrawals"],
              },
            ],
          },
        } as unknown as YearSnapshot
      }
      onEdit={() => {}}
    />,
  );
  expect(screen.getByText(/could not be fully funded/)).toBeVisible();
  expect(screen.getByText(/Limited by available withdrawals/)).toBeVisible();
});
