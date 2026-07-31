# Bug Review — The Maid Slices 1A–1C + supporting code

## Methodology
Phases of `/diagnosing-bugs`:
1. Build a feedback loop — read CONTEXT.md, ADRs, source, tests; note test results.
2. Reproduce + minimize — identify code paths / inputs that trigger each bug.
3. Hypothesize — root cause per finding.
4. Instrument — suggest minimal regression tests / logs.
5. Fix + regression test — note fix needed; tests to add.
6. Cleanup + post-mortem — file as issue comment.

## Scope
- `src/the-maid/src-tauri/src/main.rs`
- `src/the-maid/src-tauri/src/sidecar.rs`
- `src/the-maid/src-tauri/src/settings.rs`
- `src/the-maid/src-tauri/src/commands.rs`
- `src/the-maid/src/App.tsx`
- `src/the-maid/src/components/*.tsx`
- `src/the-maid/backend/the_maid/scanner.py`
- `src/the-maid/backend/the_maid/sandbox.py`
- `src/the-maid/backend/the_maid/models.py`
- Supporting `lib/*.ts`, `api.py`, `run.py`

## Test Results
- Vitest (frontend lib/components): 163 passed, 0 failed.
- Python pytest (backend, all tests): 247 passed, 6 skipped, 0 failed.
- Rust `cargo test` / `cargo check`: blocked on missing GTK/GDK system libs (`gdk-pixbuf`, `pango`, `atk`, `cairo`, `glib`). Static analysis only.

## Findings

### BUG-1: Sidecar stdout/JSON parser ignores parse errors silently and double-logs lines
**File:** `src-tauri/src/sidecar.rs` / `src-tauri/src/main.rs` (`forward_event`)
**Severity:** Medium
**How to reproduce/minimize:** Send a stdout line that is valid JSON but has an `event` field that is not a string (e.g., integer) or send a non-JSON line with `{}` inside it. `forward_event` matches `event` only via `as_str()` and silently emits `python_log` for all non-event JSON. In addition, the spawned reader already logs `INFO` every stdout line; `forward_event` also logs `python_log` for non-event JSON, resulting in double log noise.
**Root cause:** `forward_event` does not surface parse failures or malformed event payloads to the frontend; fall-through emits a generic `python_log` event instead of an error event.
**Fix:** Return an explicit `python_parse_error` event when `event` is missing or not a string, and consolidate logging to one path.
**Regression test:** Unit test that injects `{"event":123}` or `{"bogus":true}` into `forward_event` and asserts `python_parse_error` is emitted.

### BUG-2: `SidecarManager::ping()` immediately returns success without waiting for PONG
**File:** `src-tauri/src/sidecar.rs`
**Severity:** Medium
**How to reproduce/minimize:** Call `ping()` on a running sidecar. It writes `PING` and immediately sends `SidecarEvent::Pong` itself (`let _ = self.event_tx.send(SidecarEvent::Pong)`), then returns `Ok(())`. It never verifies the child actually printed `PONG`.
**Root cause:** `ping()` treats its own send as confirmation. If Python is hung, `ping()` still succeeds.
**Fix:** After sending `PING`, wait on `event_rx` for a `SidecarEvent::Stdout("PONG")` within a timeout; return error if not received. Remove the self-injected `Pong` event.
**Regression test:** Make a Python script that prints `READY` then sleeps forever; `ping()` should time out, not succeed.

### BUG-3: `restart_with_backoff` can deadlock with a poisoned lock
**File:** `src-tauri/src/sidecar.rs`
**Severity:** Low
**How to reproduce/minimize:** Any `Mutex` unwrap in tests or under panic-on-panic scenarios can poison locks. `state.lock().unwrap()` is used repeatedly without `lock().unwrap_or_else(|e| e.into_inner())`. A panic in another thread holding the lock will poison it and subsequent calls panic.
**Root cause:** Ignoring mutex poisoning.
**Fix:** Use `Mutex::lock().unwrap_or_else(|poisoned| poisoned.into_inner())` for shared state, or switch to `RwLock`/atomics for state that does not need strict exclusion. At minimum, make `state()` resilient.
**Regression test:** Add a test that panics a thread while it holds `state`, then asserts `state()` still returns a value.

### BUG-4: `SidecarManager::is_alive()` returns false if `try_wait()` errors for non-fatal reasons
**File:** `src-tauri/src/sidecar.rs`
**Severity:** Low
**How to reproduce/minimize:** `try_wait()` can return `Err` for ECHILD or other transient states even though the process is still alive. The code maps any `Err(_)` to `false`, so the frontend/backend may declare the sidecar dead prematurely.
**Root cause:** `Err(_)` treated as "not alive".
**Fix:** Distinguish `Ok(None)` (alive) and `Ok(Some(_))` (dead); for `Err`, retry or log and conservatively assume alive unless proven dead. Pair with `kill()` attempt or `/proc` check.
**Regression test:** Mock child returning `Err` from `try_wait`; assert `is_alive()` still true or at least not used for kill decisions.

### BUG-5: `kill()` on Unix sends SIGTERM and then waits; if child ignores SIGTERM it leaks
**File:** `src-tauri/src/sidecar.rs`
**Severity:** Low-Medium
**How to reproduce/minimize:** A hung Python backend that catches SIGTERM will never exit; `kill()` calls `child.wait()` which blocks forever. The `Drop` impl calls `kill()`, so app shutdown can hang.
**Root cause:** No fallback to SIGKILL and no timeout on `wait()`.
**Fix:** After SIGTERM, `wait_timeout(Duration::from_secs(2))`; if still alive, send SIGKILL, then `wait()`.
**Regression test:** Spawn a script that traps SIGTERM and sleeps; assert `kill()` returns within bounded time and the process is dead.

### BUG-6: `resolve_backend_path` falls back to a relative `.` workspace on Windows resource resolution failure
**File:** `src-tauri/src/main.rs`
**Severity:** Medium
**How to reproduce/minimize:** In a released Windows build, if `app.path().resolve(...)` fails (e.g., bundled resource missing), the fallback uses `MAID_WORKSPACE` or `.` joined with `src/the-maid/backend/run.py`. `.` resolves to the process working directory, which is usually the install dir, not the source tree; the path almost certainly does not exist.
**Root cause:** Unconditional fallback to a dev layout path even in release builds.
**Fix:** Only use the dev fallback when `cfg!(debug_assertions)` or `MAID_WORKSPACE` is set; in release builds, return a hard error so the user sees "bundled backend missing" instead of silent failure-to-spawn.
**Regression test:** Unit test for `resolve_backend_path` with a fake `AppHandle` resource path (requires refactor to accept a path enum). At minimum test that release path never falls back to `./src/...`.

