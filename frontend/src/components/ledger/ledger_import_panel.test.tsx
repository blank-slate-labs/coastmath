import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import LedgerImportPanel from "./ledger_import_panel";
import { account, CATEGORIES } from "./ledger_test_data";
import {
  csvPreview,
  csvDetails,
  csvMapping,
  ledgerImport,
  ofxPreview,
  statement,
} from "./import_test_data";

const mocks = vi.hoisted(() => ({
  accounts: vi.fn(),
  categories: vi.fn(),
  preview: vi.fn(),
  commit: vi.fn(),
  list: vi.fn(),
  revert: vi.fn(),
}));
vi.mock("@/api/ledger", () => ({
  ledger: { accounts: mocks.accounts, categories: mocks.categories },
}));
vi.mock("@/api/ledger_imports", () => ({
  ledgerImports: {
    preview: mocks.preview,
    commit: mocks.commit,
    list: mocks.list,
    revert: mocks.revert,
  },
  fileToBase64: async () => "QQ==",
}));

const FILE = { filename: "august.csv", content_base64: "QQ==" };

beforeEach(() => {
  vi.clearAllMocks();
  mocks.accounts.mockResolvedValue([
    account(),
    account({ id: "s1", provider: "simplefin", name: "Synced" }),
  ]);
  mocks.categories.mockResolvedValue(CATEGORIES);
  mocks.list.mockResolvedValue([ledgerImport()]);
  mocks.preview.mockResolvedValue(csvPreview());
  mocks.commit.mockResolvedValue({
    import: ledgerImport(),
    account: account(),
    created_account: true,
    inserted: 2,
    existing: 0,
    skipped: 1,
    removed: 1,
    rules_saved: 1,
  });
  mocks.revert.mockResolvedValue({
    import: ledgerImport({ status: "reverted" }),
    removed: 6,
    reassigned: 0,
  });
});

async function chooseFile(name = "august.csv") {
  fireEvent.change(screen.getByLabelText("Statement file"), {
    target: { files: [new File(["x"], name)] },
  });
  return screen.findByRole("button", { name: /^Import \d+ transactions$/ });
}

