// The Maid — Advanced Approval Logic Tests (Slice 4B, ADR 0005)
import { describe, it, expect } from "vitest";
import {
  defaultFieldApprovals,
  toggleField,
  applyFieldApprovals,
  reassignBucket,
  validateEditedPath,
  effectivePath,
  buildFinalProposals,
} from "../lib/approval";
import type { CleanupItem } from "../types/cleanup-plan";

function makeItem(overrides: Partial<CleanupItem> = {}): CleanupItem {
  return {
    file_id: "abc123ef",
    original_filename: "test.txt",
    current_path: "/home/user/Desktop/test.txt",
    proposed_action: "move",
    proposed_path: "/home/user/Documents/test.txt",
    proposed_tags: ["work", "important"],
    faces_detected: ["Unknown_Person_01"],
    rationale: "Moved to Documents",
    confidence: 0.85,
    ...overrides,
  };
}

describe("defaultFieldApprovals", () => {
  it("creates all-true approvals for all items", () => {
    const items = [makeItem({ file_id: "aaa11111" }), makeItem({ file_id: "bbb22222" })];
    const result = defaultFieldApprovals(items);
    expect(result["aaa11111"]).toEqual({ move: true, tags: true, faces: true });
    expect(result["bbb22222"]).toEqual({ move: true, tags: true, faces: true });
  });

  it("returns empty object for empty list", () => {
    expect(defaultFieldApprovals([])).toEqual({});
  });
});

describe("toggleField", () => {
  it("toggles move from true to false", () => {
    const state = { "abc123ef": { move: true, tags: true, faces: true } };
    const next = toggleField(state, "abc123ef", "move");
    expect(next["abc123ef"].move).toBe(false);
    expect(next["abc123ef"].tags).toBe(true);
  });

  it("toggles tags from false to true", () => {
    const state = { "abc123ef": { move: true, tags: false, faces: true } };
    const next = toggleField(state, "abc123ef", "tags");
    expect(next["abc123ef"].tags).toBe(true);
  });

  it("does not mutate the original state", () => {
    const state = { "abc123ef": { move: true, tags: true, faces: true } };
    toggleField(state, "abc123ef", "move");
    expect(state["abc123ef"].move).toBe(true);
  });

  it("creates default entry for unknown file_id", () => {
    const state: Record<string, { move: boolean; tags: boolean; faces: boolean }> = {};
    const next = toggleField(state, "new12345", "move");
    expect(next["new12345"].move).toBe(false);
  });
});

describe("applyFieldApprovals", () => {
  it("returns item unchanged when fields undefined", () => {
    const item = makeItem();
    const result = applyFieldApprovals(item, undefined);
    expect(result).toEqual(item);
  });

  it("clears tags when tags field is false", () => {
    const item = makeItem({ proposed_tags: ["work", "important"] });
    const result = applyFieldApprovals(item, { move: true, tags: false, faces: true });
    expect(result.proposed_tags).toEqual([]);
  });

  it("clears faces when faces field is false", () => {
    const item = makeItem({ faces_detected: ["Unknown_Person_01"] });
    const result = applyFieldApprovals(item, { move: true, tags: true, faces: false });
    expect(result.faces_detected).toEqual([]);
  });

  it("changes action to tag and keeps current_path when move is false", () => {
    const item = makeItem({
      proposed_action: "move",
      current_path: "/home/user/Desktop/test.txt",
      proposed_path: "/home/user/Documents/test.txt",
    });
    const result = applyFieldApprovals(item, { move: false, tags: true, faces: true });
    expect(result.proposed_action).toBe("tag");
    expect(result.proposed_path).toBe("/home/user/Desktop/test.txt");
  });

  it("keeps everything when all fields true", () => {
    const item = makeItem();
    const result = applyFieldApprovals(item, { move: true, tags: true, faces: true });
    expect(result.proposed_action).toBe("move");
    expect(result.proposed_tags).toEqual(["work", "important"]);
    expect(result.faces_detected).toEqual(["Unknown_Person_01"]);
  });

  // --- Slice 4B regression: move-off must discard user_edited_path ---
  it("clears user_edited_path when move is false so effectivePath falls back to current_path", () => {
    const item = makeItem({
      proposed_action: "move",
      current_path: "/home/user/Desktop/test.txt",
      proposed_path: "/home/user/Documents/test.txt",
      user_edited_path: "/home/user/Downloads/test.txt",
    });
    const result = applyFieldApprovals(item, { move: false, tags: true, faces: true });
    expect(result.user_edited_path).toBeUndefined();
    expect(effectivePath(result)).toBe("/home/user/Desktop/test.txt");
  });

  it("keeps user_edited_path when move is true", () => {
    const item = makeItem({
      user_edited_path: "/home/user/Downloads/test.txt",
    });
    const result = applyFieldApprovals(item, { move: true, tags: true, faces: true });
    expect(result.user_edited_path).toBe("/home/user/Downloads/test.txt");
    expect(effectivePath(result)).toBe("/home/user/Downloads/test.txt");
  });
});