### BUG-7: `setup` thread panics do not propagate; app may launch with no backend and no clear frontend error
**File:** `src-tauri/src/main.rs`
**Severity:** Medium
**How to reproduce/minimize:** If `manager.spawn()` fails and `restart_with_backoff()` also fails, the only signal to the frontend is `backend_ready(false)`. The frontend shows "Backend offline" but the user can still click scan (button disabled only by `backendReady`, but `canScan` is independent). `setup` does not return `Err`, so Tauri still starts.
**Root cause:** Failure is asynchronous; frontend has no persistent "backend failed permanently" state. `backendReady` starts `false` and stays false, but the UI text is subtle.
**Fix:** Add `backend_failed` event with the last error message; make `ScanView`/`App` display an explicit "Backend failed to start" banner and disable all backend-dependent actions when `backendReady` is false and `backendFailed` is true.
**Regression test:** Frontend test that receives `backend_ready(false)` plus a mocked `backend_failed` event and asserts a banner is rendered.

### BUG-8: `Settings::load()` fails on partial JSON instead of merging with defaults
**File:** `src-tauri/src/settings.rs`
**Severity:** Low-Medium
**How to reproduce/minimize:** If `settings.json` is present but missing new fields (e.g., `setup_complete` or `face_cluster`), serde deserializes with defaults and works today. But if a field type changes or contains invalid data (e.g., `eps: -1`), the whole load fails and the app falls back to the defaults in callers that catch the error. However, `save_settings` validates eps, so persisted corruption can only happen if the file is edited externally. Still, `load()` error is opaque to the user.
**Root cause:** All-or-nothing serde deserialization.
**Fix:** Add a migration path: if parse fails, back up the corrupt file to `settings.json.bak` and return defaults; log a warning. This protects user settings from one bad field.
**Regression test:** Write malformed `settings.json`, assert `Settings::load()` returns defaults and the backup file exists.

### BUG-9: `add_bucket` path validation does not canonicalize the path before storing
**File:** `src-tauri/src/commands.rs`
**Severity:** Low
**How to reproduce/minimize:** Add a bucket with path `~/Desktop/../Documents/Work`. `validate_path` expands tilde and checks sandbox, but it returns the non-canonical input string. Later move operations may compare against canonical paths and fail or double-resolve inconsistently. Also, the backend `/approve` endpoint calls `validate_path` independently; mismatched normalization can approve/reject inconsistently.
**Root cause:** `validate_path` returns the user-provided path unchanged.
**Fix:** Return `std::fs::canonicalize` result or at least resolve `.`/`..` before storing. Make Rust and Python normalization semantics match exactly.
**Regression test:** Add a bucket with `~/Desktop/../Documents/Work` and assert the stored path is canonical.

### BUG-10: `commands::approve_and_clean` does not verify that every `approved_id` exists in `proposals`
**File:** `src-tauri/src/commands.rs`
**Severity:** Low
**How to reproduce/minimize:** Send `approved_ids: ["missing"]`. The loop over `proposals` never finds it, so nothing happens, but the command returns `Ok("Approved files moved successfully")` even though zero moves occurred. Also, the function does not actually move files (TODO). Even with TODO, the early validation is misleading.
**Root cause:** Validation only covers paths, not the presence/execution of approved items.
**Fix:** Count matched approved items; if the count != `approved_ids.len()`, return an error listing missing IDs. When execution is implemented, ensure per-file results are returned, not a single string.
**Regression test:** Send approval request with a non-existent file_id; assert error.

### BUG-11: `commands::download_model` resume logic is broken: `use_temp` and `file_path` are both `&tmp`
**File:** `src-tauri/src/commands.rs`
**Severity:** Medium
**How to reproduce/minimize:** Try to resume a partially downloaded model. `use_temp` is computed but never used. `file_path` is always `&tmp`, and when `resume_from > 0` it opens with `.append(true)`, which is correct, but the `use_temp` dead code is confusing. More importantly, if the server returns a non-206 status after a resume attempt, the code deletes the `.part` file and **recursively calls `download_model`**, which means the existing `reqwest` response stream is dropped and the temp file content may be deleted before the partial data is committed. The recursion could also blow the async stack on repeated failures.
**Root cause:** Recursive retry after deleting the partial file; `use_temp` variable redundant; no upper bound on resume attempts.
**Fix:** Replace recursion with a loop, cap resume attempts at 1, and if non-206 after resume, delete `.part` and restart with `resume_from = 0`. Add `tokio::fs::sync_all` after writing final chunk or flush each chunk.
**Regression test:** Mock server returning 200 instead of 206 on resume and assert the download restarts from 0 and completes.

### BUG-12: `download_model` progress `percent` can exceed 100 or drop
**File:** `src-tauri/src/commands.rs`
**Severity:** Low
**How to reproduce/minimize:** When resuming, `total = content_length() + resume_from`. The server may not return `Content-Length` on a 206; `total` becomes `0` and percent stays 0 even near completion. If the server returns the remaining length in `Content-Length` (not full), `total` is correct, but if it returns full file length, `total` doubles and percent rises past 100.
**Root cause:** Assumes `Content-Length` on 206 is remaining bytes. RFC 7233 says 206 `Content-Length` is the length of the partial body unless `Content-Range` is present.
**Fix:** Parse `Content-Range` header to determine real `total` and `resume_from`; if absent, do not compute percent for resumed downloads.
**Regression test:** Mock 206 response with `Content-Range: bytes 50-99/100` and assert percent is 50% at the first chunk.

### BUG-13: `get_model_status` treats directory named `<id>` as downloaded model even if empty
**File:** `src-tauri/src/commands.rs`
**Severity:** Low
**How to reproduce/minimize:** Create an empty directory `~/.the-maid/models/text`. `get_model_status` returns `downloaded: true` and a path pointing to the directory. The app believes a 500 MB model is present and skips download, but loading will fail.
**Root cause:** Directory existence is a weak signal for model presence.
**Fix:** For directory bundles, verify at least one required file exists (e.g., `model.gguf` inside). For `.gguf` files, check `metadata.len() > 0`. Return size in bytes if possible.
**Regression test:** Empty directory `text/` should report not downloaded.