it("previews a CSV, adjusts mapping, period, target and categories, then imports", async () => {
  const onChanged = vi.fn();
  render(<LedgerImportPanel onChanged={onChanged} />);
  expect(await screen.findByText("august.csv")).toBeInTheDocument();
  const importButton = await chooseFile();
  expect(mocks.preview).toHaveBeenCalledWith(FILE);
  // Sample rows show direction for the sign check; pending rows are marked.
  expect(screen.getByText("$80.00")).toBeInTheDocument();
  expect(screen.getByText("$2,000.00")).toBeInTheDocument();
  expect(screen.getByText("PAYROLL · pending")).toBeInTheDocument();
  expect(screen.getByText("unreadable rows")).toBeInTheDocument();
  // Only file accounts are import targets.
  expect(
    within(screen.getByRole("combobox", { name: "Target account" })).queryByText("Synced"),
  ).not.toBeInTheDocument();
  expect(importButton).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox", { name: "Account name" }), {
    target: { value: "Synthetic card" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "Institution" }), {
    target: { value: "Synthetic bank" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Account type" }), {
    target: { value: "checking" },
  });
  expect(importButton).not.toBeDisabled();

  fireEvent.change(screen.getByRole("combobox", { name: "Sign" }), {
    target: { value: "inflows_negative" },
  });
  await waitFor(() =>
    expect(mocks.preview).toHaveBeenLastCalledWith({
      ...FILE,
      mapping: expect.objectContaining({ sign_convention: "inflows_negative" }),
    }),
  );

  fireEvent.click(screen.getByRole("button", { name: "Whole months" }));
  expect(screen.getByLabelText("Period start")).toHaveValue("2026-08-01");
  expect(screen.getByLabelText("Period end")).toHaveValue("2026-08-31");
  fireEvent.click(screen.getByRole("button", { name: "Dates in file" }));
  expect(screen.getByLabelText("Period start")).toHaveValue("2026-08-02");
  fireEvent.change(screen.getByLabelText("Period end"), { target: { value: "2026-08-30" } });
  fireEvent.change(screen.getByLabelText("Period start"), { target: { value: "2026-08-01" } });

  expect(screen.getByRole("combobox", { name: "Category for Groceries" })).toHaveValue("groceries");
  fireEvent.change(screen.getByRole("combobox", { name: "Category for Pay" }), {
    target: { value: "dining" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Import 2 transactions" }));
  await waitFor(() => expect(mocks.commit).toHaveBeenCalled());
  expect(mocks.commit).toHaveBeenCalledWith({
    ...FILE,
    new_account: {
      name: "Synthetic card",
      account_type: "DEPOSITORY",
      subtype: "CHECKING",
      institution_name: "Synthetic bank",
    },
    mapping: csvMapping(),
    period: { start: "2026-08-01", end: "2026-08-30" },
    categories: [
      { value: "Groceries", category: "groceries" },
      { value: "Pay", category: "dining" },
    ],
  });
  const status = await screen.findByRole("status");
  expect(status).toHaveTextContent("2 imported");
  expect(status).toHaveTextContent("1 skipped");
  expect(status).toHaveTextContent("1 removed");
  expect(onChanged).toHaveBeenCalled();
  expect(mocks.list).toHaveBeenCalledTimes(2);
  expect(
    screen.queryByRole("button", { name: /^Import \d+ transactions$/ }),
  ).not.toBeInTheDocument();
});

it("states how many rows fall before the retention window, before and after importing", async () => {
  mocks.preview.mockResolvedValue(
    csvPreview({
      retention_start: "2024-08-20",
      parsed: {
        ...csvPreview().parsed!,
        transaction_count: 1000,
        issue_count: 0,
        before_retention: 730,
      },
    }),
  );
  mocks.commit.mockResolvedValue({
    import: ledgerImport({ imported_count: 270, skipped_count: 730 }),
    account: account(),
    created_account: true,
    inserted: 270,
    existing: 0,
    skipped: 731,
    removed: 0,
    rules_saved: 0,
    before_retention: 730,
    retention_start: "2024-08-20",
  });
  render(<LedgerImportPanel onChanged={vi.fn()} />);
  const button = await chooseFile();
  expect(button).toHaveTextContent("Import 270 transactions");
  expect(screen.getByText(/dated before Aug 20, 2024, skipped/)).toHaveTextContent(
    "730 dated before Aug 20, 2024, skipped",
  );
  fireEvent.change(screen.getByRole("textbox", { name: "Account name" }), {
    target: { value: "Synthetic card" },
  });
  fireEvent.click(button);
  const status = await screen.findByRole("status");
  expect(status).toHaveTextContent("270 imported");
  expect(status).toHaveTextContent("1 skipped");
  expect(status).toHaveTextContent("730 dated before Aug 20, 2024, skipped");
});

it("disables the import when every row is before the retention window", async () => {
  mocks.preview.mockResolvedValue(
    csvPreview({
      retention_start: "2024-08-20",
      parsed: { ...csvPreview().parsed!, before_retention: 2 },
    }),
  );
  render(<LedgerImportPanel onChanged={vi.fn()} />);
  const button = await chooseFile();
  fireEvent.change(screen.getByRole("textbox", { name: "Account name" }), {
    target: { value: "Synthetic card" },
  });
  expect(button).toHaveTextContent("Import 0 transactions");
  expect(button).toBeDisabled();
});

it("shows a failed import save by the Import button and keeps the file for a retry", async () => {
  mocks.commit.mockRejectedValueOnce(new Error("The import could not be saved."));
  render(<LedgerImportPanel onChanged={vi.fn()} />);
  const button = await chooseFile();
  fireEvent.change(screen.getByRole("textbox", { name: "Account name" }), {
    target: { value: "Synthetic card" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Category for Pay" }), {
    target: { value: "dining" },
  });
  fireEvent.click(button);
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("The import could not be saved.");
  expect(alert).toHaveClass("field-error");
  // Right after the button row, not at the top of the panel.
  expect(alert.previousElementSibling).toContainElement(button);
  expect(screen.getByRole("group", { name: "Columns" })).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "Category for Pay" })).toHaveValue("dining");
  expect(screen.getByRole("textbox", { name: "Account name" })).toHaveValue("Synthetic card");
  await waitFor(() => expect(button).not.toBeDisabled());
  fireEvent.click(button);
  await waitFor(() => expect(mocks.commit).toHaveBeenCalledTimes(2));
  expect(await screen.findByRole("status")).toHaveTextContent("2 imported");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("re-previews against an existing account and refuses the same file twice", async () => {
  render(<LedgerImportPanel onChanged={vi.fn()} />);
  await chooseFile();
  mocks.preview.mockResolvedValueOnce(
    csvPreview({
      previous_import_id: "i1",
      parsed: { ...csvPreview().parsed!, existing_count: 2, issue_count: 0 },
    }),
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Target account" }), {
    target: { value: "a1" },
  });
  await waitFor(() =>
    expect(mocks.preview).toHaveBeenLastCalledWith({
      ...FILE,
      source_id: "a1",
      mapping: csvMapping(),
    }),
  );
  expect(
    await screen.findByText("This file is already imported into this account."),
  ).toBeInTheDocument();
  expect(screen.getByText("already there")).toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: "Account name" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Import 2 transactions" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(
    screen.queryByText("This file is already imported into this account."),
  ).not.toBeInTheDocument();
});

