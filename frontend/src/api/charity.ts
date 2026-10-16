import { api } from "@/api/client";
import type { CharityEntity, CharityEntityCreate, CharityEntityUpdate } from "@/types/charity";

export const listCharities = (planId: string): Promise<CharityEntity[]> =>
  api.get(`/plans/${planId}/charities`).then((r) => r.data);

export const createCharity = (planId: string, data: CharityEntityCreate): Promise<CharityEntity> =>
  api.post(`/plans/${planId}/charities`, data).then((r) => r.data);

export const updateCharity = (
  planId: string,
  id: string,
  data: CharityEntityUpdate,
): Promise<CharityEntity> =>
  api.patch(`/plans/${planId}/charities/${id}`, data).then((r) => r.data);

export const deleteCharity = (planId: string, id: string): Promise<void> =>
  api.delete(`/plans/${planId}/charities/${id}`).then(() => undefined);
