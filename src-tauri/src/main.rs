// Plasma desktop shell — supervises the FastAPI sidecar and hosts the React UI.
// No console window in release (so the backend never shows a taskbar entry).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};

use rand::RngCore;
use tauri::async_runtime::Receiver;
use tauri::{AppHandle, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_updater::UpdaterExt;

// The WebView's origin on Windows. Tauri v2's default custom protocol serves the
// app from `http://tauri.localhost` (with `useHttpsScheme` false, the default), so
// this is the expected value; the backend enforces exact-match, so it MUST equal
// what the WebView actually reports. Verify once on a real Windows build.
const WEBVIEW_ORIGIN: &str = "http://tauri.localhost";

/// Build the pre-load configuration object exposed to the WebView.
fn webview_init_script(api_base: &str, ws_url: &str, token: &str, app_version: &str) -> String {
    format!(
        "window.__CLOAKBROWSER__ = {{ apiBaseUrl: {}, wsUrl: {}, token: {}, appVersion: {} }};",
        serde_json::to_string(api_base).unwrap(),
        serde_json::to_string(ws_url).unwrap(),
        serde_json::to_string(token).unwrap(),
        serde_json::to_string(app_version).unwrap(),
    )
}

/// Tracks the one sidecar owned by this application process. Shutdown takes the
/// retained child out of the slot, which makes termination possible and keeps
/// the supervisor from registering a replacement afterward.
struct BackendLifecycle<C> {
    current_child: Option<C>,
    shutdown_requested: bool,
}

impl<C> BackendLifecycle<C> {
    fn new() -> Self {
        Self {
            current_child: None,
            shutdown_requested: false,
        }
    }

    fn register_child(&mut self, child: C) -> Result<(), C> {
        if self.shutdown_requested || self.current_child.is_some() {
            Err(child)
        } else {
            self.current_child = Some(child);
            Ok(())
        }
    }

    fn child_exited(&mut self) -> Option<C> {
        self.current_child.take()
    }

    fn begin_shutdown(&mut self) -> Option<C> {
        self.shutdown_requested = true;
        self.current_child.take()
    }

    fn should_respawn(&self) -> bool {
        !self.shutdown_requested
    }
}

/// Runs cleanup unless setup reaches its explicit success point. This covers
/// errors and panics after the sidecar has spawned but before Tauri begins
/// delivering application exit events.
struct CleanupGuard<F: FnOnce()> {
    cleanup: Option<F>,
}

impl<F: FnOnce()> CleanupGuard<F> {
    fn new(cleanup: F) -> Self {
        Self {
            cleanup: Some(cleanup),
        }
    }

    fn disarm(&mut self) {
        self.cleanup = None;
    }
}

impl<F: FnOnce()> Drop for CleanupGuard<F> {
    fn drop(&mut self) {
        if let Some(cleanup) = self.cleanup.take() {
            cleanup();
        }
    }
}

#[cfg(test)]
mod tests {
    use std::cell::Cell;

    use super::{webview_init_script, BackendLifecycle, CleanupGuard};

    #[test]
    fn webview_init_script_includes_json_safe_app_version_with_connection_config() {
        let script = webview_init_script(
            "http://127.0.0.1:4312/api/v1",
            "ws://127.0.0.1:4312/api/v1/events",
            "local-token",
            "1.0.1",
        );

        assert!(script.contains("apiBaseUrl: \"http://127.0.0.1:4312/api/v1\""));
        assert!(script.contains("wsUrl: \"ws://127.0.0.1:4312/api/v1/events\""));
        assert!(script.contains("token: \"local-token\""));
        assert!(script.contains("appVersion: \"1.0.1\""));
    }

    #[test]
    fn backend_lifecycle_retains_child_for_shutdown_and_blocks_late_respawn() {
        let mut lifecycle = BackendLifecycle::new();

        assert_eq!(lifecycle.register_child(41), Ok(()));
        assert_eq!(lifecycle.begin_shutdown(), Some(41));
        assert!(!lifecycle.should_respawn());
        assert_eq!(lifecycle.register_child(42), Err(42));
    }

    #[test]
    fn backend_lifecycle_allows_respawn_after_unexpected_exit() {
        let mut lifecycle = BackendLifecycle::new();
        lifecycle.register_child(41).unwrap();

        assert_eq!(lifecycle.child_exited(), Some(41));
        assert!(lifecycle.should_respawn());
        assert_eq!(lifecycle.register_child(42), Ok(()));
    }

    #[test]
    fn cleanup_guard_runs_on_failure_but_can_be_disarmed_after_setup() {
        let cleanups = Cell::new(0);
        {
            let _guard = CleanupGuard::new(|| cleanups.set(cleanups.get() + 1));
        }
        assert_eq!(cleanups.get(), 1);

        {
            let mut guard = CleanupGuard::new(|| cleanups.set(cleanups.get() + 1));
            guard.disarm();
        }
        assert_eq!(cleanups.get(), 1);
    }
}

/// Ask the OS for a free loopback port, then release it for the sidecar to bind.
fn free_loopback_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .expect("failed to reserve a loopback port")
        .local_addr()
        .expect("failed to read the reserved port")
        .port()
}

