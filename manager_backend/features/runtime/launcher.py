from __future__ import annotations

from typing import Any, Protocol


class BrowserHandle(Protocol):
    def close(self) -> None: ...

    def is_closed(self) -> bool: ...


class BrowserLauncher(Protocol):
    def launch(self, snapshot: dict[str, Any]) -> BrowserHandle: ...


class _PersistentContextHandle:
    def __init__(self, context: Any):
        self._context = context
        self._closed = False
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
        context = cloakbrowser.launch_persistent_context(
            str(profile_dir / "user-data"),
            headless=False,
            fingerprint_preset=snapshot["fingerprint_preset"],
            args=[f"--fingerprint={snapshot['fingerprint_seed']}"],
            browser_version=snapshot.get("browser_version"),
            user_agent=snapshot.get("custom_user_agent"),
            locale=snapshot.get("locale"),
            timezone=snapshot.get("timezone"),
        )
        for url in snapshot["startup_urls"]:
            context.new_page().goto(url)
        return _PersistentContextHandle(context)
