import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useToastStore } from "./toast_store";

describe("useToastStore", () => {
  beforeEach(() => {
    useToastStore.setState({ toasts: [] });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("gives each toast its own id", () => {
    useToastStore.getState().addToast("Saved", "success");
    useToastStore.getState().addToast("Saved", "success");
    const [first, second] = useToastStore.getState().toasts;
    expect(typeof first.id).toBe("string");
    expect(first.id).not.toBe(second.id);
  });

  it("works without crypto.randomUUID, as on a plain-HTTP host", () => {
    vi.stubGlobal("crypto", { ...globalThis.crypto, randomUUID: undefined });
    expect(() => useToastStore.getState().addToast("Saved", "info")).not.toThrow();
    expect(useToastStore.getState().toasts).toEqual([
      expect.objectContaining({ message: "Saved", type: "info" }),
    ]);
  });

  it("removes a toast after its timeout", () => {
    vi.useFakeTimers();
    useToastStore.getState().addToast("Could not save", "error");
    vi.advanceTimersByTime(2999);
    expect(useToastStore.getState().toasts).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(useToastStore.getState().toasts).toEqual([]);
  });

  it("removes a toast by id", () => {
    useToastStore.getState().addToast("Saved", "success");
    const [toast] = useToastStore.getState().toasts;
    useToastStore.getState().removeToast(toast.id);
    expect(useToastStore.getState().toasts).toEqual([]);
  });
});
