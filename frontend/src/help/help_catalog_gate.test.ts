import { getArticleMeta } from "./help_catalog";

vi.hoisted(() => {
  vi.stubEnv("VITE_TRANSACTIONS_ENABLED", "false");
});

it("keeps the transactions article out of the public catalog until the feature ships", () => {
  expect(getArticleMeta("import-transactions")).toBeUndefined();
  expect(getArticleMeta("expenses")).toBeDefined();
});
