// The Maid — Advanced Approval Logic Tests (Slice 4B, ADR 0005)
import { describe, it, expect } from "vitest";
import {
  defaultFieldApprovals,
  toggleField,
  applyFieldApprovals,
  reassignBucket,
  validateEditedPath,
  effectivePath,
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

  it("accepts relative path (frontend can't fully validate)", () => {
    const result = validateEditedPath("Desktop/file.txt", ["Desktop"]);
    expect(result.valid).toBe(true);
  });
});