/// A fresh per-process token — proves a request came from THIS shell, not another
/// local process. Regenerated every launch; never persisted, never put in a URL.
fn per_process_token() -> String {
    let mut bytes = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut bytes);
    hex::encode(bytes)
}

struct BackendSupervisor {
    lifecycle: Mutex<BackendLifecycle<CommandChild>>,
}

impl BackendSupervisor {
    fn new() -> Self {
        Self {
            lifecycle: Mutex::new(BackendLifecycle::new()),
        }
    }

    fn lifecycle(&self) -> MutexGuard<'_, BackendLifecycle<CommandChild>> {
        self.lifecycle
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    /// Spawn the frozen FastAPI backend and retain its process handle. Holding
    /// the lifecycle lock across spawn closes the race where shutdown could be
    /// requested after the check but before the new child is registered.
    fn spawn_backend(
        &self,
        app: &AppHandle,
        port: u16,
        token: &str,
    ) -> Option<Receiver<CommandEvent>> {
        let mut lifecycle = self.lifecycle();
        if !lifecycle.should_respawn() {
            return None;
        }

        let (rx, child) = app
            .shell()
            .sidecar("plasma-backend")
            .expect("plasma-backend sidecar not found")
            .env("PLASMA_PORT", port.to_string())
            .env("PLASMA_LOCAL_TOKEN", token.to_string())
            .env("PLASMA_REQUIRE_LOCAL_TOKEN", "1")
            .env("PLASMA_ALLOWED_ORIGIN", WEBVIEW_ORIGIN)
            .spawn()
            .expect("failed to spawn plasma-backend");

        if let Err(unexpected_child) = lifecycle.register_child(child) {
            let _ = unexpected_child.kill();
            return None;
        }
        Some(rx)
    }

    fn child_exited(&self) {
        self.lifecycle().child_exited();
    }

    fn should_respawn(&self) -> bool {
        self.lifecycle().should_respawn()
    }

    /// Disable future respawns before terminating the current child. This is
    /// idempotent because Tauri may report both ExitRequested and Exit.
    fn shutdown(&self) {
        let child = self.lifecycle().begin_shutdown();
        if let Some(child) = child {
            if let Err(error) = child.kill() {
                eprintln!("[backend] failed to terminate sidecar during shutdown: {error}");
            }
        }
    }
}

