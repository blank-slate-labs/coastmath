/**
 * A new expense's starting point: its name and essential or discretionary
 * share. Never saved. Debts, healthcare and charitable giving have their own
 * inputs, so none is offered. Keep native clients' lists in step with this one.
 */
export interface SpendingCategory {
  id: string;
  label: string;
  share: "essential" | "discretionary";
}

export const SPENDING_CATEGORIES: readonly SpendingCategory[] = [
  { id: "living", label: "Living expenses", share: "essential" },
  { id: "housing", label: "Housing", share: "essential" },
  { id: "kids", label: "Kids", share: "essential" },
  { id: "college", label: "College", share: "essential" },
  { id: "vehicles", label: "Vehicles", share: "essential" },
  { id: "insurance", label: "Insurance", share: "essential" },
  { id: "travel", label: "Travel", share: "discretionary" },
  { id: "hobbies", label: "Hobbies", share: "discretionary" },
  { id: "gifts", label: "Gifts", share: "discretionary" },
];

/** The label while no expense has it, otherwise the first free "Label 2", "Label 3" and so on. */
export function spendingCategoryName(label: string, existingNames: readonly string[]): string {
  const taken = new Set(existingNames);
  if (!taken.has(label)) return label;
  let number = 2;
  while (taken.has(`${label} ${number}`)) number += 1;
  return `${label} ${number}`;
}
