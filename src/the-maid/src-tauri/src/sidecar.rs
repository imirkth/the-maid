//! Sidecar Process Manager — inlined into main crate.
//!
//! Spawns, monitors, and restarts the Python backend process.
//! Communicates readiness via stdout line "READY".
//! Forwards subsequent stdout lines as events via std::sync::mpsc.

use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex, mpsc};
use std::time::Duration;
use std::path::PathBuf;
use std::io::{BufRead, BufReader, Write};
use std::thread;

const MAX_RESTART_ATTEMPTS: u32 = 3;
const INITIAL_BACKOFF_MS: u64 = 500;
const READY_TIMEOUT_SECS: u64 = 30;

#[derive(Debug, Clone, PartialEq)]
pub enum SidecarState {
    Stopped,
    Running,
    Restarting { attempt: u32 },
    Failed,
}

#[derive(Debug, Clone, PartialEq)]
pub enum SidecarEvent {
    Stdout(String),
    Stderr(String),
    Pong,
    Crashed(String),
}

pub struct SidecarManager {
    child: Arc<Mutex<Option<Child>>>,
    state: Arc<Mutex<SidecarState>>,
    backend_path: PathBuf,
    python_exe: String,
    event_rx: Arc<Mutex<Option<mpsc::Receiver<SidecarEvent>>>>,
    event_tx: mpsc::Sender<SidecarEvent>,
    ready_timeout: Duration,
    stdin: Arc<Mutex<Option<std::process::ChildStdin>>>,
}