### BUG-14: `version_greater_than` treats non-numeric versions inconsistently
**File:** `src-tauri/src/commands.rs`
**Severity:** Low
**How to reproduce/minimize:** Compare `"1.0.0-beta"` to `"1.0.0"`. The function returns `true` (because `parse_version` fails for beta, branch `(None, Some(_)) => true`), meaning a pre-release tag is considered newer than the stable release. This contradicts semver.
**Root cause:** Unknown version formats default to "newer".
**Fix:** Use a real semver parser (e.g., `semver` crate) or treat non-numeric versions as not-greater. At minimum, return `false` when `parse_version` fails unless both fail and string comparison is meaningful.
**Regression test:** `version_greater_than("1.0.0-beta", "1.0.0")` should be `false`.

### BUG-15: `check_updates` calls a remote endpoint despite privacy-first positioning
**File:** `src-tauri/src/commands.rs`
**Severity:** Low (design / ADR 0007)
**How to reproduce/minimize:** Calling `check_updates()` initiates an outbound HTTP request to `https://themaid.app/api/version` from the user's machine. ADR 0010 says no telemetry, but a version check leaks IP + user agent + timestamp. It is user-initiated, but there is no documented opt-out.
**Root cause:** Network call on update check is inherent; missing privacy disclosure.
**Fix:** Document in the UI that update checks contact the server and what is sent; add an opt-out setting to disable update checks entirely. Consider serving a static file or signed JSON over HTTPS with minimal headers.
**Regression test:** Not applicable; policy issue.

### BUG-16: `App.tsx` hides navigation but still mounts `renderView()` based on `currentView` for first-run users
**File:** `src/the-maid/src/App.tsx`
**Severity:** Low
**How to reproduce/minimize:** On first run, `currentView` defaults to `"setup"`. The sidebar is hidden, so `renderView()` shows `SetupWizard`. Good. But if any child component calls `setCurrentView` (not used in SetupWizard), or if `handleSetupComplete` is triggered when already on `"scan"`, there is no guard. Minor.
**Root cause:** View state is not guarded against first-run transitions.
**Fix:** Add an explicit guard: `if (isFirstRun && currentView !== 'setup') setCurrentView('setup');` in an effect. This prevents accidental view leaks before setup is complete.
**Regression test:** Mount `App` with mocked `setup_complete=false` and attempt to set view to `scan`; assert wizard remains.

### BUG-17: `ScanView` progress listener multiplies by 100 but backend emits `0.0–1.0`
**File:** `src/the-maid/src/components/ScanView.tsx`
**Severity:** Low (UI bug)
**How to reproduce/minimize:** Backend `emit_progress` sends `progress` in `[0,1]`. `ScanView` sets `setProgress(e.payload * 100)`, then displays `{Math.round(progress)}%` — correct. But the `scan_complete` event sets `setProgress(100)` unconditionally, even if the scan returned fewer than `max_files`. If the backend emits `scan_complete` with `count < max`, the progress bar snaps to 100%, which is fine for completion. However, if the Rust command `scan_directory` returns before the Python event stream finishes, `setScanning(false)` happens in both the response `finally` and the `scan_complete` listener, causing a harmless double-set.
**Root cause:** Two paths set `scanning=false`.
**Fix:** Move `setScanning(false)` only into the command response and ignore `scan_complete` for scanning state. Keep progress 100 when complete. Also, the `scan_progress` listener uses `e.payload * 100`; if backend ever sends raw count instead of progress, the bar jumps to 10,000%.
**Regression test:** Frontend test with mocked `scan_progress` payload 0.5 and 1.0; assert 50% and 100%.

### BUG-18: `ScanView` allows scanning even if `backendReady` is false because button label changes but not disabled logic
**File:** `src/the-maid/src/components/ScanView.tsx`
**Severity:** Low
**How to reproduce/minimize:** `scanDisabled = scanning || !directory || !backendReady || !canScan`. The button is correctly disabled. False alarm. But the label `!backendReady ? "Waiting for backend…"` is inside the disabled button, so the user sees the reason. OK.
**Root cause:** None; logic correct. Kept for completeness.
**Fix:** N/A.
**Regression test:** N/A.

### BUG-19: `SetupWizard` `isDownloadComplete` permits `skipped` for required text model
**File:** `src/the-maid/src/components/SetupWizard.tsx`
**Severity:** Low
**How to reproduce/minimize:** `text` is required. In `lib/setup.ts`, `allDownloadsDone` allows non-needed models to be `idle`, `skipped`, or `done`. Because `text` is always needed, it must be `done`. However, `SetupWizard` UI never shows a skip option for text and defaults it to `done`, so this is safe in practice. The pure logic is correct.
**Root cause:** N/A.
**Fix:** N/A.
**Regression test:** N/A.

### BUG-20: `SettingsPanel` removes a sandbox folder without confirming whether scans are in progress
**File:** `src/the-maid/src/components/SettingsPanel.tsx`
**Severity:** Low
**How to reproduce/minimize:** User can remove the only sandbox folder while a scan is running. There is no global "scan in progress" guard. The running scan may fail later or the UI becomes inconsistent (scan started with old list; settings now empty).
**Root cause:** No operation-in-progress lock shared between views.
**Fix:** Add an `App`-level `isBusy` state and disable folder removal while scanning/processing. Or, at minimum, warn before removing the last folder.
**Regression test:** Frontend test: simulate scan in progress, attempt remove folder, assert confirmation/warning or disabled button.

### BUG-21: `BucketManager` uses local state only and never calls Rust backend
**File:** `src/the-maid/src/components/BucketManager.tsx`
**Severity:** Medium
**How to reproduce/minimize:** Add a bucket in the UI; it only updates React state. Reload the app and the bucket is gone. The backend still uses hardcoded defaults in `/buckets`. ADR says buckets are user-approved destination folders; losing them is a UX/data bug.
**Root cause:** Component not wired to `get_buckets`, `add_bucket`, `remove_bucket` commands.
**Fix:** Load buckets on mount via `invoke("get_buckets")`, call `invoke("add_bucket")`/`invoke("remove_bucket")` on mutations, and refresh after.
**Regression test:** Mock Tauri invoke for buckets and assert persistence roundtrip.

