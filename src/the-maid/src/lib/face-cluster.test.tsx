// Tests for face cluster types and naming logic
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { FaceClusterInfo, RenameResult } from "../types/face-cluster";

// ─── Helpers (mirror the logic in FaceClusterView.tsx) ───

function isUnknownPerson(label: string): boolean {
  return label.startsWith("Unknown_Person_");
}

function getEditInitialValue(label: string): string {
  return isUnknownPerson(label) ? "" : label;
}

function buildRenameStatus(result: RenameResult): string {
  return `Renamed: ${result.tagged} tagged, ${result.skipped} skipped` +
    (result.errors.length ? `, ${result.errors.length} errors` : "");
}

function validateLabel(label: string): boolean {
  return label.trim().length > 0;
}

// ─── Mock invoke for integration-like tests ───

const mockInvoke = vi.fn();

async function loadClusters(): Promise<FaceClusterInfo[]> {
  return mockInvoke("get_face_clusters");
}

async function renameCluster(clusterId: number, newLabel: string): Promise<RenameResult> {
  return mockInvoke("rename_face_cluster", { clusterId, newLabel: newLabel });
}

// ─── Tests ───

describe("FaceCluster types", () => {
  it("FaceClusterInfo has required fields", () => {
    const cluster: FaceClusterInfo = {
      cluster_id: 0,
      cluster_label: "Unknown_Person_1",
      face_count: 3,
      representative_path: "/photos/face1.jpg",
      faces: [
        { file_id: "f1", file_path: "/photos/face1.jpg" },
        { file_id: "f2", file_path: "/photos/face2.jpg" },
      ],
    };
    expect(cluster.cluster_id).toBe(0);
    expect(cluster.cluster_label).toBe("Unknown_Person_1");
    expect(cluster.face_count).toBe(3);
    expect(cluster.faces.length).toBe(2);
  });

  it("RenameResult has required fields", () => {
    const result: RenameResult = {
      renamed: 3,
      tagged: 3,
      skipped: 0,
      errors: [],
      success: true,
    };
    expect(result.renamed).toBe(3);
    expect(result.tagged).toBe(3);
    expect(result.skipped).toBe(0);
    expect(result.errors.length).toBe(0);
    expect(result.success).toBe(true);
  });
});

describe("isUnknownPerson", () => {
  it("returns true for Unknown_Person_N labels", () => {
    expect(isUnknownPerson("Unknown_Person_1")).toBe(true);
    expect(isUnknownPerson("Unknown_Person_42")).toBe(true);
  });

  it("returns false for named clusters", () => {
    expect(isUnknownPerson("Sarah")).toBe(false);
    expect(isUnknownPerson("John Doe")).toBe(false);
  });

  it("returns false for empty string", () => {
    expect(isUnknownPerson("")).toBe(false);
  });
});

describe("getEditInitialValue", () => {
  it("returns empty string for Unknown_Person labels", () => {
    expect(getEditInitialValue("Unknown_Person_1")).toBe("");
    expect(getEditInitialValue("Unknown_Person_99")).toBe("");
  });

  it("returns the label for named clusters", () => {
    expect(getEditInitialValue("Sarah")).toBe("Sarah");
    expect(getEditInitialValue("John Doe")).toBe("John Doe");
  });
});

describe("validateLabel", () => {
  it("rejects empty string", () => {
    expect(validateLabel("")).toBe(false);
  });

  it("rejects whitespace-only string", () => {
    expect(validateLabel("   ")).toBe(false);
    expect(validateLabel("\t\n")).toBe(false);
  });

  it("accepts non-empty names", () => {
    expect(validateLabel("Sarah")).toBe(true);
    expect(validateLabel("John Doe")).toBe(true);
    expect(validateLabel("A")).toBe(true);
  });
});

describe("buildRenameStatus", () => {
  it("builds success message with no errors", () => {
    const result: RenameResult = { renamed: 3, tagged: 3, skipped: 0, errors: [] };
    const status = buildRenameStatus(result);
    expect(status).toBe("Renamed: 3 tagged, 0 skipped");
    expect(status).not.toContain("errors");
  });

  it("builds message with errors", () => {
    const result: RenameResult = {
      renamed: 5, tagged: 3, skipped: 2,
      errors: ["exiftool failed: /a.jpg", "File not found: /b.jpg"]
    };
    const status = buildRenameStatus(result);
    expect(status).toContain("3 tagged");
    expect(status).toContain("2 skipped");
    expect(status).toContain("2 errors");
  });

  it("handles zero tagged", () => {
    const result: RenameResult = { renamed: 3, tagged: 0, skipped: 3, errors: ["exiftool not installed"] };
    const status = buildRenameStatus(result);
    expect(status).toContain("0 tagged");
    expect(status).toContain("3 skipped");
    expect(status).toContain("1 errors");
  });
});

