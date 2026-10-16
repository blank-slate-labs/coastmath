import { fireEvent, render, screen } from "@testing-library/react";
import { it, expect, vi } from "vitest";
import { HealthcarePanel } from "./healthcare_panel";
import type { HealthcareYear, YearSnapshot } from "@/types/plan";

function year(y: number, age: number, hc: Partial<HealthcareYear>): YearSnapshot {
  return {
    year: y,
    age,
    healthcare: {
      aca_covered_adults: 0,
      aca_household_size: 0,
      aca_magi: 0,
      aca_fpl_ratio: 0,
      aca_applicable_percentage: 0,
      aca_benchmark_premium: 0,
      aca_gross_premium: 0,
      aca_credit: 0,
      aca_net_premium: 0,
      aca_eligible: false,
      aca_reason: null,
      aca_magi_estimate: 0,
      aca_credit_advanced: 0,
      aca_reconciliation: 0,
      medicare_persons: 0,
      medicare_magi_used: 0,
      medicare_lookback_year: null,
      medicare_lookback_source: "none",
      medicare_tier: 0,
      medicare_part_b: 0,
      medicare_irmaa_part_b: 0,
      medicare_irmaa_part_d: 0,
      medicare_part_d_plan: 0,
      medicare_supplement: 0,
      total: 0,
      ...hc,
    },
  } as unknown as YearSnapshot;
}

it("summarises credits, cliff years and IRMAA from engine data", () => {
  const snapshots = [
    year(2030, 60, {
      aca_covered_adults: 2,
      aca_fpl_ratio: 2.8,
      aca_gross_premium: 22000,
      aca_credit: 15000,
      aca_net_premium: 7000,
      aca_eligible: true,
      total: 7000,
    }),
    year(2031, 61, {
      aca_covered_adults: 2,
      aca_fpl_ratio: 4.5,
      aca_gross_premium: 23000,
      aca_credit: 0,
      aca_net_premium: 23000,
      aca_eligible: false,
      aca_reason: "income above 400% of the poverty line",
      total: 23000,
    }),
    year(2036, 66, {
      medicare_persons: 1,
      medicare_part_b: 2434.8,
      medicare_irmaa_part_b: 974.4,
      medicare_irmaa_part_d: 174,
      medicare_tier: 1,
      total: 3583.2,
    }),
  ];
  render(<HealthcarePanel snapshots={snapshots} configured />);
  expect(screen.getByText("Premium tax credits").nextElementSibling).toHaveTextContent("$15k");
  expect(screen.getByText("Years with IRMAA surcharges").nextElementSibling).toHaveTextContent("1");
  expect(screen.getByRole("note")).toHaveTextContent(
    "No premium tax credit in 1 marketplace year (income above 400% of the poverty line)",
  );
  const table = screen.getByRole("table", { name: "Health coverage by year" });
  expect(table).toHaveTextContent("280%");
  expect(table).toHaveTextContent("$1k (tier 1)");
});

it("links to the editor when coverage is not configured", () => {
  const onEdit = vi.fn();
  render(<HealthcarePanel snapshots={[]} configured={false} onEdit={onEdit} />);
  expect(screen.getByText(/Health coverage is off/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Edit health coverage" }));
  expect(onEdit).toHaveBeenCalled();
});
