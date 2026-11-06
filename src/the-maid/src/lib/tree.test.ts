import { describe, it, expect } from "vitest";
import { buildFolderTree, findNode, matchingIds, planMoveFolder, planRemove, planRename, validateName, type TreeCategory } from "./tree";

const file = (id: string, name = `${id}.pdf`) => ({ file_id: id, filename: name, path: `/x/${name}`, size_bytes: 1, rationale: "", confidence: 0.9, tags: [] });
const tree: TreeCategory[] = [
  { name: "To Sort", count: 1, children: [file("z")] },
  { name: "Photos", count: 3, children: [
    { name: "2024/Lisbon", files: [file("a"), file("b")] },
    { name: "2024/Xmas", files: [file("c")] },
    { name: "Old", files: [] },
  ]},
  { name: "Work", count: 2, children: [{ name: "Acme", files: [file("d")] }, { name: "Acme", files: [file("e")] }, file("f")] },
];

describe("buildFolderTree", () => {
  const nodes = buildFolderTree(tree);
  it("nests sub paths, counts files below, hides empty folders, puts holding folders last", () => {
    expect(nodes.map((n) => n.name)).toEqual(["Photos", "Work", "To Sort"]);
    const photos = nodes[0];
    expect(photos.count).toBe(3);
    expect(photos.children.map((c) => c.name)).toEqual(["2024"]);
    expect(photos.children[0].children.map((c) => c.sub)).toEqual(["2024/Lisbon", "2024/Xmas"]);
  });
  it("merges two entries with the same folder name", () => {
    expect(findNode(nodes, "Work::Acme")!.files.map((f) => f.file_id)).toEqual(["d", "e"]);
    expect(findNode(nodes, "Work::")!.files.map((f) => f.file_id)).toEqual(["f"]);
  });
});

describe("edit plans", () => {
  const nodes = buildFolderTree(tree);
  it("renames an intermediate folder by renaming every stored path under it", () => {
    const calls = planRename(findNode(nodes, "Photos::2024")!, "Year 2024", ["Photos", "Work"]);
    expect(calls.map((c) => [c.args.oldSubname, c.args.newSubname])).toEqual([
      ["2024/Lisbon", "Year 2024/Lisbon"], ["2024/Xmas", "Year 2024/Xmas"],
    ]);
  });
  it("renames a top folder, or merges it when the name already exists", () => {
    const work = findNode(nodes, "Work::")!;
    expect(planRename(work, "Jobs", ["Photos", "Work"])[0]).toEqual({ cmd: "edit_category", args: { oldName: "Work", newName: "Jobs", delete: false } });
    expect(planRename(work, "photos", ["Photos", "Work"])[0].cmd).toBe("merge_categories");
  });
  it("moves a folder with its subfolders into another folder", () => {
    const calls = planMoveFolder(findNode(nodes, "Photos::2024")!, findNode(nodes, "Work::Acme")!);
    expect(calls.map((c) => [c.args.targetCategory, c.args.targetSubcategory])).toEqual([
      ["Work", "Acme/2024/Lisbon"], ["Work", "Acme/2024/Xmas"],
    ]);
    expect(planMoveFolder(findNode(nodes, "Photos::")!, findNode(nodes, "Photos::2024/Xmas")!)).toEqual([]);
  });
  it("removing a subfolder moves its files up one level", () => {
    const [call] = planRemove(findNode(nodes, "Photos::2024/Xmas")!);
    expect(call.args).toEqual({ fileIds: ["c"], targetCategory: "Photos", targetSubcategory: "2024" });
  });
});

describe("helpers", () => {
  it("validates folder names", () => {
    expect(validateName("")).not.toBe("");
    expect(validateName("a/b")).not.toBe("");
    expect(validateName("Taxes 2024")).toBe("");
  });
  it("search keeps matching folders and their parents", () => {
    const ids = matchingIds(buildFolderTree(tree), "xmas")!;
    expect([...ids]).toEqual(["Photos::", "Photos::2024", "Photos::2024/Xmas"]);
  });
});
