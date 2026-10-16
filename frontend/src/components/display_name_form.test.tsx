import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { DisplayNameForm } from "./display_name_form";
import { useAuthStore } from "@/stores/auth_store";
import type { User } from "@/types/plan";

const user = {
  id: "u",
  is_anonymous: false,
  email: "a@example.test",
  display_name: "Alex",
} as User;
const updateProfile = vi.fn();
beforeEach(() => {
  updateProfile.mockReset();
  useAuthStore.setState({ user, updateProfile });
});

it("saves a trimmed display name", async () => {
  updateProfile.mockImplementation(async (name: string) => {
    useAuthStore.setState({ user: { ...user, display_name: name } });
  });
  render(<DisplayNameForm user={user} />);
  const input = screen.getByLabelText("Your name");
  expect(input).toHaveValue("Alex");
  expect(screen.getByRole("button", { name: "Save name" })).toBeDisabled();
  fireEvent.change(input, { target: { value: "  Alex Doe " } });
  fireEvent.click(screen.getByRole("button", { name: "Save name" }));
  await waitFor(() => expect(updateProfile).toHaveBeenCalledWith("Alex Doe"));
  expect(await screen.findByRole("status")).toHaveTextContent("Name saved.");
  expect(input).toHaveValue("Alex Doe");
});

it("keeps the draft and shows the server's message when a save fails, and rejects a blank name", async () => {
  updateProfile.mockRejectedValueOnce(new Error("Enter a name"));
  render(<DisplayNameForm user={{ ...user, display_name: "Anonymous" }} />);
  const input = screen.getByLabelText("Your name");
  expect(input).toHaveValue("");
  fireEvent.change(input, { target: { value: "   " } });
  fireEvent.submit(input.closest("form")!);
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a name.");
  expect(input).toHaveAttribute("aria-describedby", screen.getByRole("alert").id);
  expect(updateProfile).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "Sam" } });
  fireEvent.click(screen.getByRole("button", { name: "Save name" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Enter a name");
  expect(input).toHaveValue("Sam");
  expect(screen.getByRole("button", { name: "Save name" })).toBeEnabled();
});
