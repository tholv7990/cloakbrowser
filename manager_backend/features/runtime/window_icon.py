"""Plasma-dart taskbar/window icon per profile (Windows, best-effort).

An open profile shows the binary's generic Chromium icon. This applies the
plasma-dart brand icon to the browser window (WM_SETICON) and gives each profile a
distinct AppUserModelID + relaunch icon so the profiles are separate, branded
taskbar buttons rather than one grouped Chromium button. Windows-only; every
failure is swallowed so it can never block or fail a launch.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys
import tempfile
from pathlib import Path

_WM_SETICON = 0x0080
_ICON_SMALL, _ICON_BIG = 0, 1
_ICON_DIR = Path(tempfile.gettempdir()) / "cloakbrowser-profile-icons"
_hicon_cache: dict[tuple[str, int], int] = {}
_aumid_done: set[int] = set()  # hwnds whose taskbar identity is already set


# --- taskbar identity (AppUserModelID) via the window property store -----------
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_uint32)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                ("r3", ctypes.c_ushort), ("p1", ctypes.c_void_p), ("p2", ctypes.c_void_p)]


def _guid(text: str) -> "_GUID":
    g = _GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
    return g


def _pkey(pid: int) -> "_PROPERTYKEY":
    # All AppUserModel_* keys share this format id.
    key = _PROPERTYKEY()
    key.fmtid = _guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")
    key.pid = pid
    return key


def _string_propvariant(text: str) -> "_PROPVARIANT | None":
    """A VT_LPWSTR PROPVARIANT (InitPropVariantFromString isn't an exported symbol,
    so allocate the string with SHStrDupW; PropVariantClear frees it)."""
    ptr = ctypes.c_void_p()
    if ctypes.windll.shlwapi.SHStrDupW(ctypes.c_wchar_p(text), ctypes.byref(ptr)) != 0:
        return None
    pv = _PROPVARIANT()
    pv.vt = 31  # VT_LPWSTR
    pv.p1 = ptr
    return pv


def _set_taskbar_identity(hwnd: int, aumid: str, ico_path: str) -> bool:
    """Give the window a distinct AppUserModelID (so two profiles don't group into
    one taskbar button) and point its relaunch icon at the plasma .ico."""
    ole32, shell32 = ctypes.windll.ole32, ctypes.windll.shell32
    ole32.CoInitialize(None)  # idempotent per thread
    store = ctypes.c_void_p()
    iid = _guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")  # IID_IPropertyStore
    if shell32.SHGetPropertyStoreForWindow(
        ctypes.wintypes.HWND(hwnd), ctypes.byref(iid), ctypes.byref(store)
    ) != 0 or not store:
        return False
    vtbl = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0],
                       ctypes.POINTER(ctypes.c_void_p))
    set_value = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT)
    )(vtbl[6])
    commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[7])
    release = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[2])
    try:
        ok = False
        for key, text in ((_pkey(5), aumid), (_pkey(3), f"{ico_path},0")):
            pv = _string_propvariant(text)
            if pv is not None and set_value(store, ctypes.byref(key), ctypes.byref(pv)) == 0:
                ok = True
            if pv is not None:
                ole32.PropVariantClear(ctypes.byref(pv))
        commit(store)
        return ok
    finally:
        release(store)


# The brand mark: a plasma "dart" (arrow with motion lines) — a faithful raster of
# plasma-dart.svg (no SVG rasterizer is bundled, and the shapes are simple).
_DART_VIOLET = (127, 119, 221)  # #7F77DD
_DART_PINK = (212, 83, 126)  # #D4537E
_DART_LINES = ((9, 22, 26, 22, 3, 0.30), (4, 32, 24, 32, 4, 0.55), (13, 42, 26, 42, 3, 0.25))
_DART_BODY = ((34, 15), (59, 32), (34, 49), (41, 32))
_DART_HIGHLIGHT = ((34, 15), (59, 32), (50, 32), (36, 20))


def _plasma_dart_ico() -> Path:
    """Draw (and cache) the plasma-dart .ico (from plasma-dart.svg's 64x64 grid).

    The art is cropped to its content and scaled to nearly fill the icon square,
    so the mark reads large in the taskbar instead of floating with big margins.
    """
    _ICON_DIR.mkdir(parents=True, exist_ok=True)
    path = _ICON_DIR / "plasma-dart.ico"
    if path.exists():
        return path
    from PIL import Image, ImageDraw

    scale = 16  # supersample the 64-unit SVG grid, then downscale for crisp edges
    img = Image.new("RGBA", (64 * scale, 64 * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def pts(coords):
        return [(x * scale, y * scale) for x, y in coords]

    for x1, y1, x2, y2, width, opacity in _DART_LINES:
        color = (*_DART_VIOLET, int(opacity * 255))
        draw.line(pts(((x1, y1), (x2, y2))), fill=color, width=width * scale)
        radius = width * scale / 2  # round caps
        for cx, cy in ((x1, y1), (x2, y2)):
            draw.ellipse(
                [cx * scale - radius, cy * scale - radius, cx * scale + radius, cy * scale + radius],
                fill=color,
            )
    draw.polygon(pts(_DART_BODY), fill=(*_DART_VIOLET, 255))
    draw.polygon(pts(_DART_HIGHLIGHT), fill=(*_DART_PINK, 255))

    # Crop to the drawn content, then scale to fill the icon's HEIGHT so the dart
    # reads large (the mark is wide, so filling width alone leaves it small). The
    # arrow is right-aligned and fully visible; the speed lines trail in from the
    # left edge, which reads as motion.
    bbox = img.getbbox()
    content = img.crop(bbox) if bbox else img
    target = 256
    margin = round(target * 0.08)
    factor = (target - 2 * margin) / content.height
    resized = content.resize(
        (max(1, round(content.width * factor)), max(1, round(content.height * factor))),
        Image.LANCZOS,
    )
    canvas = Image.new("RGBA", (target, target), (0, 0, 0, 0))
    canvas.paste(resized, (target - margin - resized.width, (target - resized.height) // 2), resized)
    canvas.save(path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48)])
    return path


def _hicon(path: Path, size: int) -> int:
    key = (str(path), size)
    if key in _hicon_cache:
        return _hicon_cache[key]
    LR_LOADFROMFILE, IMAGE_ICON = 0x0010, 1
    handle = ctypes.windll.user32.LoadImageW(None, str(path), IMAGE_ICON, size, size, LR_LOADFROMFILE)
    _hicon_cache[key] = handle
    return handle


def _profile_chrome_pids(user_data_dir) -> set[int]:
    """Every Chrome process on this profile dir (the window-owning browser process
    isn't the only one that carries --user-data-dir, so match them all)."""
    import psutil

    from .launcher import _cmdline_user_data_dir, _normalize_udd

    owned = _normalize_udd(str(user_data_dir))
    pids: set[int] = set()
    for process in psutil.process_iter(["name"]):
        try:
            if "chrome" not in (process.info["name"] or "").lower():
                continue
            udd = _cmdline_user_data_dir(process.cmdline())
            if udd and _normalize_udd(udd) == owned:
                pids.add(process.pid)
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return pids


def apply_profile_window_icon(user_data_dir, seed: str) -> int:
    """Set the plasma icon on every visible window of the profile's browser.

    Returns how many windows were iconed (0 if none yet / not applicable).
    """
    if sys.platform != "win32":
        return 0
    try:
        pids = _profile_chrome_pids(user_data_dir)
        if not pids:
            return 0
        ico = _plasma_dart_ico()
        small, big = _hicon(ico, 16), _hicon(ico, 32)
        if not small and not big:
            return 0
        user32 = ctypes.windll.user32
        hwnds: list[int] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
        def _collect(hwnd, _lparam):
            owner = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if (owner.value in pids and user32.IsWindowVisible(hwnd)
                    and user32.GetWindowTextLengthW(hwnd) > 0):
                hwnds.append(hwnd)
            return True

        user32.EnumWindows(_collect, 0)
        aumid = f"CloakBrowser.Profile.{seed}"
        for hwnd in hwnds:
            if big:
                user32.SendMessageW(hwnd, _WM_SETICON, _ICON_BIG, big)
            if small:
                user32.SendMessageW(hwnd, _WM_SETICON, _ICON_SMALL, small)
            # A distinct AUMID gives each profile its OWN taskbar button (no
            # grouping) — set once per window.
            if hwnd not in _aumid_done:
                try:
                    if _set_taskbar_identity(hwnd, aumid, str(ico)):
                        _aumid_done.add(hwnd)
                except Exception:
                    pass
        return len(hwnds)
    except Exception:
        return 0
