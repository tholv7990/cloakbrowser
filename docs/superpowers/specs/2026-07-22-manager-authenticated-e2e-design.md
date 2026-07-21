# Manager Authenticated Windows End-to-End Validation

## Scope

Provide a repeatable authenticated smoke suite for the local Windows Manager after runtime observability, portability, extensions, and diagnostics ship. It validates real backend/frontend/browser integration without resetting the owner's account or embedding credentials.

## Credential handling

The suite reads `CLOAK_MANAGER_EMAIL` and `CLOAK_MANAGER_PASSWORD` from the process environment. It never accepts credentials as command-line flags, writes them to reports, captures them in screenshots, or commits them. Missing variables skip the live suite with a clear reason. The CloakBrowser license continues to resolve from `CLOAKBROWSER_LICENSE_KEY`.

## Test fixture

The suite creates a uniquely named disposable profile, a manager-owned temporary unpacked extension, and deterministic local cookie fixture. It uses no proxy by default. All created resource IDs and directories are recorded in memory for cleanup. Cleanup stops the owned browser, unregisters the extension, trashes then purges the disposable profile through supported APIs, and removes only the exact suite-owned temporary directory after resolved-path validation.

## Scenario

1. Start backend and frontend on configured loopback ports and verify health.
2. Log in through the UI and verify session/CSRF behavior.
3. Create a Windows profile and partially edit its notes without resetting other fields.
4. Register and assign the temporary unpacked extension.
5. Import fixture cookies and export them for semantic round-trip comparison.
6. Launch the profile, verify running-session count, runtime WebSocket state, and sanitized log entries.
7. Verify the extension is present in the launched browser.
8. Stop the profile and verify count/log transitions.
9. Export the profile and import a copy; verify new identity/seed and equivalent editable configuration.
10. Run deterministic local diagnostics. Optional live Pixelscan/IPhey/Cloudflare/Google tests require `CLOAK_LIVE_DIAGNOSTICS=1`.
11. Verify copy/open-directory path containment. Opening Explorer is asserted through an injected adapter in automated runs and may be enabled manually.
12. Clean up suite-owned resources.

## Reports

Write a redacted JSON and Markdown report below `artifacts/manager-e2e/<timestamp>`. Include commit, platform, browser tier/version, step timings, result codes, created disposable IDs, and cleanup status. Exclude passwords, cookies, license values, CSRF/session tokens, proxy credentials, full DOM, and user profile data.

## Success criteria

The deterministic authenticated suite passes on Windows against a clean temporary Manager data root. The live-existing-owner run passes when credentials are supplied. Backend tests, frontend tests, typecheck, production build, OpenAPI drift check, secret scan, and clean Git status are final gates.