### BUG-22: `BucketManager` `Date.now().toString()` IDs can collide on rapid clicks
**File:** `src/the-maid/src/components/BucketManager.tsx`
**Severity:** Low
**How to reproduce/minimize:** Double-click the Add button within the same millisecond produces duplicate IDs, causing React key warnings and inconsistent removal.
**Root cause:** Millisecond timestamp used as ID.
**Fix:** Use a counter or UUID; disable add button while saving.
**Regression test:** Simulate rapid add; assert unique IDs.

### BUG-23: `FaceClusterView` loads empty clusters because Rust command is stubbed
**File:** `src/the-maid/src/components/FaceClusterView.tsx` / `src-tauri/src/commands.rs`
**Severity:** Medium (known TODO, but still a bug in current build)
**How to reproduce/minimize:** Open Faces tab. `get_face_clusters` always returns `Ok(vec![])` in Rust. The UI correctly shows "No clusters found".
**Root cause:** Backend face clustering not wired to Rust command.
**Fix:** Implement `/faces/cluster` Python endpoint and wire it to the Rust command; return real clusters.
**Regression test:** Add integration test with a real face photo once face detector is wired.

### BUG-24: `scanner.py` emits progress too often and double-emits
**File:** `src/the-maid/backend/the_maid/scanner.py`
**Severity:** Low
**How to reproduce/minimize:** For every 100th file, the scanner calls both `self._progress_callback(self.scanned_count)` and `emit_progress(...)`. If a callback is registered, the Rust side forwards the stdout JSON, so progress may be emitted twice (once via callback, once via stdout). Also, `emit_progress` computes `min(count / max_files, 1.0)`, but if `max_files` is 0 (should not happen because constructor default is 10,000 and API enforces `ge=1`), it would divide by zero — guarded.
**Root cause:** Two progress channels.
**Fix:** Use only one channel. Remove `emit_progress` from `FileScanner` and let the caller (orchestrator / API) emit events after the callback. Keep `emit_complete`. Ensure `FileScanner` does not print directly to stdout when imported as a library.
**Regression test:** Count progress events in `test_scanner_events.py` and assert exactly one per 100 files plus completion.

### BUG-25: `scanner.py` does not handle broken symlinks safely for `file_path.is_symlink()`
**File:** `src/the-maid/backend/the_maid/scanner.py`
**Severity:** Low
**How to reproduce/minimize:** A broken symlink inside a sandbox folder: `file_path.is_symlink()` returns `True`, then `file_path.resolve()` raises `OSError`. The catch block correctly continues. But `os.walk(followlinks=False)` already skips directory symlinks; file symlinks are still yielded. The code catches `OSError`, `RuntimeError`, `ValueError`. Good. However, if the symlink target is itself inside the sandbox, `file_path.resolve()` succeeds, but the resulting `validate_path(str(target), sandbox_folders)` may raise `ValueError` if the target is under a different allowed folder not in the current scan path — that is handled. No actual bug, but worth noting.
**Root cause:** N/A.
**Fix:** N/A.
**Regression test:** Existing `test_scanner_symlinks.py::test_broken_symlink_is_skipped` covers it.

### BUG-26: `scanner.py` `scan_directory` returns list instead of generator and loads entire tree into memory
**File:** `src/the-maid/backend/the_maid/scanner.py`
**Severity:** Medium (scalability)
**How to reproduce/minimize:** Scan a directory with 10,000 files. Results list accumulates all metadata in memory before returning. For very large directories this can spike memory and slow response time.
**Root cause:** Eager list.
**Fix:** Stream results to the API response using a generator/iterator, or cap and page. At minimum, keep only the chunk currently being processed.
**Regression test:** Memory benchmark: assert scanner memory is O(1) in file count, not O(n). Add a `max_results` stream test.

### BUG-27: `sandbox.py` `validate_path` resolves symlinks before checking sandbox, allowing symlink escape through timing
**File:** `src-the-maid/backend/the_maid/sandbox.py`
**Severity:** Medium (TOCTOU)
**How to reproduce/minimize:** A malicious process swaps a symlink after `validate_path` resolves it but before the scanner opens it. The scanner's own `_is_safe_dir` and symlink target checks mitigate this for symlinks, but a regular file replaced by a symlink between validation and open can escape.
**Root cause:** Path validation and file access are separate calls; `resolve()` is point-in-time.
**Fix:** Use `O_NOFOLLOW`/`open(..., O_NOFOLLOW)` when opening files and directories; validate after `realpath`/`readlink` at access time. This is the standard TOCTOU defense.
**Regression test:** Hard to test deterministically without race injection; add a code review check and unit test that `is_symlink()` is rechecked before `stat()`.

### BUG-28: `sandbox.py` allows sandbox folders that are themselves symlinks to system dirs
**File:** `src-the-maid/backend/the_maid/sandbox.py`
**Severity:** Medium
**How to reproduce/minimize:** User adds `Desktop` to sandbox folders. If `~/Desktop` is a symlink to `/etc`, `validate_path` resolves it and checks the resolved path, so it is rejected as a system path. Good. But if the sandbox folder is a symlink to `/home/user/Downloads/../etc` or another user-controlled path, it passes. The real risk is if a sandbox folder itself points outside the home tree; `validate_path` resolves and checks containment against the resolved `home/folder`, so it will actually be outside the expected allowed tree and be rejected. So mostly safe, but the error message says "outside the sandbox" rather than explaining the folder is a symlink escape.
**Root cause:** Error messaging.
**Fix:** Improve error message when a sandbox folder resolves to a different location: "Sandbox folder X resolves to Y, which is outside the allowed scope."
**Regression test:** Create `~/Desktop` as symlink to `/tmp` and assert validation rejects with a clear message.

### BUG-29: `models.py` `download_model` is unimplemented and uses `print` instead of structured events
**File:** `src-the-maid/backend/the_maid/models.py`
**Severity:** Low-Medium (feature gap)
**How to reproduce/minimize:** Run `python -m the_maid.models download`. It prints and returns `False`. The Rust side expects to download models; if it delegates to Python later, this function needs real implementation.
**Root cause:** Placeholder.
**Fix:** Implement resumable download with progress events matching `download_model` Rust command, or remove the Python download function and keep Rust as the single downloader.
**Regression test:** N/A until architecture is chosen.

### BUG-30: `api.py` `/scan` endpoint passes `request.directory` to `validate_path` without `sandbox_folders`
**File:** `src/the-maid/backend/the_maid/api.py`
**Severity:** Low
**How to reproduce/minimize:** Rust already validates the directory against sandbox folders before sending. But the Python endpoint does a second validation with no sandbox list, which only rejects system paths. This means a request that bypasses Rust could scan any non-system directory. Defense in depth is weak.
**Fix:** Load sandbox folders from settings in the Python backend and pass them to `validate_path`. Or trust Rust and reject if sandbox list is empty.
**Regression test:** Backend test that `/scan` rejects `/tmp` when sandbox folders are configured to only `Desktop`.

