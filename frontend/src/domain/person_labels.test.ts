import { describe, expect, it } from "vitest";
import { ownerLabel, ownerPossessive, ownerSuffix } from "./person_labels";

describe("person labels", () => {
  it("maps owner values to labels and never returns a wire value", () => {
    expect(ownerLabel("self")).toBe("Primary person");
    expect(ownerLabel(null)).toBe("Primary person");
    expect(ownerLabel("spouse")).toBe("Partner");
    expect(ownerLabel("joint")).toBe("Joint");
    expect(ownerPossessive("spouse")).toBe("Partner's");
  });

  it("omits the primary person's suffix only on a single-person plan", () => {
    expect(ownerSuffix("self", false)).toBe("");
    expect(ownerSuffix("self", true)).toBe(" (Primary person)");
    expect(ownerSuffix("spouse", false)).toBe(" (Partner)");
    expect(ownerSuffix("joint", true)).toBe(" (Joint)");
  });
});
