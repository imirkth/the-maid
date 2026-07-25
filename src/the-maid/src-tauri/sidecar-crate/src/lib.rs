//! Sidecar Process Manager
//!
//! Spawns, monitors, and restarts the Python backend process.
//! Communicates readiness via stdout line "READY".
//! Forwards subsequent stdout lines as events via std::sync::mpsc.

use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex, mpsc};
use std::time::Duration;
use std::path::PathBuf;
use std::io::{BufRead, BufReader};
use std::thread;

/// Maximum restart attempts before giving up.
const MAX_RESTART_ATTEMPTS: u32 = 3;

/// Initial backoff delay in milliseconds.
const INITIAL_BACKOFF_MS: u64 = 500;

/// Timeout waiting for READY signal (seconds).
const READY_TIMEOUT_SECS: u64 = 30;

/// State of the sidecar process.
#[derive(Debug, Clone, PartialEq)]
pub enum SidecarState {
    Stopped,
    Running,
    Restarting { attempt: u32 },
    Failed,
}

/// Events emitted by the sidecar manager.
#[derive(Debug, Clone, PartialEq)]
pub enum SidecarEvent {
    /// Python printed a line to stdout (JSON or plain text).
    Stdout(String),
    /// Python printed a line to stderr.
    Stderr(String),
    /// Health check response from Python.
    Pong,
    /// Process exited unexpectedly.
    Crashed(String),
}

/// Manages the Python backend sidecar process lifecycle.
pub struct SidecarManager {
    child: Arc<Mutex<Option<Child>>>,
    state: Arc<Mutex<SidecarState>>,
    backend_path: PathBuf,
    python_exe: String,
    event_rx: Arc<Mutex<Option<mpsc::Receiver<SidecarEvent>>>>,
    event_tx: mpsc::Sender<SidecarEvent>,
    ready_timeout: Duration,
}

impl SidecarManager {
    /// Create a new SidecarManager pointing at the given Python script.
    pub fn new(backend_path: PathBuf) -> Self {
        let (tx, rx) = mpsc::channel();
        Self {
            child: Arc::new(Mutex::new(None)),
            state: Arc::new(Mutex::new(SidecarState::Stopped)),
            backend_path,
            python_exe: if cfg!(target_os = "windows") {
                "python".to_string()
            } else {
                "python3".to_string()
            },
            event_rx: Arc::new(Mutex::new(Some(rx))),
            event_tx: tx,
            ready_timeout: Duration::from_secs(READY_TIMEOUT_SECS),
        }
    }

    /// Set the Python executable path (for testing).
    pub fn with_python_exe(mut self, exe: String) -> Self {
        self.python_exe = exe;
        self
    }

    /// Set READY timeout (for testing).
    pub fn with_ready_timeout(mut self, timeout: Duration) -> Self {
        self.ready_timeout = timeout;
        self
    }

    /// Get current state.
    pub fn state(&self) -> SidecarState {
        self.state.lock().unwrap().clone()
    }

    /// Take ownership of the event receiver. Call once to start consuming events.
    /// Returns None if already taken.
    pub fn take_event_receiver(&self) -> Option<mpsc::Receiver<SidecarEvent>> {
        self.event_rx.lock().unwrap().take()
    }

    /// Send a ping to Python via stderr (Python can read stdin for commands).
    /// ponytail: simplest ping — just check if process is alive.
    pub fn ping(&self) -> Result<(), String> {
        if self.is_alive() {
            let _ = self.event_tx.send(SidecarEvent::Pong);
            Ok(())
        } else {
            Err("Backend is not running".to_string())
        }
    }

