"""Per-profile plasma taskbar/window icon (Windows, best-effort).

An open profile shows the binary's generic Chromium icon, so two open profiles
look identical in the taskbar / Alt-Tab. This gives each open profile a distinct
plasma orb, tinted by a colour derived from the profile id, applied to its browser
window with WM_SETICON. Windows-only; every failure is swallowed so it can never
block or fail a launch.
"""

from __future__ import annotations

import colorsys
import ctypes
import ctypes.wintypes
import hashlib
import sys
import tempfile
from pathlib import Path

_WM_SETICON = 0x0080
_ICON_SMALL, _ICON_BIG = 0, 1
_ICON_DIR = Path(tempfile.gettempdir()) / "cloakbrowser-profile-icons"
_hicon_cache: dict[tuple[str, int], int] = {}


def _color_for(seed: str) -> tuple[int, int, int]:
    """A vivid, stable, well-spread colour per profile (distinct hues)."""
    digest = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)
    hue = (digest % 360) / 360.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.72, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


def _ensure_ico(rgb: tuple[int, int, int]) -> Path:
    """Draw (and cache) a plasma-orb .ico in the given colour."""
    _ICON_DIR.mkdir(parents=True, exist_ok=True)
    path = _ICON_DIR / ("plasma_%02x%02x%02x.ico" % rgb)
    if path.exists():
        return path
    from PIL import Image, ImageDraw, ImageFilter

    size = 256
    center = size / 2
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Radial glow: colour fading out to transparent.
    radius = size * 0.46
    for i in range(int(radius), 0, -1):
        t = i / radius
        alpha = int(215 * (1 - t) ** 2)
        draw.ellipse([center - i, center - i, center + i, center + i], fill=(*rgb, alpha))
    # Two crossed orbital arcs (the "plasma field").
    arc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    adraw = ImageDraw.Draw(arc)
    rx, ry = size * 0.44, size * 0.15
    adraw.ellipse([center - rx, center - ry, center + rx, center + ry],
                  outline=(255, 255, 255, 205), width=max(3, size // 40))
    for angle in (28, -28):
        img = Image.alpha_composite(img, arc.rotate(angle, resample=Image.BICUBIC, center=(center, center)))
    # Bright energised core on top.
    draw = ImageDraw.Draw(img)
    core = size * 0.13
    draw.ellipse([center - core, center - core, center + core, center + core], fill=(255, 255, 255, 255))
    lighter = tuple(min(255, c + 90) for c in rgb)
    core2 = size * 0.085
    draw.ellipse([center - core2, center - core2, center + core2, center + core2], fill=(*lighter, 255))
    img = img.filter(ImageFilter.GaussianBlur(size / 200))
    img.save(path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48)])
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
        ico = _ensure_ico(_color_for(seed))
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
        for hwnd in hwnds:
            if big:
                user32.SendMessageW(hwnd, _WM_SETICON, _ICON_BIG, big)
            if small:
                user32.SendMessageW(hwnd, _WM_SETICON, _ICON_SMALL, small)
        return len(hwnds)
    except Exception:
        return 0
