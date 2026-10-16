import { useEffect } from "react";
import { useSaveStore } from "@/stores/save_store";
import { usePlanStore } from "@/stores/plan_store";
import { confirmDiscard } from "@/components/confirm_dialog";

/** Ask before the page unloads while `active` (a save in flight or a failed draft). */
export function useUnloadWarning(active: boolean) {
  useEffect(() => {
    if (!active) return;
    const preventUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", preventUnload);
    return () => window.removeEventListener("beforeunload", preventUnload);
  }, [active]);
}

/** Keep a failed form mounted unless the user explicitly discards its draft. */
export function useFailedSaveGuard(
  key: string,
  saving: boolean,
  error: string | null,
  close: () => void,
) {
  useUnloadWarning(saving || Boolean(error));
  return (options?: { confirmed?: boolean }) => {
    if (saving) return;
    const discard = () => {
      // Do not turn an uncertain write into a success when its draft is closed.
      useSaveStore.getState().discardRejected(key);
      close();
    };
    if (!error || options?.confirmed) {
      discard();
      return;
    }
    void confirmDiscard(
      "If the last save could not be confirmed, check saved values before retrying.",
    ).then((confirmed) => {
      if (!confirmed) return;
      const store = useSaveStore.getState();
      if (store.failures[key] && !store.failures[key].rejected) {
        // An unconfirmed write may have landed. The user was warned and dropped the draft:
        // reload what the server holds and stop describing a draft that is gone.
        store.acknowledge(key);
        const planId = usePlanStore.getState().plan?.id;
        if (planId) void usePlanStore.getState().loadPlan(planId);
      }
      discard();
    });
  };
}
