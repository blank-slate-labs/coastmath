import { fireEvent, render, screen } from "@testing-library/react";
import ImportHistory from "./import_history";
import { ledgerImport } from "./import_test_data";

it("confirms before reverting and states the irreversible effect", () => {
  const onRevert = vi.fn();
  render(
    <ImportHistory
      busy={false}
      onRevert={onRevert}
      imports={[
        ledgerImport({ duplicate_count: 2, skipped_count: 730 }),
        ledgerImport({ id: "i2", filename: "july.csv", status: "reverted" }),
      ]}
    />,
  );
  expect(screen.getByText(/6 added · 2 already there · 730 skipped/)).toBeInTheDocument();
  expect(screen.getByText("Reverted")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Revert" }));
  expect(screen.getByRole("group", { name: "Confirm revert" })).toHaveTextContent(
    "Removes up to 6 transactions no other import covers. This can’t be undone.",
  );
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onRevert).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Revert" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  expect(onRevert).toHaveBeenCalledWith(expect.objectContaining({ id: "i1" }));
  expect(screen.queryByRole("group", { name: "Confirm revert" })).not.toBeInTheDocument();
});

it("names the account a revert also removes", () => {
  render(
    <ImportHistory
      busy={false}
      onRevert={vi.fn()}
      imports={[ledgerImport({ revert_removes_account: true })]}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Revert" }));
  expect(screen.getByRole("group", { name: "Confirm revert" })).toHaveTextContent(
    "Removes up to 6 transactions no other import covers. This also removes Synthetic card. This can’t be undone.",
  );
});

it("names what is missing", () => {
  render(<ImportHistory imports={[]} busy={false} onRevert={vi.fn()} />);
  expect(screen.getByText("No imports yet.")).toBeInTheDocument();
});
