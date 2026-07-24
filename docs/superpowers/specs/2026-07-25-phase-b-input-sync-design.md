# Phase B — Input Sync (control-window mirror) Design

**Goal:** Interact with one running profile ("control") and mirror clicks, keystrokes,
typing, scroll, and navigation to all other selected running profiles ("followers"),
Hidemium-style.

**Status:** Built and **verified live** (2026-07-25). Two real stealth-binary
profiles, one driving the other through the shipped `InputSyncService`:

```
[nav]   follower url mirrored: True
[click] control=1 follower=1  mirrored: True
[focus] control: t  follower: t
[keys]  control='HELLO' follower='HELLO'  mirrored: True
```

Notes from verification:

- Focus propagates only through *user input*. Clicking the control's field mirrors
  the click, which focuses the follower's field, after which keystrokes land. A
  driver-level `page.focus()` mirrors nothing (it is not an input event) — worth
  remembering when writing further tests.
- The nav mirror deliberately ignores `data:`/`about:`/`chrome:` URLs, so any test
  of it must serve a real `http://` page.

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

### 2. Sync service (features/runtime/input_sync.py)
Async, runs on the FastAPI loop (workers use sync Playwright on their own threads; this
uses `async_playwright` — separate instances, no conflict).

- Connect to the control endpoint + each follower endpoint via `connect_over_cdp`.
- Control page: `Page.createIsolatedWorld` + `Runtime.evaluate` a capture script into
  that world. It `addEventListener`s pointerdown/up, keydown/up, wheel and buffers
  `{kind, type, x, y, button, key, code, text, dx, dy}` into an array the service
  drains every 50ms. **Why not `Runtime.addBinding`:** in the main world it exposes a
  callable global the page can enumerate, and it does not reach an isolated world
  without `Runtime.enable` — itself a known CDP-detection signal. Verified: the page
  sees `window.__q` and `window.__drain` as `undefined`. The world dies on navigation,
  so `Page.frameNavigated` re-arms it.
- For each drained event, fan out to followers:
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

## Scope
- Mirrors clicks, keystrokes, typing, scroll and navigation.
- **Multi-tab (v2):** every control tab is drained each tick and its events replay on
  the follower's tab at the same index, so switching tabs needs no "active tab"
  tracking. Follower tab counts are reconciled to the control's each tick — opening a
  tab in the control opens one in each follower, closing one closes the extras.
  Capped at `_MAX_TABS` so a popup loop can't spawn unbounded tabs.
- Coordinates are viewport-relative → accurate on **equal-sized** (tiled) windows.
- Debug port always-on for headed profiles; already-running profiles relaunch once.
- One sync session at a time.

## Testing
- Launcher: unit-test the `DevToolsActivePort` read + endpoint persistence (fake file).
- Sync service: `translate_event` is pure, so the event → CDP-command contract is unit
  tested without a browser. (This is why swapping the whole capture mechanism from
  `addBinding` to isolated-world polling broke none of its tests.)
- Routes: 409 without endpoints; start/stop/status happy path with a fake service.
- Frontend: panel renders running profiles, disables start without endpoints, calls the
  start mutation with the chosen control + followers.
- **`tests/manager/e2e/test_input_sync_e2e.py`** — the only test that proves the mirror
  itself: two real profiles, asserting navigation, clicks, typing and a second tab all
  reach the follower. Marked `manager_e2e`. Its teeth were verified by mutation
  (neutering `_fanout` makes it fail at the click), so it cannot rot into a vacuous pass.
