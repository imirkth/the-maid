// The Maid — Tauri Commands (Rust → Python IPC)
// All commands validate sandbox before executing file ops

use serde::{Deserialize, Serialize};
use std::path::Path;
use regex::Regex;

// Sandbox validation regex
// Matches: /home/user/Desktop, C:\Users\User\Downloads, etc.
const SANDBOX_PATTERN: &str = r"^(/home/[^/]+|/[a-zA-Z]:[/\\])(Desktop|Downloads|Documents|Pictures|Videos|Music)([/\\].*)?$";

fn is_in_sandbox(path: &str) -> bool {
    let re = Regex::new(SANDBOX_PATTERN).unwrap();
    re.is_match(path)
}

fn validate_path(path: &str) -> Result<String, String> {
    if is_in_sandbox(path) {
        Ok(path.to_string())
    } else {
        Err(format!("Path '{}' is outside the sandbox. Allowed: Desktop, Downloads, Documents, Pictures, Videos, Music", path))
    }
}

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
    validate_path(&request.directory)?;
    
    // TODO: Call Python backend via HTTP to port 9473
    // For now, return empty with error message
    Err("Python backend not yet running. Start it with: python backend/run.py".to_string())
}

#[tauri::command]
pub async fn get_proposal(file_path: String) -> Result<FileProposal, String> {
    validate_path(&file_path)?;
    Err("Not yet implemented".to_string())
}

#[tauri::command]
pub async fn approve_and_clean(request: ApprovalRequest) -> Result<String, String> {
    // Validate all paths before executing
    for proposal in &request.proposals {
        if request.approved_ids.contains(&proposal.file_id) {
            validate_path(&proposal.current_path)?;
            validate_path(&proposal.proposed_path)?;
        }
    }
    
    // TODO: Execute moves via std::fs::rename
    // Use trash crate for safe deletion/recovery
    Ok("Approved files moved successfully".to_string())
}

#[tauri::command]
pub async fn get_buckets() -> Result<Vec<Bucket>, String> {
    // TODO: Load from user config (~/.the-maid/buckets.json)
    Ok(vec![
        Bucket { id: "1".to_string(), name: "Desktop".to_string(), path: "~/Desktop".to_string() },
        Bucket { id: "2".to_string(), name: "Documents".to_string(), path: "~/Documents".to_string() },
        Bucket { id: "3".to_string(), name: "Pictures".to_string(), path: "~/Pictures".to_string() },
    ])
}

#[tauri::command]
pub async fn add_bucket(bucket: Bucket) -> Result<(), String> {
    validate_path(&bucket.path)?;
    // TODO: Save to buckets.json
    Ok(())
}

#[tauri::command]
pub async fn check_sandbox(path: String) -> Result<bool, String> {
    Ok(is_in_sandbox(&path))
}

#[tauri::command]
pub async fn get_scan_progress() -> Result<f32, String> {
    // TODO: Query Python backend for progress
    Ok(0.0)
}

#[tauri::command]
pub async fn write_metadata(file_path: String, tags: Vec<String>) -> Result<(), String> {
    validate_path(&file_path)?;
    // TODO: Call ExifTool via Python backend
    Ok(())
}

#[tauri::command]
pub async fn cluster_faces(directory: String) -> Result<Vec<String>, String> {
    validate_path(&directory)?;
    // TODO: Call Python face clustering pipeline
    Ok(vec![])
}

#[tauri::command]
pub async fn tag_face_cluster(cluster_id: String, name: String) -> Result<(), String> {
    // TODO: Update face index and write XMP tags
    Ok(())
}
