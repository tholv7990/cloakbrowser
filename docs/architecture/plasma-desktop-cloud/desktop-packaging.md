# Desktop Packaging

**Status:** Recommendation. Planning only — no packaging code exists yet in the repo
(confirmed: no `tauri.conf`, `electron`, `*.spec`, PyInstaller/Nuitka config anywhere;
root scan clean as of `main@fd6b199`).

## Confirmed current state (source-grounded)

- **Frontend:** a Vite + React + TypeScript SPA under `manager/frontend/` (build tooling
  is Vite; dev server binds a loopback origin). It talks to the local backend over HTTP.
- **Backend:** a FastAPI app under `manager_backend/`, constructed by
  `create_app()` in `manager_backend/main.py`. It **hard-refuses any non-loopback host**
  — `manager_backend/main.py:60-61` raises `ValueError("CloakBrowser Manager must bind to
  127.0.0.1")`; the default host is `127.0.0.1:8765` (`manager_backend/config.py:21-22`),
  and the allowed browser origin is the single exact string
  `http://127.0.0.1:5273` (`manager_backend/config.py:23`).
- **Browser engine:** the manager *launches* a separately-downloaded, source-patched
  CloakBrowser Chromium via Playwright (`manager_backend/features/runtime/launcher.py`).
  The engine runs as its own OS processes; it is **not** the same Chromium the UI renders in.
- There is **no** desktop shell, installer, updater, or process supervisor today. The app
  runs as `vite dev` + `uvicorn` in two terminals.

The packaging job is therefore: **wrap the existing SPA + FastAPI backend into one signed,
updatable Windows application, without touching the CloakBrowser engine or its verification.**

## Options evaluated

| Dimension | **Tauri v2** (recommended) | Electron | Python + embedded WebView (pywebview) |
|---|---|---|---|
| Installer size | Shell ~3–10 MB + WebView2 bootstrap (~1.5 MB, usually a no-op) + PyInstaller backend ~40–90 MB → **~50–100 MB** | Bundles full Chromium ~85 MB + backend ~40–90 MB → **~150–200 MB** | pywebview ~small + PyInstaller of the *whole* app ~60–120 MB |
| Memory (idle) | Uses system WebView2 (shared Edge runtime) → **low baseline** | Ships its own Chromium per app → **highest** | WebView2/Edge via pywebview → low |
| Windows compat | Win10 1803+/Win11; needs **WebView2 runtime** (evergreen on Win11, auto-present on updated Win10; bootstrapper auto-installs) | Self-contained, no runtime dep | Needs WebView2 (same caveat as Tauri) |
| Python/FastAPI sidecar mgmt | First-class **sidecar** (`externalBin`) with lifecycle bound to the app; thin Rust supervisor | `child_process.spawn` from main process; DIY supervision | Backend runs **in-process** (same interpreter) — simplest, but couples UI thread & backend crash |
| Localhost security | Backend still loopback; inject a **per-process token** over Tauri IPC (never in URL) | Same model; inject token from main process | Same process → no cross-process attack surface for the API, but weaker isolation |
| Code signing | Authenticode on NSIS/MSI bundle + the exe; well documented | Authenticode via electron-builder | Authenticode on the PyInstaller exe |
| Auto-updates | Built-in **signed updater** (Ed25519/minisign over the update manifest) | electron-updater / Squirrel (mature) | No built-in updater — DIY (weakest) |
| Chromium conflicts | **None** — UI = WebView2 (Edge), engine = CloakBrowser Chromium, clearly distinct | Ships a *second* vanilla Chromium alongside CloakBrowser's patched one — wasteful and confusing | None (WebView2) |
| Dev complexity | Higher: Rust toolchain to *build* the shell (we write almost no Rust), PyInstaller for backend | Familiar JS-only shell; PyInstaller for backend | Lowest: pure Python, but loses the updater/supervisor story |
| Headed CloakBrowser windows | Identical to all others — engine launches as separate OS processes; shell only renders the manager UI | Identical | Identical |
| Reuse current React | **100%** — load the existing `dist/` into the webview unchanged | 100% | 100% |
| Crash recovery | Rust supervisor restarts a dead backend; existing startup reconcile recovers browsers/locks | DIY supervisor in main process | Backend crash can take the UI with it (same process) |
| AV false-positive risk | Small native binary; the PyInstaller sidecar is the only real magnet → mitigate | Electron + Chromium + PyInstaller = larger heuristic surface | PyInstaller-onefile of a big app is a known magnet |

Notes carried into the comparison:
- The **AV magnet in every option is the PyInstaller-frozen Python backend**, not the shell.
  Mitigate identically everywhere: Authenticode-sign, use **onedir** (not onefile), avoid UPX,
  and submit builds to Microsoft/major AV vendors for allow-listing.
- "Headed CloakBrowser windows" is a non-differentiator: the engine is spawned by the backend
  via Playwright regardless of shell, so all options behave the same.

## Recommendation

**Tauri v2**, with:

1. The **existing React/Vite SPA unchanged** — Tauri loads the production `dist/` bundle.
2. The **FastAPI backend frozen with PyInstaller (onedir)** and shipped as a Tauri
   **sidecar** (`externalBin`), started/stopped with the app.
3. A **thin Rust supervisor** in the Tauri shell that: allocates a free loopback port,
   generates a fresh per-process token, launches the sidecar with both, health-checks it,
   restarts it on unexpected exit, and forwards the token/port to the webview via Tauri IPC.

