// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import TreeExplorer from "./TreeExplorer";
import type { TreeCategory } from "../lib/tree";

const mockInvoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (...a: unknown[]) => mockInvoke(...a) }));

const file = (id: string) => ({ file_id: id, filename: `${id}.pdf`, path: `/x/${id}.pdf`, size_bytes: 10, rationale: "", confidence: 0.9, tags: [] });
const tree: TreeCategory[] = [{ name: "Photos", count: 2, children: [{ name: "2024/Lisbon", files: [file("a")] }, { name: "2024/Xmas", files: [file("b")] }] }];

function setup() {
  const onTreeChange = vi.fn();
  render(<TreeExplorer tree={tree} approved={false} excluded={new Set()} onToggleExcluded={() => {}}
    selectedFiles={new Set()} onSelectFiles={() => {}} onTreeChange={onTreeChange} onError={() => {}} />);
  return { onTreeChange };
}

describe("TreeExplorer", () => {
  beforeEach(() => { mockInvoke.mockReset(); mockInvoke.mockResolvedValue({ tree }); Element.prototype.scrollIntoView = () => {}; });

  it("opens a folder and shows its subfolders on the right", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /^2024\s*2 files$/ }));
    expect(screen.getByRole("heading", { name: "2024" })).toBeDefined();
  });

  it("renames a nested folder inline with a double-click and Enter", async () => {
    const { onTreeChange } = setup();
    fireEvent.doubleClick(screen.getAllByText("2024")[0]);
    const input = screen.getByLabelText("Folder name") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Year 2024" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(onTreeChange).toHaveBeenCalled());
    const renames = mockInvoke.mock.calls.filter((c) => c[0] === "edit_subcategory").map((c) => c[1].newSubname);
    expect(renames).toEqual(["Year 2024/Lisbon", "Year 2024/Xmas"]);
    expect(mockInvoke).toHaveBeenCalledWith("record_tree_feedback", { feedback: { action: "rename", path: "Photos/2024", new_path: "Photos/Year 2024" } });
  });

  it("Escape cancels a rename without calling the backend", () => {
    setup();
    fireEvent.doubleClick(screen.getAllByText("Photos")[0]);
    fireEvent.keyDown(screen.getByLabelText("Folder name"), { key: "Escape" });
    expect(screen.queryByLabelText("Folder name")).toBeNull();
    expect(mockInvoke).not.toHaveBeenCalled();
  });
});
