// The Maid — Approval Logic Tests (ADR 0005)
import { describe, it, expect } from "vitest";
import {
  groupByAction,
  toggleApproval,
  approveGroup,
  rejectGroup,
  approveAll,
  rejectAll,
  getApprovedItems,
  effectivePath,
  confidenceLabel,
} from "../lib/approval";
import type { CleanupItem, ProposedAction } from "../types/cleanup-plan";

function makeItem(overrides: Partial<CleanupItem> = {}): CleanupItem {
  return {
    file_id: "abc123ef",
    original_filename: "test.txt",
    current_path: "/home/user/Desktop/test.txt",
    proposed_action: "move" as ProposedAction,
    proposed_path: "/home/user/Documents/test.txt",
    proposed_tags: ["work"],
    faces_detected: [],
    rationale: "Moved to Documents",
    confidence: 0.85,
    ...overrides,
  };
}

const items: CleanupItem[] = [
  makeItem({ file_id: "aaa11111", proposed_action: "move", proposed_path: "/home/user/Pictures/a.jpg" }),
  makeItem({ file_id: "bbb22222", proposed_action: "move", proposed_path: "/home/user/Pictures/b.jpg" }),
  makeItem({ file_id: "ccc33333", proposed_action: "tag", proposed_path: "/home/user/Desktop/c.jpg" }),
  makeItem({ file_id: "ddd44444", proposed_action: "delete", proposed_path: "/home/user/Desktop/d.tmp" }),
];

describe("groupByAction", () => {
  it("groups items by proposed_action", () => {
    const grouped = groupByAction(items);
    expect(grouped.move).toHaveLength(2);
    expect(grouped.tag).toHaveLength(1);
    expect(grouped.delete).toHaveLength(1);
  });

  it("returns empty object for empty list", () => {
    expect(groupByAction([])).toEqual({});
  });
});

describe("toggleApproval", () => {
  it("adds an unapproved item", () => {
    const approved = new Set<string>();
    const next = toggleApproval(approved, "aaa11111");
    expect(next.has("aaa11111")).toBe(true);
  });

  it("removes an approved item", () => {
    const approved = new Set(["aaa11111"]);
    const next = toggleApproval(approved, "aaa11111");
    expect(next.has("aaa11111")).toBe(false);
  });

  it("does not mutate the original set", () => {
    const approved = new Set<string>();
    toggleApproval(approved, "aaa11111");
    expect(approved.size).toBe(0);
  });
});

describe("approveGroup", () => {
  it("approves all items in a group", () => {
    const moveItems = items.filter((i) => i.proposed_action === "move");
    const approved = approveGroup(new Set(), moveItems);
    expect(approved.has("aaa11111")).toBe(true);
    expect(approved.has("bbb22222")).toBe(true);
    expect(approved.has("ccc33333")).toBe(false);
  });

  it("preserves existing approvals", () => {
    const approved = new Set(["ccc33333"]);
    const moveItems = items.filter((i) => i.proposed_action === "move");
    const next = approveGroup(approved, moveItems);
    expect(next.has("ccc33333")).toBe(true);
    expect(next.has("aaa11111")).toBe(true);
  });
});

describe("rejectGroup", () => {
  it("rejects all items in a group", () => {
    const approved = new Set(["aaa11111", "bbb22222", "ccc33333"]);
    const moveItems = items.filter((i) => i.proposed_action === "move");
    const next = rejectGroup(approved, moveItems);
    expect(next.has("aaa11111")).toBe(false);
    expect(next.has("bbb22222")).toBe(false);
    expect(next.has("ccc33333")).toBe(true); // untouched
  });
});

describe("approveAll / rejectAll", () => {
  it("approves all items", () => {
    const approved = approveAll(items);
    expect(approved.size).toBe(4);
  });

  it("rejects all items", () => {
    const approved = new Set(["aaa11111"]);
    const next = rejectAll();
    expect(next.size).toBe(0);
  });
});

describe("getApprovedItems", () => {
  it("filters to approved items only", () => {
    const approved = new Set(["aaa11111", "ccc33333"]);
    const result = getApprovedItems(items, approved);
    expect(result).toHaveLength(2);
    expect(result[0].file_id).toBe("aaa11111");
    expect(result[1].file_id).toBe("ccc33333");
  });

  it("returns empty for no approvals", () => {
    expect(getApprovedItems(items, new Set())).toEqual([]);
  });
});

describe("effectivePath", () => {
  it("returns proposed_path when no edit", () => {
    const item = makeItem({ proposed_path: "/original/path" });
    expect(effectivePath(item)).toBe("/original/path");
  });

  it("returns user_edited_path when set", () => {
    const item = makeItem({ proposed_path: "/original/path", user_edited_path: "/edited/path" });
    expect(effectivePath(item)).toBe("/edited/path");
  });
});

describe("confidenceLabel", () => {
  it("returns High for >= 0.8", () => {
    expect(confidenceLabel(0.8)).toBe("High");
    expect(confidenceLabel(0.95)).toBe("High");
  });

  it("returns Medium for 0.5-0.79", () => {
    expect(confidenceLabel(0.5)).toBe("Medium");
    expect(confidenceLabel(0.7)).toBe("Medium");
  });

  it("returns Low for >0 and <0.5", () => {
    expect(confidenceLabel(0.3)).toBe("Low");
    expect(confidenceLabel(0.1)).toBe("Low");
  });

  it("returns — for 0", () => {
    expect(confidenceLabel(0)).toBe("—");
  });
});