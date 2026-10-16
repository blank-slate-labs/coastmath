import { useRowScenarioState } from "@/stores/scenario_store";
import "./scenario.css";

/**
 * Marks a plan-builder row of the open scenario that differs from Main.
 * Rows that follow Main, and every row of an ordinary plan, show nothing.
 */
export function ScenarioBadge({ rowId }: { rowId: string | null | undefined }) {
  const state = useRowScenarioState(rowId);
  if (!state) return null;
  return (
    <span className="pill pill-info scenario-badge">
      {state === "changed" ? "Changed in scenario" : "Only in this scenario"}
    </span>
  );
}
