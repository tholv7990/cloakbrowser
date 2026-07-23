from __future__ import annotations

import ipaddress
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Protocol
from datetime import datetime, timezone

import psutil
from sqlalchemy import select
from sqlalchemy.orm import Session

from cloakbrowser.config import get_chromium_version

from ...config import ManagerSettings
from ...models import Extension, Profile, profile_extensions
from ..extensions.service import validate_registered_extension_path
from .timing import StartTimer


class BrowserHandle(Protocol):
    def close(self) -> None: ...

    def is_closed(self) -> bool: ...


class BrowserLauncher(Protocol):
    def launch(self, snapshot: dict[str, Any]) -> BrowserHandle: ...


def enabled_profile_extension_paths(
    session: Session, profile_id: str, settings: ManagerSettings
) -> list[str]:
    """Return launch-safe enabled assignments in deterministic path order."""

    extensions = list(
        session.scalars(
            select(Extension)
            .join(
                profile_extensions,
                profile_extensions.c.extension_id == Extension.id,
            )
            .where(
                profile_extensions.c.profile_id == profile_id,
                Extension.enabled.is_(True),
            )
        )
    )
    paths = [
        validate_registered_extension_path(settings, extension)
        for extension in extensions
    ]
    return sorted(paths, key=lambda path: (path.casefold(), path))


