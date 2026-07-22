"""Controlled browser-context operations for profile cookie portability."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...config import ManagerSettings
from ...errors import ManagerError
from ...models import Profile
from ..runtime.launcher import persistent_context_kwargs, profile_launch_snapshot
from ..runtime.locks import ProfileFileLock


@dataclass(frozen=True)
class CookieProfileConfig:
    """Immutable profile launch data safe to pass to a worker thread."""

    id: str
    profile_dir: Path
    fingerprint_seed: str
    fingerprint_preset: str
    browser_version: str | None
    custom_user_agent: str | None
    locale: str | None
    timezone: str | None
    proxy_url: str | None

    @classmethod
    def from_profile(
        cls,
        profile: Profile,
        settings: ManagerSettings,
        *,
        proxy_url: str | None = None,
    ) -> "CookieProfileConfig":
        if profile.runtime_state != "stopped":
            raise ManagerError(
                "profile_not_stopped",
                "The profile must be stopped for cookie operations.",
                409,
            )
        snapshot = profile_launch_snapshot(profile, settings)
        return cls(
            id=snapshot["id"],
            profile_dir=snapshot["profile_dir"],
            fingerprint_seed=snapshot["fingerprint_seed"],
            fingerprint_preset=snapshot["fingerprint_preset"],
            browser_version=snapshot["browser_version"],
            custom_user_agent=snapshot["custom_user_agent"],
            locale=snapshot["locale"],
            timezone=snapshot["timezone"],
            proxy_url=proxy_url,
        )

    def launch_snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "profile_dir": self.profile_dir,
            "fingerprint_seed": self.fingerprint_seed,
            "fingerprint_preset": self.fingerprint_preset,
            "browser_version": self.browser_version,
            "custom_user_agent": self.custom_user_agent,
            "locale": self.locale,
            "timezone": self.timezone,
            "proxy_url": self.proxy_url,
        }


class CookieContextAdapter:
    """Import and export cookies through a short-lived CloakBrowser context."""

    def __init__(
        self,
        settings: ManagerSettings,
        *,
        launch_persistent_context: Callable[..., Any] | None = None,
        lock_factory: Callable[[CookieProfileConfig], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._launch_persistent_context = launch_persistent_context
        self._lock_factory = lock_factory or self._default_lock

    def _default_lock(self, profile: CookieProfileConfig) -> ProfileFileLock:
        return ProfileFileLock(
            profile.profile_dir / ".runtime.lock", profile.id
        )

    def _launch(self, profile: CookieProfileConfig) -> Any:
        launch = self._launch_persistent_context
        if launch is None:
            import cloakbrowser

            launch = cloakbrowser.launch_persistent_context
        snapshot = profile.launch_snapshot()
        profile_dir = profile.profile_dir
        profile_dir.mkdir(parents=True, exist_ok=True)
        return launch(
            str(profile_dir / "user-data"),
            **persistent_context_kwargs(snapshot, headless=True),
        )

    def _operate(
        self, profile: CookieProfileConfig, operation: Callable[[Any], Any]
    ) -> Any:
        profile_lock = self._lock_factory(profile)
        profile_lock.acquire()
        context = None
        result = None
        failure: Exception | None = None
        try:
            try:
                context = self._launch(profile)
                try:
                    result = operation(context)
                except Exception as error:
                    failure = error
                finally:
                    try:
                        context.close()
                    except Exception as error:
                        if failure is None:
                            failure = error
            except Exception as error:
                if failure is None:
                    failure = error
        finally:
            try:
                profile_lock.release()
            except Exception as error:
                if failure is None:
                    failure = error
        if failure is not None:
            raise ManagerError(
                "cookie_operation_failed",
                "The browser cookie operation could not be completed.",
                500,
            ) from None
        return result

    def import_cookies(
        self, profile: CookieProfileConfig, cookies: list[dict[str, Any]]
    ) -> None:
        self._operate(profile, lambda context: context.add_cookies(cookies))

    def export_cookies(self, profile: CookieProfileConfig) -> list[dict[str, Any]]:
        cookies = self._operate(profile, lambda context: context.cookies())
        return list(cookies)
