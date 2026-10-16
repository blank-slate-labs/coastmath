import { StrictMode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import PlaidOAuthReturn from "./plaid_oauth_return";
import { plannerPath } from "@/extensions";

const mocks = vi.hoisted(() => ({
  takePlaidSession: vi.fn(),
  resumePlaidConnection: vi.fn(),
  replace: vi.fn(),
}));
vi.mock("@/components/ledger/plaid_link", () => ({
  takePlaidSession: mocks.takePlaidSession,
  resumePlaidConnection: mocks.resumePlaidConnection,
}));

const SESSION = { linkToken: "link-1", connectionId: null, savedAt: 1 };
const original = window.location;

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/plaid/oauth?oauth_state_id=demo-state");
  Object.defineProperty(window, "location", {
    configurable: true,
    value: {
      ...original,
      href: "http://localhost/plaid/oauth?oauth_state_id=demo-state",
      replace: mocks.replace,
    },
  });
});
afterEach(() => {
  Object.defineProperty(window, "location", { configurable: true, value: original });
});

it("resumes Link with the redirect and returns to the planner", async () => {
  mocks.takePlaidSession.mockReturnValue(SESSION);
  mocks.resumePlaidConnection.mockResolvedValue({ id: "c1" });
  render(
    <StrictMode>
      <PlaidOAuthReturn />
    </StrictMode>,
  );
  expect(screen.getByRole("status")).toHaveTextContent("Finishing with Plaid");
  await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith(plannerPath()));
  // StrictMode's second effect run never resumes Link a second time.
  expect(mocks.takePlaidSession).toHaveBeenCalledTimes(1);
  expect(mocks.resumePlaidConnection).toHaveBeenCalledWith(
    SESSION,
    "http://localhost/plaid/oauth?oauth_state_id=demo-state",
  );
  expect(original.search).toBe("");
});

it("explains an expired session", async () => {
  mocks.takePlaidSession.mockReturnValue(null);
  render(<PlaidOAuthReturn />);
  expect(await screen.findByRole("alert")).toHaveTextContent("This bank sign-in expired.");
  expect(screen.getByRole("link", { name: "Return to CoastMath" })).toHaveAttribute(
    "href",
    plannerPath(),
  );
  expect(mocks.resumePlaidConnection).not.toHaveBeenCalled();
});

it("shows a failed exchange", async () => {
  mocks.takePlaidSession.mockReturnValue(SESSION);
  mocks.resumePlaidConnection.mockRejectedValue(
    new Error("Plaid could not complete this request."),
  );
  render(<PlaidOAuthReturn />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Plaid could not complete this request.",
  );
  expect(mocks.replace).not.toHaveBeenCalled();
});
