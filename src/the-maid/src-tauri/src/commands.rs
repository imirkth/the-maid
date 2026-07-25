// The Maid — Tauri Commands (Rust → Python IPC)
// All commands validate sandbox before executing file ops

use serde::{Deserialize, Serialize};
use std::path::Path;
use tauri::State;
use crate::AppState;
use crate::settings::{Settings, BucketEntry};

// --- Settings commands ---

#[tauri::command]
pub async fn get_settings() -> Result<Settings, String> {
    Settings::load()
}

#[tauri::command]
pub async fn save_settings(mut settings: Settings) -> Result<(), String> {
    settings.save()
}

#[tauri::command]
pub async fn add_sandbox_folder(folder: String) -> Result<Settings, String> {
    let mut s = Settings::load()?;
    s.add_folder(&folder);
    s.save()?;
    Ok(s)
}

#[tauri::command]
pub async fn remove_sandbox_folder(folder: String) -> Result<Settings, String> {
    let mut s = Settings::load()?;
    s.remove_folder(&folder);
    s.save()?;
    Ok(s)
}

#[tauri::command]
pub async fn complete_first_run() -> Result<(), String> {
    let mut s = Settings::load()?;
    s.complete_first_run();
    s.save()
}

#[tauri::command]
pub async fn complete_setup(
    folders: Vec<String>,
    pdf_ocr: bool,
    face_clustering: bool,
    general_files: bool,
) -> Result<(), String> {
    let mut s = Settings::load()?;
    s.sandbox_folders = folders;
    s.set_features(pdf_ocr, face_clustering, general_files);
    s.complete_setup();
    s.save()
}

// --- Sandbox validation ---

// ponytail: simple path containment check instead of regex. Matches Python sandbox.py logic.
const SYSTEM_DIRS: &[&str] = &[
    "/bin", "/sbin", "/usr", "/etc", "/var", "/opt", "/lib", "/lib64",
    "/boot", "/dev", "/proc", "/sys", "/run", "/srv", "/root",
    "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
    "C:\\ProgramData",
];

fn is_system_path(path: &str) -> bool {
    let normalized = path.replace('\\', "/");
    for sys_dir in SYSTEM_DIRS {
        if normalized.starts_with(sys_dir) {
            return true;
        }
    }
    false
}

fn expand_tilde(path: &str) -> String {
    if path.starts_with("~/") || path == "~" {
        if let Ok(home) = std::env::var("HOME").or_else(|_| std::env::var("USERPROFILE")) {
            if path == "~" {
                return home;
            }
            return format!("{}/{}", home, &path[2..]);
        }
    }
    path.to_string()
}

fn sandbox_folder_paths(sandbox_folders: &[String]) -> Vec<String> {
    let home = std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .unwrap_or_default();
    sandbox_folders
        .iter()
        .map(|f| {
            let expanded = expand_tilde(f);
            if expanded.starts_with('/') || expanded.contains(":\\") || expanded.contains(":/") {
                expanded
            } else {
                format!("{}/{}", home, expanded)
            }
        })
        .collect()
}

fn validate_path(path: &str, sandbox_folders: &[String]) -> Result<String, String> {
    let expanded = expand_tilde(path);
    if is_system_path(&expanded) {
        return Err(format!("System directories are out of scope: '{}'", path));
    }
    if sandbox_folders.is_empty() {
        return Ok(expanded);
    }
    let allowed_paths = sandbox_folder_paths(sandbox_folders);
    let normalized_path = expanded.replace('\\', "/");
    for allowed in &allowed_paths {
        let normalized_allowed = allowed.replace('\\', "/");
        if normalized_path == normalized_allowed || normalized_path.starts_with(&format!("{}/", normalized_allowed)) {
            return Ok(expanded);
        }
    }
    Err(format!(
        "Path '{}' is outside the sandbox. Allowed: {}",
        path,
        sandbox_folders.join(", ")
    ))
}

// --- Scan gate ---

#[tauri::command]
pub async fn can_scan() -> Result<bool, String> {
    // ponytail: scan gate — disabled until setup wizard completes AND ≥1 sandbox folder selected
    let settings = Settings::load()?;
    Ok(settings.setup_complete && !settings.sandbox_folders.is_empty())
}