### BUG-31: `api.py` `/approve` endpoint returns "moved" without moving files
**File:** `src/the-maid/backend/the_maid/api.py`
**Severity:** Medium
**How to reproduce/minimize:** Call `/approve` with valid proposals; all return `status: "moved"` but nothing moves.
**Root cause:** TODO left in code.
**Fix:** Implement safe move using `trash` library or `shutil.move` with collision handling, then write metadata tags.
**Regression test:** Integration test: call `/approve` and verify file exists at destination and no longer exists at source (or is in trash).

### BUG-32: `run.py` indentation bug — the `uvicorn.run` call is not inside `if __name__ == "__main__"`
**File:** `src/the-maid/backend/run.py`
**Severity:** High (crash / startup failure)
**How to reproduce/minimize:** Open the file. Lines are:
```python
if __name__ == "__main__":
    print("READY", flush=True)
print("🧹 [The Maid] Python backend ready", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=9473, log_level="info")
```
The `print` on line 15 and `uvicorn.run` on line 16 are outside the `if` block. Worse, `uvicorn.run` is indented by 4 spaces at module level, which is a `IndentationError` at import time. When the sidecar tries to spawn `run.py`, Python will fail immediately with a syntax error, so the sidecar can never reach READY.
**Root cause:** Indentation error introduced (likely in recent edit).
**Fix:** Indent `print` and `uvicorn.run` under `if __name__ == "__main__":`, or remove the emoji `print` entirely (the `READY` line is the contract).
**Regression test:** Python test that imports `run.py` or runs `python run.py` and asserts no `IndentationError`, and that `READY` is printed on stdout.

### BUG-33: `commands.rs` `models_dir()` syntax error: missing `.map_err`
**File:** `src/the-maid/src-tauri/src/commands.rs`
**Severity:** High (does not compile)
**How to reproduce/minimize:** Line 360 reads:
```rust
.or_else(|_| std::env::var("USERPROFILE"))
       map_err(|_| "Cannot determine home directory")?;
```
The `.` before `map_err` is missing, so the file does not compile. This is a clear compile error in the current source.
**Root cause:** Typo / edit mistake.
**Fix:** Change to `.map_err(|_| "Cannot determine home directory")?;`.
**Regression test:** Once GTK libs are available, `cargo check` is the regression test.

### BUG-34: `commands.rs` `get_cleanup_plan` always returns `Ok(None)`
**File:** `src-the-maid/src-tauri/src/commands.rs`
**Severity:** Medium
**How to reproduce/minimize:** Call `get_cleanup_plan`. It always returns `None`. The approval view has a fallback `invoke("get_cleanup_plan").catch(() => {})` that does nothing with the result, so opening the approval view after a scan shows "No proposals yet" even if the backend sent a `cleanup_plan_ready` event.
**Root cause:** Plan is only delivered via events, never persisted/queryable.
**Fix:** Cache the last plan in Rust `AppState` when `cleanup_plan_ready` is received; `get_cleanup_plan` returns the cached plan. Ensure thread-safe storage (`Mutex<Option<CleanupPlanCmd>>`).
**Regression test:** Rust test: emit `cleanup_plan_ready` JSON, then call `get_cleanup_plan` and assert the same payload is returned.

### BUG-35: `commands.rs` `get_scan_progress` always returns 0.0
**File:** `src-the-maid/src-tauri/src/commands.rs`
**Severity:** Low
**How to reproduce/minimize:** Polling `get_scan_progress` always returns 0. Progress only works via events.
**Root cause:** Stub.
**Fix:** Cache progress in `AppState` when `scan_progress` events are received, or remove the polling command and rely on events only.
**Regression test:** N/A until state is cached.

### BUG-36: `commands.rs` `add_sandbox_folder` stores raw input without resolving `~`
**File:** `src-the-maid/src-tauri/src/commands.rs`
**Severity:** Low
**How to reproduce/minimize:** Add folder `~/Videos`. `expand_tilde` is used only to check `is_system_path`, but the raw string `~/Videos` is stored. The settings file will contain `~/Videos`; `ScanView` then passes it to `scan_directory`, where Rust `validate_path` expands it again. It works, but the stored value is non-canonical and backend/Python may receive it unexpanded.
**Fix:** Store canonical/expanded path in settings (or at least consistently expand before persistence and before use).
**Regression test:** Add `~/Videos`, load settings, assert stored path is absolute.

### BUG-37: `commands.rs` `save_settings` does not validate `sandbox_folders` entries
**File:** `src-the-maid/src-tauri/src/commands.rs`
**Severity:** Low
**How to reproduce/minimize:** Call `save_settings` with a settings object containing `sandbox_folders: ["/bin"]`. It persists without error. The next `can_scan` returns true, but scan would be rejected. Worse, `setup_complete` could be set true with only system folders.
**Fix:** In `save_settings`, iterate `sandbox_folders` and reject any `is_system_path`. Also validate bucket paths if present.
**Regression test:** Test `save_settings` with a system path and assert error.

### BUG-38: `commands.rs` `check_sandbox` error leaks normalized path but user input is fine
**File:** `src-the-maid/src-tauri/src/commands.rs`
**Severity:** Low
**How to reproduce/minimize:** Call `check_sandbox("/etc")`; it returns `Err("System directories are out of scope: '/etc'")`. Good.
**Root cause:** N/A.
**Fix:** N/A.
**Regression test:** N/A.

### BUG-39: `settings.rs` `Default` for `FaceClusterSettings` uses `0.0` eps instead of `0.4`
**File:** `src-the-maid/src-tauri/src/settings.rs`
**Severity:** Low
**How to reproduce/minimize:** `#[derive(Default)]` on `FaceClusterSettings` produces `eps: 0.0, min_samples: 0`. The struct also has a manual `new()` returning `eps: 0.4, min_samples: 2`. `Settings::new()` calls `FaceClusterSettings::new()`, so defaults are correct. But if a user ever constructs `FaceClusterSettings::default()` directly, DBSCAN will fail with eps=0 (all points become noise).
**Root cause:** `Default` derivation not aligned with domain default.
**Fix:** Implement `Default` manually for `FaceClusterSettings` to use `new()` values.
**Regression test:** `assert!(Settings::default().face_cluster.eps > 0.0)`.

