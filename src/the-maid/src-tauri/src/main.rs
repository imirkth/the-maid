// The Maid — Tauri Main Entry
// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{Emitter, Manager};
use std::path::PathBuf;
use std::sync::Arc;

mod commands;
mod lightning;
mod settings;
mod sidecar;

use lightning::create_lightning_invoice;

use sidecar::{SidecarManager, SidecarEvent, LlmServerManager};

/// Shared sidecar manager — accessible from commands.
pub struct AppState {
    pub sidecar: Arc<SidecarManager>,
}

fn resolve_backend_path(app: &tauri::AppHandle) -> PathBuf {
    if cfg!(target_os = "windows") {
        app.path()
            .resolve("backend/the_maid_backend.exe", tauri::path::BaseDirectory::Resource)
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
            // ponytail: extract bundled PyInstaller tarball to cache dir, return binary path.
            let tar_path = app.path()
                .resolve("resources/the-maid-backend.tar.gz", tauri::path::BaseDirectory::Resource)
                .expect("Failed to resolve bundled backend tarball");

            let cache_dir = dirs::cache_dir()
                .unwrap_or_else(|| std::env::temp_dir())
                .join("the-maid");
            let _ = std::fs::create_dir_all(&cache_dir);
            let bin_path = cache_dir.join("the-maid-backend").join("the-maid-backend");

            // Extract if binary missing or tarball is newer.
            let need_extract = !bin_path.exists() || {
                let tar_mtime = std::fs::metadata(&tar_path).and_then(|m| m.modified()).ok();
                let bin_mtime = std::fs::metadata(&bin_path).and_then(|m| m.modified()).ok();
                match (tar_mtime, bin_mtime) {
                    (Some(t), Some(b)) => t > b,
                    _ => true,
                }
            };

            if need_extract {
                log::info!("[The Maid] Extracting Python backend tarball to {:?}", cache_dir);
                let status = std::process::Command::new("tar")
                    .arg("xzf")
                    .arg(&tar_path)
                    .arg("-C")
                    .arg(&cache_dir)
                    .status()
                    .expect("Failed to extract backend tarball");
                if !status.success() {
                    panic!("Failed to extract Python backend tarball");
                }
            }

            // Ensure executable permission.
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                if let Ok(meta) = std::fs::metadata(&bin_path) {
                    let mut perms = meta.permissions();
                    perms.set_mode(0o755);
                    let _ = std::fs::set_permissions(&bin_path, perms);
                }
            }

            bin_path
        }
    }
}

/// ponytail: AppImage bundles its own libwayland which breaks WebKitGTK EGL on Wayland.
/// Re-exec with system libwayland-client.so preloaded to fix black screen.
#[cfg(target_os = "linux")]
fn fix_appimage_rendering() {
    let is_appimage = std::env::var("APPIMAGE").is_ok() || std::env::var("APPDIR").is_ok();
    if !is_appimage { return; }
    if std::env::var("MAID_RENDER_PRELOAD_DONE").is_ok() { return; }
    if std::env::var("LD_PRELOAD").is_ok() { return; }

    // System libs to preload — overrides AppImage's bundled copies that
    // conflict with host X11/Wayland WebKitGTK rendering (black screen).
    let candidates = [
        "/usr/lib/x86_64-linux-gnu/libwayland-client.so.0",
        "/usr/lib/x86_64-linux-gnu/libwayland-egl.so.1",
        "/usr/lib/x86_64-linux-gnu/libgtk-3.so.0",
        "/usr/lib/x86_64-linux-gnu/libgdk-3.so.0",
        "/lib/x86_64-linux-gnu/libwayland-client.so.0",
        "/lib/x86_64-linux-gnu/libwayland-egl.so.1",
        "/lib/x86_64-linux-gnu/libgtk-3.so.0",
        "/lib/x86_64-linux-gnu/libgdk-3.so.0",
        "/usr/lib64/libwayland-client.so.0",
        "/usr/lib64/libwayland-egl.so.1",
        "/usr/lib64/libgtk-3.so.0",
        "/usr/lib64/libgdk-3.so.0",
        "/usr/lib/libwayland-client.so.0",
        "/usr/lib/libwayland-egl.so.1",
        "/usr/lib/libgtk-3.so.0",
        "/usr/lib/libgdk-3.so.0",
    ];
    let found: Vec<&str> = candidates.iter()
        .filter(|p| std::path::Path::new(p).is_file())
        .copied()
        .collect();
    if found.is_empty() { return; }
    let preload_path = found.join(":");
    log::info!("[The Maid] Preloading system libs for AppImage rendering: {}", preload_path);
    {
        use std::os::unix::process::CommandExt;
        let exe = std::env::var("APPIMAGE").unwrap_or_else(|_| {
            std::fs::read_link("/proc/self/exe").unwrap_or_default().display().to_string()
        });
        let args: Vec<_> = std::env::args().skip(1).collect();
        let err = std::process::Command::new(&exe)
            .args(&args)
            .env("LD_PRELOAD", &preload_path)
            .env("MAID_RENDER_PRELOAD_DONE", "1")
            .exec();
        eprintln!("[The Maid] Render preload re-exec failed: {}", err);
    }
}

