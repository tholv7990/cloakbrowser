from __future__ import annotations

from typing import Any, Protocol
from datetime import datetime, timezone

import psutil
from sqlalchemy import select
from sqlalchemy.orm import Session

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

    location = profile.location or {}
    return {
        "id": profile.id,
        "profile_dir": settings.profile_root / profile.id,
        "fingerprint_seed": profile.fingerprint_seed,
        "fingerprint_preset": profile.fingerprint_preset,
        "browser_version": (
            profile.browser_version if profile.browser_version_mode == "pinned" else None
        ),
        "custom_user_agent": (
            profile.custom_user_agent if profile.user_agent_mode == "custom" else None
        ),
        "locale": location.get("locale"),
        "timezone": location.get("timezone"),
        "startup_urls": list(profile.startup_urls or []),
        "proxy_id": profile.proxy_id,
        "extension_paths": list(extension_paths or []),
    }


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
    def __init__(self, context: Any, user_data_dir: str):
        self._context = context
        self._closed = False
        self.browser_pid: int | None = None
        self.browser_created_at: datetime | None = None
        owned_path = user_data_dir.casefold()
        for process in psutil.Process().children(recursive=True):
            try:
                if owned_path in " ".join(process.cmdline()).casefold():
                    self.browser_pid = process.pid
                    self.browser_created_at = datetime.fromtimestamp(
                        process.create_time(), timezone.utc
                    )
                    break
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        context.on("close", self._mark_closed)

    def _mark_closed(self, *_args: Any) -> None:
        self._closed = True

    def close(self) -> None:
        if not self._closed:
            self._context.close()
            self._closed = True

    def is_closed(self) -> bool:
        return self._closed


class CloakPersistentLauncher:
    def launch(self, snapshot: dict[str, Any]) -> BrowserHandle:
        import cloakbrowser

        profile_dir = snapshot["profile_dir"]
        profile_dir.mkdir(parents=True, exist_ok=True)
        user_data_dir = str(profile_dir / "user-data")
        context = cloakbrowser.launch_persistent_context(
            user_data_dir,
            **persistent_context_kwargs(snapshot, headless=False),
        )
        for url in snapshot["startup_urls"]:
            context.new_page().goto(url)
        return _PersistentContextHandle(context, user_data_dir)
