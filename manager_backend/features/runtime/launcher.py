from __future__ import annotations

import json
import os
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
        "locale": location.get("locale"),
        "timezone": location.get("timezone"),
        "location": location,
        "window": dict(profile.window or {}),
        "behavior": dict(profile.behavior or {}),
        "startup_urls": list(profile.startup_urls or []),
        "proxy_id": profile.proxy_id,
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

    def __init__(self, context: Any, user_data_dir: str):
        self._context = context
        self._closed = False
        self._profile_dir = Path(user_data_dir).parent
        self._owned_path = _normalize_udd(user_data_dir)
        self.browser_pid: int | None = None
        self.browser_created_at: datetime | None = None
        self._last_probe = 0.0
        self._cdp_session: Any | None = None
        self._last_saved_urls: list[str] | None = None
        self._locate_browser()
        context.on("close", self._mark_closed)

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

    def is_closed(self) -> bool:
        if self._closed:
            return True
        # The Playwright "close" event never fires unless the sync event loop is
        # pumped, which the runtime worker's wait loop doesn't do — so poll the OS
        # for the browser process instead (throttled).
        now = time.monotonic()
        if now - self._last_probe < self._PROBE_INTERVAL:
            return False
        self._last_probe = now
        # Alive if our exact process (pid + create_time) still runs; otherwise
        # re-scan by exact --user-data-dir in case the pid was never captured.
        if self._process_alive() or self._locate_browser():
            self._snapshot_session()  # alive: keep the tab list fresh on disk
            return False
        self._closed = True
        return True


class CloakPersistentLauncher:
    def launch(self, snapshot: dict[str, Any]) -> BrowserHandle:
        import cloakbrowser
        from cloakbrowser.config import get_binary_dir

        profile_dir = snapshot["profile_dir"]
        profile_dir.mkdir(parents=True, exist_ok=True)
        user_data_path = profile_dir / "user-data"
        # Seed a default search engine (Google) so the omnibox searches instead of
        # treating typed text as a hostname. Best-effort; must never block a launch.
        try:
            ensure_initial_preferences(get_binary_dir(snapshot.get("browser_version")))
        except Exception:
            pass
        seed_default_search_engine(user_data_path)
        user_data_dir = str(user_data_path)
        context = cloakbrowser.launch_persistent_context(
            user_data_dir,
            **persistent_context_kwargs(snapshot, headless=False),
        )
        # Reopen the tabs from the last stop; fall back to startup_urls on first
        # run. Each navigation is best-effort: a dead or slow URL (a typo'd host
        # like http://test/, a hung page) must never crash the launch or block the
        # other tabs. "commit" returns as soon as the page starts loading, and a
        # total time budget caps how long a run of dead hosts can hold up a launch.
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
        return _PersistentContextHandle(context, user_data_dir)
