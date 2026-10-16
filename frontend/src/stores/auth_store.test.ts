import { beforeEach, expect, it, vi } from "vitest";
import { AxiosError } from "axios";
import type { User } from "@/types/plan";

const api = vi.hoisted(() => ({
  getMe: vi.fn(),
  startSession: vi.fn(),
  logout: vi.fn(),
  deleteCurrentUser: vi.fn(),
  updateMe: vi.fn(),
}));
vi.mock("@/api/client", () => api);
// The planner on its own, without sign-in providers.
vi.mock("@extensions/active", () => ({ default: {} }));
beforeEach(() => {
  vi.resetModules();
  vi.resetAllMocks();
  api.getMe.mockRejectedValue(new Error("offline"));
});

const signedOut = () => {
  const error = new AxiosError("expired");
  error.response = { status: 401 } as typeof error.response;
  return error;
};

it("shows a recoverable startup error on a network failure", async () => {
  const { useAuthStore } = await import("./auth_store");
  await useAuthStore.getState().ensureSession();
  expect(useAuthStore.getState().error).toContain("Could not open");
  expect(api.startSession).not.toHaveBeenCalled();
  api.getMe.mockResolvedValueOnce({ id: "local" } as User);
  await useAuthStore.getState().ensureSession();
  expect(useAuthStore.getState()).toMatchObject({
    error: null,
    isAuthenticated: true,
    user: { id: "local" },
  });
});

it("starts one anonymous session for a new browser", async () => {
  const { useAuthStore } = await import("./auth_store");
  api.getMe.mockRejectedValue(signedOut());
  api.startSession.mockResolvedValue({ id: "anonymous", is_anonymous: true } as User);
  await Promise.all(Array.from({ length: 4 }, () => useAuthStore.getState().ensureSession()));
  expect(api.getMe).toHaveBeenCalledOnce();
  expect(api.startSession).toHaveBeenCalledOnce();
  expect(useAuthStore.getState()).toMatchObject({
    user: { id: "anonymous" },
    isAuthenticated: true,
    isLoading: false,
  });
  await useAuthStore.getState().ensureSession();
  expect(api.getMe).toHaveBeenCalledOnce();
});

it("reports a session that cannot start", async () => {
  const { useAuthStore } = await import("./auth_store");
  api.getMe.mockRejectedValue(signedOut());
  api.startSession.mockRejectedValue(new Error("offline"));
  await useAuthStore.getState().ensureSession();
  expect(useAuthStore.getState()).toMatchObject({ user: null, isLoading: false });
  expect(useAuthStore.getState().error).toContain("Could not open");
});

it("signs out and deletes through the server only, then reloads the planner", async () => {
  const { useAuthStore } = await import("./auth_store");
  const assign = vi.fn();
  vi.stubGlobal("location", { ...window.location, assign });
  try {
    useAuthStore.setState({ user: { id: "u" } as User, isAuthenticated: true });
    await useAuthStore.getState().logout();
    expect(api.logout).toHaveBeenCalledOnce();
    expect(assign).toHaveBeenLastCalledWith("/");
    useAuthStore.setState({ user: { id: "u" } as User, isAuthenticated: true });
    api.deleteCurrentUser
      .mockRejectedValueOnce(new Error("disconnect failed"))
      .mockResolvedValue(undefined);
    api.getMe.mockResolvedValue({ id: "u" } as User);
    await expect(useAuthStore.getState().deleteAccount()).rejects.toThrow("disconnect failed");
    expect(useAuthStore.getState().user?.id).toBe("u");
    await useAuthStore.getState().deleteAccount();
    expect(useAuthStore.getState()).toMatchObject({ user: null, isAuthenticated: false });
    expect(assign).toHaveBeenLastCalledWith("/");
  } finally {
    vi.unstubAllGlobals();
  }
});
