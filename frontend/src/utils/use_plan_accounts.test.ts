import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePlanStore } from "@/stores/plan_store";
import { makeAdapter } from "@/test_support/adapter_stub";
import { deferred } from "@/test_support/deferred";
import type { Account } from "@/types/plan";
import { usePlanAccounts } from "./use_plan_accounts";

const account = (id: string) => ({ id, name: `Account ${id}` }) as Account;

describe("usePlanAccounts", () => {
  beforeEach(() => {
    usePlanStore.setState({ accountsRevision: 0 });
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads the accounts of a plan", async () => {
    const adapter = makeAdapter({ listAccounts: vi.fn().mockResolvedValue([account("a")]) });
    const { result } = renderHook(() => usePlanAccounts(adapter, "p1"));
    expect(result.current).toEqual({ accounts: [], status: "loading" });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.accounts).toEqual([account("a")]);
    expect(adapter.listAccounts).toHaveBeenCalledWith("p1");
  });

  it("starts empty for a new plan and ignores the earlier plan's late reply", async () => {
    const first = deferred<Account[]>();
    const second = deferred<Account[]>();
    const listAccounts = vi
      .fn()
      .mockResolvedValueOnce([account("a")])
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const adapter = makeAdapter({ listAccounts });
    const { result, rerender } = renderHook(({ planId }) => usePlanAccounts(adapter, planId), {
      initialProps: { planId: "p1" },
    });
    await waitFor(() => expect(result.current.accounts).toEqual([account("a")]));

    rerender({ planId: "p2" });
    expect(result.current).toEqual({ accounts: [], status: "loading" });
    rerender({ planId: "p3" });
    await act(async () => second.resolve([account("c")]));
    expect(result.current).toEqual({ accounts: [account("c")], status: "ready" });
    await act(async () => first.resolve([account("b")]));
    expect(result.current).toEqual({ accounts: [account("c")], status: "ready" });
  });

  it("reads again when the accounts revision changes", async () => {
    const listAccounts = vi
      .fn()
      .mockResolvedValueOnce([account("a")])
      .mockResolvedValueOnce([account("a"), account("b")]);
    const adapter = makeAdapter({ listAccounts });
    const { result } = renderHook(() => usePlanAccounts(adapter, "p1"));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    act(() => usePlanStore.setState((s) => ({ accountsRevision: s.accountsRevision + 1 })));
    // The plan's list stays in place while it is read again.
    expect(result.current).toEqual({ accounts: [account("a")], status: "loading" });
    await waitFor(() => expect(result.current.accounts).toHaveLength(2));
    expect(result.current.status).toBe("ready");
    expect(listAccounts).toHaveBeenCalledTimes(2);
  });

  it("does not set state after unmount", async () => {
    const pending = deferred<Account[]>();
    const adapter = makeAdapter({ listAccounts: vi.fn().mockReturnValue(pending.promise) });
    const consoleError = vi.spyOn(console, "error");
    const { result, unmount } = renderHook(() => usePlanAccounts(adapter, "p1"));
    unmount();
    await act(async () => pending.resolve([account("a")]));
    expect(result.current).toEqual({ accounts: [], status: "loading" });
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("reports a failed read and keeps the previous list", async () => {
    const listAccounts = vi
      .fn()
      .mockResolvedValueOnce([account("a")])
      .mockRejectedValueOnce(new Error("offline"));
    const adapter = makeAdapter({ listAccounts });
    const { result } = renderHook(() => usePlanAccounts(adapter, "p1"));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    act(() => usePlanStore.setState((s) => ({ accountsRevision: s.accountsRevision + 1 })));
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.accounts).toEqual([account("a")]);
  });

  it("waits until enabled and reads again on a new refresh key", async () => {
    const listAccounts = vi.fn().mockResolvedValue([account("a")]);
    const adapter = makeAdapter({ listAccounts });
    const { result, rerender } = renderHook(
      ({ enabled, refreshKey }) => usePlanAccounts(adapter, "p1", { enabled, refreshKey }),
      { initialProps: { enabled: false, refreshKey: 0 } },
    );
    expect(listAccounts).not.toHaveBeenCalled();

    rerender({ enabled: true, refreshKey: 0 });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    rerender({ enabled: true, refreshKey: 1 });
    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(listAccounts).toHaveBeenCalledTimes(2);
  });
});
