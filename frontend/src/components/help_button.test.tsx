import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import HelpButton from "./help_button";

it("opens the help center in a new tab with an accessible name", () => {
  render(<HelpButton />);
  const link = screen.getByRole("link", { name: "Help (opens in a new tab)" });
  expect(link).toHaveAttribute("href", "/help");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noopener");
  expect(link).not.toHaveClass("is-compact");
});

it("keeps the same name when compact shows only the glyph", () => {
  render(<HelpButton compact />);
  expect(screen.getByRole("link", { name: "Help (opens in a new tab)" })).toHaveClass(
    "app-help-button",
    "is-compact",
  );
});

it("sits in the mobile plan bar without the pinned pill's class", () => {
  render(<HelpButton placement="bar" />);
  const link = screen.getByRole("link", { name: "Help (opens in a new tab)" });
  expect(link).toHaveClass("app-help-bar-link");
  expect(link).not.toHaveClass("app-help-button");
});
