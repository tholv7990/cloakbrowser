# Desktop build (Phase 3 scaffold)

**Status:** scaffolding. The backend pieces (sidecar entrypoint, env-driven
`allowed_origin`) are implemented + tested in-repo. The **Tauri shell, PyInstaller
freeze, and installer must be built on Windows** with the Rust + PyInstaller
toolchains — they can't run in the dev container here. This doc is the runbook.

## Pieces in the repo

| Path | What | Tested here? |
|---|---|---|
| `manager_backend/serve.py` | Sidecar entrypoint — `uvicorn.run(create_app, host=127.0.0.1, port=$PLASMA_PORT, factory=True)` | ✅ (`tests/manager/test_serve.py`) |
| `manager_backend/config.py` | `allowed_origin` ← `PLASMA_ALLOWED_ORIGIN`; `require_local_token` ← `PLASMA_REQUIRE_LOCAL_TOKEN`; per-process `PLASMA_LOCAL_TOKEN`; `data_root` → `%LOCALAPPDATA%\Plasma` (adopt-legacy) | ✅ |
| `src-tauri/` | Tauri v2 shell: `tauri.conf.json`, `Cargo.toml`, `src/main.rs` supervisor | ⛔ build on Windows |
| `src-tauri/plasma-backend.spec` | PyInstaller freeze of the backend | ⛔ build on Windows |

## How it fits together at runtime

```
plasma.exe (Tauri shell)
  ├─ pick free 127.0.0.1 port P; mint per-process token T (32 random bytes)
  ├─ spawn sidecar plasma-backend.exe  (env: PLASMA_PORT=P, PLASMA_LOCAL_TOKEN=T,
  │        PLASMA_REQUIRE_LOCAL_TOKEN=1, PLASMA_ALLOWED_ORIGIN=<webview origin>)
  │        → uvicorn serves FastAPI on 127.0.0.1:P; every /api/v1 call needs T
  └─ WebView loads the bundled React app; an init script sets
     window.__CLOAKBROWSER__ = { apiBaseUrl: http://127.0.0.1:P/api/v1, wsUrl, token: T }
     → the existing frontend picks it up (no frontend change), sends Authorization: Bearer T
```

The engine binary still auto-downloads to `~/.cloakbrowser` and self-verifies — it is
**never** bundled (technical + licence requirement).

## Build steps (Windows)

Prereqs: Node, Python 3.13 with the app installed (`pip install -e ".[serve]"`),
Rust (`rustup`), Tauri CLI (`npm i -g @tauri-apps/cli`), `pip install pyinstaller`.

1. **Freeze the backend** (from repo root):
   ```
   pyinstaller src-tauri/plasma-backend.spec --noconfirm
   ```
   Copy `dist/plasma-backend/` into the Tauri sidecar slot, renaming the exe to the
   target triple Tauri expects:
   ```
   src-tauri/binaries/plasma-backend-x86_64-pc-windows-msvc.exe   (+ its _internal folder)
   ```
2. **App icon** — generate the icon set from a Plasma PNG:
   ```
   tauri icon path\to\plasma-1024.png     # writes src-tauri/icons/*
   ```
3. **Build the app + installer**:
   ```
   tauri build     # runs `npm run build` for the frontend, compiles the shell, bundles NSIS
   ```
   Output: `src-tauri/target/release/bundle/nsis/Plasma_1.0.0_x64-setup.exe`.

## To verify before shipping

- **WebView origin.** `main.rs` reports `http://tauri.localhost`; confirm the actual
  origin your Tauri version uses on Windows and keep `PLASMA_ALLOWED_ORIGIN` in sync
  (the backend enforces exact match). If it differs, update the one string in `main.rs`.
- **Readiness.** `main.rs` has a TODO to poll `/api/v1/health` (or let the SPA retry)
  before the UI expects the API.
- **Restart.** `main.rs` has a TODO to respawn the sidecar on unexpected exit.
## Phase 4 — signing, updater, uninstall (wired)

- **Updater endpoint (done).** The cloud exposes `GET /updates/tauri/{target}/{current_version}`
  returning Tauri v2's dynamic-update JSON (`version`, `pub_date`, `url`, `signature`,
  `notes`) or **204** when up to date — a small adapter over the signed release row.
  `tauri.conf.json` points `plugins.updater.endpoints` at it. Set `pubkey` to your
  **Tauri minisign public key**, and store the installer's minisign signature in the
  release row's `signature` (publish via `updates.publish_release`). Generate the
  updater keypair with `tauri signer generate`.
- **Authenticode signing (config in place, needs a cert).** `bundle.windows` sets
  `certificateThumbprint` / `digestAlgorithm` (sha256) / `timestampUrl`. Install your
  OV/EV cert in the Windows store and replace the thumbprint; `tauri build` then signs
  the exe + NSIS installer. (Alternatively use a `signCommand` for an HSM/cloud signer.)
- **Preserve/delete uninstall (done).** `src-tauri/nsis-hooks.nsh`
  (`bundle.windows.nsis.installerHooks`) adds a separate uninstall prompt — default
  **Keep** — that only removes `%LOCALAPPDATA%\Plasma` on explicit Yes; a legacy
  `CloakBrowser\Manager` root is never touched.

## Shell supervisor (implemented)

`src-tauri/src/main.rs` now:

- **Readiness-gates the UI** — after spawning the sidecar it polls the backend's public
  `GET /livez` (raw HTTP, no dep) and only builds the window once it answers 200 (15 s
  cap, then shows the window anyway). Prevents the SPA's first API calls racing startup.
- **Respawns the sidecar on unexpected exit** — a supervisor task restarts it with a
  capped backoff (reusing the same port + token so the loaded WebView keeps working),
  giving up after repeated fast crashes; resets the counter after a healthy run.

## Still to verify (needs a Windows build)

- **WebView origin** — `WEBVIEW_ORIGIN` in `main.rs` is Tauri v2's Windows default
  (`http://tauri.localhost`); confirm it on a real build and keep `PLASMA_ALLOWED_ORIGIN`
  in sync (the backend enforces exact match).
- **Minimum-supported-version** — the release row carries `min_supported_version`; wire
  a client check (or a server 426) to force-update clients below it.

## Not bundled / not weakened

- CloakBrowser engine binary: auto-downloaded per user from CloakHQ, self-verified
  (Ed25519→SHA256) — untouched.
- The loopback token gate + origin/CSRF/session checks are additive.
