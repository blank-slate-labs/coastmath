import { expect, it, vi } from "vitest";
import { api } from "./client";
import { updateCharity } from "./charity";

it("updates a giving entry using the server's PATCH contract", async () => {
  const patch = vi.spyOn(api, "patch").mockResolvedValue({ data: { name: "Corrected" } });
  try {
    expect(await updateCharity("p", "c", { name: "Corrected" })).toEqual({ name: "Corrected" });
    expect(patch).toHaveBeenCalledWith("/plans/p/charities/c", { name: "Corrected" });
  } finally {
    patch.mockRestore();
  }
});
