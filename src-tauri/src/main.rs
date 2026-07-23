// Plasma desktop shell — supervises the FastAPI sidecar and hosts the React UI.
// No console window in release (so the backend never shows a taskbar entry).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpListener;

use rand::RngCore;
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

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

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let port = free_loopback_port();
            let token = per_process_token();
            // The WebView's origin on Windows (verify per Tauri version; the backend
            // enforces exact-match, so it must equal what the shell reports).
            let webview_origin = "http://tauri.localhost";

            // Spawn the frozen FastAPI backend, injecting the port + secrets. The
            // backend binds 127.0.0.1:<port> and requires the token on every call.
            let (mut rx, _child) = app
                .shell()
                .sidecar("plasma-backend")
                .expect("plasma-backend sidecar not found")
                .env("PLASMA_PORT", port.to_string())
                .env("PLASMA_LOCAL_TOKEN", token.clone())
                .env("PLASMA_REQUIRE_LOCAL_TOKEN", "1")
                .env("PLASMA_ALLOWED_ORIGIN", webview_origin)
                .spawn()
                .expect("failed to spawn plasma-backend");

            // Surface backend stderr for diagnostics; NEVER log the token.
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    if let CommandEvent::Stderr(line) = event {
                        eprintln!("[backend] {}", String::from_utf8_lossy(&line));
                    }
                    // TODO: on CommandEvent::Terminated, respawn with backoff.
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

            WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title("Plasma")
                .inner_size(1280.0, 800.0)
                .min_inner_size(960.0, 640.0)
                .initialization_script(&init)
                .build()?;

            // TODO (readiness): poll http://127.0.0.1:<port>/api/v1/health before
            // navigating, or let the SPA show a "starting…" state and retry.
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Plasma");
}
