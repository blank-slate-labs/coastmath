import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { roomKindsFor } from "@/domain/intl_plan";
import type { TaxRegimeAccountKind, TaxRegimeCountry } from "@/types/plan";
import IntlRoomEditor from "./intl_room_editor";

const FREE_SAVER: TaxRegimeAccountKind = {
  id: "QZ:free_saver",
  label: "Free saver",
  category: "tax_free",
  carries_room: true,
};
const PENSION_SAVER: TaxRegimeAccountKind = {
  id: "QZ:pension_saver",
  label: "Pension saver",
  category: "tax_deferred",
  carries_room: true,
  uses_prior_year_income: true,
};
const GENERAL: TaxRegimeAccountKind = {
  id: "QZ:general",
  label: "General account",
  category: "tax_deferred",
};

describe("contribution room editor", () => {
  it("lists only kinds whose room carries forward", () => {
    const countries: TaxRegimeCountry[] = [
      {
        code: "QZ",
        name: "Fixture country",
        currency: "EUR",
        filing_unit: "individual",
        regions: [],
        account_kinds: [PENSION_SAVER, GENERAL, FREE_SAVER],
        benefit_rules: [],
        spec_years: [2026],
        approximations: [],
      },
    ];
    expect(roomKindsFor(countries, ["QZ"]).map((k) => k.id)).toEqual([
      "QZ:pension_saver",
      "QZ:free_saver",
    ]);
    expect(roomKindsFor(countries, ["QX"])).toEqual([]);
  });

  it("validates amounts, then saves room and prior-year income for both partners", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <IntlRoomEditor
        kinds={[PENSION_SAVER, FREE_SAVER]}
        startingRoom={[]}
        priorIncome={null}
        hasPartner
        onSave={onSave}
      />,
    );
    fireEvent.change(screen.getByLabelText(/^Free saver room, primary person/), {
      target: { value: "-5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save contribution room" }));
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText("Enter an amount of 0 or more.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/^Free saver room, primary person/), {
      target: { value: "25000" },
    });
    fireEvent.change(screen.getByLabelText("Pension saver room, partner"), {
      target: { value: "40000" },
    });
    fireEvent.change(screen.getByLabelText(/Prior-year earned income, primary person/), {
      target: { value: "90000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save contribution room" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({
        starting_room: [
          { kind: "QZ:free_saver", owner: "self", amount: 25_000 },
          { kind: "QZ:pension_saver", owner: "spouse", amount: 40_000 },
        ],
        prior_year_earned_income: { self: 90_000 },
      }),
    );
    expect(screen.getByText("Contribution room saved.")).toBeInTheDocument();
  });

  it("hides prior-year income without a kind that uses it and clears blank entries", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <IntlRoomEditor
        kinds={[FREE_SAVER]}
        startingRoom={[{ kind: "QZ:free_saver", owner: "self", amount: 1000 }]}
        priorIncome={null}
        hasPartner={false}
        onSave={onSave}
      />,
    );
    expect(screen.queryByLabelText(/Prior-year earned income/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Free saver room")).toHaveValue("1,000");
    fireEvent.change(screen.getByLabelText("Free saver room"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save contribution room" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({ starting_room: [], prior_year_earned_income: null }),
    );
  });

  it("shows the server's rejection and keeps the draft", async () => {
    const onSave = vi
      .fn()
      .mockRejectedValue(new Error("Plan was not saved. Intl settings: amount is too large."));
    render(
      <IntlRoomEditor
        kinds={[FREE_SAVER]}
        startingRoom={[]}
        priorIncome={null}
        hasPartner={false}
        onSave={onSave}
      />,
    );
    fireEvent.change(screen.getByLabelText("Free saver room"), { target: { value: "12345" } });
    fireEvent.click(screen.getByRole("button", { name: "Save contribution room" }));
    await waitFor(() => expect(screen.getByText(/amount is too large/)).toBeInTheDocument());
    expect(screen.getByLabelText("Free saver room")).toHaveValue("12,345");
    expect(screen.getByText("Unsaved contribution room changes.")).toBeInTheDocument();
  });
});
