import { apiErrorCode, spendingFeeds, spendingModels } from "./spending_models";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }));
vi.mock("./client", () => ({ api: mocks }));

beforeEach(() => {
  vi.clearAllMocks();
  for (const fn of [mocks.get, mocks.post, mocks.put, mocks.delete])
    fn.mockResolvedValue({ data: { ok: true } });
});

it("posts comparisons and applies to the plan's spending-model routes", async () => {
  const variant = { kind: "months" as const, months: ["2026-06"] };
  await expect(spendingModels.compare("p1", { variants: [variant] })).resolves.toEqual({
    ok: true,
  });
  expect(mocks.post).toHaveBeenCalledWith("/plans/p1/spending-models/compare", {
    variants: [variant],
  });
  await spendingModels.apply("p1", { variant, expected_fingerprint: "f" });
  expect(mocks.post).toHaveBeenCalledWith("/plans/p1/spending-models/apply", {
    variant,
    expected_fingerprint: "f",
  });
});

it("reads, sets and stops a plan's spending feed", async () => {
  await expect(spendingFeeds.get("p1")).resolves.toEqual({ ok: true });
  expect(mocks.get).toHaveBeenCalledWith("/ledger/spending-feeds/p1");
  await spendingFeeds.put("p1", { source_ids: ["a1"], basis: "months", months: ["2026-06"] });
  expect(mocks.put).toHaveBeenCalledWith("/ledger/spending-feeds/p1", {
    source_ids: ["a1"],
    basis: "months",
    months: ["2026-06"],
  });
  await expect(spendingFeeds.stop("p1")).resolves.toBeUndefined();
  expect(mocks.delete).toHaveBeenCalledWith("/ledger/spending-feeds/p1");
});

it("reads the error envelope's code", () => {
  expect(apiErrorCode({ response: { data: { error: { code: "CONFLICT" } } } })).toBe("CONFLICT");
  expect(apiErrorCode(new Error("network"))).toBeNull();
  expect(apiErrorCode(null)).toBeNull();
});
