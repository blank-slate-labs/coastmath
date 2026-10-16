import { useState, useEffect, useMemo } from "react";

import { getAmortizationSchedule } from "@/api/liabilities";
import type { AmortizationRow } from "@/api/liabilities";
import { deflate } from "@/utils/currency";
import { withCurrency } from "@/utils/format";
import { usePlanStore } from "@/stores/plan_store";

interface AmortizationTableProps {
  planId: string;
  liabilityId: string;
  inflationRate: number;
  /** Current extra_payment value from the liability */
  extraPayment: number;
  /** Principal balance for original-term calculation */
  principalBalance: number;
  /** Annual interest rate as percentage (e.g. 6 for 6%) */
  interestRate: number;
  /** Original term in months */
  termMonths: number | null;
  /** Monthly payment amount */
  monthlyPayment: number | null;
}

function formatCurrency(value: number): string {
  return withCurrency(Math.round(value).toLocaleString());
}

/**
 * Compute the original payoff year (without extra payments) using the standard
 * mortgage formula. Returns null if inputs are insufficient.
 */
function computeOriginalPayoffYear(
  principal: number,
  annualRatePercent: number,
  termMonths: number | null,
  monthlyPayment: number | null,
): { payoffYear: number; totalInterest: number } | null {
  if (principal <= 0) return null;

  let monthlyPmt: number;
  const monthlyRate = annualRatePercent / 100 / 12;

  if (monthlyPayment != null && monthlyPayment > 0) {
    monthlyPmt = monthlyPayment;
  } else if (termMonths != null && termMonths > 0) {
    if (monthlyRate === 0) {
      monthlyPmt = principal / termMonths;
    } else {
      const factor = Math.pow(1 + monthlyRate, termMonths);
      monthlyPmt = (principal * monthlyRate * factor) / (factor - 1);
    }
  } else {
    return null;
  }

  let balance = principal;
  let totalInterest = 0;
  let months = 0;

  while (balance > 0.01 && months < 600) {
    const interest = balance * monthlyRate;
    const principalPortion = Math.min(monthlyPmt - interest, balance);
    if (principalPortion <= 0) return null; // payment doesn't cover interest
    balance -= principalPortion;
    if (balance < 0) balance = 0;
    totalInterest += interest;
    months++;
  }

  return { payoffYear: Math.ceil(months / 12), totalInterest };
}

