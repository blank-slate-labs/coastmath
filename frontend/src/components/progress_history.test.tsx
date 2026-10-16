import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi, it, expect } from "vitest";
import ProgressHistory from "./progress_history";
import { makeAdapter } from "@/test_support/adapter_stub";
const mocks = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), remove: vi.fn() }));
const adapter = makeAdapter({
  listProgressPoints: mocks.list,
  createProgressPoint: mocks.create,
  deleteProgressPoint: mocks.remove,
});
vi.mock("@/storage/context", async () =>
  (await import("@/test_support/storage_mock")).mockStorageContext(() => adapter),
);
it("records assets less debt, shows the saved result, and reloads persisted history", async () => {
  mocks.list.mockResolvedValue([]);
  const saved = {
    id: "r",
    recorded_date: "2026-01-01",
    net_worth: -10000,
    auto_logged: false,
    assets_breakdown: {},
    liabilities_breakdown: {},
  };
  mocks.create.mockResolvedValue(saved);
  const view = render(<ProgressHistory />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Record progress" })).toBeEnabled(),
  );
  fireEvent.change(screen.getByLabelText("Record date"), { target: { value: "2026-01-01" } });
  fireEvent.change(screen.getByLabelText("Cash and investments ($)"), {
    target: { value: "10000" },
  });
  fireEvent.change(screen.getByLabelText("Total debt ($)"), { target: { value: "20000" } });
  // Property starts blank, not $0: it must be entered, and the line says so inline.
  fireEvent.click(screen.getByRole("button", { name: "Record progress" }));
  expect(mocks.create).not.toHaveBeenCalled();
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(/^Property and other assets \(\$\): /),
  );
  expect(screen.getByLabelText("Property and other assets ($)")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  fireEvent.change(screen.getByLabelText("Property and other assets ($)"), {
    target: { value: "0" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Record progress" }));
  await waitFor(() => expect(screen.getByText("-$10,000")).toBeInTheDocument());
  expect(mocks.create).toHaveBeenCalledWith(
    expect.objectContaining({
      net_worth: -10000,
      assets_breakdown: { liquid_assets: 10000, property: 0 },
      liabilities_breakdown: { debt: 20000 },
    }),
  );
  view.unmount();
  mocks.list.mockResolvedValue([saved]);
  render(<ProgressHistory />);
  await waitFor(() =>
    expect(screen.getByRole("img", { name: "Recorded net worth over time" })).toBeInTheDocument(),
  );
  expect(screen.getByText("-$10,000")).toBeInTheDocument();
});
it("retains inputs when recording fails", async () => {
  mocks.list.mockResolvedValue([]);
  mocks.create.mockRejectedValue(new Error("offline"));
  render(<ProgressHistory />);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Record progress" })).toBeEnabled(),
  );
  fireEvent.change(screen.getByLabelText("Cash and investments ($)"), {
    target: { value: "15000" },
  });
  fireEvent.change(screen.getByLabelText("Property and other assets ($)"), {
    target: { value: "0" },
  });
  fireEvent.change(screen.getByLabelText("Total debt ($)"), { target: { value: "0" } });
  fireEvent.click(screen.getByRole("button", { name: "Record progress" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not record"));
  expect(screen.getByLabelText("Cash and investments ($)")).toHaveValue("15,000");
});
