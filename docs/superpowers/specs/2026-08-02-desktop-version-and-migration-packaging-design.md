# Desktop version and migration packaging design

## Goal

Ship a desktop build that starts successfully when the local database is already at Alembic revision `0020_fingerprint_overrides`, and make the installed Plasma desktop version visible in the application.

## Root cause

The failing installation is running a stale packaged backend that predates migration `0020`, while its persistent database has already been upgraded to that revision. The current source tree and newly frozen sidecar contain `0020_fingerprint_overrides.py`; the installed application must therefore be upgraded with a distinctly versioned installer.

## Design

- Bump the Tauri desktop package and installer version from `1.0.0` to `1.0.1` in the canonical Tauri configuration and matching Rust package metadata.
- Keep Alembic as the only schema upgrade mechanism. Do not rewrite, downgrade, or delete the user's database.
- Add a packaging regression test that verifies the PyInstaller sidecar specification includes the complete `manager_backend/migrations` directory, including the current head revision.
- Pass the Tauri package version to the WebView in the existing `window.__CLOAKBROWSER__` initialization object as `appVersion`.
- Extend the frontend runtime configuration type with optional `appVersion`. Display `Plasma v<version>` at the bottom of the expanded sidebar; display `v<version>` as accessible hover text when collapsed. In non-Tauri development mode, omit the label rather than showing a misleading build version.
- Keep the existing backend `/app/version` response unchanged because it describes manager API, CloakBrowser, and Chromium versions—not the desktop shell version.

## Testing

- A backend packaging test fails if the migration directory or current Alembic head is absent from the PyInstaller specification/package input.
- A Rust unit test verifies the initialization script carries the package version without exposing or changing token handling.
- A frontend sidebar test verifies the injected desktop version is shown and that no version label is rendered when it is unavailable.
- Run focused tests, the frontend typecheck/test/build gate, Rust tests, freeze the sidecar, inspect the frozen archive for `0020_fingerprint_overrides.py`, and build the `1.0.1` NSIS installer.

## Release behavior

Installing `Plasma_1.0.1_x64-setup.exe` upgrades the stale `1.0.0` installation and replaces its packaged sidecar. Existing `%LOCALAPPDATA%\Plasma` data remains intact and Alembic advances it normally.
