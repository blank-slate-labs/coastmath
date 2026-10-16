import { render, screen, within } from "@testing-library/react";
import MilestoneOutcomes from "./milestone_outcomes";

it("keeps unachieved milestones separate from timing among reached trials", () => {
  render(
    <MilestoneOutcomes
      outcomes={[
        {
          id: "fi",
          name: "Financial independence",
          reached_trials: 3,
          unreached_trials: 1,
          unreported_trials: 0,
          reach_rate: 0.75,
          year_counts: { "2030": 1, "2034": 2 },
          p10_year: 2030,
          median_year: 2034,
          p90_year: 2034,
        },
        {
          id: "home",
          name: "Buy home",
          reached_trials: 0,
          unreached_trials: 4,
          unreported_trials: 0,
          reach_rate: 0,
          year_counts: {},
          p10_year: null,
          median_year: null,
          p90_year: null,
        },
      ]}
    />,
  );
  expect(screen.getByText(/Years cover trials that reached/)).toBeInTheDocument();
  const fi = screen.getByRole("row", { name: /Financial independence/ });
  expect(within(fi).getByText("75.0% (3 trials)")).toBeInTheDocument();
  const home = screen.getByRole("row", { name: /Buy home/ });
  expect(within(home).getByText("0.0% (0 trials)")).toBeInTheDocument();
  expect(within(home).getAllByText("—")).toHaveLength(3);
});

it("does not turn missing trial reports into a zero reach probability", () => {
  render(
    <MilestoneOutcomes
      outcomes={[
        {
          id: "fi",
          name: "FI",
          reached_trials: 1,
          unreached_trials: 0,
          unreported_trials: 1,
          reach_rate: null,
          year_counts: { "2030": 1 },
          p10_year: 2030,
          median_year: 2030,
          p90_year: 2030,
        },
      ]}
    />,
  );
  expect(screen.getByText(/Unknown \(1 trial\); 1 unreported/)).toBeInTheDocument();
});
