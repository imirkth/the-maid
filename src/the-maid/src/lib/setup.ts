// The Maid — Setup Wizard pure logic
// Extracted from SetupWizard.tsx for testability and reuse.

export interface FeatureFlags {
  pdf_ocr: boolean;
  face_clustering: boolean;
  general_files: boolean;
}

export type DownloadState = "idle" | "downloading" | "done" | "skipped";

export interface DownloadStatus {
  state: DownloadState;
  progress: number; // 0-100
}

export interface SetupPayload {
  folders: string[];
  pdf_ocr: boolean;
  face_clustering: boolean;
  general_files: boolean;
}

export type WizardStep = 1 | 2 | 3 | 4;

export function allDownloadsDone(
  downloads: Record<string, DownloadStatus>,
  features: FeatureFlags,
): boolean {
  const required: { key: string; needed: boolean }[] = [
    { key: "text", needed: true },
    { key: "pdf", needed: features.pdf_ocr },
    { key: "face", needed: features.face_clustering },
  ];
  return required.every(({ key, needed }) => {
    if (!needed) {
      // Non-needed models may be skipped or done; idle is also acceptable
      // because the user never chose to download them.
      const state = downloads[key]?.state;
      return state === "skipped" || state === "done" || state === "idle";
    }
    return downloads[key]?.state === "done";
  });
}

export function validateFolderSelection(folders: string[]): { valid: boolean; error?: string } {
  if (folders.length === 0) {
    return { valid: false, error: "Select at least one folder" };
  }
  return { valid: true };
}

export function validateFeatureSelection(features: FeatureFlags): { valid: boolean; error?: string } {
  if (!features.general_files && !features.pdf_ocr && !features.face_clustering) {
    return { valid: false, error: "Select at least one feature" };
  }
  return { valid: true };
}

export function buildSetupPayload(
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

export function nextStep(current: WizardStep): WizardStep {
  return Math.min(current + 1, 4) as WizardStep;
}

export function prevStep(current: WizardStep): WizardStep {
  return Math.max(current - 1, 1) as WizardStep;
}

export function canAdvanceFromStep1(folders: string[]): boolean {
  return folders.length > 0;
}

export function canAdvanceFromStep2(features: FeatureFlags): boolean {
  return features.general_files || features.pdf_ocr || features.face_clustering;
}

export function canAdvanceFromStep3(
  downloads: Record<string, DownloadStatus>,
  features: FeatureFlags,
): boolean {
  return allDownloadsDone(downloads, features);
}
