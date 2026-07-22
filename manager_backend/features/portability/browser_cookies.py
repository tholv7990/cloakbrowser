"""Controlled browser-context operations for profile cookie portability."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...config import ManagerSettings
from ...errors import ManagerError
from ...models import Profile
from ..runtime.launcher import persistent_context_kwargs, profile_launch_snapshot
from ..runtime.locks import ProfileFileLock


class CookieContextAdapter:
    """Import and export cookies through a short-lived CloakBrowser context."""

    def __init__(
        self,
        settings: ManagerSettings,
        *,
        launch_persistent_context: Callable[..., Any] | None = None,
        proxy_resolver: Callable[[Profile], str | None] | None = None,
        lock_factory: Callable[[Profile], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._launch_persistent_context = launch_persistent_context
        self._proxy_resolver = proxy_resolver or (lambda _profile: None)
        self._lock_factory = lock_factory or self._default_lock

    def _default_lock(self, profile: Profile) -> ProfileFileLock:
        return ProfileFileLock(
            self._settings.profile_root / profile.id / ".runtime.lock", profile.id
        )

    def _launch(self, profile: Profile) -> Any:
        launch = self._launch_persistent_context
        if launch is None:
            import cloakbrowser

            launch = cloakbrowser.launch_persistent_context
        snapshot = profile_launch_snapshot(profile, self._settings)
        snapshot["proxy_url"] = self._proxy_resolver(profile)
        profile_dir = snapshot["profile_dir"]
        profile_dir.mkdir(parents=True, exist_ok=True)
        return launch(
            str(profile_dir / "user-data"),
            **persistent_context_kwargs(snapshot, headless=True),
        )

    def _operate(self, profile: Profile, operation: Callable[[Any], Any]) -> Any:
        if profile.runtime_state != "stopped":
            raise ManagerError(
                "profile_not_stopped",
                "The profile must be stopped for cookie operations.",
                409,
            )
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

    def import_cookies(self, profile: Profile, cookies: list[dict[str, Any]]) -> None:
        self._operate(profile, lambda context: context.add_cookies(cookies))

    def export_cookies(self, profile: Profile) -> list[dict[str, Any]]:
        cookies = self._operate(profile, lambda context: context.cookies())
        return list(cookies)
