import { fireEvent, render, screen } from "@testing-library/react";
import ImportCsvMapping from "./import_csv_mapping";
import { csvDetails, csvMapping } from "./import_test_data";

it("changes roles, amounts, sign, decimal and date format", () => {
  const onChange = vi.fn();
  render(
    <ImportCsvMapping
      details={csvDetails()}
      mapping={csvMapping()}
      busy={false}
      onChange={onChange}
    />,
  );
  expect(screen.getByText(/SYNTHETIC GROCER/)).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Role of Category" }), {
    target: { value: "merchant" },
  });
  expect(onChange).toHaveBeenLastCalledWith(
    expect.objectContaining({ category_column: null, merchant_column: 3 }),
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Sign" }), {
    target: { value: "inflows_negative" },
  });
  expect(onChange).toHaveBeenLastCalledWith(
    expect.objectContaining({ sign_convention: "inflows_negative" }),
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Decimal separator" }), {
    target: { value: "," },
  });
  expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ decimal_separator: "," }));
  fireEvent.change(screen.getByRole("combobox", { name: "Amounts" }), {
    target: { value: "split" },
  });
  expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ amount_strategy: "split" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Date format" }), {
    target: { value: "%Y-%m-%d" },
  });
  expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ date_format: "%Y-%m-%d" }));
});

it("asks for a date format when day and month order is ambiguous", () => {
  const onChange = vi.fn();
  const details = csvDetails({
    date_ambiguous: true,
    sample_rows: [],
    date_formats: [
      {
        format: "%m/%d/%Y",
        label: "MM/DD/YYYY",
        matches: 2,
        date_from: "2026-03-04",
        date_to: "2026-05-06",
      },
      {
        format: "%d/%m/%Y",
        label: "DD/MM/YYYY",
        matches: 2,
        date_from: "2026-04-03",
        date_to: "2026-06-05",
      },
    ],
  });
  render(
    <ImportCsvMapping
      details={details}
      mapping={csvMapping({ date_format: null })}
      busy={false}
      onChange={onChange}
    />,
  );
  expect(screen.getByRole("status")).toHaveTextContent("ambiguous");
  fireEvent.change(screen.getByRole("combobox", { name: "Date format" }), {
    target: { value: "" },
  });
  expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ date_format: null }));
  fireEvent.change(screen.getByRole("combobox", { name: "Date format" }), {
    target: { value: "%d/%m/%Y" },
  });
  expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ date_format: "%d/%m/%Y" }));
});

it("edits debit and credit values for a type column", () => {
  const onChange = vi.fn();
  render(
    <ImportCsvMapping
      details={csvDetails()}
      busy={false}
      onChange={onChange}
      mapping={csvMapping({
        amount_strategy: "indicator",
        type_column: 3,
        category_column: null,
        debit_values: ["debit"],
      })}
    />,
  );
  expect(screen.queryByRole("combobox", { name: "Sign" })).not.toBeInTheDocument();
  const out = screen.getByRole("textbox", { name: "Money-out values" });
  expect(out).toHaveValue("debit");
  fireEvent.change(out, { target: { value: "debit, purchase" } });
  fireEvent.blur(out);
  expect(onChange).toHaveBeenLastCalledWith(
    expect.objectContaining({ debit_values: ["debit", "purchase"] }),
  );
  const into = screen.getByRole("textbox", { name: "Money-in values" });
  fireEvent.change(into, { target: { value: "Credit" } });
  fireEvent.blur(into);
  expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ credit_values: ["credit"] }));
});
