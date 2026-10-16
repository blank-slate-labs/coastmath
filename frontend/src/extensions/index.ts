import active from "@extensions/active";

// A re-export is a live binding, so modules the hosting package imports can
// import this one without an evaluation-order cycle.
export { default as extensions } from "@extensions/active";

/** Where the planner is served: "/" unless a hosting package moves it. */
export function plannerPath() {
  return active.routes?.plannerPath ?? "/";
}
export type {
  AccessExtension,
  ApiExtension,
  Extensions,
  PlannerExtension,
  PlanTextField,
  PlanTextKey,
  Refusal,
  RouteExtension,
  SampleExtension,
  SessionExtension,
  WorkspaceExtension,
} from "./types";