it("keeps a chosen period that still fits and resets one that does not", async () => {
  render(<LedgerImportPanel onChanged={vi.fn()} />);
  await chooseFile();
  fireEvent.click(screen.getByRole("button", { name: "Whole months" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Decimal separator" }), {
    target: { value: "," },
  });
  await waitFor(() => expect(mocks.preview).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.getByLabelText("Period start")).toHaveValue("2026-08-01"));
  mocks.preview.mockResolvedValueOnce(
    csvPreview({
      period: {
        suggested: { start: "2026-07-20", end: "2026-08-25" },
        earliest: "2026-07-01",
        latest: "2026-08-31",
      },
    }),
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Decimal separator" }), {
    target: { value: "." },
  });
  await waitFor(() => expect(screen.getByLabelText("Period start")).toHaveValue("2026-07-20"));
});

it("shows a mapping that cannot be read yet and builds one from column roles", async () => {
  mocks.preview.mockResolvedValue(
    csvPreview({
      mapping: null,
      parsed: null,
      period: null,
      categories: [],
      csv: csvDetails({ suggested_mapping: null, date_ambiguous: true }),
      parse_error: {
        code: "INVALID_MAPPING",
        message: "Choose a date format.",
        field: "date_format",
      },
    }),
  );
  render(<LedgerImportPanel onChanged={vi.fn()} />);
  const button = await chooseFile();
  expect(screen.getByRole("alert")).toHaveTextContent("Choose a date format.");
  expect(screen.getByRole("combobox", { name: "Role of Date" })).toHaveValue("date");
  expect(screen.queryByRole("group", { name: "Statement period" })).not.toBeInTheDocument();
  expect(button).toBeDisabled();
});

it("imports an OFX statement chosen from several, into its matched account", async () => {
  mocks.preview.mockResolvedValue(
    ofxPreview([
      statement(),
      statement({
        index: 1,
        kind: "credit_card",
        name: "Credit card ··1111",
        account_type: "CREDIT",
        subtype: "CREDIT_CARD",
        matched_source_id: "a1",
        existing_count: 1,
        transaction_count: 3,
        issue_count: 2,
        institution_name: null,
      }),
    ]),
  );
  render(<LedgerImportPanel onChanged={vi.fn()} />);
  await chooseFile("statement.qfx");
  expect(screen.getByRole("textbox", { name: "Account name" })).toHaveValue("Checking ··5678");
  expect(screen.getByRole("textbox", { name: "Institution" })).toHaveValue("Example Credit Union");
  expect(screen.getByRole("combobox", { name: "Account type" })).toHaveValue("checking");
  expect(screen.getByText(/^Period /)).toBeInTheDocument();
  expect(screen.queryByRole("group", { name: "Bank categories" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Account in file" }), {
    target: { value: "1" },
  });
  expect(screen.getByRole("combobox", { name: "Target account" })).toHaveValue("a1");
  fireEvent.click(screen.getByRole("button", { name: "Import 3 transactions" }));
  await waitFor(() =>
    expect(mocks.commit).toHaveBeenCalledWith({
      filename: "statement.qfx",
      content_base64: "QQ==",
      source_id: "a1",
      statement_index: 1,
    }),
  );
});

it("reverts an import and reports failures", async () => {
  const onChanged = vi.fn();
  render(<LedgerImportPanel onChanged={onChanged} />);
  fireEvent.click(await screen.findByRole("button", { name: "Revert" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  await waitFor(() => expect(mocks.revert).toHaveBeenCalledWith("i1", { removeAccount: false }));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
  mocks.preview.mockRejectedValueOnce(new Error("Choose a CSV, OFX or QFX file."));
  fireEvent.change(screen.getByLabelText("Statement file"), {
    target: { files: [new File(["x"], "notes.txt")] },
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("Choose a CSV, OFX or QFX file.");
  fireEvent.change(screen.getByLabelText("Statement file"), { target: { files: [] } });
  expect(mocks.preview).toHaveBeenCalledTimes(1);
});

it("commits once when Import is clicked twice before a render", async () => {
  render(<LedgerImportPanel onChanged={vi.fn()} />);
  const importButton = await chooseFile();
  fireEvent.change(screen.getByRole("textbox", { name: "Account name" }), {
    target: { value: "Synthetic card" },
  });
  // Both clicks land before React re-renders with the button disabled.
  act(() => {
    importButton.click();
    importButton.click();
  });
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("2 imported"));
  expect(mocks.commit).toHaveBeenCalledTimes(1);
});

it("reverts an import together with the account it created", async () => {
  mocks.list.mockResolvedValue([ledgerImport({ revert_removes_account: true })]);
  const onChanged = vi.fn();
  render(<LedgerImportPanel onChanged={onChanged} />);
  fireEvent.click(await screen.findByRole("button", { name: "Revert" }));
  expect(screen.getByRole("group", { name: "Confirm revert" })).toHaveTextContent(
    "This also removes Synthetic card.",
  );
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  await waitFor(() => expect(mocks.revert).toHaveBeenCalledWith("i1", { removeAccount: true }));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
});

it("reports a load failure", async () => {
  mocks.list.mockRejectedValueOnce(new Error("Offline"));
  render(<LedgerImportPanel onChanged={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Offline");
});