describe("loadClusters (invoke integration)", () => {
  beforeEach(() => {
    mockInvoke.mockReset();
  });

  it("calls get_face_clusters and returns data", async () => {
    const clusters: FaceClusterInfo[] = [
      { cluster_id: 0, cluster_label: "Unknown_Person_1", face_count: 3,
        representative_path: "/a.jpg", faces: [{ file_id: "f1", file_path: "/a.jpg" }] },
      { cluster_id: 1, cluster_label: "Sarah", face_count: 2,
        representative_path: "/b.jpg", faces: [{ file_id: "f2", file_path: "/b.jpg" }] },
    ];
    mockInvoke.mockResolvedValueOnce(clusters);
    const result = await loadClusters();
    expect(mockInvoke).toHaveBeenCalledWith("get_face_clusters");
    expect(result).toEqual(clusters);
    expect(result.length).toBe(2);
  });

  it("returns empty array when no clusters", async () => {
    mockInvoke.mockResolvedValueOnce([]);
    const result = await loadClusters();
    expect(result).toEqual([]);
  });

  it("propagates errors", async () => {
    mockInvoke.mockRejectedValueOnce(new Error("Backend down"));
    await expect(loadClusters()).rejects.toThrow("Backend down");
  });
});

describe("renameCluster (invoke integration)", () => {
  beforeEach(() => {
    mockInvoke.mockReset();
  });

  it("calls rename_face_cluster with correct args", async () => {
    const result: RenameResult = { renamed: 3, tagged: 3, skipped: 0, errors: [] };
    mockInvoke.mockResolvedValueOnce(result);
    await renameCluster(0, "Sarah");
    expect(mockInvoke).toHaveBeenCalledWith("rename_face_cluster", {
      clusterId: 0,
      newLabel: "Sarah",
    });
  });

  it("returns rename result", async () => {
    const result: RenameResult = { renamed: 5, tagged: 4, skipped: 1, errors: ["file missing"], success: true };
    mockInvoke.mockResolvedValueOnce(result);
    const actual = await renameCluster(2, "John");
    expect(actual.tagged).toBe(4);
    expect(actual.skipped).toBe(1);
    expect(actual.errors).toEqual(["file missing"]);
    expect(actual.success).toBe(true);
  });

  it("propagates errors", async () => {
    mockInvoke.mockRejectedValueOnce(new Error("Cluster not found"));
    await expect(renameCluster(999, "Ghost")).rejects.toThrow("Cluster not found");
  });
});

describe("Cluster UI state edge cases", () => {
  it("handles cluster with single face", () => {
    const cluster: FaceClusterInfo = {
      cluster_id: 0,
      cluster_label: "Unknown_Person_1",
      face_count: 1,
      representative_path: "/photo.jpg",
      faces: [{ file_id: "f1", file_path: "/photo.jpg" }],
    };
    expect(cluster.face_count).toBe(1);
    expect(isUnknownPerson(cluster.cluster_label)).toBe(true);
  });

  it("handles cluster with many faces", () => {
    const faces = Array.from({ length: 100 }, (_, i) => ({
      file_id: `f${i}`,
      file_path: `/photo${i}.jpg`,
    }));
    const cluster: FaceClusterInfo = {
      cluster_id: 5,
      cluster_label: "Large Group",
      face_count: 100,
      representative_path: "/photo0.jpg",
      faces,
    };
    expect(cluster.face_count).toBe(100);
    expect(isUnknownPerson(cluster.cluster_label)).toBe(false);
    expect(getEditInitialValue(cluster.cluster_label)).toBe("Large Group");
  });

  it("handles renaming from named to named", () => {
    const label = "Sarah";
    const newLabel = "Sara";
    expect(validateLabel(newLabel)).toBe(true);
    expect(isUnknownPerson(label)).toBe(false);
    expect(getEditInitialValue(label)).toBe("Sarah");
  });
});