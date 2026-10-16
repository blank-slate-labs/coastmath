import { useEffect, useRef, useState } from "react";
import type { Income } from "@/types/plan";
import { estimateSocialSecurity } from "@/api/client";

type Owner = "self" | "spouse";

/** Annual earned income per owner, the Social Security estimate's default input. */
export function earningsFor(incomes: Income[], owner: Owner): number {
  return incomes
    .filter((i) => i.owner === owner && i.is_earned_income && !i.is_social_security)
    .reduce((sum, i) => sum + Number(i.annual_amount), 0);
}

interface EstimateOptions {
  /** The plan's incomes; their earnings seed the estimate. */
  incomes: Income[];
  /** Recipient the form opened with, for the first estimate input. */
  initialOwner: Owner;
  birthYear: number | null;
  spouseBirthYear: number | null;
  claimingAge: number | null;
  /** Birth year of the current recipient. */
  claimBirthYear: number | null;
  /** Receives the estimated annual benefit. */
  onEstimate: (annualBenefit: number) => void;
}

/**
 * The benefit-amount estimate: its inputs, the request in flight and the
 * automatic estimate that follows the recipient and claiming age.
 */
export function useSocialSecurityEstimate({
  incomes,
  initialOwner,
  birthYear,
  spouseBirthYear,
  claimingAge,
  claimBirthYear,
  onEstimate,
}: EstimateOptions) {
  const [income, setIncome] = useState(() => {
    const earnings = earningsFor(incomes, initialOwner);
    return earnings > 0 ? String(earnings) : "";
  });
  // True while the amount holds an automatic estimate, so it follows claiming age and recipient.
  const [autoEstimated, setAutoEstimated] = useState(false);
  // Only the latest estimate request may write the amount.
  const seqRef = useRef(0);
  const [mode, setMode] = useState<"income" | "pia">("income");
  const [monthlyPia, setMonthlyPia] = useState("");
  const [expectedPercent, setExpectedPercent] = useState("100");
  const [estimating, setEstimating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(overrides?: { income: number; age: number | null; birth: number | null }) {
    const input = overrides ? overrides.income : Number(mode === "pia" ? monthlyPia : income);
    const runMode = overrides ? "income" : mode;
    if (!Number.isFinite(input) || input <= 0) {
      setError(
        runMode === "pia" ? "Enter a positive monthly PIA" : "Enter a positive annual income",
      );
      return;
    }
    const expected = Number(expectedPercent);
    if (runMode === "pia" && (!Number.isFinite(expected) || expected < 0 || expected > 100)) {
      setError("Expected benefit must be a percentage between 0 and 100");
      return;
    }
    const seq = ++seqRef.current;
    setEstimating(true);
    setError(null);
    try {
      const result = await estimateSocialSecurity(
        runMode === "pia" ? null : input,
        (overrides ? overrides.age : claimingAge) ?? 67,
        overrides ? overrides.birth : claimBirthYear,
        runMode === "pia" ? { monthlyPia: input, expectedBenefitPercentage: expected } : undefined,
      );
      if (seq !== seqRef.current) return;
      onEstimate(result.estimated_annual_benefit);
      setAutoEstimated(!!overrides);
    } catch (err) {
      if (seq === seqRef.current) setError(err instanceof Error ? err.message : "Estimate failed");
    } finally {
      if (seq === seqRef.current) setEstimating(false);
    }
  }

  /** Estimates from the recipient's earnings; does nothing when they have none. */
  function autoEstimate(next: { owner: Owner; age: number | null }) {
    const earnings = earningsFor(incomes, next.owner);
    if (earnings <= 0) return;
    setIncome(String(earnings));
    void run({
      income: earnings,
      age: next.age,
      birth: next.owner === "spouse" ? spouseBirthYear : birthYear,
    });
  }

  /** A typed amount wins over any estimate still in flight. */
  function cancel() {
    seqRef.current += 1;
    setEstimating(false);
    setAutoEstimated(false);
  }

  return {
    mode,
    setMode,
    income,
    setIncome,
    monthlyPia,
    setMonthlyPia,
    expectedPercent,
    setExpectedPercent,
    estimating,
    error,
    autoEstimated,
    estimate: () => void run(),
    autoEstimate,
    cancel,
  };
}

export type SocialSecurityEstimate = ReturnType<typeof useSocialSecurityEstimate>;

/**
 * First-year benefit for a PIA-based income, shown as a preview and saved as
 * its amount. Only the latest request may write it.
 */
export function useBenefitPreview({
  enabled,
  pia,
  expectedPercent,
  claimingAge,
  claimBirthYear,
}: {
  enabled: boolean;
  pia: string;
  expectedPercent: string;
  claimingAge: number | null;
  claimBirthYear: number | null;
}): number | null {
  const [preview, setPreview] = useState<number | null>(null);
  const seqRef = useRef(0);

  useEffect(() => {
    const seq = ++seqRef.current;
    setPreview(null);
    const monthlyPia = Number(pia);
    const expected = Number(expectedPercent);
    if (
      !enabled ||
      claimingAge == null ||
      !(monthlyPia > 0) ||
      !Number.isFinite(expected) ||
      expected < 0 ||
      expected > 100
    )
      return;
    Promise.resolve(
      estimateSocialSecurity(null, claimingAge, claimBirthYear, {
        monthlyPia,
        expectedBenefitPercentage: expected,
      }),
    )
      .then((result) => {
        if (seq === seqRef.current && result) setPreview(result.estimated_annual_benefit);
      })
      .catch(() => {
        /* The preview is optional; the projection still sizes the benefit. */
      });
  }, [enabled, pia, expectedPercent, claimingAge, claimBirthYear]);

  return preview;
}
