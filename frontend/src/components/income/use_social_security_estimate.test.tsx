import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { estimateSocialSecurity } from "@/api/client";
import { deferred } from "@/test_support/deferred";
import { makeIncome } from "@/test_support/record_builders";
import {
  earningsFor,
  useBenefitPreview,
  useSocialSecurityEstimate,
} from "./use_social_security_estimate";

vi.mock("@/api/client", () => ({ estimateSocialSecurity: vi.fn() }));

type EstimateResult = Awaited<ReturnType<typeof estimateSocialSecurity>>;
const result = (benefit: number) =>
  ({
    estimated_annual_benefit: benefit,
    claiming_age: 67,
    claiming_factor: 1,
    full_retirement_age: 67,
  }) as EstimateResult;

const incomes = [
  makeIncome({ id: "a", owner: "self", annual_amount: 60000, is_earned_income: true }),
  makeIncome({ id: "b", owner: "spouse", annual_amount: 40000, is_earned_income: true }),
  makeIncome({ id: "c", owner: "self", annual_amount: 9000 }),
];

beforeEach(() => {
  vi.mocked(estimateSocialSecurity).mockReset();
});

describe("earningsFor", () => {
  it("sums the owner's earned income", () => {
    expect(earningsFor(incomes, "self")).toBe(60000);
    expect(earningsFor(incomes, "spouse")).toBe(40000);
  });
});

describe("useSocialSecurityEstimate", () => {
  function setup(onEstimate = vi.fn()) {
    const hook = renderHook(() =>
      useSocialSecurityEstimate({
        incomes,
        initialOwner: "self",
        birthYear: 1966,
        spouseBirthYear: 1968,
        claimingAge: 67,
        claimBirthYear: 1966,
        onEstimate,
      }),
    );
    return { ...hook, onEstimate };
  }

  it("lets only the latest automatic estimate write the amount", async () => {
    const first = deferred<EstimateResult>();
    const second = deferred<EstimateResult>();
    vi.mocked(estimateSocialSecurity)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const { result: hook, onEstimate } = setup();
    expect(hook.current.income).toBe("60000");

    act(() => hook.current.autoEstimate({ owner: "self", age: 67 }));
    act(() => hook.current.autoEstimate({ owner: "spouse", age: 70 }));
    expect(estimateSocialSecurity).toHaveBeenLastCalledWith(40000, 70, 1968, undefined);
    expect(hook.current.income).toBe("40000");

    await act(async () => second.resolve(result(30000)));
    await act(async () => first.resolve(result(20000)));
    expect(onEstimate).toHaveBeenCalledTimes(1);
    expect(onEstimate).toHaveBeenCalledWith(30000);
    expect(hook.current.autoEstimated).toBe(true);
    expect(hook.current.estimating).toBe(false);
  });

  it("drops an estimate in flight once the amount is typed", async () => {
    const pending = deferred<EstimateResult>();
    vi.mocked(estimateSocialSecurity).mockReturnValueOnce(pending.promise);
    const { result: hook, onEstimate } = setup();
    act(() => hook.current.estimate());
    expect(hook.current.estimating).toBe(true);
    act(() => hook.current.cancel());
    expect(hook.current.estimating).toBe(false);
    await act(async () => pending.resolve(result(25000)));
    expect(onEstimate).not.toHaveBeenCalled();
    expect(hook.current.autoEstimated).toBe(false);
  });

  it("rejects a manual PIA estimate without a positive PIA", () => {
    const { result: hook } = setup();
    act(() => hook.current.setMode("pia"));
    act(() => hook.current.estimate());
    expect(hook.current.error).toBe("Enter a positive monthly PIA");
    expect(estimateSocialSecurity).not.toHaveBeenCalled();
  });
});

describe("useBenefitPreview", () => {
  it("sizes the preview only when enabled with a valid PIA and claiming age", async () => {
    vi.mocked(estimateSocialSecurity).mockResolvedValue(result(24000));
    const { result: hook, rerender } = renderHook((props) => useBenefitPreview(props), {
      initialProps: {
        enabled: false,
        pia: "2000",
        expectedPercent: "100",
        claimingAge: 67 as number | null,
        claimBirthYear: 1966 as number | null,
      },
    });
    expect(estimateSocialSecurity).not.toHaveBeenCalled();
    rerender({
      enabled: true,
      pia: "2000",
      expectedPercent: "100",
      claimingAge: 67,
      claimBirthYear: 1966,
    });
    await waitFor(() => expect(hook.current).toBe(24000));
    expect(estimateSocialSecurity).toHaveBeenCalledWith(null, 67, 1966, {
      monthlyPia: 2000,
      expectedBenefitPercentage: 100,
    });
    rerender({
      enabled: true,
      pia: "2000",
      expectedPercent: "100",
      claimingAge: null,
      claimBirthYear: 1966,
    });
    expect(hook.current).toBeNull();
  });
});
