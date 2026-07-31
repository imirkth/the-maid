// The Maid — Tauri Main Entry
// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::Manager;
use std::path::PathBuf;
use std::sync::Arc;

mod commands;
mod lightning;
mod settings;
mod sidecar;

use lightning::create_lightning_invoice;

use sidecar::{SidecarManager, SidecarEvent};

/// Shared sidecar manager — accessible from commands.
pub struct AppState {
    pub sidecar: Arc<SidecarManager>,
}

fn resolve_backend_path(app: &tauri::AppHandle) -> PathBuf {
    if cfg!(target_os = "windows") {
        app.path()
            .resolve("backend/the_maid_backend.exe", tauri::BaseDirectory::Resource)
            .unwrap_or_else(|_| {
                #[cfg(debug_assertions)]
                {
                    let workspace = std::env::var("MAID_WORKSPACE")
                        .unwrap_or_else(|_| String::from("."));
                    PathBuf::from(workspace).join("src/the-maid/backend/run.py")
                }
                #[cfg(not(debug_assertions))]
                {
                    panic!("Failed to resolve bundled backend executable")
                }
            })
    } else {
        #[cfg(debug_assertions)]
        {
            let workspace = std::env::var("MAID_WORKSPACE")
                .unwrap_or_else(|_| {
                    let home = std::env::var("HOME").unwrap_or_else(|_| String::from("."));
                    format!("{}/.openclaw/workspace-the-maid", home)
                });
            PathBuf::from(workspace).join("src/the-maid/backend/run.py")
        }
        #[cfg(not(debug_assertions))]
        {
            app.path()
                .resolve("backend/run.py", tauri::BaseDirectory::Resource)
                .expect("Failed to resolve bundled backend run.py")
        }
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

            let manager_clone = manager.clone();
            let emit_handle = app_handle.clone();
            std::thread::spawn(move || {
                match manager_clone.spawn() {
                    Ok(()) => {
                        log::info!("[The Maid] Python backend is READY");
                        let _ = emit_handle.emit("backend_ready", true);

                        if let Some(rx) = manager_clone.take_event_receiver() {
                            let fwd_handle = emit_handle.clone();
                            std::thread::spawn(move || {
                                for event in rx {
                                    forward_event(&fwd_handle, event);
                                }
                            });
                        }
                    }
                    Err(e) => {
                        log::error!("[The Maid] Failed to start Python backend: {}", e);
                        match manager_clone.restart_with_backoff() {
                            Ok(()) => {
                                log::info!("[The Maid] Python backend restarted successfully");
                                let _ = emit_handle.emit("backend_ready", true);
                                if let Some(rx) = manager_clone.take_event_receiver() {
                                    let fwd_handle = emit_handle.clone();
                                    std::thread::spawn(move || {
                                        for event in rx {
                                            forward_event(&fwd_handle, event);
                                        }
                                    });
                                }
                            }
                            Err(e2) => {
                                log::error!("[The Maid] Python backend failed after restarts: {}", e2);
                                let _ = emit_handle.emit("backend_ready", false);
                            }
                        }
                    }
                }
            });

            app.manage(AppState { sidecar: manager });
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
            lightning::create_lightning_invoice,
            lightning::verify_lightning_payment_cmd,
            commands::ping_backend,
            commands::get_settings,
            commands::save_settings,
            commands::add_sandbox_folder,
            commands::remove_sandbox_folder,
            commands::complete_first_run,
            commands::complete_setup,
            commands::can_scan,
            commands::get_cleanup_plan,
            commands::get_face_clusters,
            commands::rename_face_cluster,
            commands::check_updates,
            commands::get_app_version,
            commands::get_model_status,
            commands::download_model,
        ])
        .run(tauri::generate_context!())
        .expect("error while running The Maid application");
}

fn forward_event(handle: &tauri::AppHandle, event: SidecarEvent) {
    match event {
        SidecarEvent::Stdout(line) => {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&line) {
                if let Some(event_name) = val.get("event").and_then(|v| v.as_str()) {
                    match event_name {
                        "scan_progress" => {
                            let progress = val.get("progress").and_then(|v| v.as_f64()).unwrap_or(0.0);
                            let _ = handle.emit("scan_progress", progress);
                        }
                        "scan_complete" => {
                            let _ = handle.emit("scan_complete", &val);
                        }
                        "cleanup_plan_ready" => {
                            let _ = handle.emit("cleanup_plan_ready", &val);
                        }
                        _ => {
                            let _ = handle.emit("python_event", &val);
                        }
                    }
                }
            } else {
                let _ = handle.emit("python_log", line);
            }
        }
        SidecarEvent::Stderr(line) => {
            log::warn!("[The Maid] Python stderr: {}", line);
            let _ = handle.emit("python_error", line);
        }
        SidecarEvent::Pong => {
            let _ = handle.emit("backend_pong", true);
        }
        SidecarEvent::Crashed(msg) => {
            log::error!("[The Maid] Python crashed: {}", msg);
            let _ = handle.emit("backend_crashed", msg);
        }
    }
}