def profile_launch_snapshot(
    profile: Profile,
    settings: ManagerSettings,
    *,
    extension_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Build the one canonical Manager launch snapshot for a profile."""

    location = dict(profile.location or {})
    return {
        "id": profile.id,
        "profile_dir": settings.profile_root / profile.id,
        "fingerprint_seed": profile.fingerprint_seed,
        "fingerprint_preset": profile.fingerprint_preset,
        "fingerprint_revision": profile.fingerprint_revision,
        "fingerprint_config_hash": profile.fingerprint_config_hash,
        # Quantum model: "installed" profiles launch the bundled build (uncapped
        # concurrency). Latest Pro (seat-capped) is an explicit opt-in — pin its
        # version. Passing None here would resolve to latest Pro and spend a seat.
        "browser_version": (
            profile.browser_version
            if profile.browser_version_mode == "pinned"
            else get_chromium_version()
        ),
        "custom_user_agent": (
            profile.custom_user_agent if profile.user_agent_mode == "custom" else None
        ),
        # Only a "manual" geo profile pins locale/timezone here. "proxy" is filled
        # from the exit IP during proxy preflight; "system" (or "proxy" with no
        # proxy) leaves them unset so the browser follows the host — either way a
        # stale stored value must not leak and cause a timezone/IP mismatch.
        "locale": location.get("locale") if location.get("geo_mode") == "manual" else None,
        "timezone": location.get("timezone") if location.get("geo_mode") == "manual" else None,
        "location": location,
        "window": dict(profile.window or {}),
        "behavior": dict(profile.behavior or {}),
        "startup_urls": list(profile.startup_urls or []),
        "proxy_id": profile.proxy_id,
        "test_proxy_before_launch": getattr(
            profile, "test_proxy_before_launch", True
        ),
        "extension_paths": list(extension_paths or []),
    }


_SESSION_FILE = "last-session.json"

# The stealth binary ships with NO prepopulated search engines, so the omnibox
# has no search fallback and types plain text as a hostname ("test" -> http://test/).
# The default search provider is a *protected* Chromium pref (HMAC-guarded in
# Secure Preferences), so it can't be injected into a profile's prefs after the
# fact — a plain-Preferences write is rejected as tampering. Chromium DOES apply
# `initial_preferences` (next to the executable) on a profile's first run and
# stamps a valid MAC itself, so that is where we seed Google. Applies to new
# profiles only; existing ones are already past first-run.
_INITIAL_PREFS_FILE = "initial_preferences"
_SEARCH_TEMPLATE_URL_DATA = {
    "short_name": "Google",
    "keyword": "google.com",
    "url": "https://www.google.com/search?q={searchTerms}",
    "suggestions_url": "https://www.google.com/complete/search?output=chrome&q={searchTerms}",
    "favicon_url": "https://www.google.com/favicon.ico",
    "safe_for_autoreplace": False,
    "input_encodings": ["UTF-8"],
    "date_created": "0",
    "last_modified": "0",
    "id": "1",
    "sync_guid": "google-default-000000000000",
    "prepopulate_id": 1,
    "is_active": 1,
}


def ensure_initial_preferences(binary_dir: Path) -> None:
    """Seed Google as the default search engine for new profiles via the binary's
    `initial_preferences`. Idempotent; re-created after a binary update. Never
    raises — a bad seed must not block a launch."""
    payload = {
        "distribution": {
            "skip_first_run_ui": True,
            "import_search_engine": False,
            "import_history": False,
            "make_chrome_default": False,
        },
        "default_search_provider_data": {"template_url_data": _SEARCH_TEMPLATE_URL_DATA},
    }
    try:
        desired = json.dumps(payload)
        target = binary_dir / _INITIAL_PREFS_FILE
        if target.exists() and target.read_text(encoding="utf-8") == desired:
            return
        target.write_text(desired, encoding="utf-8")
    except OSError:
        pass


def _google_search_ready(default_dir: Path) -> bool:
    """True if this profile already has a working Google DSE (so we skip re-seeding)."""
    try:
        secure = json.loads((default_dir / "Secure Preferences").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not (secure.get("default_search_provider_data") or {}).get("template_url_data"):
        return False
    web_data = default_dir / "Web Data"
    if not web_data.exists():
        return False
    try:
        conn = sqlite3.connect(str(web_data))
        try:
            row = conn.execute(
                "SELECT 1 FROM keywords WHERE keyword='google.com' AND is_active=1"
            ).fetchone()
        finally:
            conn.close()
        return bool(row)
    except sqlite3.Error:
        return False


def ensure_google_search(user_data_dir: Path) -> None:
    """One-time seed so the profile's omnibox searches Google (see google_seed).

    Idempotent: skips instantly once the profile has a working Google DSE. The
    seed runs in a separate process (isolated from the manager's Playwright driver)
    and off-screen. Best-effort — never blocks or fails a launch. Runs before the
    profile is launched, so its files are not locked.
    """
    if _google_search_ready(user_data_dir / "Default"):
        return
    try:
        subprocess.run(
            [sys.executable, "-m", "manager_backend.features.runtime.google_seed",
             str(user_data_dir)],
            timeout=45,
            check=False,
        )
    except Exception:
        pass


def seed_default_search_engine(user_data_dir: Path) -> None:
    """Heal an EXISTING profile that has no default search engine.

    New profiles get Google from the binary's `initial_preferences` at first run.
    A profile that predates that (already ran, still no provider) is healed once
    here: seed the provider into `Preferences` and drop `Secure Preferences` so
    Chromium re-baselines its tracked-pref MACs and trusts the seeded value
    instead of resetting it as tampering. Only pref-level state resets (extensions
    re-load at launch; homepage/pinned re-baseline) — cookies, logins and history
    are separate files and are untouched. Runs before launch (files unlocked) and
    is a one-time no-op once a provider exists. Never raises.
    """
    default = user_data_dir / "Default"
    prefs = default / "Preferences"
    try:
        if not prefs.exists():
            return  # brand-new profile -> initial_preferences seeds it at first run
        data = json.loads(prefs.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("default_search_provider_data"):
            return  # already has a provider (healed, or user-chosen) -> leave it
        data["default_search_provider_data"] = {"template_url_data": _SEARCH_TEMPLATE_URL_DATA}
        prefs.write_text(json.dumps(data), encoding="utf-8")
        (default / "Secure Preferences").unlink(missing_ok=True)
    except (OSError, ValueError):
        pass  # a bad seed must never block a launch


# Tab-session restoration reads an on-disk file, so treat it as untrusted: only a
# bounded number of real web URLs (http/https, sane length) may be reopened, and
# restoring them is capped by a total time budget so a run of dead hosts can't
# stall a launch.
_MAX_RESTORE_TABS = 25
_RESTORE_SCHEMES = ("http://", "https://")
_MAX_URL_LENGTH = 2048
_RESTORE_TIME_BUDGET_SECONDS = 30.0


def _valid_restore_url(url: object) -> bool:
    return (
        isinstance(url, str)
        and 0 < len(url) <= _MAX_URL_LENGTH
        and url.startswith(_RESTORE_SCHEMES)
    )


def _read_last_session(profile_dir: Path) -> list[str]:
    """Return the saved tab URLs (validated + bounded); [] if none or malformed."""
    try:
        data = json.loads((profile_dir / _SESSION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or not isinstance(data.get("urls"), list):
        return []
    valid = [url for url in data["urls"] if _valid_restore_url(url)]
    return valid[:_MAX_RESTORE_TABS]


def urls_to_open(profile_dir: Path, startup_urls: list[str]) -> list[str]:
    """Restore the previous tabs if any were saved; otherwise seed startup_urls."""
    return _read_last_session(profile_dir) or list(startup_urls)


# The consistent fingerprint preset spoofs a 1920x1080 screen. Sizing the window
# to it makes outer==screen (a coherent, maximized-looking window) instead of
# OS-maximizing to a larger real monitor — which would leak the real size (e.g.
# an ultrawide) and contradict the spoofed screen. The 146 free binary lacks the
# engine's screen-clamp (a 148+ feature), so the manager sizes the window itself.
_DEFAULT_WINDOW_SIZE = (1920, 1080)


def _window_size_arg(window: dict[str, Any]) -> str:
    if window.get("mode") == "custom" and window.get("width") and window.get("height"):
        return f"--window-size={int(window['width'])},{int(window['height'])}"
    return f"--window-size={_DEFAULT_WINDOW_SIZE[0]},{_DEFAULT_WINDOW_SIZE[1]}"


def persistent_context_kwargs(
    snapshot: dict[str, Any], *, headless: bool
) -> dict[str, Any]:
    """Translate a Manager snapshot into CloakBrowser persistent-context options."""

    args = [f"--fingerprint={snapshot['fingerprint_seed']}"]
    if not headless:  # headed runtime only — not the cookie/diagnostic utility launches
        args.append(_window_size_arg(snapshot.get("window") or {}))
    # WebRTC leak guard: when the profile routes WebRTC through its proxy, spoof
    # the WebRTC IP to the proxy exit IP so the real IP can't leak via STUN.
    # cloakbrowser resolves "auto" -> exit IP (and drops the flag if there is no
    # proxy). Without this the field is dead config and WebRTC exposes the host IP.
    location = snapshot.get("location") or {}
    if snapshot.get("proxy_url") and location.get("webrtc_mode", "proxy") == "proxy":
        exit_ip = snapshot.get("proxy_exit_ip")
        if exit_ip:
            args.append(f"--fingerprint-webrtc-ip={ipaddress.ip_address(exit_ip)}")
        else:
            args.append("--fingerprint-webrtc-ip=auto")
    kwargs = {
        "headless": headless,
        "fingerprint_preset": snapshot["fingerprint_preset"],
        "args": args,
        "browser_version": snapshot.get("browser_version"),
        "user_agent": snapshot.get("custom_user_agent"),
        "proxy": snapshot.get("proxy_url"),
        "locale": snapshot.get("locale"),
        "timezone": snapshot.get("timezone"),
    }
    extension_paths = snapshot.get("extension_paths")
    if extension_paths:
        kwargs["extension_paths"] = list(extension_paths)
    return kwargs


def _normalize_udd(path: str) -> str:
    """Canonicalize a user-data-dir for exact, case/separator-insensitive compare."""
    try:
        resolved = os.path.realpath(path)
    except (OSError, ValueError):
        resolved = path
    return os.path.normcase(os.path.normpath(resolved))


def _cmdline_user_data_dir(cmdline: list[str]) -> str | None:
    """Extract the exact --user-data-dir value from a process cmdline (or None)."""
    for index, arg in enumerate(cmdline):
        if arg.startswith("--user-data-dir="):
            return arg.split("=", 1)[1]
        if arg == "--user-data-dir" and index + 1 < len(cmdline):
            return cmdline[index + 1]
    return None


class _PersistentContextHandle:
    _PROBE_INTERVAL = 2.0

    def __init__(self, context: Any, user_data_dir: str, icon_seed: str | None = None):
        self._context = context
        self._closed = False
        self._profile_dir = Path(user_data_dir).parent
        self._user_data_dir = user_data_dir
        self._owned_path = _normalize_udd(user_data_dir)
        self.browser_pid: int | None = None
        self.browser_created_at: datetime | None = None
        self._last_probe = 0.0
        self._cdp_session: Any | None = None
        self._last_saved_urls: list[str] | None = None
        self._icon_seed = icon_seed  # per-profile taskbar icon
        self._icon_applies_left = 6  # slow-path re-apply on probes, long-term safety net
        # Front-load the icon: start the burst BEFORE the (blocking) _locate_browser
        # scan so it begins stamping the instant the window appears — the window is
        # born with Chrome's default icon and every millisecond before our override
        # lands is a visible frame of it. The burst keeps winning while Chrome
        # re-sets its own icon during startup. Best-effort, never blocks.
        if icon_seed:
            threading.Thread(target=self._icon_burst, name="profile-icon", daemon=True).start()
        self._locate_browser()
        context.on("close", self._mark_closed)

    def _icon_burst(self) -> None:
        # Scan for the profile's Chrome pids ONCE (the browser process is stable
        # from launch), then re-stamp its windows every ~30ms so Chrome never wins
        # a visible frame while it re-sets its own icon during startup — the source
        # of the flicker. Skipping the per-iteration whole-OS process_iter also
        # keeps the burst from competing with the browser's cold start for CPU.
        from .window_icon import _profile_chrome_pids, apply_profile_window_icon

        pids: set[int] | None = None
        # ~15ms cadence for 5s: tight enough that a re-set by Chrome is overwritten
        # within a frame, and long enough to cover the whole tab-restore window
        # (each restored tab can make Chrome re-touch the icon). EnumWindows +
        # SendMessage is cheap; the costly whole-OS scan runs at most once.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not self._closed:
            try:
                if not pids:
                    pids = _profile_chrome_pids(self._user_data_dir) or None
                apply_profile_window_icon(self._user_data_dir, self._icon_seed, pids=pids)
            except Exception:
                pass
            time.sleep(0.015)

    def _apply_icon(self) -> None:
        if self._icon_seed is None or self._icon_applies_left <= 0:
            return
        from .window_icon import apply_profile_window_icon

        if apply_profile_window_icon(self._user_data_dir, self._icon_seed):
            self._icon_applies_left -= 1

    def _locate_browser(self) -> bool:
        """Find the profile's browser process by its --user-data-dir.

        Scans all processes (not just our children): Playwright launches Chrome
        behind a node driver, and in the runtime worker the child-tree scan misses
        it — a full scan finds it regardless of parent, which is also what lets us
        detect a user-closed window (the process is simply gone).
        """
        for process in psutil.process_iter(["name"]):
            try:
                if "chrome" not in (process.info["name"] or "").lower():
                    continue
                udd = _cmdline_user_data_dir(process.cmdline())
                if udd is not None and _normalize_udd(udd) == self._owned_path:
                    self.browser_pid = process.pid
                    self.browser_created_at = datetime.fromtimestamp(
                        process.create_time(), timezone.utc
                    )
                    return True
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        return False

    def _process_alive(self) -> bool:
        """True only if OUR exact browser process still runs — verifying the pid's
        create_time matches, so a reused pid is never mistaken for a live browser."""
        if self.browser_pid is None or self.browser_created_at is None:
            return False
        try:
            created = datetime.fromtimestamp(
                psutil.Process(self.browser_pid).create_time(), timezone.utc
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False
        return created == self.browser_created_at

    def _mark_closed(self, *_args: Any) -> None:
        self._closed = True

    def _cdp(self) -> Any | None:
        """A reusable CDP session bound to any live page (rebuilt if it dies)."""
        if self._cdp_session is not None:
            return self._cdp_session
        pages = self._context.pages
        if not pages:
            return None
        try:
            self._cdp_session = self._context.new_cdp_session(pages[0])
        except Exception:
            self._cdp_session = None
        return self._cdp_session

    def _snapshot_session(self) -> None:
        """Capture the live tab URLs so a direct window close still restores them.

        Reads them via CDP ``Target.getTargets`` — the browser's own list, fresh
        every call — instead of Playwright's page cache, which the runtime worker
        thread never pumps (so it would miss user-opened tabs and navigations).
        Never writes an empty set, so a close-race can't wipe a good session.
        """
        try:
            session = self._cdp()
            if session is None:
                return
            infos = session.send("Target.getTargets").get("targetInfos", [])
        except Exception:
            self._cdp_session = None  # bound page likely gone — rebuild next probe
            return
        urls = [
            info["url"]
            for info in infos
            if info.get("type") == "page" and _valid_restore_url(info.get("url"))
        ][:_MAX_RESTORE_TABS]
        if urls and urls != self._last_saved_urls:
            try:
                (self._profile_dir / _SESSION_FILE).write_text(
                    json.dumps({"urls": urls}), encoding="utf-8"
                )
                self._last_saved_urls = urls
            except OSError:
                pass  # never let session capture block the run

    def close(self) -> None:
        if not self._closed:
            self._snapshot_session()  # final fresh capture (browser may still be up)
            try:
                self._context.close()
            except Exception:
                pass  # the browser may already be gone (user closed the window)
            self._closed = True

    def _throttled_refresh(self) -> None:
        """Keep the tab list + taskbar icon fresh, but only on the probe cadence.
        The cheap liveness check in is_closed() runs far more often than this."""
        now = time.monotonic()
        if now - self._last_probe < self._PROBE_INTERVAL:
            return
        self._last_probe = now
        self._snapshot_session()
        self._apply_icon()

    def is_closed(self) -> bool:
        if self._closed:
            return True
        # The Playwright "close" event never fires unless the sync event loop is
        # pumped, which the runtime worker's wait loop doesn't do — so poll the OS.
        # The cheap pid liveness check runs on EVERY call so a user-closed window
        # (the X button) is detected within ~0.1s; only the expensive full scan +
        # tab snapshot + icon refresh are throttled to _PROBE_INTERVAL. Previously
        # the whole check was throttled, so the list took up to 2s to update.
        if self.browser_pid is not None:
            if self._process_alive():
                self._throttled_refresh()
                return False
            # Our exact process is gone. One confirming full scan (the pid could
            # have been a transient during startup) before declaring it closed.
            if self._locate_browser():
                self._throttled_refresh()
                return False
            self._closed = True
            return True
        # No pid captured yet: fall back to the throttled full scan to find it.
        now = time.monotonic()
        if now - self._last_probe < self._PROBE_INTERVAL:
            return False
        self._last_probe = now
        if self._locate_browser():
            self._snapshot_session()
            self._apply_icon()
            return False
        self._closed = True
        return True

    def wait_until_closed(self) -> None:
        """Block until the browser PROCESS exits, then return — the immediate-close
        signal the worker's watcher thread waits on. Uses OS process-wait
        primitives only (Windows WaitForSingleObject, else psutil), NEVER Playwright,
        so it is safe to call off the worker thread (no cross-thread driver access).
        Returns promptly if the pid was never captured (the is_closed() poll then
        owns finalization) or the handle is already closed. is_closed() runs
        concurrently and sets _closed on a create_time-verified exit, so a reused
        pid can never keep this blocked."""
        deadline = time.monotonic() + 5.0
        while (
            self.browser_pid is None
            and not self._closed
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)
        pid = self.browser_pid
        if pid is None or self._closed:
            return
        if sys.platform == "win32" and self._wait_process_exit_windows(pid):
            self._closed = True
            return
        try:
            proc = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._closed = True
            return
        while not self._closed:
            try:
                proc.wait(timeout=1.0)
            except psutil.TimeoutExpired:
                if not self._process_alive():
                    break
                continue
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            break
        self._closed = True

    def _wait_process_exit_windows(self, pid: int) -> bool:
        """Block on the process handle for true 0-latency exit detection of a
        non-child process. Returns True if the exit (or an explicit close) was
        observed, False if the process couldn't be opened (caller falls back)."""
        import ctypes

        SYNCHRONIZE = 0x00100000
        WAIT_OBJECT_0 = 0x0
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        try:
            while not self._closed:
                # 1s slices so an explicit close() (which sets _closed) unblocks us.
                if kernel32.WaitForSingleObject(handle, 1000) == WAIT_OBJECT_0:
                    return True
            return True
        finally:
            kernel32.CloseHandle(handle)


class CloakPersistentLauncher:
    def launch(self, snapshot: dict[str, Any]) -> BrowserHandle:
        import cloakbrowser

        # Own throwaway timer: splits the launch black box into seed vs context
        # creation vs tab restore and logs one runtime.launch_breakdown line. Kept
        # internal so launch()'s signature is unchanged (injectable fakes intact).
        breakdown = StartTimer()
        profile_dir = snapshot["profile_dir"]
        profile_dir.mkdir(parents=True, exist_ok=True)
        user_data_path = profile_dir / "user-data"
        # One-time seed so the omnibox searches Google instead of treating typed
        # text as a hostname. Best-effort; must never block a launch.
        with breakdown.stage("google_seed"):
            ensure_google_search(user_data_path)
        user_data_dir = str(user_data_path)
        with breakdown.stage("context_creation"):
            context = cloakbrowser.launch_persistent_context(
                user_data_dir,
                **persistent_context_kwargs(snapshot, headless=False),
            )
        # Create the handle first so its icon burst starts stamping the plasma
        # taskbar icon immediately — concurrently with (not after) tab restore,
        # which otherwise let Chrome's default icon show for the whole restore.
        with breakdown.stage("handle_locate"):
            handle = _PersistentContextHandle(context, user_data_dir, icon_seed=snapshot["id"])
        # Reopen the tabs from the last stop; fall back to startup_urls on first
        # run. Each navigation is best-effort: a dead or slow URL (a typo'd host
        # like http://test/, a hung page) must never crash the launch or block the
        # other tabs. "commit" returns as soon as the page starts loading, and a
        # total time budget caps how long a run of dead hosts can hold up a launch.
        with breakdown.stage("tab_restore"):
            deadline = time.monotonic() + _RESTORE_TIME_BUDGET_SECONDS
            for url in urls_to_open(profile_dir, snapshot["startup_urls"]):
                if time.monotonic() >= deadline:
                    break  # bounded total restoration time
                page = context.new_page()
                try:
                    page.goto(url, wait_until="commit", timeout=15000)
                except Exception:
                    try:
                        page.close()  # don't leave a dangling failed/blank tab
                    except Exception:
                        pass
        breakdown.emit(snapshot["id"], event="runtime.launch_breakdown")
        return handle
