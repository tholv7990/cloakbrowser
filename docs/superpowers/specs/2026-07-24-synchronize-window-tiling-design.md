# Synchronize — Window Tiling (Phase A) — Design

**Date:** 2026-07-24
**Status:** Approved (design); implementation pending
**Scope:** Phase A of a Hidemium-style "Synchronize" feature. Phase A = **arrange the
open browser windows of running profiles on a monitor** (Grid / Cascade). Phase B (input
mirroring — "1 click → all profiles") is explicitly **out of scope** here and gets its own
spec.

## Goal & context

Multi-accounting operators want to see many profile windows at once, tidily laid out.
Hidemium's "Synchronize" screen does two things: (1) tile the windows, (2) mirror input
from a "Main" window to "Controlled" windows. This spec covers **only (1)**.

Plasma is **Windows-only**. Every running profile is a real Chromium window on the
desktop. `manager_backend/features/runtime/window_icon.py` already enumerates each
profile's top-level windows (by `--user-data-dir` → Chrome pids → `EnumWindows` → HWND)
to stamp taskbar icons. Phase A reuses that enumeration to **position** those windows.

## Non-goals

- No input mirroring / Main-vs-Controlled window model (Phase B).
- No "Uniform size" toggle (Grid is inherently uniform) or "View windows"/bring-to-front.
- No cross-platform positioning. Windows-only, matching the product.
- No new licensing/capability gate — this is core local functionality.

## Positioning mechanism (decision)

Use **direct Win32 `SetWindowPos`** on each profile's main window, reusing the
`window_icon.py` enumeration. Runs synchronously in the request thread — no CDP, no
per-worker command-queue plumbing.

**Rejected alternative:** CDP `Browser.setWindowBounds` via the live `_cdp()` session on
each `_PersistentContextHandle`. It is cross-platform, but Playwright's sync CDP is
thread-affine, so it would require dispatching a command into each worker thread and
plumbing a result back. Not worth it on a Windows-only app when the Win32 enumeration
already exists. `ponytail:` reuse over new machinery.

**Fingerprint coherence:** tiling makes a window **smaller** than the spoofed 1920×1080
screen. A window ≤ screen is normal and coherent (audit F-015 only forbids window *larger*
than screen), so there is **no fingerprint regression**. Windows are restored (un-maximized)
before being positioned.

## Backend

New module `manager_backend/features/runtime/windows.py` and two routes added to the
existing runtime router (`features/runtime/routes.py`).

### Endpoints

- **`GET /api/v1/runtime/monitors`**
  → `{ "monitors": [ { "id": str, "label": str, "width": int, "height": int,
        "work_area": { "x": int, "y": int, "width": int, "height": int },
        "is_primary": bool } ] }`
  Enumerated via Win32 `EnumDisplayMonitors` + `GetMonitorInfo` (MONITORINFOEX gives
  `rcMonitor`, `rcWork`, primary flag, device name). `id` is the 0-based index as a
  string; `label` is a human string (e.g. `"Monitor 1 (1920×1080)"`, `" — Primary"`).

- **`POST /api/v1/runtime/windows/arrange`**
  body → `{ "profile_ids": [str], "monitor_id": str, "layout": "grid" | "cascade" }`
  → `{ "results": [ { "profile_id": str, "ok": bool, "error": str | null } ] }`
  `error` values: `"not_running"` (no live window found for the profile),
  `"position_failed"` (window found but `SetWindowPos` failed). Unknown `monitor_id`
  falls back to the primary monitor. Empty `profile_ids` → `{ "results": [] }`.

### Layout math (pure, unit-tested)

`compute_layout(n, work_area, layout) -> list[Rect]` where `Rect = (x, y, w, h)` in
absolute virtual-desktop coordinates. `work_area = (wx, wy, W, H)`.

- **Grid:** `cols = ceil(sqrt(n))`, `rows = ceil(n / cols)`.
  `cell_w = W // cols`, `cell_h = H // rows`. Window `i` (0-based):
  `col = i % cols`, `row = i // cols`,
  `x = wx + col*cell_w`, `y = wy + row*cell_h`, `w = cell_w`, `h = cell_h`.
  The right/bottom cells extend to the work-area edge to absorb integer remainder.

