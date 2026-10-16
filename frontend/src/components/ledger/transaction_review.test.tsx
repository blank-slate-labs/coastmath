import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import TransactionReview from "./transaction_review";
import { CATEGORIES, txn } from "./ledger_test_data";

const mocks = vi.hoisted(() => ({
  transactions: vi.fn(),
  updateTransaction: vi.fn(),
  exportTransactions: vi.fn(),
}));
vi.mock("@/api/ledger", () => ({ ledger: mocks }));
const reportMocks = vi.hoisted(() => ({ downloadReport: vi.fn() }));
vi.mock("@/utils/projection_report", () => reportMocks);
const suggestionMocks = vi.hoisted(() => ({ status: vi.fn(), run: vi.fn() }));
vi.mock("@/api/ledger_suggestions", () => ({ ledgerSuggestions: suggestionMocks }));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.transactions.mockResolvedValue({
    transactions: [
      txn(),
      txn({
        id: "t2",
        description: "Card payment",
        merchant_name: "Synthetic Coffee",
        status: "PENDING",
        category_override: "dining",
        category: "dining",
        amount: -20,
      }),
    ],
    total: 2,
  });
  mocks.updateTransaction.mockResolvedValue({ transaction: txn(), rule: null });
  suggestionMocks.status.mockResolvedValue({
    offered: false,
    running: false,
    pending: null,
    last_run: null,
  });
});

function renderReview(onChanged = vi.fn()) {
  render(
    <TransactionReview
      categories={CATEGORIES}
      months={["2026-08"]}
      currency="USD"
      refreshKey={0}
      onChanged={onChanged}
    />,
  );
  return onChanged;
}

