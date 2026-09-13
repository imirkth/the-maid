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

/// Kill any process listening on the given TCP port.
/// Used as a fallback when the Child handle is held by a different thread's
/// Arc clone and isn't available on the current thread.
fn kill_process_on_port(port: u16) {
    #[cfg(target_os = "linux")]
    {
        // Use ss to find the PID, then kill it.
        let ss_output = std::process::Command::new("ss")
            .args(["-tlnp"])
            .output();
        if let Ok(out) = ss_output {
            let stdout = String::from_utf8_lossy(&out.stdout);
            for line in stdout.lines() {
                if line.contains(&format!(":{} ", port)) {
                    // Parse pid=1234 from ss output
                    if let Some(pid_start) = line.find("pid=") {
                        let rest = &line[pid_start + 4..];
                        let pid_str: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
                        if let Ok(pid) = pid_str.parse::<i32>() {
                            log::info!("[The Maid] Killing orphaned backend PID {} on port {}", pid, port);
                            let _ = std::process::Command::new("kill")
                                .args(["-9", &pid_str])
                                .output();
                        }
                    }
                }
            }
        }
    }

    #[cfg(target_os = "windows")]
    {
        // netstat -ano | findstr :PORT
        let _ = std::process::Command::new("cmd")
            .args(["/C", &format!("for /f \"tokens=5\" %a in ('netstat -ano ^| findstr :{}') do taskkill /F /PID %a", port)])
            .output();
    }

    #[cfg(target_os = "macos")]
    {
        let _ = std::process::Command::new("bash")
            .args(["-c", &format!("lsof -ti :{} | xargs kill -9", port)])
            .output();
    }
}

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
    port: u16,
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
            port: 9473,
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

    /// HTTP health check to verify backend is responding.
    /// ponytail: backend is a uvicorn HTTP server — ping via GET /health, not stdin.
    /// Note: we do NOT check is_alive() because the child handle is stored in the
    /// spawn thread's Arc clone, not the one AppState holds — so self.child is
    /// always None on the ping path. The HTTP connection failure is our alive check.
    pub fn ping(&self) -> Result<(), String> {
        let port = self.port;
        let url = format!("http://127.0.0.1:{}/health", port);
        let (tx, rx) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let result = std::net::TcpStream::connect(format!("127.0.0.1:{}", port))
                .and_then(|mut stream| {
                    use std::io::{Read, Write};
                    let req = format!("GET /health HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n\r\n", port);
                    stream.write_all(req.as_bytes())?;
                    let mut buf = String::new();
                    stream.read_to_string(&mut buf)?;
                    Ok(buf.contains("200 OK") || buf.contains("\"ok\""))
                });
            let _ = tx.send(result);
        });
        let result = rx.recv_timeout(std::time::Duration::from_secs(3))
            .map_err(|_| "Ping timeout".to_string())?
            .map_err(|e| format!("Ping failed: {}", e))?;
        if result {
            let _ = self.event_tx.send(SidecarEvent::Pong);
            Ok(())
        } else {
            Err("Ping failed: health check returned non-200".to_string())
        }
    }

    /// Spawn the Python backend process.
    /// Returns Ok(()) if process printed "READY" on stdout.
    /// On timeout, kills the child to prevent process leak.
    pub fn spawn(&self) -> Result<(), String> {
        // ponytail: kill any orphaned backend from a previous run before spawning.
        // Without this, the new process can't bind to port 9473 and crashes immediately.
        kill_process_on_port(self.port);
        std::thread::sleep(Duration::from_millis(100));

        // ponytail: if backend_path is a .py file, run with python_exe; otherwise run binary directly.
        // Clear AppImage's Python env vars so PyInstaller binary uses its own bundled Python.
        let is_py = self.backend_path.extension().map_or(false, |ext| ext == "py");
        let mut cmd = if is_py {
            let mut c = Command::new(&self.python_exe);
            c.arg(&self.backend_path);
            c
        } else {
            Command::new(&self.backend_path)
        };
        cmd.env_remove("PYTHONHOME")
            .env_remove("PYTHONPATH")
            .env_remove("PYTHONSTARTUP");
        let mut child = cmd
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
                        if l.contains("READY") || l.contains("Uvicorn running") {
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
        // 1. Try the stored child handle first (works if spawn ran on this thread)
        let mut child_guard = self.child.lock().unwrap();
        if let Some(mut child) = child_guard.take() {
            let _ = child.kill();
            match child.wait() {
                Ok(_) => log::info!("[The Maid] Python backend terminated cleanly"),
                Err(e) => log::warn!("[The Maid] Error waiting for Python exit: {}", e),
            }
        }
        drop(child_guard);

        // 2. Fallback: kill any orphaned backend holding our port.
        // The spawn thread stores the Child in its own Arc clone, so the main
        // thread's self.child is None — we must hunt by port to avoid orphans.
        kill_process_on_port(self.port);

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

/// Manages the bundled llama-server process for local LLM inference.
/// No external Ollama needed — the model is bundled inside the AppImage.
pub struct LlmServerManager {
    child: Option<Child>,
    model_path: PathBuf,
    mmproj_path: Option<PathBuf>,
    server_path: PathBuf,
    lib_dir: PathBuf,
    port: u16,
}

impl LlmServerManager {
    pub fn new(resources_dir: &PathBuf) -> Option<Self> {
        let llama_dir = resources_dir.join("llama");
        let server_path = llama_dir.join("llama-server");
        let model_path = llama_dir.join("gemma-4-E2B-it-Q4_K_M.gguf");
        let mmproj_path = llama_dir.join("gemma-4-E2B-mmproj-BF16.gguf");

        let mmproj_exists = mmproj_path.exists();

        if !server_path.exists() || !model_path.exists() {
            log::info!("[The Maid] Bundled LLM not found at {:?}, skipping", llama_dir);
            return None;
        }

        Some(Self {
            child: None,
            model_path,
            mmproj_path: if mmproj_exists { Some(mmproj_path) } else { None },
            server_path,
            lib_dir: llama_dir,
            port: 8080,
        })
    }

    pub fn start(&mut self) -> Result<(), String> {
        log::info!("[The Maid] Starting bundled LLM server...");

        let mut cmd = Command::new(&self.server_path);
        let child = cmd.arg("-m").arg(&self.model_path)
            .arg("--port").arg(self.port.to_string())
            .arg("--host").arg("127.0.0.1")
            .arg("--ctx-size").arg("8192")
            .arg("--n-predict").arg("2048");
        if let Some(ref mmproj) = self.mmproj_path {
            cmd.arg("--mmproj").arg(mmproj);
        }
        let child = cmd.env("LD_LIBRARY_PATH", &self.lib_dir)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to start llama-server: {}", e))?;

        self.child = Some(child);

        // Wait for server to be ready (check /health via raw TCP)
        let deadline = std::time::Instant::now() + Duration::from_secs(60);
        loop {
            if let Ok(mut stream) = std::net::TcpStream::connect_timeout(
                &std::net::SocketAddr::from(([127, 0, 0, 1], self.port)),
                Duration::from_secs(2),
            ) {
                use std::io::{Read, Write};
                let _ = stream.write_all(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");
                let mut buf = String::new();
                let _ = stream.read_to_string(&mut buf);
                if buf.contains("200 OK") || buf.contains("ok") {
                    log::info!("[The Maid] Bundled LLM server is ready on port {}", self.port);
                    return Ok(());
                }
            }
            if std::time::Instant::now() > deadline {
                self.child.as_mut().map(|c| c.kill());
                return Err("LLM server did not become ready within 60s".to_string());
            }
            std::thread::sleep(Duration::from_millis(500));
        }
    }

    pub fn port(&self) -> u16 {
        self.port
    }

    pub fn kill(&mut self) {
        if let Some(mut child) = self.child.take() {
            let _ = child.kill();
            let _ = child.wait();
            log::info!("[The Maid] LLM server terminated");
        }
    }
}

impl Drop for LlmServerManager {
    fn drop(&mut self) {
        self.kill();
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
        script
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