/// True once the sidecar answers its public liveness probe (`/livez` → 200). A raw
/// HTTP/1.0 GET so we need no HTTP-client dep; a bare TCP accept isn't enough because
/// uvicorn binds the socket before the app has finished starting.
fn backend_ready(port: u16) -> bool {
    let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let req = format!(
        "GET /livez HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut buf = String::new();
    let _ = stream.read_to_string(&mut buf);
    buf.starts_with("HTTP/1.1 200") || buf.starts_with("HTTP/1.0 200")
}

/// Check the cloud update endpoint once at startup; if a newer signed build is
/// offered, download, verify (Ed25519 over the installer, done by the plugin),
/// install, and relaunch. Entirely best-effort: any failure — offline, no
/// release, bad signature — is logged and swallowed so it never blocks launch.
/// The endpoint + pubkey live in tauri.conf.json; a dev build (no updater
/// config / unsigned) simply returns an error here and is ignored.
async fn check_for_update(app: AppHandle) {
    let updater = match app.updater() {
        Ok(updater) => updater,
        Err(error) => {
            eprintln!("[updater] unavailable: {error}");
            return;
        }
    };
    match updater.check().await {
        Ok(Some(update)) => {
            eprintln!("[updater] installing {} -> {}", update.current_version, update.version);
            if let Err(error) = update.download_and_install(|_, _| {}, || {}).await {
                eprintln!("[updater] install failed: {error}");
                return;
            }
            app.restart();
        }
        Ok(None) => eprintln!("[updater] up to date"),
        Err(error) => eprintln!("[updater] check failed: {error}"),
    }
}

fn main() {
    let backend = Arc::new(BackendSupervisor::new());
    let setup_backend = Arc::clone(&backend);

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(move |app| {
            let cleanup_backend = Arc::clone(&setup_backend);
            let mut setup_cleanup = CleanupGuard::new(move || cleanup_backend.shutdown());
            let port = free_loopback_port();
            let token = per_process_token();

            // First spawn, then a supervisor that respawns on unexpected exit with a
            // capped backoff (reusing the same port + token, so the already-loaded
            // WebView keeps working). Gives up after repeated fast crashes.
            let first_rx = setup_backend
                .spawn_backend(&app.handle(), port, &token)
                .expect("backend shutdown requested during initial spawn");
            let sup_app = app.handle().clone();
            let sup_token = token.clone();
            let supervisor = Arc::clone(&setup_backend);
            tauri::async_runtime::spawn(async move {
                let mut rx = first_rx;
                let mut fails: u32 = 0;
                loop {
                    let started = Instant::now();
                    while let Some(event) = rx.recv().await {
                        // Surface backend stderr for diagnostics; NEVER log the token.
                        if let CommandEvent::Stderr(line) = event {
                            eprintln!("[backend] {}", String::from_utf8_lossy(&line));
                        }
                    }
                    // Channel closed => the sidecar exited.
                    supervisor.child_exited();
                    if !supervisor.should_respawn() {
                        break;
                    }
                    if started.elapsed().as_secs() >= 30 {
                        fails = 0; // ran healthily for a while; not a crash loop
                    }
                    fails += 1;
                    if fails > 10 {
                        eprintln!("[backend] gave up respawning after repeated fast exits");
                        break;
                    }
                    let backoff = std::cmp::min(fails, 5) as u64;
                    eprintln!("[backend] exited; respawning in {backoff}s (attempt {fails})");
                    tokio::time::sleep(Duration::from_secs(backoff)).await;
                    let Some(next_rx) = supervisor.spawn_backend(&sup_app, port, &sup_token) else {
                        break;
                    };
                    rx = next_rx;
                }
            });

            // Hand (apiBaseUrl, wsUrl, token) to the WebView BEFORE the page loads,
            // via window.__CLOAKBROWSER__ — the existing frontend config reads it, so
            // no frontend change is needed. The token travels only here, not in a URL.
            let api_base = format!("http://127.0.0.1:{port}/api/v1");
            let ws_url = format!("ws://127.0.0.1:{port}/api/v1/events");
            let init = webview_init_script(&api_base, &ws_url, &token, env!("CARGO_PKG_VERSION"));

            // Readiness gate: wait for the sidecar to answer /livez before showing the
            // UI, so the SPA's first API calls don't race the backend's startup. Cap the
            // wait so a wedged backend still shows the window (the SPA shows its own
            // error state). setup runs before any window exists, so this blocks nothing.
            let deadline = Instant::now() + Duration::from_secs(15);
            while Instant::now() < deadline && !backend_ready(port) {
                std::thread::sleep(Duration::from_millis(100));
            }

            WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title("Plasma")
                .inner_size(1280.0, 800.0)
                .min_inner_size(960.0, 640.0)
                .initialization_script(&init)
                .build()?;

            // Check for an app update in the background once the window is up.
            let update_app = app.handle().clone();
            tauri::async_runtime::spawn(check_for_update(update_app));

            setup_cleanup.disarm();
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Plasma");

    app.run(move |_app_handle, event| {
        if matches!(
            event,
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
        ) {
            backend.shutdown();
        }
    });
}
