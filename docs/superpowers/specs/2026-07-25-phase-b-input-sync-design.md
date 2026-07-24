# Phase B — Input Sync (control-window mirror) Design

**Goal:** Interact with one running profile ("control") and mirror clicks, keystrokes,
typing, scroll, and navigation to all other selected running profiles ("followers"),
Hidemium-style.

**Status:** Feasibility spiked and confirmed (2026-07-25). `--remote-debugging-port=0`
on the stealth-binary launch opens an externally reachable CDP endpoint
(`DevToolsActivePort` written, `/json/version` returns Chrome 146); CDP
`Input.dispatchKeyEvent`, `Input.insertText`, and `Input.dispatchMouseEvent` all
register in the page. Spike: `scratchpad/spike_cdp_sync.py`.

## Architecture

Today there is **no** control channel into a running profile's page content: the main
launch opens no debug port, and the live Playwright context is thread-confined to the
worker. So Phase B adds a CDP channel.

### 1. Launch — expose a CDP endpoint (launcher.py)
- Append `--remote-debugging-port=0` to the args in `persistent_context_kwargs`
  **only for headed runtime launches** (`headless=False`); headless utility/diagnostic
  launches stay clean.
- After launch, the handle reads `<user-data-dir>/DevToolsActivePort` (first line = port;
  poll up to ~5s) and exposes it. The worker persists
  `runtime.cdp_endpoint = "http://127.0.0.1:<port>"` (the currently-dead column) next to
  `browser_pid`, so the sync service can find it.
- Stealth: 127.0.0.1-only, random ephemeral port. The browser is already CDP-driven via
  Playwright, so this adds no new web-detectable signal — only a local attack surface,
  accepted for a local desktop app.

### 2. Sync service (new: features/runtime/sync_service.py)
Async, runs on the FastAPI loop (workers use sync Playwright on their own threads; this
uses `async_playwright` — separate instances, no conflict).

- Connect to the control endpoint + each follower endpoint via `connect_over_cdp`.
- Control page: `Runtime.addBinding("__plasmaSync")`, then inject a capture script (on the
  current page AND `addScriptToEvaluateOnNewDocument` for navigations) that
  `addEventListener`s pointerdown/up, keydown/up, input, wheel and reports
  `{type, x, y, button, key, code, text, deltaX, deltaY, ...}` via `window.__plasmaSync`.
- On each `Runtime.bindingCalled`, fan out to followers:
  - pointer → `Input.dispatchMouseEvent` (mousePressed/mouseReleased/mouseMoved) at the
    same viewport coords.
  - key → `Input.dispatchKeyEvent` (keyDown/keyUp) + `Input.insertText` for the typed text.
  - wheel → `Input.dispatchMouseEvent` type=mouseWheel.
- Navigation: subscribe to the control's main-frame `Page.frameNavigated`; call
  `page.goto(url)` on each follower.
- One active session at a time (app.state.input_sync). Stop tears down bindings + closes
  the CDP connections (does not close the browsers).

### 3. Routes (features/runtime/routes.py)
- `POST /runtime/sync/start` `{control_profile_id, follower_profile_ids}` → 409 if any
  selected profile has no `cdp_endpoint` (needs relaunch) or a session is already running.
- `POST /runtime/sync/stop` → tears down.
- `GET /runtime/sync/status` → `{active, control_profile_id, follower_profile_ids}`.

### 4. Frontend (features/synchronize/)
- A "Sync input" panel below the tiling console: control radio + follower checkboxes
  (running profiles only), Start/Stop, live status. Nudge to "Tile first" so windows are
  equal-sized (coords are viewport-relative). Disable + explain when a profile lacks an
  endpoint ("relaunch to enable sync").

## v1 scope boundaries
- Mirrors clicks, keystrokes, typing, scroll, navigation on the **active tab** only.
  New tabs / popups out of scope.
- Coordinates are viewport-relative → accurate on **equal-sized** (tiled) windows.
- Debug port always-on for headed profiles; already-running profiles relaunch once.

## Testing
- Launcher: unit-test the `DevToolsActivePort` read + endpoint persistence (fake file).
- Sync service: unit-test event → CDP-command translation with a fake CDP session
  (assert a captured click yields the right `Input.dispatchMouseEvent`, a key yields the
  right `Input.dispatchKeyEvent`, navigation yields `goto`).
- Routes: 409 without endpoints; start/stop/status happy path with a fake service.
- Frontend: panel renders running profiles, disables start without endpoints, calls the
  start mutation with the chosen control + followers.
