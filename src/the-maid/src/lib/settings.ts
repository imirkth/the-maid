// The Maid — Settings pure logic
// Extracted for testability and reuse from SettingsPanel.tsx.

export interface Settings {
  sandbox_folders: string[];
  first_run: boolean;
  buckets: { id: string; name: string; path: string }[];
  features: { pdf_ocr: boolean; face_clustering: boolean; general_files: boolean };
  setup_complete: boolean;
  lightning_node_url?: string;
}

export interface ModelStatus {
  id: string;
  name: string;
  size_mb: number;
  downloaded: boolean;
  path: string;
}

export interface UpdateInfo {
  current_version: string;
  latest_version: string;
  update_available: boolean;
  release_notes: string | null;
  upgrade_price: number | null;
}

// ponytail: system dirs mirror Rust SYSTEM_DIRS — keep in sync
const SYSTEM_DIRS = [
  "/bin", "/sbin", "/usr", "/etc", "/var", "/opt", "/lib", "/lib64",
  "/boot", "/dev", "/proc", "/sys", "/run", "/srv", "/root",
  "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)", "C:\\ProgramData",
];

export function isSystemPath(path: string): boolean {
  const normalized = path.replace(/\\/g, "/");
  return SYSTEM_DIRS.some((d) => {
    const dir = d.replace(/\\/g, "/");
    // Must match full component: either exact, or followed by /
    return normalized === dir || normalized.startsWith(dir + "/");
  });
}

export function validateFolderName(folder: string): { valid: boolean; error?: string } {
  const trimmed = folder.trim();
  if (trimmed.length === 0) {
    return { valid: false, error: "Folder name cannot be empty" };
  }
  if (isSystemPath(trimmed)) {
    return { valid: false, error: "System directories are not allowed" };
  }
  return { valid: true };
}

export function folderExistsInList(folder: string, folders: string[]): boolean {
  return folders.some((f) => f === folder);
}

// ponytail: ADR 0007 — upgrade = price difference. User paid X, new version costs Y → upgrade = Y - X.
export function calculateUpgradePrice(originalPaid: number, newVersionPrice: number): number {
  return Math.max(0, newVersionPrice - originalPaid);
}

export function formatStorageUsed(models: ModelStatus[]): string {
  const total = models
    .filter((m) => m.downloaded)
    .reduce((sum, m) => sum + m.size_mb, 0);
  if (total === 0) return "0 MB";
  if (total >= 1024) return `${(total / 1024).toFixed(1)} GB`;
  return `${total} MB`;
}

export function downloadedCount(models: ModelStatus[]): number {
  return models.filter((m) => m.downloaded).length;
}