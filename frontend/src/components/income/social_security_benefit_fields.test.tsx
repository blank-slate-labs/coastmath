import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SocialSecurityBenefitFields } from "./social_security_benefit_fields";
import type { SocialSecurityEstimate } from "./use_social_security_estimate";
import { exSpouseDraft } from "@/components/ex_spouse_fields";

function estimateStub(overrides: Partial<SocialSecurityEstimate> = {}): SocialSecurityEstimate {
  return {
    mode: "income",
    setMode: vi.fn(),
    income: "80000",
    setIncome: vi.fn(),
    monthlyPia: "",
    setMonthlyPia: vi.fn(),
    expectedPercent: "100",
    setExpectedPercent: vi.fn(),
    estimating: false,
    error: null,
    autoEstimated: false,
    estimate: vi.fn(),
    autoEstimate: vi.fn(),
    cancel: vi.fn(),
    ...overrides,
  };
}

function renderFields(
  overrides: Partial<React.ComponentProps<typeof SocialSecurityBenefitFields>> = {},
) {
  const props: React.ComponentProps<typeof SocialSecurityBenefitFields> = {
    basis: "amount",
    onBasisChange: vi.fn(),
    piaReflects: "continued_work",
    onPiaReflectsChange: vi.fn(),
    coveredYears: 35,
    onCoveredYearsChange: vi.fn(),
    pia: "",
    onPiaChange: vi.fn(),
    expectedPercent: "100",
    onExpectedPercentChange: vi.fn(),
    preview: null,
    exSpouse: exSpouseDraft(null),
    onExSpouseChange: vi.fn(),
    claimingAge: 67,
    onClaimingAgeChange: vi.fn(),
    claimYear: 2033,
    startMilestoneId: "",
    startYear: null,
    estimate: estimateStub(),
    ...overrides,
  };
  render(<SocialSecurityBenefitFields {...props} />);
  return props;
}

describe("SocialSecurityBenefitFields", () => {
  it("shows the amount estimate on the benefit-amount basis", () => {
    const props = renderFields();
    expect(screen.getByRole("radio", { name: "Benefit amount" })).toBeChecked();
    expect(screen.queryByLabelText(/PIA per month at full retirement age/)).toBeNull();
    expect(screen.getByLabelText("Current annual income (for estimate)")).toHaveValue("80,000");
    expect(screen.getByText(/Benefits begin the year you turn 67 \(2033\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Estimate from income" }));
    expect(props.estimate.estimate).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("radio", { name: "PIA" }));
    expect(props.onBasisChange).toHaveBeenCalledWith("pia");
  });

  it("disables the estimate while one runs and shows its error", () => {
    renderFields({ estimate: estimateStub({ estimating: true, error: "Estimate failed" }) });
    expect(screen.getByRole("button", { name: "Estimating…" })).toBeDisabled();
    expect(screen.getByText("Estimate failed")).toBeInTheDocument();
  });

  it("shows the PIA inputs and the first-year preview on the PIA basis", () => {
    const props = renderFields({ basis: "pia", pia: "2000", preview: 24000 });
    expect(screen.queryByRole("button", { name: "Estimate from income" })).toBeNull();
    expect(
      screen.getByText(/First-year benefit at claiming age 67: \$24,000 a year/),
    ).toBeVisible();
    fireEvent.change(screen.getByLabelText("Expected benefit paid (%)"), {
      target: { value: "80" },
    });
    expect(props.onExpectedPercentChange).toHaveBeenCalledWith("80");
    fireEvent.change(screen.getByLabelText("My PIA reflects…"), {
      target: { value: "current_record" },
    });
    expect(props.onPiaReflectsChange).toHaveBeenCalledWith("current_record");
  });

  it("reports a cleared claiming age as null", () => {
    const props = renderFields();
    fireEvent.change(screen.getByLabelText(/Claiming age/), { target: { value: "" } });
    expect(props.onClaimingAgeChange).toHaveBeenCalledWith(null);
    fireEvent.change(screen.getByLabelText(/Claiming age/), { target: { value: "70" } });
    expect(props.onClaimingAgeChange).toHaveBeenLastCalledWith(70);
  });
});
