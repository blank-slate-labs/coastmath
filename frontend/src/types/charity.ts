// TypeScript interfaces matching backend CharityEntity schemas

export type CharityType = "qcd" | "daf" | "direct";
/** DAF/direct gifts: cash, or appreciated shares from the taxable brokerage source account. */
export type CharityFunding = "cash" | "appreciated_shares";

export interface CharityEntity {
  id: string;
  plan_id: string;
  name: string;
  entity_type: CharityType;
  annual_amount: number;
  start_milestone_id: string | null;
  end_milestone_id: string | null;
  source_account_id?: string | null;
  funding?: CharityFunding;
}

export interface CharityEntityCreate {
  name: string;
  entity_type: CharityType;
  annual_amount: number;
  start_milestone_id?: string | null;
  end_milestone_id?: string | null;
  source_account_id?: string | null;
  funding?: CharityFunding;
}

export interface CharityEntityUpdate {
  name?: string;
  entity_type?: CharityType;
  annual_amount?: number;
  start_milestone_id?: string | null;
  end_milestone_id?: string | null;
  source_account_id?: string | null;
  funding?: CharityFunding;
}
