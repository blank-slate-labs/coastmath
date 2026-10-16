import { fireEvent, render, screen } from "@testing-library/react";
import LedgerAccounts from "./ledger_accounts";
import { account } from "./ledger_test_data";

it("lists accounts and toggles spending", () => {
  const onToggle = vi.fn();
  render(
    <LedgerAccounts
      busy={false}
      onToggle={onToggle}
      onRemove={vi.fn()}
      accounts={[
        account(),
        account({
          id: "a2",
          mask: null,
          subtype: null,
          account_type: "DEPOSITORY",
          counts_toward_spending: false,
        }),
      ]}
    />,
  );
  expect(screen.getByText("Synthetic card ··0001")).toBeInTheDocument();
  const toggles = screen.getAllByRole("checkbox", { name: "Count spending" });
  expect(toggles[0]).toBeChecked();
  fireEvent.click(toggles[1]);
  expect(onToggle).toHaveBeenCalledWith(expect.objectContaining({ id: "a2" }), true);
});

it("names what is missing", () => {
  render(<LedgerAccounts busy={false} onToggle={vi.fn()} onRemove={vi.fn()} accounts={[]} />);
  expect(screen.getByText("No accounts yet.")).toBeInTheDocument();
});

it("removes a file account only after confirming, and never offers it for synced accounts", () => {
  const onRemove = vi.fn();
  render(
    <LedgerAccounts
      busy={false}
      onToggle={vi.fn()}
      onRemove={onRemove}
      accounts={[account(), account({ id: "s1", name: "Synced checking", provider: "simplefin" })]}
    />,
  );
  expect(screen.queryByRole("button", { name: "Remove Synced checking" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Remove Synthetic card" }));
  const confirm = screen.getByRole("group", { name: "Confirm removing Synthetic card" });
  expect(confirm).toHaveTextContent(
    "Deletes its imports, its rules and 3 transactions. This can’t be undone.",
  );
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onRemove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Remove Synthetic card" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove account" }));
  expect(onRemove).toHaveBeenCalledWith(expect.objectContaining({ id: "a1" }));
  expect(screen.queryByRole("group")).toBeNull();
});