### BUG-40: `approval.ts` `validateEditedPath` does not reject `..` that escapes when `home` is unknown
**File:** `src/the-maid/src/lib/approval.ts`
**Severity:** Low
**How to reproduce/minimize:** With `home` undefined and sandbox folder `Desktop`, the path `Desktop/../etc/passwd` is normalized by `resolveAgainstHome` to `Desktop/../etc/passwd` → parts `['Desktop','..','etc','passwd']` → stack pops Desktop then pushes `etc` → `etc/passwd`, which does not start with `Desktop`, so it is rejected. Good. But `home` is always provided in `ApprovalView` (via `homeDir`), so this is mostly theoretical. If `home` were missing, `/tmp/Desktop/file` would be rejected because it does not start with `Desktop`. OK.
**Root cause:** N/A.
**Fix:** N/A.
**Regression test:** N/A.

### BUG-41: `approval.ts` `reassignBucket` uses `item.original_filename`, which may contain unsafe characters
**File:** `src/the-maid/src/lib/approval.ts`
**Severity:** Low
**How to reproduce/minimize:** If a filename contains `/` or `\` (rare but possible on some filesystems), the constructed `newPath` will create nested directories or escape. The Rust move code (when implemented) should validate/sanitize.
**Root cause:** Path construction trusts `original_filename`.
**Fix:** Sanitize filename by replacing path separators and null bytes before concatenation. Do the same in Rust before moving.
**Regression test:** Filename `evil/dir.txt` should produce path with sanitized name, not nested directory.

### BUG-42: `useDonation.ts` polling continues if `invoice` object identity changes while URL stays same
**File:** `src/the-maid/src/hooks/useDonation.ts`
**Severity:** Low
**How to reproduce/minimize:** If `setInvoice` is called with a new object for the same invoice, the effect deps `[invoice, paid, terminal]` cause the interval to be cleared and restarted. This can delay polling briefly. Minor.
**Root cause:** Object identity in dependency array.
**Fix:** Use `invoice.verify_url` and `invoice.expiry` as deps instead of the whole object.
**Regression test:** N/A; stability improvement.

### BUG-43: `useDonation.ts` does not stop polling when invoice expires if expiry is from bolt11 only
**File:** `src/the-maid/src/hooks/useDonation.ts`
**Severity:** Low
**How to reproduce/minimize:** If `result.expires_at` is missing, the hook falls back to `parseBolt11Expiry`. It sets `invoice.expiry` from bolt11. The polling effect checks `invoice.expiry !== undefined && isInvoiceExpired(invoice.expiry)` and returns early. So polling stops. Good. But if both `expires_at` and bolt11 expiry are missing, polling runs forever until terminal/paid. This matches behavior for open invoices.
**Root cause:** N/A; acceptable per LNURL.
**Fix:** N/A.
**Regression test:** N/A.

### BUG-44: `SettingsPanel.tsx` `checkForUpdates` does not handle `updateInfo` already present + re-check
**File:** `src/the-maid/src/components/SettingsPanel.tsx`
**Severity:** Low
**How to reproduce/minimize:** Click check updates, then click again. The old `updateInfo` remains visible during loading, which is fine. If an error occurs on the second check, `updateInfo` is not cleared, so stale success info is shown alongside the new error.
**Root cause:** Error handler does not clear previous info.
**Fix:** On error, set `updateInfo(null)`.
**Regression test:** N/A.

### BUG-45: `FaceClusterView.tsx` `cluster.representative_path` loaded via `file://` without sandbox check
**File:** `src/the-maid/src/components/FaceClusterView.tsx`
**Severity:** Low-Medium
**How to reproduce/minimize:** When face clustering returns a representative path, the component renders `<img src={file://...}>`. If the backend ever returns a path outside the sandbox (bug or malicious model), the UI may read arbitrary files via the file protocol. The Tauri CSP is null, so `file://` might be restricted; but if allowed, this is a local file read vector.
**Root cause:** Trusts representative path.
**Fix:** Validate `representative_path` against sandbox folders in Rust before returning; do not render if validation fails. Also set a strict CSP that disallows `file:` sources except for allowed asset paths.
**Regression test:** Rust test: `get_face_clusters` rejects cluster whose representative path is `/etc/passwd`.

### BUG-46: `scanner.py` `emit_complete` is called even if scan is interrupted by exception
**File:** `src/the-maid/backend/the_maid/scanner.py`
**Severity:** Low
**How to reproduce/minimize:** If an unexpected exception occurs during scanning, `scan_directory` raises and `emit_complete` is not reached. But in normal code paths, `emit_complete` is always called. The Rust side might wait forever for `scan_complete` if an exception bubbles. However, the API wraps it in a try/except and returns 500, so events are not sent.
**Root cause:** Event contract is brittle.
**Fix:** Wrap scan in a try/finally that emits `scan_error` or `scan_complete` with `error` field on exception. Update Rust `forward_event` to handle `scan_error`.
**Regression test:** Backend test that raises inside scan and asserts error event is emitted.

### BUG-47: `api.py` `write_metadata` endpoint accepts `List[str]` but no validation/sanitization
**File:** `src/the-maid/backend/the_maid/api.py`
**Severity:** Low
**How to reproduce/minimize:** Pass empty tags, tags with newlines, or very long tags. Endpoint returns `tags_written` count without writing anything. Future implementation must sanitize.
**Root cause:** TODO.
**Fix:** When implementing, validate tags with an allowlist (printable ASCII, length limit) and escape for ExifTool.
**Regression test:** N/A until implemented.

### BUG-48: `commands.rs` `ping_backend` command is synchronous even though `ping` is synchronous
**File:** `src-the-maid/src-tauri/src/commands.rs`
**Severity:** Low
**How to reproduce/minimize:** `ping_backend` is `async` and calls `state.sidecar.ping()`, which does blocking I/O while holding a mutex. In Tauri's async runtime, blocking calls should use `spawn_blocking`. A slow/hung stdin could block an async thread.
**Root cause:** Blocking call in async command.
**Fix:** Wrap `ping()` in `tokio::task::spawn_blocking`.
**Regression test:** Hard without integration; add a note in code.

