import { render, screen } from "@testing-library/react";
import CompareChart from "./compare_chart";
import { comparison, outcome } from "./month_compare_test_data";

function renderChart(variants = comparison().variants) {
  const { container } = render(
    <CompareChart
      plan={comparison().plan}
      variants={variants}
      mode="nominal"
      onModeChange={vi.fn()}
    />,
  );
  return {
    paths: [...container.querySelectorAll("path[data-series]")].map((path) =>
      path.getAttribute("data-series"),
    ),
  };
}

it("draws one line per distinct variant and the plan last", () => {
  const [june, july] = comparison().variants;
  const { paths } = renderChart([
    june,
    {
      ...july,
      net_worth_path: july.net_worth_path.map((point) => ({
        ...point,
        net_worth: point.net_worth / 2,
      })),
    },
  ]);
  expect(paths).toEqual(["variant-0", "variant-1", "plan"]);
  expect(screen.getByText("Jun 2026")).toBeVisible();
  expect(screen.getByText("Jul 2026")).toBeVisible();
});

it("merges variants that would draw on the same line into one legend entry", () => {
  const same = comparison().variants[0].net_worth_path;
  const { paths } = renderChart([
    outcome({ label: "Nov 2025", net_worth_path: same }),
    outcome({
      label: "Dec 2025",
      net_worth_path: same.map((point) => ({ ...point, net_worth: point.net_worth + 3 })),
    }),
    outcome({
      label: "Jul 2026",
      net_worth_path: same.map((point) => ({ ...point, net_worth: point.net_worth * 2 })),
    }),
  ]);
  expect(paths).toEqual(["variant-0", "variant-1", "plan"]);
  expect(screen.getByText("Nov 2025, Dec 2025 (same line)")).toBeVisible();
  expect(screen.getByText("Jul 2026")).toBeVisible();
  expect(
    screen.getByRole("img", { name: /Nov 2025, Dec 2025 \(same line\), Jul 2026/ }),
  ).toBeVisible();
});
