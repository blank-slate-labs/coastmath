import type { SimulationResult } from "@/types/plan";

/**
 * Whether a projection has anything in it. The engine projects an empty plan as rows of $0, which
 * read as results; these checks keep results that need inputs from stating figures they cannot have.
 * Balances come from the projection itself, so a plan whose accounts have not loaded still counts.
 */
function inputs(simulation: SimulationResult) {
  const snapshots = simulation.yearly_snapshots ?? [];
  return {
    spending: snapshots.some((s) => s.expenses > 0),
    income: snapshots.some((s) => s.gross_income > 0),
    holdings: snapshots.some(
      (s) =>
        Object.keys(s.accounts ?? {}).length > 0 ||
        s.real_assets_value !== 0 ||
        s.liabilities_balance !== 0,
    ),
  };
}

/** What every results view says for a plan with nothing in it. */
export const EMPTY_PLAN_TEXT = "No accounts, income or expenses yet.";

/** No spending, income, accounts, property or debt in any year: there is no projection to show. */
export function isEmptyProjection(simulation: SimulationResult | null | undefined): boolean {
  if (!simulation) return true;
  const { spending, income, holdings } = inputs(simulation);
  return !spending && !income && !holdings;
}

/**
 * What a risk result (Monte Carlo, the wellness grades) lacks: spending to fund, and money to fund it
 * with. The line names what is missing, or is null when the plan has both.
 */
export function missingRiskInputs(simulation: SimulationResult | null | undefined): string | null {
  if (!simulation) return null;
  const { spending, income, holdings } = inputs(simulation);
  const missing = [
    ...(!income && !holdings ? ["accounts", "income"] : []),
    ...(!spending ? ["expenses"] : []),
  ];
  if (spending && (income || holdings)) return null;
  const list =
    missing.length === 1 ? missing[0] : `${missing.slice(0, -1).join(", ")} or ${missing.at(-1)}`;
  return `No ${list} yet.`;
}
