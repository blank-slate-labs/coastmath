import { fireEvent, render, screen } from "@testing-library/react";
import LedgerRules from "./ledger_rules";
import { CATEGORIES, rule } from "./ledger_test_data";

it("edits rule text on blur, changes category and deletes", () => {
  const onUpdate = vi.fn();
  const onDelete = vi.fn();
  render(
    <LedgerRules
      rules={[rule()]}
      categories={CATEGORIES}
      busy={false}
      onUpdate={onUpdate}
      onDelete={onDelete}
    />,
  );
  expect(screen.getByText("Merchant is")).toBeInTheDocument();
  expect(screen.getByText("4 matched")).toBeInTheDocument();
  const text = screen.getByRole("textbox", { name: "Rule text" });
  fireEvent.blur(text);
  expect(onUpdate).not.toHaveBeenCalled();
  fireEvent.change(text, { target: { value: "synthetic market" } });
  fireEvent.blur(text);
  expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ id: "r1" }), {
    pattern: "synthetic market",
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Rule category" }), {
    target: { value: "dining" },
  });
  expect(onUpdate).toHaveBeenLastCalledWith(expect.objectContaining({ id: "r1" }), {
    category: "dining",
  });
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  expect(onDelete).toHaveBeenCalled();
});

it("names what is missing", () => {
  render(
    <LedgerRules
      rules={[]}
      categories={CATEGORIES}
      busy={false}
      onUpdate={vi.fn()}
      onDelete={vi.fn()}
    />,
  );
  expect(screen.getByText("No rules yet.")).toBeInTheDocument();
});
