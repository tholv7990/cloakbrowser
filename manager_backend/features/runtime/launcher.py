from __future__ import annotations

from typing import Any, Protocol
from datetime import datetime, timezone

import psutil


class BrowserHandle(Protocol):
    def close(self) -> None: ...

    def is_closed(self) -> bool: ...


class BrowserLauncher(Protocol):
    def launch(self, snapshot: dict[str, Any]) -> BrowserHandle: ...


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
        return _PersistentContextHandle(context, user_data_dir)
