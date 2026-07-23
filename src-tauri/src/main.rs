// Plasma desktop shell — supervises the FastAPI sidecar and hosts the React UI.
// No console window in release (so the backend never shows a taskbar entry).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::time::{Duration, Instant};

use rand::RngCore;
use tauri::async_runtime::Receiver;
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

// The WebView's origin on Windows. Tauri v2's default custom protocol serves the
// app from `http://tauri.localhost` (with `useHttpsScheme` false, the default), so
// this is the expected value; the backend enforces exact-match, so it MUST equal
// what the WebView actually reports. Verify once on a real Windows build.
const WEBVIEW_ORIGIN: &str = "http://tauri.localhost";

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

/// Spawn the frozen FastAPI backend on `port`, injecting the port + secrets. Returns
/// the event stream; the channel closes when the process exits (drives respawn).
fn spawn_backend(app: &AppHandle, port: u16, token: &str) -> Receiver<CommandEvent> {
    let (rx, _child) = app
        .shell()
        .sidecar("plasma-backend")
        .expect("plasma-backend sidecar not found")
        .env("PLASMA_PORT", port.to_string())
        .env("PLASMA_LOCAL_TOKEN", token.to_string())
        .env("PLASMA_REQUIRE_LOCAL_TOKEN", "1")
        .env("PLASMA_ALLOWED_ORIGIN", WEBVIEW_ORIGIN)
        .spawn()
        .expect("failed to spawn plasma-backend");
    rx
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

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let port = free_loopback_port();
            let token = per_process_token();

            // First spawn, then a supervisor that respawns on unexpected exit with a
            // capped backoff (reusing the same port + token, so the already-loaded
            // WebView keeps working). Gives up after repeated fast crashes.
            let first_rx = spawn_backend(&app.handle(), port, &token);
            let sup_app = app.handle().clone();
            let sup_token = token.clone();
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
                    rx = spawn_backend(&sup_app, port, &sup_token);
                }
            });

            // Hand (apiBaseUrl, wsUrl, token) to the WebView BEFORE the page loads,
            // via window.__CLOAKBROWSER__ — the existing frontend config reads it, so
            // no frontend change is needed. The token travels only here, not in a URL.
            let api_base = format!("http://127.0.0.1:{port}/api/v1");
            let ws_url = format!("ws://127.0.0.1:{port}/api/v1/events");
            let init = format!(
                "window.__CLOAKBROWSER__ = {{ apiBaseUrl: {}, wsUrl: {}, token: {} }};",
                serde_json::to_string(&api_base).unwrap(),
                serde_json::to_string(&ws_url).unwrap(),
                serde_json::to_string(&token).unwrap(),
            );

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

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Plasma");
}