it("downloads the ledger as CSV and reports a failed download", async () => {
  mocks.exportTransactions.mockResolvedValueOnce("date,amount\r\n");
  renderReview();
  fireEvent.click(await screen.findByRole("button", { name: "Download CSV" }));
  await waitFor(() =>
    expect(reportMocks.downloadReport).toHaveBeenCalledWith(
      "date,amount\r\n",
      "transactions.csv",
      "text/csv;charset=utf-8",
    ),
  );
  mocks.exportTransactions.mockRejectedValueOnce(new Error("Offline"));
  fireEvent.click(screen.getByRole("button", { name: "Download CSV" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Offline");
  expect(reportMocks.downloadReport).toHaveBeenCalledTimes(1);
});

it("offers no download for an empty ledger", async () => {
  mocks.transactions.mockResolvedValue({ transactions: [], total: 0 });
  renderReview();
  expect(await screen.findByText("No transactions yet.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Download CSV" })).not.toBeInTheDocument();
});

it("pads every column so narrow headers stay apart", async () => {
  renderReview();
  await screen.findByText("SYNTHETIC GROCER");
  for (const name of ["Amount", "Category"]) {
    expect(screen.getByRole("columnheader", { name })).toHaveStyle({ padding: "4px" });
  }
  const cells = within(screen.getAllByRole("row")[1]).getAllByRole("cell");
  for (const cell of cells) expect(cell).toHaveStyle({ padding: "4px" });
});

it("filters by month, category and uncategorized", async () => {
  renderReview();
  await screen.findByText("SYNTHETIC GROCER");
  expect(screen.getByText("Synthetic Coffee")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Month" }), {
    target: { value: "2026-08" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Category" }), {
    target: { value: "dining" },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: "Uncategorized only" }));
  await waitFor(() =>
    expect(mocks.transactions).toHaveBeenLastCalledWith({
      month: "2026-08",
      category: "dining",
      uncategorized: true,
      limit: 100,
      offset: 0,
    }),
  );
});

it("changes category, applies to similar, resets, excludes and marks one-time", async () => {
  const onChanged = renderReview();
  await screen.findByText("SYNTHETIC GROCER");
  fireEvent.change(screen.getByRole("combobox", { name: "Category for SYNTHETIC GROCER" }), {
    target: { value: "dining" },
  });
  await waitFor(() =>
    expect(mocks.updateTransaction).toHaveBeenCalledWith("t1", { category: "dining" }),
  );
  fireEvent.click(screen.getByRole("checkbox", { name: "Apply category to similar" }));
  await waitFor(() =>
    expect(
      screen.getByRole("combobox", { name: "Category for SYNTHETIC GROCER" }),
    ).not.toBeDisabled(),
  );
  fireEvent.change(screen.getByRole("combobox", { name: "Category for SYNTHETIC GROCER" }), {
    target: { value: "dining" },
  });
  await waitFor(() =>
    expect(mocks.updateTransaction).toHaveBeenLastCalledWith("t1", {
      category: "dining",
      apply_to_similar: true,
    }),
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Reset" })).not.toBeDisabled());
  fireEvent.click(screen.getByRole("button", { name: "Reset" }));
  await waitFor(() =>
    expect(mocks.updateTransaction).toHaveBeenLastCalledWith("t2", { category: null }),
  );
  await waitFor(() =>
    expect(screen.getByRole("checkbox", { name: "Exclude SYNTHETIC GROCER" })).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByRole("checkbox", { name: "Exclude SYNTHETIC GROCER" }));
  await waitFor(() =>
    expect(mocks.updateTransaction).toHaveBeenLastCalledWith("t1", { excluded: true }),
  );
  await waitFor(() =>
    expect(screen.getByRole("checkbox", { name: "One-time SYNTHETIC GROCER" })).not.toBeDisabled(),
  );
  fireEvent.click(screen.getByRole("checkbox", { name: "One-time SYNTHETIC GROCER" }));
  await waitFor(() =>
    expect(mocks.updateTransaction).toHaveBeenLastCalledWith("t1", { one_time: true }),
  );
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(5));
});

it("keeps the row and reports a failed save", async () => {
  mocks.updateTransaction.mockRejectedValueOnce(
    new Error("Transactions are unavailable in this release."),
  );
  const onChanged = renderReview();
  await screen.findByText("SYNTHETIC GROCER");
  fireEvent.click(screen.getByRole("checkbox", { name: "One-time SYNTHETIC GROCER" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("unavailable in this release");
  expect(onChanged).not.toHaveBeenCalled();
});

it("counts and pages long lists above and below the table", async () => {
  const rows = Array.from({ length: 100 }, (_, i) => txn({ id: `t${i}`, description: `ROW ${i}` }));
  mocks.transactions.mockResolvedValue({ transactions: rows, total: 284 });
  renderReview();
  const top = () => screen.getByRole("group", { name: "Transaction pages" });
  const bottom = () => screen.getByRole("group", { name: "Transaction pages, end of list" });
  await waitFor(() => expect(top()).toHaveTextContent("1–100 of 284"));
  expect(bottom()).toHaveTextContent("1–100 of 284");
  expect(screen.getAllByRole("row")).toHaveLength(101);
  const table = screen.getByRole("table");
  expect(top().compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(bottom().compareDocumentPosition(table) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  expect(within(top()).getByRole("button", { name: "Newer" })).toBeDisabled();
  fireEvent.click(within(top()).getByRole("button", { name: "Older" }));
  await waitFor(() => expect(top()).toHaveTextContent("101–200 of 284"));
  fireEvent.click(within(bottom()).getByRole("button", { name: "Older" }));
  await waitFor(() => expect(bottom()).toHaveTextContent("201–284 of 284"));
  expect(within(top()).getByRole("button", { name: "Older" })).toBeDisabled();
  fireEvent.click(within(top()).getByRole("button", { name: "Newer" }));
  await waitFor(() => expect(top()).toHaveTextContent("101–200 of 284"));
  expect(mocks.transactions).toHaveBeenCalledWith(expect.objectContaining({ offset: 200 }));
});

it("shows a short list without a count or pages", async () => {
  renderReview();
  expect(await screen.findAllByRole("row")).toHaveLength(3);
  expect(screen.queryByText(/\d+ transactions?$/)).not.toBeInTheDocument();
  expect(screen.queryByRole("group", { name: "Transaction pages" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Older" })).not.toBeInTheDocument();
});

it("shows a load failure", async () => {
  mocks.transactions.mockRejectedValueOnce("offline");
  renderReview();
  expect(await screen.findByRole("alert")).toHaveTextContent("could not be confirmed");
});

it("labels a suggested category and accepts it as the override", async () => {
  mocks.transactions.mockResolvedValue({
    transactions: [txn({ category: "dining", category_source: "llm" })],
    total: 1,
  });
  const onChanged = renderReview();
  expect(await screen.findByText("Suggested")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Accept 1 suggested" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Accept suggestion for SYNTHETIC GROCER" }));
  await waitFor(() =>
    expect(mocks.updateTransaction).toHaveBeenCalledWith("t1", { category: "dining" }),
  );
  expect(onChanged).toHaveBeenCalledTimes(1);
});