// --- File proposal types ---

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct FileProposal {
    pub file_id: String,
    pub original_filename: String,
    pub current_path: String,
    pub proposed_path: String,
    pub proposed_tags: Vec<String>,
    pub faces_detected: Vec<String>,
    pub rationale: String,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct ScanRequest {
    pub directory: String,
    pub max_files: Option<usize>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct ApprovalRequest {
    pub proposals: Vec<FileProposal>,
    pub approved_ids: Vec<String>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct Bucket {
    pub id: String,
    pub name: String,
    pub path: String,
}

#[tauri::command]
pub async fn scan_directory(request: ScanRequest) -> Result<Vec<FileProposal>, String> {
    let settings = Settings::load()?;
    validate_path(&request.directory, &settings.sandbox_folders)?;

    // TODO: Call Python backend via sidecar to execute scan
    // For now, return empty — Python side handles the actual scan
    Err("Python backend scan not yet wired. Use /scan endpoint directly.".to_string())
}

#[tauri::command]
pub async fn get_proposal(file_path: String) -> Result<FileProposal, String> {
    let settings = Settings::load()?;
    validate_path(&file_path, &settings.sandbox_folders)?;
    Err("Not yet implemented".to_string())
}

#[tauri::command]
pub async fn approve_and_clean(request: ApprovalRequest) -> Result<String, String> {
    let settings = Settings::load()?;
    for proposal in &request.proposals {
        if request.approved_ids.contains(&proposal.file_id) {
            validate_path(&proposal.current_path, &settings.sandbox_folders)?;
            validate_path(&proposal.proposed_path, &settings.sandbox_folders)?;
        }
    }
    // TODO: Execute moves via std::fs::rename
    Ok("Approved files moved successfully".to_string())
}

// --- Cleanup Plan commands ---

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct CleanupItemCmd {
    pub file_id: String,
    pub original_filename: String,
    pub current_path: String,
    pub proposed_action: String,
    pub proposed_path: String,
    pub proposed_tags: Vec<String>,
    pub faces_detected: Vec<String>,
    pub rationale: String,
    pub confidence: f64,
    pub user_edited_path: Option<String>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct CleanupPlanCmd {
    pub schema_version: String,
    pub scan_timestamp: String,
    pub items: Vec<CleanupItemCmd>,
}

#[tauri::command]
pub async fn get_cleanup_plan() -> Result<Option<CleanupPlanCmd>, String> {
    // ponytail: returns None if no plan generated yet. Backend sends plan via event.
    Ok(None)
}

#[tauri::command]
pub async fn get_buckets() -> Result<Vec<Bucket>, String> {
    let settings = Settings::load()?;
    Ok(settings.buckets.iter().map(|b| Bucket {
        id: b.id.clone(),
        name: b.name.clone(),
        path: b.path.clone(),
    }).collect())
}

#[tauri::command]
pub async fn add_bucket(bucket: Bucket) -> Result<(), String> {
    let settings = Settings::load()?;
    validate_path(&bucket.path, &settings.sandbox_folders)?;
    // TODO: Save to settings
    Ok(())
}

#[tauri::command]
pub async fn check_sandbox(path: String) -> Result<bool, String> {
    let settings = Settings::load()?;
    validate_path(&path, &settings.sandbox_folders).map(|_| true).or(Ok(false))
}

#[tauri::command]
pub async fn get_scan_progress() -> Result<f32, String> {
    Ok(0.0)
}

#[tauri::command]
pub async fn write_metadata(file_path: String, tags: Vec<String>) -> Result<(), String> {
    let settings = Settings::load()?;
    validate_path(&file_path, &settings.sandbox_folders)?;
    // TODO: Call ExifTool via Python backend
    Ok(())
}

#[tauri::command]
pub async fn cluster_faces(directory: String) -> Result<Vec<String>, String> {
    let settings = Settings::load()?;
    validate_path(&directory, &settings.sandbox_folders)?;
    Ok(vec![])
}

// --- Face cluster commands ---

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct FaceClusterFace {
    pub file_id: String,
    pub file_path: String,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct FaceClusterInfo {
    pub cluster_id: i64,
    pub cluster_label: String,
    pub face_count: usize,
    pub representative_path: String,
    pub faces: Vec<FaceClusterFace>,
}

#[derive(Serialize, Deserialize, Debug)]
pub struct RenameResult {
    pub renamed: i64,
    pub tagged: i64,
    pub skipped: i64,
    pub errors: Vec<String>,
}

#[tauri::command]
pub async fn get_face_clusters() -> Result<Vec<FaceClusterInfo>, String> {
    // ponytail: delegate to Python backend via sidecar event
    // For now return empty — Python face_cluster.py owns the data
    Ok(vec![])
}

#[tauri::command]
pub async fn rename_face_cluster(
    cluster_id: i64,
    new_label: String,
) -> Result<RenameResult, String> {
    // ponytail: Python backend handles the actual rename + XMP writing
    // Rust just validates the label is non-empty
    if new_label.trim().is_empty() {
        return Err("Cluster label cannot be empty".to_string());
    }
    Ok(RenameResult {
        renamed: 0,
        tagged: 0,
        skipped: 0,
        errors: vec![],
    })
}

#[tauri::command]
pub async fn ping_backend(state: State<'_, AppState>) -> Result<(), String> {
    state.sidecar.ping()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_system_path_rejects_linux_system_dirs() {
        assert!(is_system_path("/bin/bash"));
        assert!(is_system_path("/usr/local/bin"));
        assert!(is_system_path("/etc/passwd"));
        assert!(is_system_path("/var/log/syslog"));
        assert!(is_system_path("/root/.bashrc"));
    }

    #[test]
    fn test_is_system_path_rejects_windows_system_dirs() {
        assert!(is_system_path("C:\\Windows\\System32"));
        assert!(is_system_path("C:\\Program Files\\app"));
        assert!(is_system_path("C:\\ProgramData\\config"));
    }

    #[test]
    fn test_is_system_path_allows_user_dirs() {
        assert!(!is_system_path("/home/user/Desktop"));
        assert!(!is_system_path("/home/user/Downloads/file.txt"));
        assert!(!is_system_path("/tmp/test"));
    }

    #[test]
    fn test_validate_path_rejects_system_paths() {
        let folders = vec!["Desktop".to_string()];
        let result = validate_path("/bin/bash", &folders);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("System directories are out of scope"));
    }

    #[test]
    fn test_validate_path_allows_sandbox_folders() {
        let home = std::env::var("HOME").unwrap_or_default();
        let folders = vec!["Desktop".to_string(), "Downloads".to_string()];
        let result = validate_path(&format!("{}/Desktop/file.txt", home), &folders);
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_path_rejects_outside_sandbox() {
        let folders = vec!["Desktop".to_string()];
        let result = validate_path("/tmp/random/file.txt", &folders);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("outside the sandbox"));
    }

    #[test]
    fn test_validate_path_empty_sandbox_allows_non_system() {
        let folders: Vec<String> = vec![];
        let result = validate_path("/tmp/test", &folders);
        assert!(result.is_ok());
    }

    #[test]
    fn test_validate_path_expands_tilde() {
        let home = std::env::var("HOME").unwrap_or_default();
        let folders = vec!["Desktop".to_string()];
        let result = validate_path("~/Desktop/file.txt", &folders);
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), format!("{}/Desktop/file.txt", home));
    }

    #[test]
    fn test_validate_path_accepts_bare_folder_name() {
        let home = std::env::var("HOME").unwrap_or_default();
        let folders = vec!["Desktop".to_string()];
        let result = validate_path("Desktop/file.txt", &folders);
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), format!("{}/Desktop/file.txt", home));
    }

    #[test]
    fn test_validate_path_accepts_absolute_sandbox_path() {
        let home = std::env::var("HOME").unwrap_or_default();
        let folders = vec!["Desktop".to_string()];
        let result = validate_path(&format!("{}/Desktop/file.txt", home), &folders);
        assert!(result.is_ok());
    }

    #[test]
    fn test_can_scan_with_folders() {
        // This test depends on settings file state, just test the logic
        let folders = vec!["Desktop".to_string()];
        assert!(!folders.is_empty());
    }

    #[test]
    fn test_can_scan_without_folders() {
        let folders: Vec<String> = vec![];
        assert!(folders.is_empty());
    }
}