- **Cascade:** fixed window size `cw = round(W*0.6)`, `ch = round(H*0.7)`; step `= 32px`.
  `slots = max(1, min((W-cw)//step, (H-ch)//step))`; window `i`:
  `slot = i % slots`, `x = wx + slot*step`, `y = wy + slot*step`, `w = cw`, `h = ch`.
  Wrapping keeps every window fully on-screen.

### Arrange flow

`arrange_windows(items, work_area, layout, *, find_window, move_window)`:
`items = [(profile_id, user_data_dir)]`. Dependencies `find_window(user_data_dir)->hwnd|None`
and `move_window(hwnd, rect)->bool` are **injected** (real = Win32; tests = fakes),
matching the codebase's injectable-dependency pattern.

1. Resolve which items have a live window (`find_window` non-None). Others → `not_running`.
2. `compute_layout(len(running), work_area, layout)` → rects.
3. For each running item + its rect, `move_window`; record `ok` / `position_failed`.
4. Return results **in the original `profile_ids` order**.

The route resolves each `profile_id` to `settings.profile_root / profile_id / "user-data"`,
validates the profile exists (DB), selects the monitor by `monitor_id` (default primary),
and calls `arrange_windows`.

### Win32 primitives (in `windows.py`)

- `list_monitors()` — `EnumDisplayMonitors` + `GetMonitorInfoW`.
- `find_main_window(user_data_dir)` — reuse `_profile_chrome_pids`; `EnumWindows` for a
  **visible, titled, top-level** window owned by those pids (the browser frame); return the
  first. `None` if none (profile not running / no window yet).
- `move_window(hwnd, rect)` — `ShowWindow(hwnd, SW_RESTORE)` then
  `SetWindowPos(hwnd, 0, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE)`.
- All best-effort and Windows-guarded (`sys.platform != "win32"` → empty/False), like
  `window_icon.py`.

## Frontend

New page `manager/frontend/src/features/synchronize/SynchronizePage.tsx` + a left-nav entry
"Synchronize" and route.

- **Left panel:** the running profiles (reuse the existing runtime/profiles query, filtered
  to `status == running`), each with a checkbox; default all checked. Shows profile name +
  a running badge, matching existing list styling.
- **Right panel ("Console"):** Monitor `<select>` (from `GET monitors`, default primary),
  Layout radio (Grid / Cascade), **Tile windows** button → `POST arrange` with the checked
  profile ids. Per-profile result surfaced inline (ok / not-running / failed).
- **API client:** add `getMonitors()` and `arrangeWindows(payload)` to the runtime API
  (real adapter → the two endpoints; mock adapter → canned monitors + all-ok results).
- **Types:** `Monitor`, `ArrangeLayout`, `ArrangeResult` in `types/api.ts`.
- **i18n:** en + vi strings.
- No capability flag — always shown.

## Data flow

```
Synchronize page ──GET /runtime/monitors──▶ backend (EnumDisplayMonitors)
                 ──POST /runtime/windows/arrange {ids, monitor, layout}──▶
                     resolve user-data dirs ▸ find live windows ▸ compute_layout
                     ▸ SetWindowPos each ▸ results[]  ◀── inline status per profile
```

## Error handling

- Non-running profile in the request → `ok:false, error:"not_running"` (not an exception).
- `SetWindowPos` failure → `ok:false, error:"position_failed"`.
- Unknown `monitor_id` → primary monitor (never a 4xx for a stale monitor list).
- Non-Windows host → monitors `[]`, arrange all `not_running` (feature simply inert).
- No secrets involved; results carry only profile ids + fixed error codes.

## Testing

- **Backend unit (pure):** `compute_layout` — grid col/row math for n=1,2,3,4,5,9;
  remainder absorption at edges; cascade wrap; n=0. No Win32 in these tests.
- **Backend arrange:** `arrange_windows` with fake `find_window`/`move_window` —
  all-running, some not-running (order preserved, correct rect count), position failure,
  empty list.
- **Backend routes:** `monitors` with a stubbed enumerator; `arrange` with a fake
  positioner injected on `app.state`, asserting response shape + error codes.
- **Frontend:** SynchronizePage against the mock adapter — renders running list, selects a
  layout + monitor, POSTs arrange, shows per-profile results.

## Future (Phase B, separate spec)

Input mirroring: inject a capture observer into a "Main" window and replay mouse/keyboard/
scroll/navigation into "Controlled" windows via CDP `Input.dispatch*`, with per-profile
timing jitter to avoid a trivial cross-profile correlation signal. The Synchronize page's
list + console is the home for the Main/Controlled model.
