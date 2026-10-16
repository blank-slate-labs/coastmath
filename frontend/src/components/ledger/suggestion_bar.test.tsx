import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import SuggestionBar from "./suggestion_bar";
import { txn } from "./ledger_test_data";
import type { SuggestionStatus } from "@/api/ledger_suggestions";

const mocks = vi.hoisted(() => ({ bulkUpdate: vi.fn(), status: vi.fn(), run: vi.fn() }));
vi.mock("@/api/ledger", () => ({ ledger: { bulkUpdate: mocks.bulkUpdate } }));
vi.mock("@/api/ledger_suggestions", () => ({
  ledgerSuggestions: { status: mocks.status, run: mocks.run },
}));

const offered = (overrides: Partial<SuggestionStatus> = {}): SuggestionStatus => ({
  offered: true,
  running: false,
  pending: 3,
  last_run: null,
  ...overrides,
});
const suggested = [
  txn({ id: "s1", category: "dining", category_source: "llm" }),
  txn({ id: "s2", category: "groceries", category_source: "llm" }),
  txn({ id: "s3", category: "dining", category_source: "llm" }),
  txn({ id: "p1", category_source: "provider" }),
];

beforeEach(() => {
  vi.clearAllMocks();
  mocks.status.mockResolvedValue(offered());
  mocks.bulkUpdate.mockResolvedValue({ transactions: [] });
});

it("renders nothing when not offered and nothing is suggested", async () => {
  mocks.status.mockResolvedValue({ offered: false, running: false, pending: null, last_run: null });
  const { container } = render(
    <SuggestionBar transactions={[txn()]} refreshKey={0} onChanged={vi.fn()} />,
  );
  await waitFor(() => expect(mocks.status).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});

it("hides the run button when the status cannot load", async () => {
  mocks.status.mockRejectedValue(new Error("offline"));
  render(<SuggestionBar transactions={suggested} refreshKey={0} onChanged={vi.fn()} />);
  await waitFor(() => expect(mocks.status).toHaveBeenCalled());
  expect(screen.queryByRole("button", { name: /Suggest categories/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Accept 3 suggested" })).toBeInTheDocument();
});

it("runs suggestions and refreshes when rows were suggested", async () => {
  mocks.run.mockResolvedValue(
    offered({
      pending: 0,
      last_run: { status: "suggested", suggested: 3, sent: 3, message: null, finished_at: null },
    }),
  );
  const onChanged = vi.fn();
  render(<SuggestionBar transactions={[]} refreshKey={0} onChanged={onChanged} />);
  fireEvent.click(await screen.findByRole("button", { name: "Suggest categories (3)" }));
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: "Suggest categories (0)" })).toBeDisabled();
});

it("shows a failed run without refreshing", async () => {
  mocks.run.mockResolvedValue(
    offered({
      last_run: {
        status: "failed",
        suggested: 0,
        sent: 0,
        message: "The suggestion service is unavailable.",
        finished_at: null,
      },
    }),
  );
  const onChanged = vi.fn();
  render(<SuggestionBar transactions={[]} refreshKey={0} onChanged={onChanged} />);
  fireEvent.click(await screen.findByRole("button", { name: "Suggest categories (3)" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("unavailable");
  expect(onChanged).not.toHaveBeenCalled();
});

it("reports a refused run and disables while running elsewhere", async () => {
  mocks.run.mockRejectedValue(new Error("Category suggestions are not configured."));
  const { unmount } = render(
    <SuggestionBar transactions={[]} refreshKey={0} onChanged={vi.fn()} />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Suggest categories (3)" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("not configured");
  unmount();
  mocks.status.mockResolvedValue(offered({ running: true }));
  render(<SuggestionBar transactions={[]} refreshKey={1} onChanged={vi.fn()} />);
  expect(await screen.findByRole("button", { name: "Suggest categories (3)" })).toBeDisabled();
});

it("accepts every visible suggestion, one bulk update per category", async () => {
  const onChanged = vi.fn();
  render(<SuggestionBar transactions={suggested} refreshKey={0} onChanged={onChanged} />);
  fireEvent.click(await screen.findByRole("button", { name: "Accept 3 suggested" }));
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  expect(mocks.bulkUpdate).toHaveBeenCalledWith(["s1", "s3"], { category: "dining" });
  expect(mocks.bulkUpdate).toHaveBeenCalledWith(["s2"], { category: "groceries" });
  expect(mocks.bulkUpdate).toHaveBeenCalledTimes(2);
});