describe("reassignBucket", () => {
  it("updates proposed_path to bucket path + filename", () => {
    const item = makeItem({ original_filename: "photo.jpg" });
    const bucket = { id: "1", name: "Photos", path: "/home/user/Pictures" };
    const result = reassignBucket(item, bucket);
    expect(result.proposed_path).toBe("/home/user/Pictures/photo.jpg");
    expect(result.user_edited_path).toBe("/home/user/Pictures/photo.jpg");
  });

  it("updates rationale with bucket name", () => {
    const item = makeItem({ rationale: "Image file" });
    const bucket = { id: "2", name: "Archive", path: "/home/user/Archive" };
    const result = reassignBucket(item, bucket);
    expect(result.rationale).toBe("Reassigned to Archive: Image file");
  });

  it("does not mutate the original item", () => {
    const item = makeItem({ original_filename: "doc.pdf" });
    const bucket = { id: "1", name: "Docs", path: "/home/user/Documents" };
    reassignBucket(item, bucket);
    expect(item.proposed_path).toBe("/home/user/Documents/test.txt");
  });

  // --- Slice 4B regression: reassigning implies a move ---
  it("changes tag action to move when reassigning to a bucket", () => {
    const item = makeItem({
      proposed_action: "tag",
      current_path: "/home/user/Desktop/unknown.xyz",
      proposed_path: "/home/user/Desktop/unknown.xyz",
    });
    const bucket = { id: "1", name: "Archive", path: "/home/user/Archive" };
    const result = reassignBucket(item, bucket);
    expect(result.proposed_action).toBe("move");
  });
});

