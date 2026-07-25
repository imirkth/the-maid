// The Maid — Tauri Main Entry
// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::Manager;
use std::process::Command;
use std::path::PathBuf;

mod commands;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Spawn Python backend on startup
            let app_handle = app.handle();
            spawn_python_backend(app_handle)?;
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

fn spawn_python_backend(app: &tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    // Determine Python backend path
    let backend_path = if cfg!(target_os = "windows") {
        app.path().resolve("backend/the_maid_backend.exe", tauri::BaseDirectory::Resource)?
    } else {
        // Development: run from workspace
        let workspace = std::env::var("MAID_WORKSPACE")
            .unwrap_or_else(|_| String::from("~/.openclaw/workspace-the-maid"));
        let expanded = shellexpand::tilde(&workspace);
        PathBuf::from(expanded.to_string()).join("backend/run.py")
    };

    println!("[The Maid] Starting Python backend at: {:?}", backend_path);

    // TODO: Start Python HTTP server on port 9473
    // For now, log the intent
    Ok(())
}
