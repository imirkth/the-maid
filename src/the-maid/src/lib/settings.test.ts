// The Maid — Settings logic tests
// Pure functions for folder validation, upgrade pricing, model status.

import { describe, it, expect } from "vitest";
import {
  isSystemPath,
  validateFolderName,
  folderExistsInList,
  calculateUpgradePrice,
  formatStorageUsed,
  downloadedCount,
  type ModelStatus,
} from "./settings";

describe("Settings — folder validation", () => {
  it("rejects empty folder name", () => {
    expect(validateFolderName("")).toEqual({ valid: false, error: "Folder name cannot be empty" });
    expect(validateFolderName("   ")).toEqual({ valid: false, error: "Folder name cannot be empty" });
  });

  it("rejects system paths", () => {
    expect(validateFolderName("/bin").valid).toBe(false);
    expect(validateFolderName("/usr/local").valid).toBe(false);
    expect(validateFolderName("/etc/passwd").valid).toBe(false);
    expect(validateFolderName("C:\\Windows\\System32").valid).toBe(false);
  });

  it("accepts normal folder names", () => {
    expect(validateFolderName("Desktop").valid).toBe(true);
    expect(validateFolderName("Downloads").valid).toBe(true);
    expect(validateFolderName("~/Documents/Projects").valid).toBe(true);
    expect(validateFolderName("/home/user/Custom").valid).toBe(true);
  });
});

describe("Settings — system path detection", () => {
  it("detects Linux system dirs", () => {
    expect(isSystemPath("/bin/bash")).toBe(true);
    expect(isSystemPath("/usr/bin/python3")).toBe(true);
    expect(isSystemPath("/var/log/syslog")).toBe(true);
    expect(isSystemPath("/root/.bashrc")).toBe(true);
  });

  it("detects Windows system dirs", () => {
    expect(isSystemPath("C:\\Windows\\System32")).toBe(true);
    expect(isSystemPath("C:\\Program Files\\app")).toBe(true);
    expect(isSystemPath("C:\\ProgramData\\config")).toBe(true);
  });

  it("allows user dirs", () => {
    expect(isSystemPath("/home/user/Desktop")).toBe(false);
    expect(isSystemPath("/tmp/test")).toBe(false);
    expect(isSystemPath("Desktop")).toBe(false);
    expect(isSystemPath("~/Pictures")).toBe(false);
  });
});

describe("Settings — folder exists in list", () => {
  it("returns true when folder is in list", () => {
    expect(folderExistsInList("Desktop", ["Desktop", "Downloads"])).toBe(true);
  });

  it("returns false when folder is not in list", () => {
    expect(folderExistsInList("Videos", ["Desktop", "Downloads"])).toBe(false);
  });

  it("returns false for empty list", () => {
    expect(folderExistsInList("Desktop", [])).toBe(false);
  });
});

describe("Settings — upgrade pricing (ADR 0007)", () => {
  it("calculates upgrade as price difference", () => {
    // User paid $15 for v1, v2 costs $20 → upgrade is $5
    expect(calculateUpgradePrice(15, 20)).toBe(5);
  });

  it("upgrade is free when new version costs same or less", () => {
    expect(calculateUpgradePrice(30, 30)).toBe(0);
    expect(calculateUpgradePrice(40, 30)).toBe(0);
  });

  it("upgrade is full price when original was $0", () => {
    expect(calculateUpgradePrice(0, 40)).toBe(40);
  });
});

describe("Settings — model status helpers", () => {
  const allDownloaded: ModelStatus[] = [
    { id: "text", name: "Text LLM", size_mb: 500, downloaded: true, path: "/a" },
    { id: "pdf", name: "PDF OCR", size_mb: 1000, downloaded: true, path: "/b" },
    { id: "face", name: "Face", size_mb: 100, downloaded: true, path: "/c" },
  ];

  const noneDownloaded: ModelStatus[] = [
    { id: "text", name: "Text LLM", size_mb: 500, downloaded: false, path: "" },
    { id: "pdf", name: "PDF OCR", size_mb: 1000, downloaded: false, path: "" },
    { id: "face", name: "Face", size_mb: 100, downloaded: false, path: "" },
  ];

  const someDownloaded: ModelStatus[] = [
    { id: "text", name: "Text LLM", size_mb: 500, downloaded: true, path: "/a" },
    { id: "pdf", name: "PDF OCR", size_mb: 1000, downloaded: false, path: "" },
    { id: "face", name: "Face", size_mb: 100, downloaded: true, path: "/c" },
  ];

  it("formatStorageUsed — sums downloaded models", () => {
    expect(formatStorageUsed(allDownloaded)).toBe("1.6 GB");
    expect(formatStorageUsed(noneDownloaded)).toBe("0 MB");
    expect(formatStorageUsed(someDownloaded)).toBe("600 MB");
  });

  it("downloadedCount — counts downloaded models", () => {
    expect(downloadedCount(allDownloaded)).toBe(3);
    expect(downloadedCount(noneDownloaded)).toBe(0);
    expect(downloadedCount(someDownloaded)).toBe(2);
  });

  it("formatStorageUsed — handles exactly 1024 MB", () => {
    const exactly1gb: ModelStatus[] = [
      { id: "x", name: "X", size_mb: 1024, downloaded: true, path: "/x" },
    ];
    expect(formatStorageUsed(exactly1gb)).toBe("1.0 GB");
  });
});