import { render, screen } from "@testing-library/react";
import MonthOverview from "./month_overview";
import { month } from "./ledger_test_data";

it("stacks spending, marks take-home and sets incomplete months apart", () => {
  const { container } = render(
    <MonthOverview
      currency="USD"
      months={[
        month(),
        month({ month: "2026-09", complete: false, discretionary: -50, income: 0 }),
      ]}
    />,
  );
  expect(screen.getByRole("img", { name: "Spending by month" })).toBeInTheDocument();
  const groups = container.querySelectorAll("g[data-month]");
  expect(groups).toHaveLength(2);
  expect(groups[0].getAttribute("data-complete")).toBe("true");
  expect(groups[1].getAttribute("data-complete")).toBe("false");
  expect(groups[1].getAttribute("opacity")).toBe("0.35");
  expect(groups[1].querySelector("rect[stroke-dasharray]")).not.toBeNull();
  expect(container.querySelectorAll("line[data-take-home]")).toHaveLength(1);
  expect(groups[0].querySelector("title")?.textContent).toContain("take-home");
  expect(groups[1].querySelector("title")?.textContent).toContain("incomplete");
});

it("names what is missing when there are no months", () => {
  render(<MonthOverview currency="USD" months={[]} />);
  expect(screen.getByText("No months yet.")).toBeInTheDocument();
});

it("thins month labels when many months show", () => {
  const months = Array.from({ length: 24 }, (_, i) =>
    month({ month: `20${25 + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}` }),
  );
  const { container } = render(<MonthOverview currency="EUR" months={months} />);
  expect(container.querySelectorAll("text")).toHaveLength(12);
});
