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


_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SW_RESTORE = 9
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_MONITORINFOF_PRIMARY = 0x1


class WindowManager:
    """Real Win32 window manager. All calls guarded to no-op off Windows and to
    swallow failures (arranging must never crash a request)."""

    def list_monitors(self) -> list[Monitor]:
        if sys.platform != "win32":
            return []
        try:
            monitors = self._enumerate_monitors()
            # EnumDisplayMonitors can legitimately return nothing (e.g. some RDP /
            # headless-session contexts). Never leave the UI with an empty monitor
            # list — fall back to the primary screen so tiling still works.
            return monitors or self._primary_monitor_fallback()
        except Exception:
            try:
                return self._primary_monitor_fallback()
            except Exception:
                return []

    def _primary_monitor_fallback(self) -> list[Monitor]:
        import ctypes

        user32 = ctypes.windll.user32
        width = int(user32.GetSystemMetrics(0))   # SM_CXSCREEN
        height = int(user32.GetSystemMetrics(1))  # SM_CYSCREEN
        if width <= 0 or height <= 0:
            return []

        class _RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        work: WorkArea = (0, 0, width, height)
        rc = _RECT()
        if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rc), 0):  # SPI_GETWORKAREA
            work = (rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top)
        return [
            Monitor(
                id="0",
                label=f"Monitor 1 ({width}×{height}) — Primary",
                width=width,
                height=height,
                work_area=work,
                is_primary=True,
            )
        ]

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
            user32.ShowWindow(hwnd, _SW_RESTORE)  # un-minimize / un-maximize first
            # Position AND raise to the front, so tiled profiles are actually
            # visible instead of keeping their old z-order behind the manager /
            # other apps. The topmost -> not-topmost toggle forces the window
            # above others without stealing keyboard focus (SWP_NOACTIVATE).
            # HWND_TOPMOST/HWND_NOTOPMOST are (HWND)-1 / -2 — wrap in c_void_p so
            # ctypes passes the full pointer-width value, not a truncated 32-bit int.
            ok = user32.SetWindowPos(
                hwnd, ctypes.c_void_p(_HWND_TOPMOST),
                int(x), int(y), int(w), int(h), _SWP_NOACTIVATE,
            )
            user32.SetWindowPos(
                hwnd, ctypes.c_void_p(_HWND_NOTOPMOST), 0, 0, 0, 0,
                _SWP_NOACTIVATE | _SWP_NOMOVE | _SWP_NOSIZE,
            )
            return bool(ok)
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
