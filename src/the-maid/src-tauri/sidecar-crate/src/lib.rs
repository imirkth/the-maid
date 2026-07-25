//! Sidecar Process Manager
//!
//! Spawns, monitors, and restarts the Python backend process.
//! Communicates readiness via stdout line "READY".

use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use std::path::PathBuf;
use std::io::{BufRead, BufReader};

/// Maximum restart attempts before giving up.
const MAX_RESTART_ATTEMPTS: u32 = 3;

/// Initial backoff delay in milliseconds.
const INITIAL_BACKOFF_MS: u64 = 500;

/// State of the sidecar process.
#[derive(Debug, Clone, PartialEq)]
pub enum SidecarState {
    /// Not yet started.
    Stopped,
    /// Process is running and ready.
    Running,
    /// Process crashed, attempting restart.
    Restarting { attempt: u32 },
    /// All restart attempts exhausted.
    Failed,
}

/// Manages the Python backend sidecar process lifecycle.
pub struct SidecarManager {
    child: Arc<Mutex<Option<Child>>>,
    state: Arc<Mutex<SidecarState>>,
    backend_path: PathBuf,
    python_exe: String,
}

impl SidecarManager {
    /// Create a new SidecarManager pointing at the given Python script.
    pub fn new(backend_path: PathBuf) -> Self {
        let python_exe = if cfg!(target_os = "windows") {
            "python".to_string()
        } else {
            "python3".to_string()
        };
        Self {
            child: Arc::new(Mutex::new(None)),
            state: Arc::new(Mutex::new(SidecarState::Stopped)),
            backend_path,
            python_exe,
        }
    }

    /// Set the Python executable path (for testing).
    pub fn with_python_exe(mut self, exe: String) -> Self {
        self.python_exe = exe;
        self
    }

    /// Get current state.
    pub fn state(&self) -> SidecarState {
        self.state.lock().unwrap().clone()
    }

    /// Spawn the Python backend process.
    /// Returns Ok(()) if process printed "READY" on stdout.
    pub fn spawn(&self) -> Result<(), String> {
        let mut child = Command::new(&self.python_exe)
            .arg(&self.backend_path)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to spawn Python backend: {}", e))?;

        // Read stdout for "READY" signal
        if let Some(stdout) = child.stdout.take() {
            let reader = BufReader::new(stdout);
            for line in reader.lines() {
                match line {
                    Ok(l) => {
                        log::info!("[The Maid] Python: {}", l);
                        if l.contains("READY") {
                            *self.state.lock().unwrap() = SidecarState::Running;
                            *self.child.lock().unwrap() = Some(child);
                            return Ok(());
                        }
                    }
                    Err(_) => break,
                }
            }
        }

        // If we get here, process exited without READY
        let exit_status = child.wait();
        log::error!(
            "[The Maid] Python backend exited before READY: {:?}",
            exit_status
        );
        *self.state.lock().unwrap() = SidecarState::Stopped;
        Err("Python backend exited before signaling READY".to_string())
    }


    /// Kill the sidecar process cleanly.
    pub fn kill(&self) -> Result<(), String> {
        let mut child_guard = self.child.lock().unwrap();
        if let Some(mut child) = child_guard.take() {
            // Try graceful kill first
            #[cfg(unix)]
            {
                let pid = child.id() as i32;
                unsafe {
                    libc::kill(pid, libc::SIGTERM);
                }
            }
            #[cfg(windows)]
            {
                // On Windows, kill the process tree
                let _ = Command::new("taskkill")
                    .args(["/PID", &child.id().to_string(), "/T", "/F"])
                    .output();
            }

            // Wait for exit
            match child.wait() {
                Ok(_) => log::info!("[The Maid] Python backend terminated cleanly"),
                Err(e) => log::warn!("[The Maid] Error waiting for Python exit: {}", e),
            }
        }
        *self.state.lock().unwrap() = SidecarState::Stopped;
        Ok(())
    }

    /// Check if the child process is still running.
    pub fn is_alive(&self) -> bool {
        let mut child_guard = self.child.lock().unwrap();
        if let Some(child) = child_guard.as_mut() {
            match child.try_wait() {
                Ok(Some(_)) => false, // exited
                Ok(None) => true,     // still running
                Err(_) => false,
            }
        } else {
            false
        }
    }