fn main() {
    #[cfg(target_os = "linux")]
    {
        // ponytail: WebKitGTK rendering fixes — set for ALL Linux builds, not just AppImage.
        // NVIDIA + X11 without compositor = black screen without these.
        if std::env::var("WEBKIT_DISABLE_DMABUF_RENDERER").is_err() {
            std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
        }
        if std::env::var("WEBKIT_DISABLE_COMPOSITING_MODE").is_err() {
            std::env::set_var("WEBKIT_DISABLE_COMPOSITING_MODE", "1");
        }
    }

    env_logger::init();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let app_handle = app.handle().clone();

            // ponytail: NVIDIA + X11 + no compositor = black screen in Tauri/WRY.
            // The raw Python WebKit test works fine, so the issue is WRY's
            // accelerated compositing path. We grab the raw WebView and disable it.
            #[cfg(target_os = "linux")]
            {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.set_background_color(Some(tauri::utils::config::Color(10, 14, 26, 255)));
                    window.with_webview(|webview| {
                        use webkit2gtk::{WebViewExt, SettingsExt};
                        let wv = webview.inner();
                        if let Some(settings) = wv.settings() {
                            settings.set_enable_accelerated_2d_canvas(false);
                        }
                    });
                }
            }

            let backend_path = resolve_backend_path(&app_handle);

            // Resolve resources dir for bundled LLM
            let resources_dir = app_handle.path()
                .resource_dir()
                .unwrap_or_else(|_| PathBuf::from("."));

            log::info!("[The Maid] Starting Python backend at: {:?}", backend_path);

            // Start bundled LLM server first (if available)
            let mut llm_server = LlmServerManager::new(&resources_dir);
            if let Some(ref mut llm) = llm_server {
                match llm.start() {
                    Ok(()) => {
                        // Set env var so Python backend knows where the LLM is
                        std::env::set_var("THE_MAID_LLM_BASE_URL", format!("http://127.0.0.1:{}", llm.port()));
                        std::env::set_var("THE_MAID_LLM_MODEL", "gemma-4-E2B-it-Q4_K_M");
                    }
                    Err(e) => {
                        log::warn!("[The Maid] Bundled LLM failed to start: {} — will try Ollama fallback", e);
                    }
                }
            }

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
            commands::remove_bucket,
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
            commands::pick_folder,
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
            commands::categorize_files,
            commands::get_tree,
            commands::save_tree,
            commands::merge_tree,
            commands::edit_category,
            commands::move_file_in_tree,
            commands::approve_tree_structure,
            commands::execute_tree_moves,
            commands::edit_subcategory,
            commands::merge_categories,
            commands::bulk_move_files,
            commands::clear_tree,
        ])
        .build(tauri::generate_context!())
        .expect("error while building The Maid application")
        .run(|app_handle, event| {
            // ponytail: kill backend on app exit — Arc<SidecarManager> Drop won't fire while spawn thread holds a clone.
            if let tauri::RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<AppState>() {
                    let _ = state.sidecar.kill();
                }
            }
        });
}

fn forward_event(handle: &tauri::AppHandle, event: SidecarEvent) {
    match event {
        SidecarEvent::Stdout(line) => {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&line) {
                if let Some(event_name) = val.get("event").and_then(|v| v.as_str()) {
                    match event_name {
                        "scan_progress" => {
                            let _ = handle.emit("scan_progress", &val);
                        }
                        "scan_complete" => {
                            let _ = handle.emit("scan_complete", &val);
                        }
                        "cleanup_plan_ready" => {
                            let _ = handle.emit("cleanup_plan_ready", &val);
                        }
                        "categorize_start" | "categorize_progress" | "categorize_complete" => {
                            let _ = handle.emit(event_name, &val);
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
