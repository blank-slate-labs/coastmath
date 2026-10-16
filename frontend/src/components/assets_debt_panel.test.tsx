import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, it, expect } from "vitest";
import AssetsDebtPanel from "./assets_debt_panel";
import { makeAdapter } from "@/test_support/adapter_stub";
import { makePlan } from "@/test_support/plan_builder";
const mocks = vi.hoisted(() => ({ save: vi.fn(), accounts: vi.fn() }));
const adapter = makeAdapter({
  listAccounts: mocks.accounts,
  createRealAsset: mocks.save,
  updateLiability: mocks.save,
});
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
it("opens the property form and retains it after a failed persistence attempt", async () => {
  mocks.accounts.mockResolvedValue([]);
  mocks.save.mockRejectedValue(
    new Error(
      "Create property Car could not be confirmed while offline. Keep your draft, reconnect, and check saved values before retrying.",
    ),
  );
  render(<AssetsDebtPanel plan={makePlan({ id: "p" })} />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Add property or vehicle" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Add property or vehicle" }));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Car" } });
  fireEvent.change(screen.getByLabelText("Current value ($)"), { target: { value: "20000" } });
  fireEvent.submit(screen.getByRole("button", { name: "Add real asset" }).closest("form")!);
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Create property Car could not be confirmed while offline",
    ),
  );
  vi.spyOn(window, "confirm").mockReturnValue(false);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.getByLabelText("Name")).toHaveValue("Car");
  vi.restoreAllMocks();
});

it("retains a rejected loan draft, cancels discard, and closes only on successful retry", async () => {
  mocks.accounts.mockResolvedValue([]);
  mocks.save
    .mockRejectedValueOnce(
      new Error(
        "Save debt “UX Loan” in “Plan A” was not saved. Name: Enter a name containing at least one non-space character. Review the indicated input in the editor and save again.",
      ),
    )
    .mockResolvedValueOnce({});
  const debt = {
    id: "d",
    name: "UX Loan",
    principal_balance: 10000,
    interest_rate: 5.5,
    term_months: 12,
    monthly_payment: 858.37,
    payment_type: "fixed",
  };
  render(<AssetsDebtPanel plan={makePlan({ id: "p", name: "Plan A", liabilities: [debt] })} />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Edit UX Loan / schedule" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Edit UX Loan / schedule" }));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "   " } });
  fireEvent.submit(screen.getByRole("button", { name: "Update loan or debt" }).closest("form")!);
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Save debt “UX Loan” in “Plan A” was not saved. Name:",
    ),
  );
  expect(screen.getByRole("alert")).toHaveFocus();
  expect(screen.getByLabelText("Name")).toHaveValue("   ");
  expect(screen.getByLabelText("Principal balance ($)")).toHaveValue("10,000");
  vi.spyOn(window, "confirm").mockReturnValue(false);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.getByLabelText("Name")).toHaveValue("   ");
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "UX Loan corrected" } });
  fireEvent.submit(screen.getByRole("button", { name: "Update loan or debt" }).closest("form")!);
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(mocks.save).toHaveBeenLastCalledWith(
    "p",
    "d",
    expect.objectContaining({ name: "UX Loan corrected", principal_balance: 10000 }),
  );
  vi.restoreAllMocks();
});
