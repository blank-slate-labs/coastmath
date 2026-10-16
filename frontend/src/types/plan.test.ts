import { describe, expect, it } from "vitest";
import * as fs from "fs";
import * as path from "path";

// TypeScript merges repeated interface declarations silently, so a field added
// in a second `export interface X` block far from the first goes unnoticed.
describe("plan.ts wire-type mirror", () => {
  it("declares each exported interface and type exactly once", () => {
    const source = fs.readFileSync(path.resolve(__dirname, "./plan.ts"), "utf-8");
    const names = [...source.matchAll(/^export\s+(?:interface|type)\s+([A-Za-z_$][\w$]*)/gm)].map(
      (m) => m[1],
    );
    expect(names.length).toBeGreaterThan(100);
    const seen = new Set<string>();
    const duplicates = names.filter((name) => (seen.has(name) ? true : (seen.add(name), false)));
    expect(duplicates).toEqual([]);
  });
});
