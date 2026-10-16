import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import TerminalRouter, { canonicalPath } from "./terminal_router";

// The planner on its own, without a hosting package.
vi.mock("@extensions/active", () => ({ default: {} }));
vi.mock("./app", () => ({ default: () => <div>Planner page</div> }));
vi.mock("./pages/plaid_oauth_return", () => ({ default: () => <div>Plaid return page</div> }));
vi.mock("./pages/terminal_dashboard", () => ({
  TerminalDashboard: () => <div>Terminal page</div>,
}));

const visit = (url: string) => {
  window.history.replaceState(null, "", url);
  return render(<TerminalRouter />);
};
afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
});

it.each([
  ["/", "Planner page", "/"],
  ["/terminal", "Terminal page", "/terminal"],
  ["/terminal/", "Terminal page", "/terminal"],
  ["/plaid/oauth/", "Plaid return page", "/plaid/oauth"],
  ["/sample", "Page not found", "/sample"],
  ["/no-such-page", "Page not found", "/no-such-page"],
])("opens %s and settles on %s at %s", async (url, text, pathname) => {
  visit(url);
  expect(await screen.findByText(text)).toBeVisible();
  expect(window.location.pathname).toBe(pathname);
});

it("canonicalizes paths without touching unrelated ones", () => {
  expect(canonicalPath("/")).toBe("/");
  expect(canonicalPath("/terminal///")).toBe("/terminal");
  expect(canonicalPath("/landing")).toBe("/landing");
});
