// The Maid — Tauri Main Entry
// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::Manager;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

mod commands;

use maid_sidecar::SidecarManager;

/// Shared sidecar manager — accessible from commands.
pub struct AppState {
    pub sidecar: Arc<SidecarManager>,
}

fn resolve_backend_path(app: &tauri::AppHandle) -> PathBuf {
    if cfg!(target_os = "windows") {
        app.path()
            .resolve("backend/the_maid_backend.exe", tauri::BaseDirectory::Resource)
            .unwrap_or_else(|_| {
                // Dev fallback
                let workspace = std::env::var("MAID_WORKSPACE")
                    .unwrap_or_else(|_| String::from("."));
                PathBuf::from(workspace).join("src/the-maid/backend/run.py")
            })
    } else {
        // Development: run from workspace
        let workspace = std::env::var("MAID_WORKSPACE")
            .unwrap_or_else(|_| {
                let home = std::env::var("HOME").unwrap_or_else(|_| String::from("."));
                format!("{}/.openclaw/workspace-the-maid", home)
            });
        PathBuf::from(workspace).join("src/the-maid/backend/run.py")
    }
}

fn main() {
    env_logger::init();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let app_handle = app.handle().clone();
            let backend_path = resolve_backend_path(&app_handle);

            log::info!("[The Maid] Starting Python backend at: {:?}", backend_path);

            let manager = Arc::new(SidecarManager::new(backend_path));

            // Spawn in a separate thread so we don't block setup
            let manager_clone = manager.clone();
            let emit_handle = app_handle.clone();
            std::thread::spawn(move || {
                match manager_clone.spawn() {
                    Ok(()) => {
                        log::info!("[The Maid] Python backend is READY");
                        let _ = emit_handle.emit("backend_ready", true);
                    }
                    Err(e) => {
                        log::error!("[The Maid] Failed to start Python backend: {}", e);
                        // Attempt restart with backoff
                        match manager_clone.restart_with_backoff() {
                            Ok(()) => {
                                log::info!("[The Maid] Python backend restarted successfully");
                                let _ = emit_handle.emit("backend_ready", true);
                            }
                            Err(e2) => {
                                log::error!("[The Maid] Python backend failed after restarts: {}", e2);
                                let _ = emit_handle.emit("backend_ready", false);
                            }
                        }
                    }
                }
            });

            // Store sidecar manager in app state
            app.manage(AppState {
                sidecar: manager,
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::scan_directory,
            commands::get_proposal,
            commands::approve_and_clean,
            commands::get_buckets,
            commands::add_bucket,
            commands::check_sandbox,
            commands::get_scan_progress,
            commands::write_metadata,
            commands::cluster_faces,
            commands::tag_face_cluster,
        ])
        .run(tauri::generate_context!())
        .expect("error while running The Maid application");
}