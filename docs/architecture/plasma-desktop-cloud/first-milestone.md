# First milestone — desktop v1 (lowest-risk path)

**Status:** implementation plan (planning only; no product code written yet). Scope = ship an
installable, self-hardened **local** desktop Plasma that a first cohort can run, *before* any cloud
account/licence exists. Cloud auth/activation land in milestone 2 (see [authentication.md](authentication.md),
[activation-and-entitlements.md](activation-and-entitlements.md)).

Guiding rule: every step is independently shippable, reversible, and leaves the current
`vite dev + uvicorn` workflow working until the last cutover.

## Why this ordering

The single hard gate is legal, not technical — bundling/serving the CloakBrowser engine to customers
needs a CloakHQ OEM/SaaS licence (`BINARY-LICENSE.md:93`). So milestone 1 deliberately ships the
**desktop shell + local hardening** (which needs no engine-redistribution deal, because each user's
machine still auto-downloads the engine from CloakHQ) and **defers** the paid cloud/licence flow
until that agreement exists.

## Phase 0 — legal + prerequisites (blocking, no code)

- [ ] Written CloakHQ position on per-user auto-download inside a commercial Plasma app, or an
      OEM/SaaS quote (`info@cloakbrowser.dev`). **Gate for selling**, not for building/testing.
- [ ] Windows code-signing certificate (OV or EV) procured.
- Acceptance: legal answer on file; cert usable by the CI signer.

## Phase 1 — loopback hardening (backend-only, tiny, high value)

**Goal:** a rogue local process cannot drive Plasma even if it guesses the port + Origin.

- The mechanism already exists but is unwired: `install_token` is generated per install
  (`config.py:48-68`) and `require_local_token` is a constant-time Bearer check
  (`security.py:24-35`) — but the API router is gated only by the owner session (`api.py:24`).
- [ ] Add `require_local_token` as a **router-level dependency** on `api_router` (and the WS
      `/events`), alongside the existing session/CSRF/Origin checks.
- [ ] Support a **per-process** token via env (`PLASMA_LOCAL_TOKEN`) that overrides the on-disk
      install-token file when present, so a token read from disk can't outlive the process.
- [ ] Frontend `http.ts` attaches `Authorization: Bearer <token>` on every request (token injected
      at runtime, never in a URL/log). In dev, read it from an env-seeded `window.__PLASMA__`.
- **Feature flag:** `PLASMA_REQUIRE_LOCAL_TOKEN` (default off in dev, on in packaged builds) so the
  browser dev workflow keeps working during the transition.
- **Tests-first:** request without the bearer → 401; with it → passes; WS handshake without it →
  4401; token never appears in logs (secret-scan test). **Rollback:** flip the flag off.
- Acceptance: non-slow suite green; manual curl without token is rejected on a packaged build.

## Phase 2 — data_root rename with back-compat (backend-only)

**Goal:** move to `%LOCALAPPDATA%\Plasma\` without orphaning existing profiles.

- Today `data_root` = `%LOCALAPPDATA%\CloakBrowser\Manager` (`config.py:10-14`); the export magic,
  `%LOCALAPPDATA%\CloakBrowser` dir, and API field names are intentionally kept as "CloakBrowser"
  (per project memory) — so the rename touches **only** the on-disk data root, nothing wire-facing.
- [ ] Resolution order for `data_root`: `CLOAK_MANAGER_DATA_ROOT` env → `%LOCALAPPDATA%\Plasma` (new)
      → **if absent but the legacy `%LOCALAPPDATA%\CloakBrowser\Manager` exists, adopt it in place**
      (no move) and log a one-time notice. A move/copy is opt-in, not automatic (avoids a risky
      multi-GB profile copy on first launch).
- **Feature flag:** `PLASMA_DATA_ROOT_MODE = legacy|plasma|auto` (default `auto`).
- **Tests-first:** fresh install → uses `…\Plasma`; existing legacy dir + no Plasma dir → adopts
      legacy; both present → prefers `…\Plasma`. **Rollback:** `legacy` mode.
- Acceptance: existing profiles open unchanged; a fresh box creates `…\Plasma`.

## Phase 3 — Tauri shell + PyInstaller sidecar (packaging skeleton)

**Goal:** one signed `.exe` that starts the backend and shows the UI. (See
[desktop-packaging.md](desktop-packaging.md) for the decision + supervisor design.)

- [ ] `src-tauri/` Tauri v2 project loading the built React `dist/`.
- [ ] PyInstaller **onedir** spec for `manager_backend` (freeze the FastAPI app), shipped as a Tauri
      `externalBin` sidecar.
- [ ] Rust supervisor: pick a free loopback port, mint a per-process token, spawn the sidecar with
      `PLASMA_LOCAL_TOKEN`/`PLASMA_PORT`/`CLOAK_MANAGER_DATA_ROOT=%LOCALAPPDATA%\Plasma`, poll
      `/api/v1/health` until ready, restart on unexpected exit, forward `(port, token)` to the WebView
      via IPC.
- [ ] Add the Tauri WebView origin (`https://tauri.localhost`) to `allowed_origin` (or serve the SPA
      from the backend) — keep the exact-Origin + CSRF checks intact.
- [ ] Sidecar runs **windowless** (`CREATE_NO_WINDOW`) → no stray console taskbar entry.
- **Tests:** health-handshake integration test (spawn frozen sidecar, hit `/health` with the token);
  supervisor restart test. **Rollback:** ship nothing — dev workflow unaffected.
- Acceptance: double-click launches Plasma, a profile starts, the taskbar shows the Plasma icon
  (validated by [../../windows-icons-startup/manual-icon-verification.md](../../windows-icons-startup/manual-icon-verification.md)).

## Phase 4 — installer, update, uninstall (packaging)

- [ ] NSIS installer via the Tauri bundler, **Authenticode-signed**; bundle the WebView2 evergreen
      bootstrapper + the PyInstaller backend. Engine binary is **not** bundled.
- [ ] Tauri **signed updater** (Ed25519/minisign over the update manifest) for shell + sidecar;
      atomic swap + rollback to the prior version dir; DB migrates on next start **after** the
      existing auto-backup (`backups/service.py`).
- [ ] NSIS custom uninstall page: separate **"Delete local browser profiles?"** question, default
      **Keep** (see [local-data-ownership.md](local-data-ownership.md)).
- **Tests:** update-manifest signature verify (good/tampered); failed-swap rollback; uninstall
      preserve-vs-delete on a seeded `data_root`.
- Acceptance: install → upgrade → repair → uninstall(keep) all preserve profiles; uninstall(delete)
  removes them only after the second confirm.

## Milestone 1 exit criteria

- Signed installer produces a working local Plasma; profiles/proxies/launch/diagnostics all function.
- Loopback API rejects untokened local callers; no secret in any log; binary verification untouched.
- Existing profiles survive install/upgrade/reinstall.
- **Not** in milestone 1 (needs milestone 2 + the licence deal): cloud login, activation keys, device
  registration, entitlement gating, offline grace, auto-start, CDP automation.

## What comes next (milestone 2, summary)

Cloud control plane + PKCE login + device identity + activation/entitlement gating + offline grace —
each its own doc in this folder. Milestone 1 stays valuable even if the cloud slips, because it is a
self-contained, signed, local product.
