// The Maid — Setup Wizard Logic Tests
// Pure functions for setup state transitions, feature flags, and download state.

import { describe, it, expect } from "vitest";
import {
  type FeatureFlags,
  type DownloadStatus,
  type WizardStep,
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

describe("Setup Wizard — setup_complete state transitions", () => {
  // Simulates the Rust settings state machine: setup_complete gates can_scan.
  // ponytail: pure logic — Rust side tested separately.
  interface SettingsState {
    first_run: boolean;
    setup_complete: boolean;
    sandbox_folders: string[];
    features: FeatureFlags;
  }

  function defaultState(): SettingsState {
    return {
      first_run: true,
      setup_complete: false,
      sandbox_folders: [],
      features: { pdf_ocr: false, face_clustering: false, general_files: false },
    };
  }

  function completeSetup(state: SettingsState, folders: string[], features: FeatureFlags): SettingsState {
    return {
      first_run: false,
      setup_complete: true,
      sandbox_folders: folders,
      features,
    };
  }

  function canScan(state: SettingsState): boolean {
    return state.setup_complete && state.sandbox_folders.length > 0;
  }

  it("default state — scan disabled", () => {
    expect(canScan(defaultState())).toBe(false);
  });

  it("setup_complete with folders — scan enabled", () => {
    const state = completeSetup(defaultState(), ["Desktop"], { pdf_ocr: false, face_clustering: false, general_files: true });
    expect(canScan(state)).toBe(true);
  });

  it("setup_complete without folders — scan disabled", () => {
    const state = completeSetup(defaultState(), [], { pdf_ocr: false, face_clustering: false, general_files: true });
    expect(canScan(state)).toBe(false);
  });

  it("setup incomplete but has folders — scan disabled", () => {
    const state = defaultState();
    state.sandbox_folders = ["Desktop"];
    expect(canScan(state)).toBe(false);
  });

  it("completeSetup clears first_run flag", () => {
    const state = completeSetup(defaultState(), ["Desktop"], { pdf_ocr: false, face_clustering: false, general_files: true });
    expect(state.first_run).toBe(false);
  });
});

describe("Setup Wizard — feature flag persistence", () => {
  // Verify buildSetupPayload roundtrips through JSON (simulates save/load)
  it("feature flags survive JSON roundtrip", () => {
    const features: FeatureFlags = { pdf_ocr: true, face_clustering: true, general_files: false };
    const payload = buildSetupPayload(["Desktop"], features);
    const json = JSON.stringify(payload);
    const parsed = JSON.parse(json);
    expect(parsed.pdf_ocr).toBe(true);
    expect(parsed.face_clustering).toBe(true);
    expect(parsed.general_files).toBe(false);
  });

  it("all-false feature flags persist correctly", () => {
    const features: FeatureFlags = { pdf_ocr: false, face_clustering: false, general_files: false };
    const payload = buildSetupPayload([], features);
    const json = JSON.stringify(payload);
    const parsed = JSON.parse(json);
    expect(parsed.pdf_ocr).toBe(false);
    expect(parsed.face_clustering).toBe(false);
    expect(parsed.general_files).toBe(false);
  });

  it("folder list persists through payload", () => {
    const folders = ["Desktop", "Downloads", "Documents", "Pictures"];
    const payload = buildSetupPayload(folders, { pdf_ocr: true, face_clustering: false, general_files: true });
    const json = JSON.stringify(payload);
    const parsed = JSON.parse(json);
    expect(parsed.folders).toEqual(folders);
  });
});

describe("Setup Wizard — folder selection validation", () => {
  it("rejects empty folder list", () => {
    const result = validateFolderSelection([]);
    expect(result.valid).toBe(false);
    expect(result.error).toBeDefined();
  });

  it("accepts single folder", () => {
    expect(validateFolderSelection(["Desktop"]).valid).toBe(true);
  });

  it("accepts multiple folders", () => {
    expect(validateFolderSelection(["Desktop", "Downloads", "Documents"]).valid).toBe(true);
  });

  it("error message mentions at least one folder", () => {
    const result = validateFolderSelection([]);
    expect(result.error).toContain("at least one");
  });
});

describe("Setup Wizard — wizard step type", () => {
  it("WizardStep type constrains to 1-4", () => {
    const step: WizardStep = 1;
    expect(step).toBe(1);
    expect(nextStep(step)).toBe(2);
    expect(prevStep(4)).toBe(3);
  });
});