### BUG-49: `commands.rs` `download_model` emits progress events before file is flushed/renamed
**File:** `src-the-maid/src-tauri/src/commands.rs`
**Severity:** Low
**How to reproduce/minimize:** If the app crashes after the final `complete=true` event but before `rename`, the UI thinks the model is done but the file is still `.part`. On next run `get_model_status` checks for `.gguf` and reports not downloaded, confusing the user.
**Root cause:** Complete event sent before atomic commit.
**Fix:** Rename first, then emit `complete=true`. If rename fails, emit error.
**Regression test:** Simulate crash/restart and assert `.gguf` exists before complete event in test harness.

### BUG-50: `sidecar.rs` `spawn()` waits on `state() == Running` polled every 50ms but has no timeout shorter than `ready_timeout`
**File:** `src-tauri/src/sidecar.rs`
**Severity:** Low
**How to reproduce/minimize:** A script that prints `READY` immediately but then exits quickly: the stdout reader sets state to `Running`, spawn returns `Ok`, and then the child dies. The frontend gets `backend_ready(true)` but the sidecar is already dead. The event-forward thread will emit `backend_crashed` shortly after, but there is a window where the UI enables scanning on a dead backend.
**Root cause:** Readiness signal is not tied to process liveness.
**Fix:** After detecting `READY`, verify `is_alive()` before returning `Ok` from `spawn`. If the child died, return error.
**Regression test:** Script prints READY and exits; `spawn()` should return error, not Ok.

### BUG-51: `App.tsx` `backendReady` defaults to `false`; if `backend_ready(true)` is missed before listener attaches, UI stays disabled
**File:** `src/the-maid/src/App.tsx`
**Severity:** Low
**How to reproduce/minimize:** The listener attaches in `useEffect` after initial render. The Rust `setup` thread emits `backend_ready` in the background. If the event fires between app start and React effect attachment, the frontend never receives it and `backendReady` stays false until a reconnect. Tauri events are usually buffered, but not guaranteed.
**Root cause:** Race between backend readiness and frontend listener registration.
**Fix:** On `useEffect` mount, also call `invoke("ping_backend")` to synchronously check liveness. If it succeeds, set `backendReady(true)`. Keep the listener for subsequent changes.
**Regression test:** Frontend test: render App with backend already ready; assert `ping_backend` is invoked and status becomes ready.

### BUG-52: `setup.ts` `canAdvanceFromStep2` allows all-false features because `general_files` is forced true in UI but not in pure function
**File:** `src/the-maid/src/lib/setup.ts`
**Severity:** Low
**How to reproduce/minimize:** `canAdvanceFromStep2` returns true if any feature is true. In the UI, `general_files` is checked by default and `SetupWizard` always keeps it true (no way to uncheck). The pure function is correct. N/A.
**Root cause:** N/A.
**Fix:** N/A.
**Regression test:** N/A.

### BUG-53: `commands.rs` `get_app_version` returns `CARGO_PKG_VERSION` fallback; if version constant and Cargo version drift, update check is wrong
**File:** `src-the-maid/src-tauri/src/commands.rs`
**Severity:** Low
**How to reproduce/minimize:** `APP_VERSION = "0.1.0"`, Cargo version is also `0.1.0` per `Cargo.toml`. If a future release updates only one, `check_updates` uses `env_version()` (Cargo), while UI might display `APP_VERSION` from a stale constant elsewhere. There is no other use of `APP_VERSION` except fallback, so low risk.
**Root cause:** Duplicate version source.
**Fix:** Remove `APP_VERSION` constant and rely solely on `CARGO_PKG_VERSION`.
**Regression test:** Assert `get_app_version()` equals `CARGO_PKG_VERSION`.

### BUG-54: `scanner.py` `FileScanner._extract_metadata` calls `file_path.stat()` which follows symlinks
**File:** `src/the-maid/backend/the_maid/scanner.py`
**Severity:** Low
**How to reproduce/minimize:** For a symlink inside the sandbox pointing to another file inside the sandbox, `stat()` follows the link and reports the target's size/mtime. That is likely desired (scan the target). For a symlink to outside, the code skips it before `stat()`. Good.
**Root cause:** N/A.
**Fix:** N/A.
**Regression test:** N/A.

