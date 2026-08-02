# Desktop Version and Migration Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a `Plasma 1.0.1` installer whose frozen backend contains Alembic migration `0020_fingerprint_overrides` and whose sidebar displays the installed desktop version.

**Architecture:** Treat the Tauri package version as the desktop-version source of truth and inject it through the existing WebView initialization object. Preserve Alembic and the existing database; prevent packaging regressions by testing the PyInstaller spec and inspecting the final frozen archive.

**Tech Stack:** Python/PyInstaller/Alembic, Rust/Tauri 2, React/TypeScript/Vitest, NSIS.

## Global Constraints

- Do not modify, downgrade, or delete the user's database.
- Desktop release version is exactly `1.0.1`.
- Desktop version comes from Tauri package metadata, not Chromium or backend API metadata.
- The complete `manager_backend/migrations` directory must ship in the sidecar.
- Existing unrelated working-tree files remain untouched.

---

### Task 1: Lock migration packaging with a regression test

**Files:**
- Create: `tests/manager/test_desktop_packaging.py`
- Modify: `src-tauri/plasma-backend.spec`

**Interfaces:**
- Consumes: repository migration files and PyInstaller `datas` configuration.
- Produces: a packaging contract that includes `manager_backend/migrations` and current head `0020_fingerprint_overrides.py`.

- [ ] **Step 1: Write the failing packaging test**

Add a test that parses/runs the spec's data-file helper and asserts that the migration source directory exists and contains `0020_fingerprint_overrides.py`. The production change that makes it pass is a repository-root-based migration data mapping rather than fragile `..` paths.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/manager/test_desktop_packaging.py -q`
Expected: FAIL because the current spec exposes no testable root-based data mapping.

- [ ] **Step 3: Implement the minimal stable mapping**

Resolve repository paths from `SPEC`/`Path(__file__)` context in `plasma-backend.spec`, keeping destination paths `manager_backend` and `manager_backend/migrations` unchanged.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/manager/test_desktop_packaging.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `fix(desktop): package all database migrations`

### Task 2: Inject the canonical desktop version

**Files:**
- Modify: `src-tauri/tauri.conf.json`
- Modify: `src-tauri/Cargo.toml`
- Modify: `src-tauri/Cargo.lock`
- Modify: `src-tauri/src/main.rs`

**Interfaces:**
- Produces: `window.__CLOAKBROWSER__.appVersion: string` populated from `env!("CARGO_PKG_VERSION")`.

- [ ] **Step 1: Write a failing Rust unit test**

Extract a pure `webview_init_script(api_base: &str, ws_url: &str, token: &str, app_version: &str) -> String` contract and test that the generated script contains JSON-safe `appVersion: "1.0.1"` alongside the existing endpoint/token fields.

- [ ] **Step 2: Verify RED**

Run: `cargo test --manifest-path src-tauri/Cargo.toml`
Expected: FAIL because `webview_init_script` and `appVersion` do not exist.

- [ ] **Step 3: Implement version injection and bump metadata**

Set both Tauri and Cargo versions to `1.0.1`, update the lockfile through Cargo, implement the pure script builder, and call it with `env!("CARGO_PKG_VERSION")`.

- [ ] **Step 4: Verify GREEN**

Run: `cargo test --manifest-path src-tauri/Cargo.toml`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat(desktop): expose application version`

### Task 3: Display the version in the sidebar

**Files:**
- Modify: `manager/frontend/src/vite-env.d.ts`
- Modify: `manager/frontend/src/api/config.ts`
- Modify: `manager/frontend/src/layouts/Sidebar.tsx`
- Create or modify: `manager/frontend/src/layouts/Sidebar.test.tsx`

**Interfaces:**
- Consumes: optional runtime `appVersion`.
- Produces: expanded footer text `Plasma v1.0.1`; no misleading label when absent.

- [ ] **Step 1: Write failing frontend tests**

Render the sidebar with injected `appVersion: "1.0.1"` and assert `Plasma v1.0.1` is visible. Render without `appVersion` and assert no desktop-version label is present.

- [ ] **Step 2: Verify RED**

Run: `npm --prefix manager/frontend run test -- src/layouts/Sidebar.test.tsx`
Expected: FAIL because the runtime config and footer do not expose the version.

- [ ] **Step 3: Implement the minimal footer**

Type and export the optional desktop version from runtime config, render it beside the collapse control in expanded mode, and retain an accessible title in collapsed mode.

- [ ] **Step 4: Verify GREEN**

Run: `npm --prefix manager/frontend run test -- src/layouts/Sidebar.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat(manager-ui): display desktop app version`

### Task 4: Build and verify the fixed installer

**Files:**
- Generated: `dist/plasma-backend.exe`
- Generated: `src-tauri/binaries/plasma-backend-x86_64-pc-windows-msvc.exe`
- Generated: `src-tauri/target/release/bundle/nsis/Plasma_1.0.1_x64-setup.exe`

**Interfaces:**
- Produces: installable `1.0.1` upgrade preserving `%LOCALAPPDATA%\Plasma`.

- [ ] **Step 1: Run release gates**

Run frontend typecheck/tests/build, `cargo test --manifest-path src-tauri/Cargo.toml`, and focused manager packaging/migration tests.

- [ ] **Step 2: Freeze the backend**

Run: `python -m PyInstaller src-tauri/plasma-backend.spec --noconfirm --clean`
Expected: `dist/plasma-backend.exe`.

- [ ] **Step 3: Inspect the frozen archive**

Run PyInstaller archive viewer and assert it lists `manager_backend\\migrations\\versions\\0020_fingerprint_overrides.py`.

- [ ] **Step 4: Build the installer**

Run: `.\build.ps1 -SkipFrontendInstall`
Expected: `src-tauri/target/release/bundle/nsis/Plasma_1.0.1_x64-setup.exe`.

- [ ] **Step 5: Verify and report**

Record installer timestamp, size, SHA-256, Authenticode/updater signature status, and confirm no build processes remain.