export default function AmortizationTable({
  planId,
  liabilityId,
  inflationRate,
  extraPayment,
  principalBalance,
  interestRate,
  termMonths,
  monthlyPayment,
}: AmortizationTableProps) {
  const [schedule, setSchedule] = useState<AmortizationRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const currencyMode = usePlanStore((s) => s.currencyMode);

  useEffect(() => {
    // A response for a liability or plan no longer shown must not replace the current one.
    let active = true;
    setLoading(true);
    setError(null);
    getAmortizationSchedule(planId, liabilityId)
      .then((res) => {
        if (!active) return;
        setSchedule(res.schedule);
        setLoading(false);
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load schedule");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [planId, liabilityId]);

  const adjustedSchedule = useMemo(() => {
    if (currencyMode === "nominal") return schedule;
    return schedule.map((row) => ({
      ...row,
      principal_paid: deflate(row.principal_paid, inflationRate, row.year),
      interest_paid: deflate(row.interest_paid, inflationRate, row.year),
      remaining_balance: deflate(row.remaining_balance, inflationRate, row.year),
      cumulative_interest: deflate(row.cumulative_interest, inflationRate, row.year),
    }));
  }, [schedule, currencyMode, inflationRate]);

  const totals = useMemo(() => {
    let totalPrincipal = 0;
    let totalInterest = 0;
    for (const row of adjustedSchedule) {
      totalPrincipal += row.principal_paid;
      totalInterest += row.interest_paid;
    }
    return {
      totalPrincipal,
      totalInterest,
      totalCost: totalPrincipal + totalInterest,
    };
  }, [adjustedSchedule]);

  const extraPaymentComparison = useMemo(() => {
    if (
      extraPayment <= 0 ||
      schedule.length === 0 ||
      schedule[schedule.length - 1].remaining_balance > 0.01
    )
      return null;

    const acceleratedPayoffYear = schedule[schedule.length - 1].year;
    const acceleratedTotalInterest = schedule[schedule.length - 1].cumulative_interest;

    const original = computeOriginalPayoffYear(
      principalBalance,
      interestRate,
      termMonths,
      monthlyPayment,
    );
    if (!original) return null;

    const interestSaved = original.totalInterest - acceleratedTotalInterest;
    if (interestSaved <= 0) return null;

    return {
      originalPayoffYear: original.payoffYear,
      acceleratedPayoffYear,
      interestSaved,
    };
  }, [schedule, extraPayment, principalBalance, interestRate, termMonths, monthlyPayment]);

  if (loading) return <div>Loading amortization schedule...</div>;
  if (error) return <div style={{ color: "red" }}>{error}</div>;
  if (schedule.length === 0) return <div>No amortization data available.</div>;

  return (
    <div style={{ marginTop: 12, overflowX: "auto" }}>
      <p style={{ fontSize: 12 }}>
        Negative principal reduction means unpaid interest was added to the balance.
      </p>
      {schedule.length > 0 && schedule[schedule.length - 1].remaining_balance > 0.01 && (
        <p role="status">Debt remains outstanding at the end of this 50-year schedule.</p>
      )}
      {extraPaymentComparison && (
        <div
          data-testid="extra-payment-comparison"
          style={{
            padding: 8,
            marginBottom: 8,
            background: "#e8f5e9",
            borderRadius: 4,
            fontSize: 14,
          }}
        >
          Payoff with extra payments: Year {extraPaymentComparison.acceleratedPayoffYear} (original:
          ~Year {extraPaymentComparison.originalPayoffYear}, saving ~
          {formatCurrency(extraPaymentComparison.interestSaved)} in interest)
        </div>
      )}

      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: 14,
        }}
      >
        <thead>
          <tr style={{ borderBottom: "2px solid #333" }}>
            <th style={{ textAlign: "right", padding: 4 }}>Year</th>
            <th style={{ textAlign: "right", padding: 4 }}>Principal reduction</th>
            <th style={{ textAlign: "right", padding: 4 }}>Interest paid</th>
            <th style={{ textAlign: "right", padding: 4 }}>Remaining balance</th>
            <th style={{ textAlign: "right", padding: 4 }}>Cumulative interest</th>
          </tr>
        </thead>
        <tbody>
          {adjustedSchedule.map((row) => {
            const isPayoff = row.remaining_balance === 0;
            return (
              <tr
                key={row.year}
                data-testid={isPayoff ? "payoff-row" : undefined}
                style={{
                  borderBottom: "1px solid #ddd",
                  background: isPayoff ? "#c8e6c9" : undefined,
                }}
              >
                <td style={{ textAlign: "right", padding: 4 }}>{row.year}</td>
                <td style={{ textAlign: "right", padding: 4 }}>
                  {formatCurrency(row.principal_paid)}
                </td>
                <td style={{ textAlign: "right", padding: 4 }}>
                  {formatCurrency(row.interest_paid)}
                </td>
                <td style={{ textAlign: "right", padding: 4 }}>
                  {formatCurrency(row.remaining_balance)}
                </td>
                <td style={{ textAlign: "right", padding: 4 }}>
                  {formatCurrency(row.cumulative_interest)}
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr data-testid="summary-row" style={{ borderTop: "2px solid #333", fontWeight: "bold" }}>
            <td style={{ textAlign: "right", padding: 4 }}>Total</td>
            <td style={{ textAlign: "right", padding: 4 }}>
              {formatCurrency(totals.totalPrincipal)}
            </td>
            <td style={{ textAlign: "right", padding: 4 }}>
              {formatCurrency(totals.totalInterest)}
            </td>
            <td style={{ textAlign: "right", padding: 4 }} />
            <td style={{ textAlign: "right", padding: 4 }}>
              {formatCurrency(totals.totalInterest)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