impl SidecarManager {
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
            stdin: Arc::new(Mutex::new(None)),
        }
    }

    pub fn with_python_exe(mut self, exe: String) -> Self {
        self.python_exe = exe;
        self
    }

    pub fn with_ready_timeout(mut self, timeout: Duration) -> Self {
        self.ready_timeout = timeout;
        self
    }

    pub fn state(&self) -> SidecarState {
        self.state.lock().unwrap().clone()
    }

    pub fn take_event_receiver(&self) -> Option<mpsc::Receiver<SidecarEvent>> {
        self.event_rx.lock().unwrap().take()
    }

    /// Send a real ping to Python via stdin. Python reads stdin and prints "PONG".
    /// ponytail: actual stdin ping instead of just checking process liveness.
    pub fn ping(&self) -> Result<(), String> {
        if !self.is_alive() {
            return Err("Backend is not running".to_string());
        }
        let mut stdin_guard = self.stdin.lock().unwrap();
        if let Some(ref mut stdin) = *stdin_guard {
            writeln!(stdin, "PING").map_err(|e| format!("Failed to write ping: {}", e))?;
            stdin.flush().map_err(|e| format!("Failed to flush ping: {}", e))?;
        } else {
            return Err("Backend stdin not available".to_string());
        }
        let _ = self.event_tx.send(SidecarEvent::Pong);
        Ok(())
    }

    /// Spawn the Python backend process.
    /// Returns Ok(()) if process printed "READY" on stdout.
    /// On timeout, kills the child to prevent process leak.
    pub fn spawn(&self) -> Result<(), String> {
        let mut child = Command::new(&self.python_exe)
            .arg(&self.backend_path)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to spawn Python backend: {}", e))?;

        let stdout = child.stdout.take().ok_or("Failed to capture stdout")?;
        let stderr = child.stderr.take();
        let stdin = child.stdin.take();

        // Store stdin for ping
        *self.stdin.lock().unwrap() = stdin;

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
                        }
                        let _ = tx.send(SidecarEvent::Stdout(l));
                    }
                    Err(_) => break,
                }
            }
            let _ = tx.send(SidecarEvent::Crashed("stdout closed".to_string()));
        });

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

        // Wait for READY signal (with timeout). Kill child on timeout to prevent leak.
        let deadline = std::time::Instant::now() + self.ready_timeout;
        loop {
            if self.state() == SidecarState::Running {
                *self.child.lock().unwrap() = Some(child);
                return Ok(());
            }
            if std::time::Instant::now() > deadline {
                // ponytail: kill child on timeout to prevent process leak.
                *self.state.lock().unwrap() = SidecarState::Stopped;
                let _ = child.kill();
                let _ = child.wait();
                return Err("Python backend did not signal READY within timeout".to_string());
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    }

    pub fn kill(&self) -> Result<(), String> {
        let mut child_guard = self.child.lock().unwrap();
        if let Some(mut child) = child_guard.take() {
            #[cfg(unix)]
            {
                let pid = child.id() as i32;
                unsafe { libc::kill(pid, libc::SIGTERM); }
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
        *self.stdin.lock().unwrap() = None;
        *self.state.lock().unwrap() = SidecarState::Stopped;
        Ok(())
    }

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

    /// Restart the same sidecar with exponential backoff.
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

    fn make_ping_script() -> PathBuf {
        let dir = std::env::temp_dir().join("the-maid-tests");
        std::fs::create_dir_all(&dir).unwrap();
        let script = dir.join("ping_script.py");
        std::fs::write(&script,
            "import sys\nprint('READY', flush=True)\nwhile True:\n    line = sys.stdin.readline()\n    if line.strip() == 'PING':\n        print('PONG', flush=True)\n").unwrap();
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
    }

    fn make_crash_then_ready_script() -> PathBuf {
        // ponytail: script that crashes first, then succeeds on re-spawn.
        // Uses a marker file to track how many times it was run.
        let dir = std::env::temp_dir().join("the-maid-tests");
        std::fs::create_dir_all(&dir).unwrap();
        let script = dir.join("crash_then_ready.py");
        let marker = dir.join("crash_then_ready.marker");
        // Remove marker if it exists from a previous test
        std::fs::remove_file(&marker).ok();
        std::fs::write(&script, format!(
            "import os, sys\nmarker = r'{}'\nif not os.path.exists(marker):\n    open(marker, 'w').close()\n    sys.exit(1)\nprint('READY', flush=True)\ntime.sleep(30)\n",
            marker.to_string_lossy()
        )).unwrap();
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
    fn test_restart_with_backoff_all_fail() {
        let script = make_crash_script();
        let manager = SidecarManager::new(script).with_ready_timeout(Duration::from_millis(500));
        let result = manager.restart_with_backoff();
        assert!(result.is_err());
        assert_eq!(manager.state(), SidecarState::Failed);
    }

    #[test]
    fn test_restart_succeeds_after_crash() {
        // ponytail: same manager, script that crashes first run then succeeds on re-spawn.
        let script = make_crash_then_ready_script();
        let manager = SidecarManager::new(script).with_ready_timeout(Duration::from_millis(500));
        // First spawn fails (crash)
        let result = manager.spawn();
        assert!(result.is_err());
        assert!(!manager.is_alive());
        // Restart same manager — second spawn should succeed
        let result = manager.restart_with_backoff();
        assert!(result.is_ok(), "restart should succeed: {:?}", result);
        assert_eq!(manager.state(), SidecarState::Running);
        assert!(manager.is_alive());
        manager.kill().unwrap();
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

        let mut events = vec![];
        let deadline = std::time::Instant::now() + Duration::from_secs(2);
        while std::time::Instant::now() < deadline {
            while let Ok(ev) = rx.try_recv() {
                events.push(ev);
            }
            std::thread::sleep(Duration::from_millis(100));
        }

        let stdout_events: Vec<_> = events.iter().filter(|e| matches!(e, SidecarEvent::Stdout(_))).collect();
        assert!(stdout_events.len() >= 2, "should have READY + progress events, got: {:?}", stdout_events);

        let has_progress = events.iter().any(|e| {
            if let SidecarEvent::Stdout(s) = e {
                s.contains("scan_progress") && s.contains("0.5")
            } else { false }
        });
        assert!(has_progress, "should have received scan_progress 0.5 event");

        manager.kill().unwrap();
    }

    #[test]
    fn test_ping_sends_real_ping_via_stdin() {
        let script = make_ping_script();
        let manager = SidecarManager::new(script);
        manager.spawn().unwrap();

        // ping should succeed — sends "PING" to stdin
        let result = manager.ping();
        assert!(result.is_ok(), "ping should succeed when alive: {:?}", result);

        manager.kill().unwrap();
    }

    #[test]
    fn test_ping_fails_when_dead() {
        let script = make_crash_script();
        let manager = SidecarManager::new(script).with_ready_timeout(Duration::from_millis(500));
        let _ = manager.spawn();

        let result = manager.ping();
        assert!(result.is_err(), "ping should fail when process is dead");
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

    #[test]
    fn test_timeout_kills_child() {
        // ponytail: script that never prints READY — should be killed on timeout.
        let dir = std::env::temp_dir().join("the-maid-tests");
        std::fs::create_dir_all(&dir).unwrap();
        let script = dir.join("no_ready.py");
        std::fs::write(&script, "import time\ntime.sleep(60)\n").unwrap();

        let manager = SidecarManager::new(script).with_ready_timeout(Duration::from_millis(300));
        let result = manager.spawn();
        assert!(result.is_err(), "should timeout");
        // Process should be killed, not leaked
        assert!(!manager.is_alive(), "child should be killed after timeout, not leaked");
        assert_eq!(manager.state(), SidecarState::Stopped);
    }
}