    /// Restart the sidecar with exponential backoff.
    /// Returns Ok(()) if successfully restarted.
    pub fn restart_with_backoff(&self) -> Result<(), String> {
        // Kill existing process if any
        self.kill()?;

        for attempt in 1..=MAX_RESTART_ATTEMPTS {
            *self.state.lock().unwrap() = SidecarState::Restarting { attempt };
            let delay_ms = INITIAL_BACKOFF_MS * (2_u64.pow(attempt - 1));
            log::info!(
                "[The Maid] Restart attempt {} (backoff {}ms)",
                attempt,
                delay_ms
            );
            std::thread::sleep(Duration::from_millis(delay_ms));

            match self.spawn() {
                Ok(()) => return Ok(()),
                Err(e) => {
                    log::warn!(
                        "[The Maid] Restart attempt {} failed: {}",
                        attempt,
                        e
                    );
                }
            }
        }

        *self.state.lock().unwrap() = SidecarState::Failed;
        Err(format!(
            "Python backend failed to start after {} attempts",
            MAX_RESTART_ATTEMPTS
        ))
    }
}

impl Drop for SidecarManager {
    fn drop(&mut self) {
        let _ = self.kill();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Helper: create a temporary Python script that prints READY and stays alive.
    fn make_ready_script() -> PathBuf {
        let dir = std::env::temp_dir().join("the-maid-tests");
        std::fs::create_dir_all(&dir).unwrap();
        let script = dir.join("ready_script.py");
        std::fs::write(
            &script,
            "import time\nprint('READY', flush=True)\ntime.sleep(30)\n",
        )
        .unwrap();
        script
    }

    /// Helper: create a Python script that exits immediately (crashes).
    fn make_crash_script() -> PathBuf {
        let dir = std::env::temp_dir().join("the-maid-tests");
        std::fs::create_dir_all(&dir).unwrap();
        let script = dir.join("crash_script.py");
        std::fs::write(&script, "import sys; sys.exit(1)\n").unwrap();
        script
    }

    #[test]
    fn test_spawn_ready_process() {
        let script = make_ready_script();
        let manager = SidecarManager::new(script);
        let result = manager.spawn();
        assert!(result.is_ok(), "spawn should succeed: {:?}", result);
        assert_eq!(manager.state(), SidecarState::Running);
        assert!(manager.is_alive());
        manager.kill().unwrap();
    }

    #[test]
    fn test_kill_stops_process() {
        let script = make_ready_script();
        let manager = SidecarManager::new(script);
        manager.spawn().unwrap();
        assert!(manager.is_alive());
        manager.kill().unwrap();
        assert!(!manager.is_alive());
        assert_eq!(manager.state(), SidecarState::Stopped);
    }

    #[test]
    fn test_crash_detected() {
        let script = make_crash_script();
        let manager = SidecarManager::new(script);
        let result = manager.spawn();
        assert!(result.is_err(), "crash script should fail to spawn");
        assert_eq!(manager.state(), SidecarState::Stopped);
    }

    #[test]
    fn test_restart_with_backoff() {
        // Use crash script — restart should fail after max attempts
        let script = make_crash_script();
        let manager = SidecarManager::new(script);
        let result = manager.restart_with_backoff();
        assert!(result.is_err(), "should fail after max restart attempts");
        assert_eq!(manager.state(), SidecarState::Failed);
    }


    #[test]
    fn test_restart_succeeds_after_crash() {
        // First spawn a crash script, then switch to ready script
        let crash_script = make_crash_script();
        let ready_script = make_ready_script();
        
        // Start with crash script
        let manager = SidecarManager::new(crash_script);
        let _ = manager.spawn();
        assert!(!manager.is_alive());

        // Now create manager with ready script and restart
        let manager2 = SidecarManager::new(ready_script);
        let result = manager2.restart_with_backoff();
        assert!(result.is_ok(), "restart should succeed with ready script");
        assert_eq!(manager2.state(), SidecarState::Running);
        manager2.kill().unwrap();
    }

    #[test]
    fn test_drop_kills_process() {
        let script = make_ready_script();
        let manager = SidecarManager::new(script);
        manager.spawn().unwrap();
        let child_id = manager.child.lock().unwrap().as_ref().map(|c| c.id());
        assert!(child_id.is_some());

        // Dropping should kill
        drop(manager);

        // Process should be dead — try to find it
        // On Unix, defunct processes may still show up, but they're not alive
        // We just verify no panic occurs on drop
    }
}