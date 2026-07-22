from __future__ import annotations

import json
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
_INTERNAL_URL_PREFIXES = ("about:", "chrome:", "chrome-extension:", "devtools:", "edge:")

# A fresh CloakBrowser profile ships with no default search engine, so the
# address bar treats plain text as a hostname ("test" -> http://test/) instead
# of searching. Seed Google so it behaves like normal Chrome.
_DEFAULT_SEARCH_PREFS = {
    "default_search_provider_data": {
        "template_url_data": {
            "short_name": "Google",
            "keyword": "google.com",
            "url": "https://www.google.com/search?q={searchTerms}",
            "suggestions_url": "https://www.google.com/complete/search?client=chrome&q={searchTerms}",
            "favicon_url": "https://www.google.com/favicon.ico",
            "prepopulate_id": 1,
            "safe_for_autoreplace": True,
        }
    }
}


def seed_default_search_engine(user_data_dir: Path) -> None:
    """Ensure the profile has a default search engine (Google) before launch.

    Applies to new profiles and to existing ones that never got one; leaves a
    search engine the user has already chosen untouched. Written before launch,
    so the profile is not running and the file is not locked.
    """
    prefs = user_data_dir / "Default" / "Preferences"
    try:
        if prefs.exists():
            data = json.loads(prefs.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "default_search_provider_data" in data:
                return
            data.update(_DEFAULT_SEARCH_PREFS)
        else:
            prefs.parent.mkdir(parents=True, exist_ok=True)
            data = dict(_DEFAULT_SEARCH_PREFS)
        prefs.write_text(json.dumps(data), encoding="utf-8")
    except (OSError, ValueError):
        pass  # a bad seed must never block a launch


def _read_last_session(profile_dir: Path) -> list[str]:
    """Return the tab URLs saved when the profile was last stopped (may be empty)."""
    try:
        data = json.loads((profile_dir / _SESSION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [url for url in data.get("urls", []) if isinstance(url, str) and url]


def urls_to_open(profile_dir: Path, startup_urls: list[str]) -> list[str]:
    """Restore the previous tabs if any were saved; otherwise seed startup_urls."""
    return _read_last_session(profile_dir) or list(startup_urls)


def persistent_context_kwargs(
    snapshot: dict[str, Any], *, headless: bool
) -> dict[str, Any]:
    """Translate a Manager snapshot into CloakBrowser persistent-context options."""

    kwargs = {
        "headless": headless,
        "fingerprint_preset": snapshot["fingerprint_preset"],
        "args": [f"--fingerprint={snapshot['fingerprint_seed']}"],
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


class _PersistentContextHandle:
    _PROBE_INTERVAL = 2.0

    def __init__(self, context: Any, user_data_dir: str):
        self._context = context
        self._closed = False
        self._profile_dir = Path(user_data_dir).parent
        self._owned_path = user_data_dir.casefold()
        self.browser_pid: int | None = None
        self.browser_created_at: datetime | None = None
        self._last_probe = 0.0
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
                if self._owned_path in " ".join(process.cmdline()).casefold():
                    self.browser_pid = process.pid
                    self.browser_created_at = datetime.fromtimestamp(
                        process.create_time(), timezone.utc
                    )
                    return True
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        return False

    def _mark_closed(self, *_args: Any) -> None:
        self._closed = True

    def _save_session(self) -> None:
        """Persist the open tab URLs so the next launch reopens them."""
        try:
            urls: list[str] = []
            for page in self._context.pages:
                try:
                    url = page.url
                except Exception:
                    continue
                if url and not url.startswith(_INTERNAL_URL_PREFIXES):
                    urls.append(url)
            (self._profile_dir / _SESSION_FILE).write_text(
                json.dumps({"urls": urls}), encoding="utf-8"
            )
        except Exception:
            pass  # never let session capture block a clean stop

    def close(self) -> None:
        if not self._closed:
            self._save_session()
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
        if self.browser_pid is not None:
            if psutil.pid_exists(self.browser_pid):
                return False
            self._closed = True
            return True
        # Never captured a pid — re-scan; if nothing owns the dir, it's gone.
        if self._locate_browser():
            return False
        self._closed = True
        return True


class CloakPersistentLauncher:
    def launch(self, snapshot: dict[str, Any]) -> BrowserHandle:
        import cloakbrowser

        profile_dir = snapshot["profile_dir"]
        profile_dir.mkdir(parents=True, exist_ok=True)
        user_data_path = profile_dir / "user-data"
        seed_default_search_engine(user_data_path)
        user_data_dir = str(user_data_path)
        context = cloakbrowser.launch_persistent_context(
            user_data_dir,
            **persistent_context_kwargs(snapshot, headless=False),
        )
        # Reopen the tabs from the last stop; fall back to startup_urls on first
        # run. Each navigation is best-effort: a dead or slow URL (a typo'd host
        # like http://test/, a hung page) must never crash the launch or block
        # the other tabs. "commit" also returns as soon as the page starts
        # loading, so a heavy site doesn't hold up the launch.
        for url in urls_to_open(profile_dir, snapshot["startup_urls"]):
            page = context.new_page()
            try:
                page.goto(url, wait_until="commit", timeout=15000)
            except Exception:
                continue
        return _PersistentContextHandle(context, user_data_dir)
