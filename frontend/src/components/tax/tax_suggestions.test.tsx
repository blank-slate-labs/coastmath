import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";

import { TaxSuggestions } from "./tax_suggestions";
import { usePlanStore } from "@/stores/plan_store";
import type { TaxSuggestionsResponse } from "@/types/plan";
import { makePlan } from "@/test_support/plan_builder";

const suggest = vi.fn();
vi.mock("@/api/client", () => ({ suggestTaxStrategies: (...args: unknown[]) => suggest(...args) }));

const plan = makePlan({ id: "p1" });

const response: TaxSuggestionsResponse = {
  suggestions: [
    {
      key: "max_hsa",
      title: "Max HSA",
      lifetime_tax_change: -14235,
      end_net_worth_change: 206808,
      rules: [
        {
          change: "add",
          priority_rank: 2,
          priority_type: "pre_tax_contribution",
          target_account_id: "h",
          source_account_id: null,
          source_income_id: "w",
          conversion_mode: "fixed",
          bracket_ceiling_rate: null,
          backdoor_roth: false,
        },
      ],
    },
    {
      key: "gain_harvest",
      title: "0% gain harvesting",
      lifetime_tax_change: -9000,
      end_net_worth_change: 0,
      rules: [
        {
          change: "add",
          priority_rank: 3,
          priority_type: "gain_harvest",
          target_account_id: null,
          source_account_id: "b",
          source_income_id: null,
          conversion_mode: "fill_bracket",
          bracket_ceiling_rate: 0,
          backdoor_roth: false,
        },
      ],
    },
    {
      key: "mega_backdoor",
      title: "Mega backdoor Roth",
      lifetime_tax_change: -3000,
      end_net_worth_change: 120000,
      rules: [
        {
          change: "add",
          priority_rank: 2,
          priority_type: "after_tax_401k",
          target_account_id: "rk",
          source_account_id: null,
          source_income_id: "w",
          conversion_mode: "fixed",
          bracket_ceiling_rate: null,
          backdoor_roth: false,
        },
      ],
    },
  ],
  pre_tax_discount_rate: 0.24,
};

describe("TaxSuggestions", () => {
  beforeEach(() => {
    suggest.mockReset();
    usePlanStore.setState({ plan, accountsRevision: 0 });
  });

  it("lists each suggestion with its tax and net worth change and a help link", async () => {
    suggest.mockResolvedValue(response);
    render(<TaxSuggestions />);
    expect(suggest).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Find suggestions" }));
    const list = await screen.findByRole("list", { name: "Tax suggestions" });
    expect(suggest).toHaveBeenCalledWith("p1");
    const [hsa, harvest, mega] = within(list).getAllByRole("listitem");
    expect(within(hsa).getByRole("link", { name: "Max HSA" })).toHaveAttribute("href", "/help/hsa");
    expect(within(hsa).getByText("Lifetime taxes").nextElementSibling).toHaveTextContent("-$14k");
    expect(within(hsa).getByText("End net worth, after tax").nextElementSibling).toHaveTextContent(
      "+$207k",
    );
    expect(screen.getByText(/^Nominal dollars\./)).toHaveTextContent(
      "Nominal dollars. Pre-tax balances net of 24% income tax.",
    );
    expect(within(harvest).getByRole("link", { name: "0% gain harvesting" })).toHaveAttribute(
      "href",
      "/help/capital-gains-and-dividends#gain-harvesting",
    );
    expect(within(mega).getByRole("link", { name: "Mega backdoor Roth" })).toHaveAttribute(
      "href",
      "/help/backdoor-roth#mega-backdoor",
    );
    expect(screen.queryByRole("button", { name: /apply/i })).not.toBeInTheDocument();
  });

  it("shows the empty state and recovers from a failed request", async () => {
    suggest.mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce({ suggestions: [] });
    render(<TaxSuggestions />);
    fireEvent.click(screen.getByRole("button", { name: "Find suggestions" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not check suggestions");
    fireEvent.click(screen.getByRole("button", { name: "Find suggestions" }));
    expect(await screen.findByText("No suggestions.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("drops results when the plan changes", async () => {
    let resolve!: (value: TaxSuggestionsResponse) => void;
    suggest.mockReturnValue(
      new Promise<TaxSuggestionsResponse>((done) => {
        resolve = done;
      }),
    );
    render(<TaxSuggestions />);
    fireEvent.click(screen.getByRole("button", { name: "Find suggestions" }));
    expect(screen.getByRole("button", { name: "Simulating…" })).toBeDisabled();
    act(() => usePlanStore.setState({ plan: { ...plan, birth_year: 1980 } }));
    await act(async () => {
      resolve(response);
    });
    expect(screen.queryByRole("list", { name: "Tax suggestions" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find suggestions" })).toBeEnabled();
  });
});
