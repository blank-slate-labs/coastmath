import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useSaveStore } from "@/stores/save_store";
import { usePlanStore } from "@/stores/plan_store";
import { useFailedSaveGuard } from "./use_failed_save_guard";
import { makePlan } from "@/test_support/plan_builder";

const confirmDiscard = vi.hoisted(() => vi.fn<(message?: string) => Promise<boolean>>());
vi.mock("@/components/confirm_dialog", () => ({ confirmDiscard }));

const key = "put /plans/p/expenses/e";
const loadPlan = vi.fn().mockResolvedValue(undefined);
beforeEach(() => {
  useSaveStore.setState(useSaveStore.getInitialState());
  usePlanStore.setState({ plan: makePlan({ id: "p" }), loadPlan });
  loadPlan.mockClear();
  confirmDiscard.mockReset().mockResolvedValue(true);
});

function fail(rejected: boolean) {
  const store = useSaveStore.getState();
  store.finish(key, false, store.begin(key), {
    message: "Save expense could not be confirmed.",
    rejected,
  });
}

it("drops an unconfirmed save's message and reloads saved values once its draft is discarded", async () => {
  act(() => fail(false));
  const close = vi.fn();
  const { result } = renderHook(() =>
    useFailedSaveGuard(key, false, "Save expense could not be confirmed.", close),
  );
  await act(async () => {
    result.current();
  });
  expect(confirmDiscard).toHaveBeenCalled();
  expect(close).toHaveBeenCalled();
  expect(useSaveStore.getState().failed).toEqual([]);
  expect(loadPlan).toHaveBeenCalledWith("p");
});

it("keeps the unconfirmed save's message when the draft is kept", async () => {
  confirmDiscard.mockResolvedValue(false);
  act(() => fail(false));
  const close = vi.fn();
  const { result } = renderHook(() =>
    useFailedSaveGuard(key, false, "Save expense could not be confirmed.", close),
  );
  await act(async () => {
    result.current();
  });
  expect(close).not.toHaveBeenCalled();
  expect(useSaveStore.getState().failed).toEqual([key]);
});

it("discards a rejected save without reloading", async () => {
  act(() => fail(true));
  const { result } = renderHook(() =>
    useFailedSaveGuard(key, false, "Save expense was not saved.", vi.fn()),
  );
  await act(async () => {
    result.current();
  });
  expect(useSaveStore.getState().failed).toEqual([]);
  expect(loadPlan).not.toHaveBeenCalled();
});
