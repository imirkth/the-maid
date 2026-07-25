// The Maid — Setup Wizard Logic Tests
// Pure functions for setup state transitions, feature flags, and download state.

import { describe, it, expect } from "vitest";
import {
  type FeatureFlags,
  type DownloadStatus,
  allDownloadsDone,
  validateFolderSelection,
  validateFeatureSelection,
  buildSetupPayload,
  nextStep,
  prevStep,
  canAdvanceFromStep1,
  canAdvanceFromStep2,
  canAdvanceFromStep3,
} from "./setup";

const idleDownloads: Record<string, DownloadStatus> = {
  text: { state: "idle", progress: 0 },
  pdf: { state: "idle", progress: 0 },
  face: { state: "idle", progress: 0 },
};

describe("Setup Wizard — folder selection", () => {
  it("validates at least one folder selected", () => {
    expect(validateFolderSelection([])).toEqual({ valid: false, error: "Select at least one folder" });
    expect(validateFolderSelection(["Desktop"]).valid).toBe(true);
    expect(validateFolderSelection(["Desktop", "Downloads"]).valid).toBe(true);
  });

  it("canAdvanceFromStep1 requires folders", () => {
    expect(canAdvanceFromStep1([])).toBe(false);
    expect(canAdvanceFromStep1(["Desktop"])).toBe(true);
  });
});

describe("Setup Wizard — feature selection", () => {
  it("validates at least one feature", () => {
    const none: FeatureFlags = { pdf_ocr: false, face_clustering: false, general_files: false };
    expect(validateFeatureSelection(none).valid).toBe(false);
  });

  it("general_files alone is valid", () => {
    const general: FeatureFlags = { pdf_ocr: false, face_clustering: false, general_files: true };
    expect(validateFeatureSelection(general).valid).toBe(true);
  });

  it("all features selected is valid", () => {
    const all: FeatureFlags = { pdf_ocr: true, face_clustering: true, general_files: true };
    expect(validateFeatureSelection(all).valid).toBe(true);
  });

  it("no features selected is invalid", () => {
    const none: FeatureFlags = { pdf_ocr: false, face_clustering: false, general_files: false };
    expect(validateFeatureSelection(none).valid).toBe(false);
  });

  it("canAdvanceFromStep2 requires at least one feature", () => {
    const none: FeatureFlags = { pdf_ocr: false, face_clustering: false, general_files: false };
    const general: FeatureFlags = { pdf_ocr: false, face_clustering: false, general_files: true };
    expect(canAdvanceFromStep2(none)).toBe(false);
    expect(canAdvanceFromStep2(general)).toBe(true);
  });
});

describe("Setup Wizard — download state", () => {
  it("allDownloadsDone — text only (general_files feature)", () => {
    const features: FeatureFlags = { pdf_ocr: false, face_clustering: false, general_files: true };
    const downloads = {
      ...idleDownloads,
      text: { state: "done", progress: 100 },
    };
    expect(allDownloadsDone(downloads, features)).toBe(true);
  });

  it("allDownloadsDone — false when required text model is not done", () => {
    const features: FeatureFlags = { pdf_ocr: false, face_clustering: false, general_files: true };
    const downloads = {
      ...idleDownloads,
    };
    expect(allDownloadsDone(downloads, features)).toBe(false);
  });

  it("allDownloadsDone — requires pdf when pdf_ocr selected", () => {
    const features: FeatureFlags = { pdf_ocr: true, face_clustering: false, general_files: true };
    const downloads = {
      ...idleDownloads,
      text: { state: "done", progress: 100 },
      pdf: { state: "downloading", progress: 50 },
    };
    expect(allDownloadsDone(downloads, features)).toBe(false);
  });

  it("allDownloadsDone — pdf skipped is ok when not selected", () => {
    const features: FeatureFlags = { pdf_ocr: false, face_clustering: false, general_files: true };
    const downloads = {
      ...idleDownloads,
      text: { state: "done", progress: 100 },
      pdf: { state: "skipped", progress: 0 },
    };
    expect(allDownloadsDone(downloads, features)).toBe(true);
  });

  it("allDownloadsDone — all features done", () => {
    const features: FeatureFlags = { pdf_ocr: true, face_clustering: true, general_files: true };
    const downloads = {
      text: { state: "done", progress: 100 },
      pdf: { state: "done", progress: 100 },
      face: { state: "done", progress: 100 },
    };
    expect(allDownloadsDone(downloads, features)).toBe(true);
  });

  it("allDownloadsDone is pure — does not mutate downloads", () => {
    const features: FeatureFlags = { pdf_ocr: false, face_clustering: false, general_files: true };
    const downloads = {
      text: { state: "done", progress: 100 },
      pdf: { state: "idle", progress: 0 },
      face: { state: "idle", progress: 0 },
    };
    const before = JSON.stringify(downloads);
    allDownloadsDone(downloads, features);
    expect(JSON.stringify(downloads)).toBe(before);
  });

  it("canAdvanceFromStep3 — false when download in progress", () => {
    const features: FeatureFlags = { pdf_ocr: true, face_clustering: false, general_files: true };
    const downloads = {
      text: { state: "done", progress: 100 },
      pdf: { state: "downloading", progress: 50 },
      face: { state: "idle", progress: 0 },
    };
    expect(canAdvanceFromStep3(downloads, features)).toBe(false);
  });

  it("canAdvanceFromStep3 — true when all required done", () => {
    const features: FeatureFlags = { pdf_ocr: false, face_clustering: false, general_files: true };
    const downloads = {
      text: { state: "done", progress: 100 },
      pdf: { state: "idle", progress: 0 },
      face: { state: "idle", progress: 0 },
    };
    expect(canAdvanceFromStep3(downloads, features)).toBe(true);
  });
});

describe("Setup Wizard — step navigation", () => {
  it("nextStep increments up to 4", () => {
    expect(nextStep(1)).toBe(2);
    expect(nextStep(2)).toBe(3);
    expect(nextStep(3)).toBe(4);
    expect(nextStep(4)).toBe(4);
  });

  it("prevStep decrements down to 1", () => {
    expect(prevStep(4)).toBe(3);
    expect(prevStep(3)).toBe(2);
    expect(prevStep(2)).toBe(1);
    expect(prevStep(1)).toBe(1);
  });
});

describe("Setup Wizard — payload building", () => {
  it("builds correct payload from folders and features", () => {
    const folders = ["Desktop", "Downloads"];
    const features: FeatureFlags = { pdf_ocr: true, face_clustering: false, general_files: true };
    const payload = buildSetupPayload(folders, features);
    expect(payload).toEqual({
      folders: ["Desktop", "Downloads"],
      pdf_ocr: true,
      face_clustering: false,
      general_files: true,
    });
  });

  it("builds payload with no optional features", () => {
    const folders = ["Pictures"];
    const features: FeatureFlags = { pdf_ocr: false, face_clustering: false, general_files: true };
    const payload = buildSetupPayload(folders, features);
    expect(payload.folders).toEqual(["Pictures"]);
    expect(payload.pdf_ocr).toBe(false);
    expect(payload.face_clustering).toBe(false);
    expect(payload.general_files).toBe(true);
  });
});
