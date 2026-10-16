import { api } from "@/api/client";
import type { RealAsset, RealAssetCreate, RealAssetUpdate } from "@/types/plan";

export const listRealAssets = (planId: string): Promise<RealAsset[]> =>
  api.get(`/plans/${planId}/real-assets`).then((r) => r.data);

export const createRealAsset = (planId: string, data: RealAssetCreate): Promise<RealAsset> =>
  api.post(`/plans/${planId}/real-assets`, data).then((r) => r.data);

export const updateRealAsset = (
  planId: string,
  id: string,
  data: RealAssetUpdate,
): Promise<RealAsset> => api.put(`/plans/${planId}/real-assets/${id}`, data).then((r) => r.data);

export const deleteRealAsset = (planId: string, id: string): Promise<void> =>
  api.delete(`/plans/${planId}/real-assets/${id}`).then(() => undefined);
