# Synchronize — Window Tiling (Phase A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated "Synchronize" page that tiles the open browser windows of running profiles on a chosen monitor (Grid / Cascade).

**Architecture:** A Windows-only backend module (`features/runtime/windows.py`) enumerates monitors and each running profile's main window via Win32 (reusing `window_icon._profile_chrome_pids`), and positions windows with `SetWindowPos`. Pure layout math + an orchestrator with injected Win32 dependencies keep it unit-testable. Two routes on the existing runtime router expose it; a React "Synchronize" page drives it through the standard `ApiAdapter`.

**Tech Stack:** FastAPI + Pydantic (backend), ctypes Win32, React + TanStack Query + Vite + Vitest (frontend). Spec: `docs/superpowers/specs/2026-07-24-synchronize-window-tiling-design.md`.

## Global Constraints

- **Platform:** Windows-only. Every Win32 call is guarded (`sys.platform != "win32"` → empty/False); the feature is inert (monitors `[]`, all `not_running`) elsewhere. Never raise from a Win32 path.
- **Three-ports rule does NOT apply** — this is `manager_backend` + `manager/frontend`, not the `cloakbrowser` wrapper. Do not touch `cloakbrowser/`, `js/`, or `dotnet/`.
- **No secrets, fixed error codes only.** Results carry only `profile_id` + one of `null` / `"not_running"` / `"position_failed"`. Never log window titles, URLs, or paths.
- **Fingerprint coherence:** windows are only ever sized **≤** the spoofed 1920×1080 screen (tiling shrinks them), which is coherent — do not add any path that sizes a window larger than the profile's spoofed screen.
- **Errors:** raise `ManagerError(code, message, status)` for true failures; batch-level per-profile failures are returned as `ok:false` results, never exceptions.
- **Commits are gated on the user's explicit approval** (project rule: do not commit or push unless the user asks). Each task ends with a staged `git add` + a prepared commit message; **hold the actual `git commit` until the user says so.** Never push.
- **Backend run/test:** `python -m pytest tests/manager/<file> -v` from repo root (system Python 3.13). **Frontend:** from repo root, `npm --prefix manager/frontend run <script>`.

## File Structure

**Backend (create):**
- `manager_backend/features/runtime/windows.py` — `Rect`/`Monitor` types, `compute_layout` (pure), `arrange_windows` (orchestrator, injected deps), `WindowManager` (real Win32), module singleton.
- `tests/manager/test_window_tiling.py` — layout math + orchestrator + route tests.

**Backend (modify):**
- `manager_backend/features/runtime/schemas.py` — add monitor/arrange schemas.
- `manager_backend/features/runtime/routes.py` — add `GET /runtime/monitors`, `POST /runtime/windows/arrange`.
- `manager_backend/main.py` — set `app.state.window_manager = WindowManager()`.

**Frontend (create):**
- `manager/frontend/src/features/synchronize/api.ts` — `useMonitors`, `useArrangeWindows`.
- `manager/frontend/src/features/synchronize/SynchronizePage.tsx` — the page.
- `manager/frontend/src/features/synchronize/SynchronizePage.test.tsx` — page test vs mock.

**Frontend (modify):**
- `manager/frontend/src/types/api.ts` — `Monitor`, `ArrangeLayout`, `ArrangeRequest`, `ArrangeResult`, `ArrangeResponse`.
- `manager/frontend/src/api/adapter.ts` — two interface methods.
- `manager/frontend/src/api/real.ts` — real impl.
- `manager/frontend/src/mocks/mockApi.ts` — mock impl.
- `manager/frontend/src/api/index.ts` — `queryKeys.monitors`.
- `manager/frontend/src/layouts/Sidebar.tsx` — nav entry.
- `manager/frontend/src/app/router.tsx` — route.
- `manager/frontend/src/i18n/en.ts`, `manager/frontend/src/i18n/vi.ts` — strings.

---

### Task 1: Pure layout math (`compute_layout`)

**Files:**
- Create: `manager_backend/features/runtime/windows.py`
- Test: `tests/manager/test_window_tiling.py`

**Interfaces:**
- Produces: `Rect = tuple[int,int,int,int]` (x,y,w,h); `WorkArea = tuple[int,int,int,int]` (x,y,w,h); `compute_layout(n: int, work_area: WorkArea, layout: str) -> list[Rect]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/manager/test_window_tiling.py
from __future__ import annotations

from manager_backend.features.runtime.windows import compute_layout


WORK = (0, 0, 1920, 1040)  # x, y, w, h


def test_grid_single_window_fills_work_area():
    assert compute_layout(1, WORK, "grid") == [(0, 0, 1920, 1040)]


def test_grid_four_windows_two_by_two():
    rects = compute_layout(4, WORK, "grid")
    assert len(rects) == 4
    assert rects[0] == (0, 0, 960, 520)
    assert rects[3] == (960, 520, 960, 520)


def test_grid_three_windows_edges_absorb_remainder():
    # cols=2, rows=2. Odd width/height must be absorbed by the last col/row so
    # windows meet the work-area edge with no dead gap.
    rects = compute_layout(3, (0, 0, 1921, 1041), "grid")
    assert rects[1][0] + rects[1][2] == 1921  # right edge of top-right window
    assert rects[2][1] + rects[2][3] == 1041  # bottom edge of bottom-left window


def test_zero_windows_is_empty():
    assert compute_layout(0, WORK, "grid") == []
    assert compute_layout(0, WORK, "cascade") == []


def test_cascade_steps_and_wraps_on_screen():
    rects = compute_layout(60, WORK, "cascade")
    assert len(rects) == 60
    # Every window stays fully within the work area.
    for x, y, w, h in rects:
        assert 0 <= x and x + w <= 1920
        assert 0 <= y and y + h <= 1040
    # First is at the origin; the second is stepped down-right.
    assert rects[0][0] == 0 and rects[0][1] == 0
    assert rects[1][0] == 32 and rects[1][1] == 32
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/manager/test_window_tiling.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError: cannot import name 'compute_layout'`.