### BUG-55: `sandbox.py` `_normalize` uses `path.resolve()` which resolves symlinks, but `validate_path` calls it on `home / f` and on `resolved`. The `os.sep` prefix check may fail on Windows because `os.sep` is `\` while `resolved_str` has been normalized to `\` by `str(path)`. It is fine.
**File:** `src-the-maid/backend/the_maid/sandbox.py`
**Severity:** Low
**How to reproduce/minimize:** On Windows, `resolved_str.startswith(allowed_path + os.sep)` where `os.sep` is `\` and `allowed_path` from `_normalize` is also `\`. Should work. Good.
**Root cause:** N/A.
**Fix:** N/A.
**Regression test:** N/A.

### BUG-56: `models.py` `categorize_file` passes prompt to `self.llm(...)` using dict response indexing that may KeyError
**File:** `src-the-maid/backend/the_maid/models.py`
**Severity:** Medium
**How to reproduce/minimize:** `llama-cpp-python` can return response as a string or with a different shape depending on version/params. The code does `response["choices"][0]["text"]`. If `choices` is missing or empty, it raises `KeyError` or `IndexError`, crashing the categorization call.
**Root cause:** Assumes llama-cpp response shape.
**Fix:** Use `.get()` or a typed wrapper; catch `KeyError`/`IndexError` and return fallback rationale. Match the exact API contract of the pinned llama-cpp version.
**Regression test:** Mock LLM returning `{}` and assert fallback instead of crash.

### BUG-57: `models.py` LLM prompt does not instruct the model to stay within sandbox or existing buckets
**File:** `src/the-maid/backend/the_maid/models.py`
**Severity:** Low-Medium (design)
**How to reproduce/minimize:** The prompt only asks for a JSON destination path. The model may propose `/root/...` or `/etc/...`, which will be rejected by sandbox validation later. The user will see many rejected proposals.
**Root cause:** Prompt lacks bucket list and sandbox constraints.
**Fix:** Include allowed buckets and a constraint line: "Only propose paths inside the user's allowed folders: ... Never propose system directories."
**Regression test:** N/A.

### BUG-58: `main.rs` `forward_event` emits `scan_progress` with `progress` but `ScanView` multiplies by 100. If Python emits count instead of progress, bar overflows
**File:** `src-the-maid/src/main.rs`, `ScanView.tsx`
**Severity:** Low
**How to reproduce/minimize:** If backend `scanner.py` is modified to emit `count` instead of `progress` in `scan_progress`, the frontend will render `count * 100` percent. Current code emits `progress`. OK.
**Root cause:** N/A.
**Fix:** N/A.
**Regression test:** N/A.

### BUG-59: `commands.rs` `add_bucket` returns `Ok(())` and does not return the created bucket id, forcing frontend reload
**File:** `src-the-maid/src-tauri/src/commands.rs`
**Severity:** Low
**How to reproduce/minimize:** Add a bucket via `add_bucket`; command returns `()`. The frontend has to call `get_buckets` again to know the new id. This is inefficient and can lead to stale state if the second call fails.
**Fix:** Return the new `Bucket` (with generated id) from `add_bucket`.
**Regression test:** Rust test asserts returned id is numeric and increments.

### BUG-60: `commands.rs` `get_buckets` does not expand tilde in returned paths
**File:** `src-the-maid/src-tauri/src/commands.rs`
**Severity:** Low
**How to reproduce/minimize:** If buckets are stored with `~/Documents/Work`, the UI receives the raw string. `ApprovalView` resolves via `effectivePath` and passes to Rust validation, which expands. It works but is inconsistent with the ADR requirement that `proposed_path` be absolute.
**Root cause:** Stored bucket paths may contain `~`.
**Fix:** Expand `~` when returning buckets; store absolute paths.
**Regression test:** Add bucket `~/Work`, assert returned path is absolute.

## Summary Table

| # | Severity | File(s) | Title |
|---|----------|---------|-------|
| 32 | High | `run.py` | IndentationError: `uvicorn.run` outside `__main__` block |
| 33 | High | `commands.rs` | Missing `.` before `map_err` in `models_dir()` — compile error |
| 2 | Medium | `sidecar.rs` | `ping()` succeeds without waiting for PONG |
| 6 | Medium | `main.rs` | Bad Windows fallback path in release builds |
| 7 | Medium | `main.rs` | Backend permanent failure not surfaced in UI |
| 11 | Medium | `commands.rs` | Broken resume + recursive retry in `download_model` |
| 12 | Medium | `commands.rs` | Progress percent can exceed 100 / be wrong on resume |
| 21 | Medium | `BucketManager.tsx` | Buckets not persisted to backend |
| 23 | Medium | `FaceClusterView.tsx`/`commands.rs` | Face clusters always empty (stub) |
| 26 | Medium | `scanner.py` | Scanner accumulates full results in memory |
| 27 | Medium | `sandbox.py` | TOCTOU: validation vs. file access race |
| 28 | Medium | `sandbox.py` | Sandbox folder symlink escape messaging |
| 30 | Medium | `api.py` | `/scan` lacks sandbox folder defense in depth |
| 31 | Medium | `api.py` | `/approve` reports moved without moving |
| 34 | Medium | `commands.rs` | `get_cleanup_plan` always returns `None` |
| 39 | Medium | `settings.rs` | `Default` for `FaceClusterSettings` gives eps=0 |
| 45 | Medium | `FaceClusterView.tsx` | `file://` image without sandbox validation |
| 49 | Medium | `commands.rs` | Complete event before atomic model rename |
| 50 | Medium | `sidecar.rs` | `spawn()` can return OK for a process that just died |
| 51 | Medium | `App.tsx` | Frontend can miss `backend_ready` event |
| 56 | Medium | `models.py` | LLM response indexing may crash |
| 57 | Medium | `models.py` | Prompt lacks sandbox/bucket constraints |
| 1 | Medium | `sidecar.rs`/`main.rs` | Silent parse errors + double logging |
| 3 | Low | `sidecar.rs` | Mutex poisoning not handled |
| 4 | Low | `sidecar.rs` | `is_alive()` false on `try_wait` error |
| 5 | Low-Medium | `sidecar.rs` | `kill()` may hang on SIGTERM-ignoring child |
| 8 | Low-Medium | `settings.rs` | Corrupt settings file not recovered gracefully |
| 9 | Low | `commands.rs` | Bucket path not canonicalized before storage |
| 10 | Low | `commands.rs` | `approve_and_clean` misreports missing IDs |
| 13 | Low | `commands.rs` | Empty model directory treated as downloaded |
| 14 | Low | `commands.rs` | Pre-release versions considered newer than stable |
| 15 | Low | `commands.rs` | Update check leaks network metadata (policy) |
| 16 | Low | `App.tsx` | No guard against first-run view leak |
| 17 | Low | `ScanView.tsx` | Progress set from two paths |
| 20 | Low | `SettingsPanel.tsx` | No guard against folder removal during scan |
| 22 | Low | `BucketManager.tsx` | Rapid add can create duplicate IDs |
| 24 | Low | `scanner.py` | Double progress emission |
| 35 | Low | `commands.rs` | `get_scan_progress` always 0 |
| 36 | Low | `commands.rs` | Sandbox folder stored as raw input |
| 37 | Low | `commands.rs` | `save_settings` accepts system folders |
| 41 | Low | `approval.ts` | Filenames with path separators can escape |
| 42 | Low | `useDonation.ts` | Polling interval reset on object identity |
| 44 | Low | `SettingsPanel.tsx` | Stale update info on error |
| 46 | Low | `scanner.py` | No `scan_error` event on exception |
| 47 | Low | `api.py` | Metadata tags not validated/sanitized |
| 48 | Low | `commands.rs` | `ping_backend` blocks async thread |
| 53 | Low | `commands.rs` | Duplicate version source |
| 59 | Low | `commands.rs` | `add_bucket` should return new bucket |
| 60 | Low | `commands.rs` | Bucket paths not expanded for UI |

## Immediate Action Items (compile blockers)
1. Fix `run.py` indentation.
2. Fix `commands.rs` `models_dir()` syntax error.
3. Re-run `cargo check` to confirm compilation.
4. Add a Python test that imports/runs `run.py` without syntax error.

## Post-Mortem
The two compile-time bugs (#32, #33) are the most urgent because they prevent the Rust sidecar from spawning Python and the Rust binary from building. Several medium-severity bugs (#2, #6, #7, #11, #12, #21, #26, #27, #31, #34, #49, #50, #51, #56, #57) should be fixed before a release because they affect reliability, sandbox correctness, or UX. Many low-severity findings are polish or defensive improvements. The codebase already has solid frontend/backend unit test coverage; the main gap is Rust integration tests, which are currently blocked by missing GTK dev libraries in this environment.