    /// Spawn the Python backend process.
    /// Returns Ok(()) if process printed "READY" on stdout.
    /// After READY, a background thread forwards stdout/stderr lines as events.
    pub fn spawn(&self) -> Result<(), String> {
        let mut child = Command::new(&self.python_exe)
            .arg(&self.backend_path)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to spawn Python backend: {}", e))?;

        let stdout = child.stdout.take().ok_or("Failed to capture stdout")?;
        let stderr = child.stderr.take();

        // Read stdout for READY, then keep reading for events
        let reader = BufReader::new(stdout);
        let tx = self.event_tx.clone();
        let state = self.state.clone();

        thread::spawn(move || {
            for line in reader.lines() {
                match line {
                    Ok(l) => {
                        log::info!("[The Maid] Python: {}", l);
                        if l.contains("READY") {
                            *state.lock().unwrap() = SidecarState::Running;
                            // Child is still alive — we took stdout but not the child handle.
                            // The child handle will be set by the caller after this returns.
                            // Actually we need to signal back. Use the channel.
                            let _ = tx.send(SidecarEvent::Stdout(l.clone()));
                            // After READY, keep reading and forwarding all lines
                            continue;
                        }
                        let _ = tx.send(SidecarEvent::Stdout(l));
                    }
                    Err(_) => break,
                }
            }
            // stdout closed — process exited
            let _ = tx.send(SidecarEvent::Crashed("stdout closed".to_string()));
        });

        // Forward stderr in a separate thread
        if let Some(stderr) = stderr {
            let tx = self.event_tx.clone();
            thread::spawn(move || {
                let reader = BufReader::new(stderr);
                for line in reader.lines() {
                    match line {
                        Ok(l) => {
                            log::warn!("[The Maid] Python stderr: {}", l);
                            let _ = tx.send(SidecarEvent::Stderr(l));
                        }
                        Err(_) => break,
                    }
                }
            });
        }

        // Wait for READY signal via channel (with timeout)
        let deadline = std::time::Instant::now() + self.ready_timeout;
        loop {
            if self.state() == SidecarState::Running {
                *self.child.lock().unwrap() = Some(child);
                return Ok(());
            }
            if std::time::Instant::now() > deadline {
                *self.state.lock().unwrap() = SidecarState::Stopped;
                return Err("Python backend did not signal READY within 30s".to_string());
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    }

    /// Kill the sidecar process cleanly.
    pub fn kill(&self) -> Result<(), String> {
        let mut child_guard = self.child.lock().unwrap();
        if let Some(mut child) = child_guard.take() {
            #[cfg(unix)]
            {
                let pid = child.id() as i32;
                unsafe {
                    libc::kill(pid, libc::SIGTERM);
                }
            }
            #[cfg(windows)]
            {
                let _ = Command::new("taskkill")
                    .args(["/PID", &child.id().to_string(), "/T", "/F"])
                    .output();
            }
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
                Ok(Some(_)) => false,
                Ok(None) => true,
                Err(_) => false,
            }
        } else {
            false
        }
    }

    /// Restart the sidecar with exponential backoff.
    pub fn restart_with_backoff(&self) -> Result<(), String> {
        self.kill()?;
        for attempt in 1..=MAX_RESTART_ATTEMPTS {
            *self.state.lock().unwrap() = SidecarState::Restarting { attempt };
            let delay_ms = INITIAL_BACKOFF_MS * (2_u64.pow(attempt - 1));
            log::info!("[The Maid] Restart attempt {} (backoff {}ms)", attempt, delay_ms);
            std::thread::sleep(Duration::from_millis(delay_ms));
            match self.spawn() {
                Ok(()) => return Ok(()),
                Err(e) => log::warn!("[The Maid] Restart attempt {} failed: {}", attempt, e),
            }
        }
        *self.state.lock().unwrap() = SidecarState::Failed;
        Err(format!("Python backend failed to start after {} attempts", MAX_RESTART_ATTEMPTS))
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

    fn make_ready_script() -> PathBuf {
        let dir = std::env::temp_dir().join("the-maid-tests");
        std::fs::create_dir_all(&dir).unwrap();
        let script = dir.join("ready_script.py");
        std::fs::write(&script, "import time\nprint('READY', flush=True)\ntime.sleep(30)\n").unwrap();
        script
    }

    fn make_event_script() -> PathBuf {
        let dir = std::env::temp_dir().join("the-maid-tests");
        std::fs::create_dir_all(&dir).unwrap();
        let script = dir.join("event_script.py");
        std::fs::write(&script,
            "import time\nprint('READY', flush=True)\ntime.sleep(0.2)\nprint('{\"event\":\"scan_progress\",\"progress\":0.5}', flush=True)\ntime.sleep(0.2)\nprint('{\"event\":\"scan_progress\",\"progress\":1.0}', flush=True)\ntime.sleep(30)\n"
        ).unwrap();
        script
    }

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
        let manager = SidecarManager::new(script).with_ready_timeout(Duration::from_millis(500));
        let result = manager.spawn();
        assert!(result.is_err(), "crash script should fail to spawn");
        assert_eq!(manager.state(), SidecarState::Stopped);
    }

    #[test]
    fn test_restart_with_backoff() {
        let script = make_crash_script();
        let manager = SidecarManager::new(script).with_ready_timeout(Duration::from_millis(500));
        let result = manager.restart_with_backoff();
        assert!(result.is_err());
        assert_eq!(manager.state(), SidecarState::Failed);
    }

    #[test]
    fn test_restart_succeeds_after_crash() {
        let crash_script = make_crash_script();
        let ready_script = make_ready_script();
        let manager = SidecarManager::new(crash_script);
        let _ = manager.spawn();
        assert!(!manager.is_alive());
        let manager2 = SidecarManager::new(ready_script);
        let result = manager2.restart_with_backoff();
        assert!(result.is_ok());
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
        drop(manager);
    }

    #[test]
    fn test_event_receiver_gets_stdout_events() {
        let script = make_event_script();
        let manager = SidecarManager::new(script);
        manager.spawn().unwrap();

        let rx = manager.take_event_receiver().expect("event receiver should exist");

        // Collect events for a short time
        let mut events = vec![];
        let deadline = std::time::Instant::now() + Duration::from_secs(2);
        while std::time::Instant::now() < deadline {
            while let Ok(ev) = rx.try_recv() {
                events.push(ev);
            }
            std::thread::sleep(Duration::from_millis(100));
        }

        // Should have received READY line + at least one scan_progress event
        let stdout_events: Vec<_> = events.iter().filter(|e| matches!(e, SidecarEvent::Stdout(_))).collect();
        assert!(stdout_events.len() >= 2, "should have READY + progress events, got: {:?}", stdout_events);

        // Find the JSON progress event
        let has_progress = events.iter().any(|e| {
            if let SidecarEvent::Stdout(s) = e {
                s.contains("scan_progress") && s.contains("0.5")
            } else { false }
        });
        assert!(has_progress, "should have received scan_progress 0.5 event");

        manager.kill().unwrap();
    }

    #[test]
    fn test_ping_pong() {
        let script = make_ready_script();
        let manager = SidecarManager::new(script);
        manager.spawn().unwrap();

        let rx = manager.take_event_receiver().unwrap();

        // ping should succeed when alive
        let result = manager.ping();
        assert!(result.is_ok(), "ping should succeed when alive");

        // should receive Pong event
        let mut got_pong = false;
        for _ in 0..10 {
            if let Ok(SidecarEvent::Pong) = rx.try_recv() {
                got_pong = true;
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        assert!(got_pong, "should receive Pong event after ping");

        manager.kill().unwrap();
    }

    #[test]
    fn test_take_event_receiver_once() {
        let script = make_ready_script();
        let manager = SidecarManager::new(script);
        manager.spawn().unwrap();

        let rx1 = manager.take_event_receiver();
        assert!(rx1.is_some(), "first take should succeed");

        let rx2 = manager.take_event_receiver();
        assert!(rx2.is_none(), "second take should return None");

        manager.kill().unwrap();
    }
}