- [ ] **Step 3: Write minimal implementation**

```python
# manager_backend/features/runtime/windows.py
"""Window arrangement for the Synchronize page (Windows, best-effort).

Pure layout math + an orchestrator with injected Win32 dependencies, plus the
real Win32 WindowManager. Every OS call is guarded and swallowing — arranging
windows must never raise into a request. See
docs/superpowers/specs/2026-07-24-synchronize-window-tiling-design.md.
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from typing import Protocol


Rect = tuple[int, int, int, int]       # x, y, w, h  (absolute virtual-desktop px)
WorkArea = tuple[int, int, int, int]   # x, y, w, h

_CASCADE_STEP = 32


def compute_layout(n: int, work_area: WorkArea, layout: str) -> list[Rect]:
    """Absolute (x, y, w, h) rects for `n` windows on `work_area`.

    grid: ceil(sqrt(n)) columns; the right/bottom cells extend to the work-area
    edge so integer division leaves no gap. cascade: fixed-size windows stepped
    by 32px, wrapping before they leave the work area."""
    if n <= 0:
        return []
    wx, wy, width, height = work_area
    if layout == "cascade":
        cw = max(1, round(width * 0.6))
        ch = max(1, round(height * 0.7))
        slots = max(1, min((width - cw) // _CASCADE_STEP, (height - ch) // _CASCADE_STEP))
        return [
            (wx + (i % slots) * _CASCADE_STEP, wy + (i % slots) * _CASCADE_STEP, cw, ch)
            for i in range(n)
        ]
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    cell_w = width // cols
    cell_h = height // rows
    rects: list[Rect] = []
    for i in range(n):
        col, row = i % cols, i // cols
        x, y = wx + col * cell_w, wy + row * cell_h
        w = (width - col * cell_w) if col == cols - 1 else cell_w
        h = (height - row * cell_h) if row == rows - 1 else cell_h
        rects.append((x, y, w, h))
    return rects
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/manager/test_window_tiling.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Stage (hold commit per Global Constraints)**

```bash
git add manager_backend/features/runtime/windows.py tests/manager/test_window_tiling.py
# Prepared message — commit only when the user approves:
#   feat(runtime): pure grid/cascade window layout math
```

---

### Task 2: Orchestrator (`arrange_windows`) with injected Win32 deps

**Files:**
- Modify: `manager_backend/features/runtime/windows.py`
- Test: `tests/manager/test_window_tiling.py`

**Interfaces:**
- Consumes: `compute_layout`, `Rect`, `WorkArea` (Task 1).
- Produces:
  - `@dataclass Monitor` with fields `id: str, label: str, width: int, height: int, work_area: WorkArea, is_primary: bool`.
  - `class WindowManagerProtocol(Protocol)` with `list_monitors() -> list[Monitor]`, `find_main_window(user_data_dir: str) -> int | None`, `move_window(hwnd: int, rect: Rect) -> bool`.
  - `arrange_windows(items: list[tuple[str, str | None]], work_area: WorkArea, layout: str, manager: WindowManagerProtocol) -> list[dict]` — `items` is `(profile_id, user_data_dir|None)`; returns dicts `{"profile_id", "ok", "error"}` in the original order.
  - `safe_profile_id(profile_id: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/manager/test_window_tiling.py
from manager_backend.features.runtime.windows import (
    Monitor,
    arrange_windows,
    safe_profile_id,
)


class FakeManager:
    def __init__(self, windows: dict[str, int], move_ok: bool = True):
        self._windows = windows          # user_data_dir -> hwnd
        self._move_ok = move_ok
        self.moved: list[tuple[int, tuple]] = []

    def list_monitors(self):
        return [Monitor("0", "Main", 1920, 1080, (0, 0, 1920, 1040), True)]

    def find_main_window(self, user_data_dir: str):
        return self._windows.get(user_data_dir)

    def move_window(self, hwnd: int, rect):
        self.moved.append((hwnd, rect))
        return self._move_ok


def test_arrange_positions_running_and_skips_others():
    mgr = FakeManager(windows={"/p/a/ud": 11, "/p/c/ud": 33})
    items = [("a", "/p/a/ud"), ("b", "/p/b/ud"), ("c", "/p/c/ud")]
    results = arrange_windows(items, (0, 0, 1920, 1040), "grid", mgr)
    assert results == [
        {"profile_id": "a", "ok": True, "error": None},
        {"profile_id": "b", "ok": False, "error": "not_running"},
        {"profile_id": "c", "ok": True, "error": None},
    ]
    # Only the two running windows were laid out (n=2), in original order.
    assert [hwnd for hwnd, _ in mgr.moved] == [11, 33]


def test_arrange_reports_position_failure():
    mgr = FakeManager(windows={"/p/a/ud": 11}, move_ok=False)
    results = arrange_windows([("a", "/p/a/ud")], (0, 0, 1920, 1040), "grid", mgr)
    assert results == [{"profile_id": "a", "ok": False, "error": "position_failed"}]


def test_arrange_none_user_data_dir_is_not_running():
    mgr = FakeManager(windows={})
    results = arrange_windows([("x", None)], (0, 0, 1920, 1040), "grid", mgr)
    assert results == [{"profile_id": "x", "ok": False, "error": "not_running"}]


def test_safe_profile_id_rejects_traversal():
    assert safe_profile_id("abc-123")
    assert not safe_profile_id("../etc")
    assert not safe_profile_id("a/b")
    assert not safe_profile_id("..")
    assert not safe_profile_id("")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/manager/test_window_tiling.py -v`
Expected: FAIL — `ImportError: cannot import name 'Monitor'` (and `arrange_windows`, `safe_profile_id`).

- [ ] **Step 3: Write minimal implementation**

```python
# add to manager_backend/features/runtime/windows.py (below compute_layout)

@dataclass
class Monitor:
    id: str
    label: str
    width: int
    height: int
    work_area: WorkArea
    is_primary: bool


class WindowManagerProtocol(Protocol):
    def list_monitors(self) -> list[Monitor]: ...
    def find_main_window(self, user_data_dir: str) -> int | None: ...
    def move_window(self, hwnd: int, rect: Rect) -> bool: ...


def safe_profile_id(profile_id: str) -> bool:
    """True only if the id is a single safe path segment (no traversal). Guards
    the profile_root join before building a user-data path from request input."""
    return bool(profile_id) and profile_id not in (".", "..") and os.path.basename(
        profile_id
    ) == profile_id and "\\" not in profile_id and "/" not in profile_id


def arrange_windows(
    items: list[tuple[str, str | None]],
    work_area: WorkArea,
    layout: str,
    manager: WindowManagerProtocol,
) -> list[dict]:
    """Position the running profiles' windows on `work_area`. `items` is
    (profile_id, user_data_dir|None); a None dir or a profile with no live
    window is `not_running`. Results preserve the input order."""
    results: list[dict | None] = [None] * len(items)
    running: list[tuple[int, int]] = []  # (result_index, hwnd)
    for index, (profile_id, user_data_dir) in enumerate(items):
        hwnd = manager.find_main_window(user_data_dir) if user_data_dir else None
        if hwnd is None:
            results[index] = {"profile_id": profile_id, "ok": False, "error": "not_running"}
        else:
            running.append((index, hwnd))
    rects = compute_layout(len(running), work_area, layout)
    for (index, hwnd), rect in zip(running, rects):
        ok = bool(manager.move_window(hwnd, rect))
        results[index] = {
            "profile_id": items[index][0],
            "ok": ok,
            "error": None if ok else "position_failed",
        }
    return [r for r in results if r is not None]
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/manager/test_window_tiling.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Stage (hold commit)**

```bash
git add manager_backend/features/runtime/windows.py tests/manager/test_window_tiling.py
#   feat(runtime): arrange_windows orchestrator with injected Win32 deps
```

---

### Task 3: Real Win32 `WindowManager`

**Files:**
- Modify: `manager_backend/features/runtime/windows.py`
- Test: `tests/manager/test_window_tiling.py`

**Interfaces:**
- Consumes: `Monitor`, `Rect` (Task 2); `window_icon._profile_chrome_pids` (existing).
- Produces: `class WindowManager` implementing `WindowManagerProtocol`; module singleton `WINDOW_MANAGER = WindowManager()`.

- [ ] **Step 1: Write the failing test** (behavioral + platform-guarded — the real Win32 is exercised only on Windows)

```python
# append to tests/manager/test_window_tiling.py
import sys as _sys
import pytest

from manager_backend.features.runtime.windows import WindowManager


def test_find_main_window_missing_profile_is_none():
    # A user-data dir with no running browser has no window, on any platform.
    assert WindowManager().find_main_window(r"C:\does\not\exist\ud") is None


@pytest.mark.skipif(_sys.platform != "win32", reason="Win32 monitor enumeration")
def test_list_monitors_returns_primary_on_windows():
    monitors = WindowManager().list_monitors()
    assert monitors  # at least one
    assert any(m.is_primary for m in monitors)
    m = monitors[0]
    assert m.width > 0 and m.height > 0
    wx, wy, ww, wh = m.work_area
    assert ww > 0 and wh > 0


def test_list_monitors_empty_off_windows(monkeypatch):
    monkeypatch.setattr(
        "manager_backend.features.runtime.windows.sys.platform", "linux"
    )
    assert WindowManager().list_monitors() == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/manager/test_window_tiling.py -v`
Expected: FAIL — `ImportError: cannot import name 'WindowManager'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to manager_backend/features/runtime/windows.py

_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SW_RESTORE = 9
_MONITORINFOF_PRIMARY = 0x1


class WindowManager:
    """Real Win32 window manager. All calls guarded to no-op off Windows and to
    swallow failures (arranging must never crash a request)."""

    def list_monitors(self) -> list[Monitor]:
        if sys.platform != "win32":
            return []
        try:
            return self._enumerate_monitors()
        except Exception:
            return []

    def find_main_window(self, user_data_dir: str) -> int | None:
        if sys.platform != "win32" or not user_data_dir:
            return None
        try:
            from .window_icon import _profile_chrome_pids

            pids = _profile_chrome_pids(user_data_dir)
            if not pids:
                return None
            return self._main_window_for_pids(pids)
        except Exception:
            return None

    def move_window(self, hwnd: int, rect: Rect) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import ctypes

            x, y, w, h = rect
            user32 = ctypes.windll.user32
            user32.ShowWindow(hwnd, _SW_RESTORE)  # un-maximize before positioning
            return bool(
                user32.SetWindowPos(
                    hwnd, 0, int(x), int(y), int(w), int(h),
                    _SWP_NOZORDER | _SWP_NOACTIVATE,
                )
            )
        except Exception:
            return False

    # --- Win32 internals ------------------------------------------------------

    def _main_window_for_pids(self, pids: set[int]) -> int | None:
        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        found: list[int] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        def _collect(hwnd, _lparam):
            owner = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            # Top-level, visible, titled window owned by this profile's browser =
            # the browser frame (same test window_icon uses to stamp the icon).
            if (
                owner.value in pids
                and user32.IsWindowVisible(hwnd)
                and user32.GetWindow(hwnd, 4) == 0  # GW_OWNER: 0 => top-level
                and user32.GetWindowTextLengthW(hwnd) > 0
            ):
                found.append(hwnd)
            return True

        user32.EnumWindows(_collect, 0)
        return found[0] if found else None

    def _enumerate_monitors(self) -> list[Monitor]:
        import ctypes
        import ctypes.wintypes

        class _RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        class _MONITORINFOEX(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                        ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong),
                        ("szDevice", ctypes.c_wchar * 32)]

        user32 = ctypes.windll.user32
        monitors: list[Monitor] = []

        @ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.wintypes.HMONITOR, ctypes.wintypes.HDC,
            ctypes.POINTER(_RECT), ctypes.wintypes.LPARAM,
        )
        def _collect(hmonitor, _hdc, _lprect, _lparam):
            info = _MONITORINFOEX()
            info.cbSize = ctypes.sizeof(_MONITORINFOEX)
            if not user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                return True
            mon, work = info.rcMonitor, info.rcWork
            width, height = mon.right - mon.left, mon.bottom - mon.top
            is_primary = bool(info.dwFlags & _MONITORINFOF_PRIMARY)
            index = len(monitors)
            monitors.append(
                Monitor(
                    id=str(index),
                    label=f"Monitor {index + 1} ({width}×{height})"
                    + (" — Primary" if is_primary else ""),
                    width=width,
                    height=height,
                    work_area=(work.left, work.top, work.right - work.left,
                               work.bottom - work.top),
                    is_primary=is_primary,
                )
            )
            return True

        user32.EnumDisplayMonitors(0, 0, _collect, 0)
        return monitors


WINDOW_MANAGER = WindowManager()
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/manager/test_window_tiling.py -v`
Expected: PASS (on Windows all pass; elsewhere the `win32` test is skipped).

- [ ] **Step 5: Stage (hold commit)**

```bash
git add manager_backend/features/runtime/windows.py tests/manager/test_window_tiling.py
#   feat(runtime): Win32 WindowManager (monitors, main-window find, SetWindowPos)
```

---

### Task 4: Schemas, routes, and app wiring

**Files:**
- Modify: `manager_backend/features/runtime/schemas.py`
- Modify: `manager_backend/features/runtime/routes.py`
- Modify: `manager_backend/main.py:181` (near `app.state.runtime_manager = ...`)
- Test: `tests/manager/test_window_tiling.py`

**Interfaces:**
- Consumes: `WindowManager`, `WINDOW_MANAGER`, `arrange_windows`, `safe_profile_id`, `Monitor` (Tasks 2–3); `app.state.settings.profile_root`, `app.state.window_manager`.
- Produces: `GET /api/v1/runtime/monitors` → `{"monitors":[MonitorRead]}`; `POST /api/v1/runtime/windows/arrange` (`ArrangeRequest`) → `{"results":[ArrangeResultRead]}`.

- [ ] **Step 1: Write the failing route tests**

```python
# append to tests/manager/test_window_tiling.py

def _install_fake_manager(client, windows=None, monitors=None):
    from manager_backend.features.runtime.windows import Monitor

    class _WM:
        def list_monitors(self):
            return monitors if monitors is not None else [
                Monitor("0", "Main", 1920, 1080, (0, 0, 1920, 1040), True)
            ]

        def find_main_window(self, user_data_dir):
            return (windows or {}).get(user_data_dir)

        def move_window(self, hwnd, rect):
            return True

    client.app.state.window_manager = _WM()


def test_get_monitors(client, auth_headers):
    _install_fake_manager(client)
    resp = client.get("/api/v1/runtime/monitors", headers=auth_headers)
    assert resp.status_code == 200
    monitors = resp.json()["monitors"]
    assert monitors[0]["id"] == "0"
    assert monitors[0]["is_primary"] is True
    assert monitors[0]["work_area"] == {"x": 0, "y": 0, "width": 1920, "height": 1040}


def test_arrange_unknown_profiles_are_not_running(client, auth_headers):
    _install_fake_manager(client, windows={})
    resp = client.post(
        "/api/v1/runtime/windows/arrange",
        headers=auth_headers,
        json={"profile_ids": ["p1", "p2"], "monitor_id": "0", "layout": "grid"},
    )
    assert resp.status_code == 200
    assert [r["error"] for r in resp.json()["results"]] == ["not_running", "not_running"]


def test_arrange_positions_running_window(client, auth_headers):
    settings = client.app.state.settings
    udd = str(settings.profile_root / "p1" / "user-data")
    _install_fake_manager(client, windows={udd: 123})
    resp = client.post(
        "/api/v1/runtime/windows/arrange",
        headers=auth_headers,
        json={"profile_ids": ["p1"], "monitor_id": "0", "layout": "grid"},
    )
    assert resp.status_code == 200
    assert resp.json()["results"] == [{"profile_id": "p1", "ok": True, "error": None}]


def test_arrange_traversal_id_is_not_running(client, auth_headers):
    _install_fake_manager(client, windows={})
    resp = client.post(
        "/api/v1/runtime/windows/arrange",
        headers=auth_headers,
        json={"profile_ids": ["../secret"], "monitor_id": "0", "layout": "grid"},
    )
    assert resp.json()["results"][0]["error"] == "not_running"


def test_arrange_no_monitor_all_not_running(client, auth_headers):
    _install_fake_manager(client, monitors=[])  # non-Windows / no displays
    resp = client.post(
        "/api/v1/runtime/windows/arrange",
        headers=auth_headers,
        json={"profile_ids": ["p1"], "monitor_id": "0", "layout": "grid"},
    )
    assert resp.json()["results"][0]["error"] == "not_running"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/manager/test_window_tiling.py -k "monitors or arrange" -v`
Expected: FAIL — 404 (routes not defined) / `AttributeError` on `app.state.window_manager`.

- [ ] **Step 3a: Add schemas**

```python
# add to manager_backend/features/runtime/schemas.py

class WorkAreaRead(BaseModel):
    x: int
    y: int
    width: int
    height: int


class MonitorRead(BaseModel):
    id: str
    label: str
    width: int
    height: int
    work_area: WorkAreaRead
    is_primary: bool


class MonitorsResponse(BaseModel):
    monitors: list[MonitorRead]


class ArrangeRequest(BaseModel):
    profile_ids: list[str]
    monitor_id: str
    layout: Literal["grid", "cascade"]


class ArrangeResultRead(BaseModel):
    profile_id: str
    ok: bool
    error: str | None = None


class ArrangeResponse(BaseModel):
    results: list[ArrangeResultRead]
```

- [ ] **Step 3b: Add routes**

```python
# add to manager_backend/features/runtime/routes.py
from fastapi import Request  # already imported; keep single import

from .schemas import (  # extend the existing import
    ArrangeRequest,
    ArrangeResponse,
    MonitorsResponse,
    RuntimePage,
    RuntimeRead,
)
from .windows import Monitor, arrange_windows, safe_profile_id


def _monitor_to_dict(monitor: Monitor) -> dict:
    wx, wy, ww, wh = monitor.work_area
    return {
        "id": monitor.id,
        "label": monitor.label,
        "width": monitor.width,
        "height": monitor.height,
        "work_area": {"x": wx, "y": wy, "width": ww, "height": wh},
        "is_primary": monitor.is_primary,
    }


def _select_monitor(monitors: list[Monitor], monitor_id: str) -> Monitor | None:
    if not monitors:
        return None
    for monitor in monitors:
        if monitor.id == monitor_id:
            return monitor
    for monitor in monitors:  # unknown id -> primary (stale dropdown is not an error)
        if monitor.is_primary:
            return monitor
    return monitors[0]


@router.get("/runtime/monitors", response_model=MonitorsResponse)
def list_monitors(request: Request):
    manager = request.app.state.window_manager
    return {"monitors": [_monitor_to_dict(m) for m in manager.list_monitors()]}


@router.post("/runtime/windows/arrange", response_model=ArrangeResponse)
def arrange(payload: ArrangeRequest, request: Request):
    manager = request.app.state.window_manager
    settings = request.app.state.settings
    monitor = _select_monitor(manager.list_monitors(), payload.monitor_id)
    if monitor is None:  # non-Windows / no displays -> feature inert
        return {
            "results": [
                {"profile_id": pid, "ok": False, "error": "not_running"}
                for pid in payload.profile_ids
            ]
        }
    items: list[tuple[str, str | None]] = []
    for pid in payload.profile_ids:
        if safe_profile_id(pid):
            items.append((pid, str(settings.profile_root / pid / "user-data")))
        else:
            items.append((pid, None))
    results = arrange_windows(items, monitor.work_area, payload.layout, manager)
    return {"results": results}
```

- [ ] **Step 3c: Wire the manager on app.state**

```python
# manager_backend/main.py — next to `app.state.runtime_manager = RuntimeManager(...)` (~line 181)
from .features.runtime.windows import WINDOW_MANAGER  # top-of-file import group

app.state.window_manager = WINDOW_MANAGER
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/manager/test_window_tiling.py -v`
Expected: PASS (all tasks 1–4 tests).

Then the full suite: `python -m pytest tests/manager -q` → Expected: all pass (no regressions).

- [ ] **Step 5: Stage (hold commit)**

```bash
git add manager_backend/features/runtime/schemas.py manager_backend/features/runtime/routes.py manager_backend/main.py tests/manager/test_window_tiling.py
#   feat(runtime): monitors + windows/arrange endpoints
```

---

### Task 5: Frontend API wiring (types, adapter, real, mock, queryKeys)

**Files:**
- Modify: `manager/frontend/src/types/api.ts`
- Modify: `manager/frontend/src/api/adapter.ts`
- Modify: `manager/frontend/src/api/real.ts`
- Modify: `manager/frontend/src/mocks/mockApi.ts`
- Modify: `manager/frontend/src/api/index.ts`

**Interfaces:**
- Produces (types): `ArrangeLayout = 'grid' | 'cascade'`; `Monitor`, `ArrangeRequest`, `ArrangeResult`, `ArrangeResponse`. Adapter methods `getMonitors(): Promise<Monitor[]>` and `arrangeWindows(payload: ArrangeRequest): Promise<ArrangeResponse>`. `queryKeys.monitors`.

- [ ] **Step 1: Add types** — append to `manager/frontend/src/types/api.ts`:

```ts
export type ArrangeLayout = 'grid' | 'cascade';

export interface Monitor {
  id: string;
  label: string;
  width: number;
  height: number;
  work_area: { x: number; y: number; width: number; height: number };
  is_primary: boolean;
}

export interface ArrangeRequest {
  profile_ids: string[];
  monitor_id: string;
  layout: ArrangeLayout;
}

export interface ArrangeResult {
  profile_id: string;
  ok: boolean;
  error: string | null;
}

export interface ArrangeResponse {
  results: ArrangeResult[];
}
```

- [ ] **Step 2: Extend the adapter interface** — in `manager/frontend/src/api/adapter.ts`, add `Monitor, ArrangeRequest, ArrangeResponse` to the type import from `@/types/api`, and add to `interface ApiAdapter` (after the `listSessions` / runtime group):

```ts
  // Window arrangement (Synchronize page) — Windows-only, inert elsewhere
  getMonitors(): Promise<Monitor[]>;
  arrangeWindows(payload: ArrangeRequest): Promise<ArrangeResponse>;
```

- [ ] **Step 3: Implement in the real adapter** — in `manager/frontend/src/api/real.ts`, import `apiRequest` (already used there) and the types, and add the two methods to the `realApi` object:

```ts
  async getMonitors() {
    const data = await apiRequest<{ monitors: Monitor[] }>('/runtime/monitors');
    return data.monitors;
  },
  async arrangeWindows(payload: ArrangeRequest) {
    return apiRequest<ArrangeResponse>('/runtime/windows/arrange', {
      method: 'POST',
      body: payload,
    });
  },
```

- [ ] **Step 4: Implement in the mock adapter** — in `manager/frontend/src/mocks/mockApi.ts`, add to the `mockApi` object:

```ts
  async getMonitors() {
    return [
      {
        id: '0',
        label: 'Monitor 1 (1920×1080) — Primary',
        width: 1920,
        height: 1080,
        work_area: { x: 0, y: 0, width: 1920, height: 1040 },
        is_primary: true,
      },
    ];
  },
  async arrangeWindows(payload: ArrangeRequest) {
    return {
      results: payload.profile_ids.map((profile_id) => ({
        profile_id,
        ok: true,
        error: null,
      })),
    };
  },
```

(Import `ArrangeRequest`, `ArrangeResponse`, `Monitor` at the top of `mockApi.ts` if not already; return types are inferred to match the interface.)

- [ ] **Step 5: Add the query key** — in `manager/frontend/src/api/index.ts`, add to the `queryKeys` object:

```ts
  monitors: ['runtime', 'monitors'] as const,
```

- [ ] **Step 6: Verify typecheck passes**

Run: `npm --prefix manager/frontend run typecheck`
Expected: no errors (mock and real both satisfy the extended `ApiAdapter`).

- [ ] **Step 7: Stage (hold commit)**

```bash
git add manager/frontend/src/types/api.ts manager/frontend/src/api/adapter.ts manager/frontend/src/api/real.ts manager/frontend/src/mocks/mockApi.ts manager/frontend/src/api/index.ts
#   feat(frontend): monitors + arrangeWindows API surface (real + mock)
```

---

### Task 6: Synchronize page + hooks + test

**Files:**
- Create: `manager/frontend/src/features/synchronize/api.ts`
- Create: `manager/frontend/src/features/synchronize/SynchronizePage.tsx`
- Create: `manager/frontend/src/features/synchronize/SynchronizePage.test.tsx`

**Interfaces:**
- Consumes: `api.getMonitors`, `api.arrangeWindows`, `queryKeys.monitors` (Task 5); `api.listProfiles` + `ProfileRead.runtime_state` (existing).
- Produces: `useMonitors()`, `useArrangeWindows()`, `SynchronizePage` (default+named export).

- [ ] **Step 1: Write the failing page test**

```tsx
// manager/frontend/src/features/synchronize/SynchronizePage.test.tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { SynchronizePage } from './SynchronizePage';
import { api } from '@/api';

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SynchronizePage />
    </QueryClientProvider>,
  );
}

describe('SynchronizePage', () => {
  it('lists running profiles and arranges them on Tile', async () => {
    vi.spyOn(api, 'listProfiles').mockResolvedValue({
      items: [
        { id: 'p1', name: 'Alpha', runtime_state: 'running' },
        { id: 'p2', name: 'Beta', runtime_state: 'stopped' },
      ],
      total: 2,
    } as never);
    const arrange = vi
      .spyOn(api, 'arrangeWindows')
      .mockResolvedValue({ results: [{ profile_id: 'p1', ok: true, error: null }] });

    renderPage();

    // Only the running profile appears.
    expect(await screen.findByText('Alpha')).toBeInTheDocument();
    expect(screen.queryByText('Beta')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /tile windows/i }));

    await waitFor(() =>
      expect(arrange).toHaveBeenCalledWith(
        expect.objectContaining({ profile_ids: ['p1'], layout: 'grid' }),
      ),
    );
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm --prefix manager/frontend run test -- src/features/synchronize/SynchronizePage.test.tsx`
Expected: FAIL — cannot resolve `./SynchronizePage`.

- [ ] **Step 3a: Write the hooks**

```ts
// manager/frontend/src/features/synchronize/api.ts
import { useMutation, useQuery } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import type { ArrangeRequest } from '@/types/api';

export function useMonitors() {
  return useQuery({ queryKey: queryKeys.monitors, queryFn: () => api.getMonitors() });
}

export function useArrangeWindows() {
  return useMutation({ mutationFn: (payload: ArrangeRequest) => api.arrangeWindows(payload) });
}
```

- [ ] **Step 3b: Write the page**

```tsx
// manager/frontend/src/features/synchronize/SynchronizePage.tsx
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, queryKeys } from '@/api';
import { useT } from '@/i18n';
import type { ArrangeLayout, ArrangeResult } from '@/types/api';
import { useMonitors, useArrangeWindows } from './api';

export function SynchronizePage() {
  const t = useT();
  const profilesQuery = useQuery({
    queryKey: queryKeys.profiles({ page: 1, page_size: 200 }),
    queryFn: () => api.listProfiles({ page: 1, page_size: 200 }),
  });
  const monitorsQuery = useMonitors();
  const arrange = useArrangeWindows();

  const running = useMemo(
    () => (profilesQuery.data?.items ?? []).filter((p) => p.runtime_state === 'running'),
    [profilesQuery.data],
  );

  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [monitorId, setMonitorId] = useState<string>('');
  const [layout, setLayout] = useState<ArrangeLayout>('grid');
  const [results, setResults] = useState<Record<string, ArrangeResult>>({});

  // Default: all running selected; primary monitor.
  useEffect(() => {
    setSelected((prev) => {
      const next = { ...prev };
      for (const p of running) if (!(p.id in next)) next[p.id] = true;
      return next;
    });
  }, [running]);
  useEffect(() => {
    const monitors = monitorsQuery.data ?? [];
    if (!monitorId && monitors.length) {
      setMonitorId((monitors.find((m) => m.is_primary) ?? monitors[0]).id);
    }
  }, [monitorsQuery.data, monitorId]);

  const chosenIds = running.filter((p) => selected[p.id]).map((p) => p.id);

  async function onTile() {
    if (!chosenIds.length || !monitorId) return;
    const res = await arrange.mutateAsync({ profile_ids: chosenIds, monitor_id: monitorId, layout });
    setResults(Object.fromEntries(res.results.map((r) => [r.profile_id, r])));
  }

  function resultLabel(id: string): string | null {
    const r = results[id];
    if (!r) return null;
    if (r.ok) return t('synchronize.ok');
    return r.error === 'not_running' ? t('synchronize.notRunning') : t('synchronize.failed');
  }

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <header>
        <h1 className="text-lg font-semibold text-ink">{t('synchronize.title')}</h1>
        <p className="text-sm text-ink-muted">{t('synchronize.subtitle')}</p>
      </header>

      <div className="grid flex-1 grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        {/* Running profiles */}
        <section className="rounded-lg border border-line bg-surface p-3">
          <h2 className="mb-2 text-[13px] font-medium text-ink-muted">
            {t('synchronize.running')}
          </h2>
          {running.length === 0 ? (
            <p className="p-4 text-sm text-ink-muted">{t('synchronize.noRunning')}</p>
          ) : (
            <ul className="space-y-1">
              {running.map((p) => (
                <li key={p.id} className="flex items-center justify-between rounded-md px-2 py-1.5">
                  <label className="flex items-center gap-2 text-sm text-ink">
                    <input
                      type="checkbox"
                      checked={!!selected[p.id]}
                      onChange={(e) =>
                        setSelected((s) => ({ ...s, [p.id]: e.target.checked }))
                      }
                    />
                    {p.name}
                  </label>
                  {resultLabel(p.id) && (
                    <span className="text-xs text-ink-muted">{resultLabel(p.id)}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Console */}
        <section className="space-y-4 rounded-lg border border-line bg-surface p-4">
          <div>
            <label className="mb-1 block text-[13px] font-medium text-ink">
              {t('synchronize.monitor')}
            </label>
            <select
              className="w-full rounded-md border border-line bg-surface-sunken px-2 py-1.5 text-sm"
              value={monitorId}
              onChange={(e) => setMonitorId(e.target.value)}
            >
              {(monitorsQuery.data ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>

          <fieldset>
            <legend className="mb-1 text-[13px] font-medium text-ink">
              {t('synchronize.layout')}
            </legend>
            {(['grid', 'cascade'] as ArrangeLayout[]).map((value) => (
              <label key={value} className="mr-4 inline-flex items-center gap-1.5 text-sm">
                <input
                  type="radio"
                  name="layout"
                  checked={layout === value}
                  onChange={() => setLayout(value)}
                />
                {t(`synchronize.${value}`)}
              </label>
            ))}
          </fieldset>

          <button
            type="button"
            onClick={onTile}
            disabled={!chosenIds.length || arrange.isPending}
            className="w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {t('synchronize.tile')}
          </button>
        </section>
      </div>
    </div>
  );
}

export default SynchronizePage;
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm --prefix manager/frontend run test -- src/features/synchronize/SynchronizePage.test.tsx`
Expected: PASS.

- [ ] **Step 5: Stage (hold commit)**

```bash
git add manager/frontend/src/features/synchronize/
#   feat(frontend): Synchronize page (window tiling) + hooks + test
```

---

### Task 7: Nav entry, route, and i18n

**Files:**
- Modify: `manager/frontend/src/layouts/Sidebar.tsx`
- Modify: `manager/frontend/src/app/router.tsx`
- Modify: `manager/frontend/src/i18n/en.ts`
- Modify: `manager/frontend/src/i18n/vi.ts`

**Interfaces:**
- Consumes: `SynchronizePage` (Task 6). Produces: `/synchronize` route + nav item; `nav.synchronize` + `synchronize.*` translation keys (en + vi).

- [ ] **Step 1: Add i18n keys (en)** — in `manager/frontend/src/i18n/en.ts`, add `synchronize` to the `nav` object and a new `synchronize` section (match the file's nested-object style):

```ts
// inside `nav: { ... }`
    synchronize: 'Synchronize',
```
```ts
// new top-level section
  synchronize: {
    title: 'Synchronize',
    subtitle: 'Arrange the windows of your running profiles across a monitor.',
    running: 'Running profiles',
    noRunning: 'No running profiles. Launch a profile to arrange its window.',
    monitor: 'Monitor',
    layout: 'Layout',
    grid: 'Grid',
    cascade: 'Cascade',
    tile: 'Tile windows',
    ok: 'Arranged',
    notRunning: 'Not running',
    failed: 'Failed',
  },
```

- [ ] **Step 2: Add i18n keys (vi)** — mirror in `manager/frontend/src/i18n/vi.ts` with identical shape:

```ts
// inside `nav: { ... }`
    synchronize: 'Đồng bộ',
```
```ts
  synchronize: {
    title: 'Đồng bộ',
    subtitle: 'Sắp xếp cửa sổ của các hồ sơ đang chạy trên một màn hình.',
    running: 'Hồ sơ đang chạy',
    noRunning: 'Không có hồ sơ đang chạy. Hãy khởi chạy một hồ sơ để sắp xếp cửa sổ.',
    monitor: 'Màn hình',
    layout: 'Bố cục',
    grid: 'Lưới',
    cascade: 'Xếp chồng',
    tile: 'Sắp xếp cửa sổ',
    ok: 'Đã sắp xếp',
    notRunning: 'Chưa chạy',
    failed: 'Thất bại',
  },
```

- [ ] **Step 3: Add the route** — in `manager/frontend/src/app/router.tsx`, import and add a child route (no capability gate — always available):

```tsx
import { SynchronizePage } from '@/features/synchronize/SynchronizePage';
```
```tsx
      { path: 'synchronize', element: <SynchronizePage /> },
```
(place it right after the `profiles/:id/edit` entry, before the capability-gated routes.)

- [ ] **Step 4: Add the nav item** — in `manager/frontend/src/layouts/Sidebar.tsx`, import the icon and add to the `NAV` array (after `/profiles`):

```tsx
import { LayoutGrid } from 'lucide-react'; // add to the existing lucide-react import
```
```tsx
    { to: '/synchronize', key: 'nav.synchronize', icon: LayoutGrid },
```

- [ ] **Step 5: Verify typecheck, build, and tests**

Run: `npm --prefix manager/frontend run typecheck`
Expected: no errors (`nav.synchronize` and `synchronize.*` now exist as `TranslationKey`s).

Run: `npm --prefix manager/frontend run test`
Expected: all pass (including the new page test).

Run: `npm --prefix manager/frontend run build`
Expected: build succeeds.

- [ ] **Step 6: Stage (hold commit)**

```bash
git add manager/frontend/src/layouts/Sidebar.tsx manager/frontend/src/app/router.tsx manager/frontend/src/i18n/en.ts manager/frontend/src/i18n/vi.ts
#   feat(frontend): Synchronize nav entry, route, and i18n (en/vi)
```

---

## Self-Review

**Spec coverage:**
- Positioning via Win32 reusing `window_icon` enumeration → Task 3. ✓
- `GET /runtime/monitors` + `POST /runtime/windows/arrange`, error codes `not_running`/`position_failed`, unknown-monitor → primary, empty `profile_ids` → `{results:[]}` (falls out of the loop) → Task 4. ✓
- Grid (`cols=⌈√n⌉`, edge absorb) + Cascade (0.6×/0.7×, 32px step, wrap) → Task 1. ✓
- Order-preserving results, running-only layout → Task 2. ✓
- Fingerprint coherence (windows ≤ screen) → Global Constraints + no larger-than-screen path. ✓
- Dedicated Synchronize page, running list + monitor + layout + tile, no capability gate, en+vi → Tasks 6–7. ✓
- Non-Windows inert (monitors `[]` → all `not_running`) → Task 3 guard + Task 4 `_select_monitor` None branch + test. ✓
- Testing plan (pure math, orchestrator with fakes, routes with fake manager, page vs mock) → Tasks 1–4, 6. ✓

**Placeholder scan:** none — every step has runnable code/commands.

**Type consistency:** `Monitor`/`Rect`/`WorkArea`, `arrange_windows`/`compute_layout`/`safe_profile_id` used identically across Tasks 1–4; frontend `Monitor`/`ArrangeRequest`/`ArrangeResponse`/`ArrangeResult`/`ArrangeLayout` and `getMonitors`/`arrangeWindows`/`queryKeys.monitors` consistent across Tasks 5–7. `runtime_state === 'running'` matches the existing `ProfileRead` field.

**Out of scope (Phase B, separate spec):** input mirroring (Main/Controlled windows, "1 click → all").