Why Tauri wins for *this* product specifically: it is the only option that does **not** ship
a second Chromium next to CloakBrowser's patched engine. For a fingerprint-stealth product,
a redundant vanilla Chromium is both wasted footprint and an avoidable AV/user-confusion
signal. Tauri's WebView2 UI is visibly and structurally distinct from the launched browser
windows. The trade-off is Rust build-toolchain complexity, which is bounded because we write
essentially no application logic in Rust — only sidecar/supervisor glue and `tauri.conf`.

Electron remains the fallback if Rust build infrastructure proves too costly for the team; it
loses on size, memory, and the double-Chromium concern but keeps a JS-only mental model.
pywebview is rejected for v1 because it has no first-class signed updater and couples the UI
and backend into one process (a backend crash blanks the UI).

## Sidecar & process-supervision design

```
Tauri shell (Rust)                     PyInstaller sidecar (FastAPI)
  ├─ pick free port P on 127.0.0.1
  ├─ token T = 32 bytes CSPRNG
  ├─ spawn backend(env: PLASMA_LOCAL_TOKEN=T, PLASMA_PORT=P,
  │                     CLOAK_MANAGER_DATA_ROOT=%LOCALAPPDATA%\Plasma)
  ├─ poll http://127.0.0.1:P/api/v1/health until ready (bounded)
  ├─ hand (P, T) to the WebView via Tauri IPC  ── never via URL/query ──►  window.__PLASMA__ = {port,token}
  └─ on backend exit(code≠stopping): log, backoff, respawn; surface a UI banner
```

- **Loopback auth (per-process, not a shipped secret).** The backend *already* contains the
  mechanism: `install_token` is generated per install (`config.py:48-68`, `secrets.token_urlsafe(32)`,
  file `0o600`) and a `require_local_token` Bearer dependency exists
  (`manager_backend/security.py:24-35`, constant-time compare). **Today that dependency is
  defined but not attached to the API router** (the router is gated only by the owner
  session — `manager_backend/api.py:24`). The desktop migration wires `require_local_token`
  as a router-level dependency and has Tauri inject the token, so a rogue local process that
  guesses the port and Origin still cannot call the API without `T`. Prefer a **per-process**
  token (fresh each launch, passed by the supervisor) over the persisted install-token file,
  so a token leaked from disk does not outlive the process.
- **Origin model.** The Tauri WebView origin on Windows is `https://tauri.localhost` (or
  `tauri://localhost`). Either (a) add that exact origin to `allowed_origin`, or (b) serve the
  SPA from the backend so the origin is the loopback URL. Keep the existing exact-string Origin
  check (`dependencies.py:29-32`) and CSRF double-submit (`auth/sessions.py:61-65`) intact.
- **Tokens never in URLs/logs.** `T` travels only via IPC and the `Authorization` header;
  it is excluded from request logging. This satisfies the "no token in URL/log/plaintext SQLite"
  requirement.
- **Port strategy.** Prefer an ephemeral free port over the fixed `8765` to avoid collisions
  with a second instance and to reduce the value of a fixed target; single-instance lock
  prevents two shells racing the same `data_root`.

## Installer, upgrade, repair, uninstall

- **Installer:** Tauri bundler → **NSIS** (recommended for the custom uninstall prompt) or WiX
  MSI, **Authenticode-signed** (EV or OV cert). Bundles the shell, the WebView2 bootstrapper,
  and the PyInstaller backend directory. The CloakBrowser Chromium is **not** bundled — it
  auto-downloads on first launch and self-verifies (Ed25519-then-SHA256), unchanged.
- **Data root:** `%LOCALAPPDATA%\Plasma\` with subdirs `state\`, `db\` (SQLite), `profiles\`,
  `extensions\`, `diagnostics\`, `logs\`, `backups\`, `update-staging\`. (Today the backend
  uses `%LOCALAPPDATA%\CloakBrowser\Manager`; see `migration-plan.md` for the rename/compat.)
- **Upgrade:** Tauri signed updater replaces the shell + sidecar **atomically** (stage → verify
  hash + signature → swap → relaunch). On next launch the backend runs Alembic to head
  (`apply_schema`, `db.py`) **after** an automatic pre-migration DB backup
  (`features/backups` already does `VACUUM INTO` snapshots). Failed swap rolls back to the
  prior version directory.
- **Repair:** reinstall app files only; never touch `data_root` (profiles/db/backups survive).
- **Uninstall:** NSIS custom page asks a **separate, explicit question**: *"Delete your local
  browser profiles and data?"* — default **Keep**. Keep → remove app files + `state/`, `logs/`,
  `update-staging/` only; leave `profiles/`, `db/`, `backups/`. Delete → also remove
  `profiles/`, `db/`, `backups/` after a second confirmation. Never delete silently.

## Open decisions for the product owner

- WebView2 delivery: rely on the **Evergreen bootstrapper** (tiny, online) vs bundle the
  **Fixed Version** runtime (~150 MB, offline-safe). Recommend Evergreen for v1.
- Certificate type: **OV** (cheaper, has SmartScreen reputation ramp-up) vs **EV** (immediate
  SmartScreen trust, hardware token). Recommend EV if budget allows, given AV/SmartScreen
  sensitivity for this product category.
- Installer framework: **NSIS** (needed for the custom preserve/delete uninstall page) vs MSI
  (better for managed/enterprise deployment). Recommend NSIS for v1.
