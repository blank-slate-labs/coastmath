import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { IncomeGrowthTaxFields } from "./income_growth_tax_fields";

function renderFields(overrides: Partial<React.ComponentProps<typeof IncomeGrowthTaxFields>> = {}) {
  const props: React.ComponentProps<typeof IncomeGrowthTaxFields> = {
    forceOpen: false,
    isActive: true,
    onActiveChange: vi.fn(),
    growthRate: "",
    onGrowthRateChange: vi.fn(),
    growthCap: "",
    onGrowthCapChange: vi.fn(),
    growthCapInflationLinked: false,
    onGrowthCapInflationLinkedChange: vi.fn(),
    segmentRows: [],
    onSegmentRowsChange: vi.fn(),
    scheduleAllowed: false,
    isSocialSecurity: false,
    isOther: false,
    isEarnedIncome: true,
    onEarnedIncomeChange: vi.fn(),
    earned: true,
    isSelfEmployed: false,
    onSelfEmployedChange: vi.fn(),
    withholdingPercent: "",
    onWithholdingPercentChange: vi.fn(),
    ...overrides,
  };
  const utils = render(<IncomeGrowthTaxFields {...props} />);
  return { ...utils, props };
}

describe("IncomeGrowthTaxFields", () => {
  it("stays collapsed until an error or an excluded income opens it", () => {
    const { container, rerender, props } = renderFields();
    const details = () => container.querySelector("details") as HTMLDetailsElement;
    expect(details().open).toBe(false);
    rerender(<IncomeGrowthTaxFields {...props} forceOpen />);
    expect(details().open).toBe(true);
  });

  it("reports changes to the growth and tax inputs", () => {
    const { props } = renderFields();
    fireEvent.change(screen.getByLabelText("Growth rate (% per year)"), {
      target: { value: "3" },
    });
    expect(props.onGrowthRateChange).toHaveBeenCalledWith("3");
    fireEvent.click(screen.getByLabelText(/Self-employed/));
    expect(props.onSelfEmployedChange).toHaveBeenCalledWith(true);
    fireEvent.click(screen.getByLabelText("Include in projection"));
    expect(props.onActiveChange).toHaveBeenCalledWith(false);
    fireEvent.change(screen.getByLabelText(/Tax withholding/), { target: { value: "10" } });
    expect(props.onWithholdingPercentChange).toHaveBeenCalledWith("10");
  });

  it("offers the earned checkbox only for Other income and the inflation cap only with a cap", () => {
    renderFields({ isOther: true, earned: false, isEarnedIncome: false, growthCap: "500" });
    expect(screen.getByLabelText(/Earned income \(wages or self-employment/)).not.toBeChecked();
    expect(screen.queryByLabelText(/Self-employed/)).toBeNull();
    expect(screen.getByLabelText(/Cap rises with inflation/)).toBeInTheDocument();
    expect(screen.getByText(/A blank rate keeps a fixed nominal amount/)).toBeInTheDocument();
  });

  it("states the blank-rate rule for Social Security", () => {
    renderFields({ isSocialSecurity: true, earned: false, isEarnedIncome: false });
    expect(
      screen.getByText(
        /A blank rate follows the Social Security COLA assumption\. Use 0 for a fixed nominal amount\./,
      ),
    ).toBeInTheDocument();
  });
});