describe("validateEditedPath", () => {
  it("rejects empty path", () => {
    const result = validateEditedPath("", ["Desktop"]);
    expect(result.valid).toBe(false);
    expect(result.error).toContain("empty");
  });

  it("rejects whitespace-only path", () => {
    const result = validateEditedPath("   ", ["Desktop"]);
    expect(result.valid).toBe(false);
  });

  it("rejects system paths (Linux)", () => {
    const result = validateEditedPath("/bin/bash", ["Desktop"]);
    expect(result.valid).toBe(false);
    expect(result.error).toContain("System directories");
  });

  it("rejects system paths (Windows)", () => {
    const result = validateEditedPath("C:\\Windows\\System32", ["Desktop"]);
    expect(result.valid).toBe(false);
    expect(result.error).toContain("System directories");
  });

  it("accepts paths within sandbox folders", () => {
    const result = validateEditedPath("/home/user/Desktop/file.txt", ["/home/user/Desktop", "/home/user/Downloads"]);
    expect(result.valid).toBe(true);
  });

  it("accepts paths within Downloads sandbox", () => {
    const result = validateEditedPath("/home/user/Downloads/photo.jpg", ["/home/user/Desktop", "/home/user/Downloads"]);
    expect(result.valid).toBe(true);
  });

  it("rejects absolute paths outside sandbox", () => {
    const result = validateEditedPath("/tmp/random/file.txt", ["Desktop"]);
    expect(result.valid).toBe(false);
    expect(result.error).toContain("outside the sandbox");
  });

  it("accepts any path when no sandbox folders set", () => {
    const result = validateEditedPath("/tmp/anything", []);
    expect(result.valid).toBe(true);
  });

  it("rejects Windows system path with ProgramData", () => {
    const result = validateEditedPath("C:\\ProgramData\\config", ["Desktop"]);
    expect(result.valid).toBe(false);
  });

  it("accepts relative path under home sandbox", () => {
    const result = validateEditedPath("Desktop/file.txt", ["Desktop"]);
    expect(result.valid).toBe(true);
  });

  // --- Slice 4B regression: false-positive system prefix ---
  it("does not reject path that merely starts with a system dir name", () => {
    const result = validateEditedPath("/bingo/file.txt", ["/home/user/Desktop"]);
    expect(result.valid).toBe(false);
    expect(result.error).not.toContain("System directories");
    expect(result.error).toContain("outside the sandbox");
  });

  it("does not reject path that merely starts with /usr prefix", () => {
    const result = validateEditedPath("/usrfake/evil.txt", ["/home/user/Desktop"]);
    expect(result.valid).toBe(false);
    expect(result.error).not.toContain("System directories");
    expect(result.error).toContain("outside the sandbox");
  });

  // --- Slice 4B regression: relative sandbox must be under home ---
  it("rejects relative sandbox name appearing as non-home component", () => {
    const result = validateEditedPath("/tmp/Desktop/file.txt", ["Desktop"]);
    expect(result.valid).toBe(false);
    expect(result.error).toContain("outside the sandbox");
  });

  it("rejects relative path escaping via ..", () => {
    const result = validateEditedPath("Desktop/../Documents/file.txt", ["Desktop"], "/home/user");
    expect(result.valid).toBe(false);
    expect(result.error).toContain("outside the sandbox");
  });

  it("resolves ~ to home", () => {
    const result = validateEditedPath("~/Desktop/file.txt", ["Desktop"], "/home/user");
    expect(result.valid).toBe(true);
  });
});

describe("buildFinalProposals", () => {
  it("returns only approved items", () => {
    const a = makeItem({ file_id: "aaa11111" });
    const b = makeItem({ file_id: "bbb22222" });
    const result = buildFinalProposals([a, b], new Set(["aaa11111"]), {}, false);
    expect(result).toHaveLength(1);
    expect(result[0].file_id).toBe("aaa11111");
  });

  it("ignores stored field approvals when not in advanced mode", () => {
    const item = makeItem({
      file_id: "aaa11111",
      user_edited_path: "/home/user/Downloads/test.txt",
    });
    const fields = { "aaa11111": { move: false, tags: true, faces: true } };
    const result = buildFinalProposals([item], new Set(["aaa11111"]), fields, false);
    expect(result[0].proposed_action).toBe("move");
    expect(effectivePath(result[0])).toBe("/home/user/Downloads/test.txt");
  });

  it("applies stored field approvals when in advanced mode", () => {
    const item = makeItem({
      file_id: "aaa11111",
      current_path: "/home/user/Desktop/test.txt",
      proposed_path: "/home/user/Documents/test.txt",
      user_edited_path: "/home/user/Downloads/test.txt",
    });
    const fields = { "aaa11111": { move: false, tags: true, faces: true } };
    const result = buildFinalProposals([item], new Set(["aaa11111"]), fields, true);
    expect(result[0].proposed_action).toBe("tag");
    expect(effectivePath(result[0])).toBe("/home/user/Desktop/test.txt");
  });
});
