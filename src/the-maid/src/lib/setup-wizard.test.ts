// The Maid — Setup Wizard Logic Tests
// Pure functions for setup state transitions, feature flags, and download state.

import { describe, it, expect } from "vitest";

// --- Pure logic extracted from SetupWizard for testing ---

interface FeatureFlags {
  pdf_ocr: boolean;
  face_clustering: boolean;
  general_files: boolean;
}

type DownloadState = "idle" | "downloading" | "done" | "skipped";

interface DownloadStatus {
  state: DownloadState;
  progress: number;
}

// Check if all required downloads are complete
function allDownloadsDone(
  downloads: Record<string, DownloadStatus>,
  features: FeatureFlags,
): boolean {
  const required: { key: string; needed: boolean }[] = [
    { key: "text", needed: true },
    { key: "pdf", needed: features.pdf_ocr },
    { key: "face", needed: features.face_clustering },
  ];
  return required.every(({ key, needed }) => {
    if (!needed) return downloads[key]?.state === "skipped" || downloads[key]?.state === "done" || true;
    return downloads[key]?.state === "done";
  });
}

// Validate folder selection — at least one must be selected
function validateFolderSelection(folders: string[]): { valid: boolean; error?: string } {
  if (folders.length === 0) {
    return { valid: false, error: "Select at least one folder" };
  }
  return { valid: true };
}

// Validate feature selection — general_files is the minimum
function validateFeatureSelection(features: FeatureFlags): { valid: boolean; error?: string } {
  if (!features.general_files && !features.pdf_ocr && !features.face_clustering) {
    return { valid: false, error: "Select at least one feature" };
  }
  return { valid: true };
}

// Build the setup payload sent to the backend
interface SetupPayload {
  folders: string[];
  pdf_ocr: boolean;
  face_clustering: boolean;
  general_files: boolean;
}

function buildSetupPayload(
  folders: string[],
  features: FeatureFlags,
): SetupPayload {
  return {
    folders,
    pdf_ocr: features.pdf_ocr,
    face_clustering: features.face_clustering,
    general_files: features.general_files,
  };
}

// Determine which step to show based on state
type WizardStep = 1 | 2 | 3 | 4;

function nextStep(current: WizardStep): WizardStep {
  return Math.min(current + 1, 4) as WizardStep;
}

function prevStep(current: WizardStep): WizardStep {
  return Math.max(current - 1, 1) as WizardStep;
}

// Can advance from step 1?
function canAdvanceFromStep1(folders: string[]): boolean {
  return folders.length > 0;
}

// Can advance from step 3 (downloads)?
function canAdvanceFromStep3(
  downloads: Record<string, DownloadStatus>,
  features: FeatureFlags,
): boolean {
  return allDownloadsDone(downloads, features);
}

// --- Tests ---

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
});

describe("Setup Wizard — download state", () => {
  const idleDownloads: Record<string, DownloadStatus> = {
    text: { state: "idle", progress: 0 },
    pdf: { state: "idle", progress: 0 },
    face: { state: "idle", progress: 0 },
  };

  it("allDownloadsDone — text only (general_files feature)", () => {
    const features: FeatureFlags = { pdf_ocr: false, face_clustering: false, general_files: true };
    const downloads = {
      ...idleDownloads,
      text: { state: "done", progress: 100 },
    };
    expect(allDownloadsDone(downloads, features)).toBe(true);
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