import { create } from "zustand";

/**
 * One-shot hand-off from new-plan setup to the Income section: after Goals,
 * the Add income form opens once for that plan so the salary comes next.
 */
interface SetupFlowState {
  addIncomeFor: string | null;
  requestAddIncome: (planId: string) => void;
  /** True once for the requested plan, then cleared. */
  takeAddIncome: (planId: string) => boolean;
}

export const useSetupFlow = create<SetupFlowState>()((set, get) => ({
  addIncomeFor: null,
  requestAddIncome: (planId) => set({ addIncomeFor: planId }),
  takeAddIncome: (planId) => {
    if (get().addIncomeFor !== planId) return false;
    set({ addIncomeFor: null });
    return true;
  },
}));
