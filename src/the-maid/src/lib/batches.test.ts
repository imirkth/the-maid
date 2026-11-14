import { describe, it, expect } from "vitest";
import { splitIntoBatches } from "./batches";

const f = (path: string) => ({ path });
const many = (dir: string, n: number) => Array.from({ length: n }, (_, i) => f(`/d/${dir}/f${i}.txt`));

describe("splitIntoBatches", () => {
  it("keeps a small scan in one batch", () => {
    const files = many("A", 10);
    expect(splitIntoBatches(files, "/d", 100)).toEqual([{ label: "", files }]);
  });

  it("covers every file exactly once and respects the size cap", () => {
    const files = [...many("Data/Pictures", 250), ...many("Data/programme", 120), ...many("Eva", 90),
      ...many("Sarah", 30), f("/d/loose.txt")];
    const batches = splitIntoBatches(files, "/d", 200);
    const seen = batches.flatMap((b) => b.files.map((x) => x.path));
    expect(seen.sort()).toEqual(files.map((x) => x.path).sort());
    expect(batches.every((b) => b.files.length <= 200)).toBe(true);
  });

  it("splits a too-big folder by its sub-folders and keeps folders whole", () => {
    const files = [...many("Data/Pictures", 150), ...many("Data/programme", 120), ...many("Eva", 40)];
    const batches = splitIntoBatches(files, "/d", 200);
    for (const dir of ["Data/Pictures", "Data/programme", "Eva"]) {
      const holding = batches.filter((b) => b.files.some((x) => x.path.includes(`/${dir}/`)));
      expect(holding).toHaveLength(1);
    }
    expect(batches.map((b) => b.label).join(" | ")).toContain("Data/Pictures");
  });
});
