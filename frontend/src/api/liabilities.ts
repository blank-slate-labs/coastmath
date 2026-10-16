import { api } from "@/api/client";

import type { Liability, LiabilityCreate, LiabilityUpdate } from "@/types/plan";

export interface AmortizationRow {
  year: number;
  principal_paid: number;
  interest_paid: number;
  remaining_balance: number;
  cumulative_interest: number;
}

export interface AmortizationResponse {
  schedule: AmortizationRow[];
}

export const listLiabilities = (planId: string): Promise<Liability[]> =>
  api.get(`/plans/${planId}/liabilities`).then((r) => r.data);

export const createLiability = (planId: string, data: LiabilityCreate): Promise<Liability> =>
  api.post(`/plans/${planId}/liabilities`, data).then((r) => r.data);

export const updateLiability = (
  planId: string,
  id: string,
  data: LiabilityUpdate,
): Promise<Liability> => api.put(`/plans/${planId}/liabilities/${id}`, data).then((r) => r.data);

export const deleteLiability = (planId: string, id: string): Promise<void> =>
  api.delete(`/plans/${planId}/liabilities/${id}`).then(() => undefined);

export const getAmortizationSchedule = (
  planId: string,
  liabilityId: string,
): Promise<AmortizationResponse> =>
  api.get(`/plans/${planId}/liabilities/${liabilityId}/amortization`).then((r) => r.data);
