from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

from ...models import RuntimeSession
from ...config import ManagerSettings
from ...errors import ManagerError
from .logs import append_profile_log
from .service import transition_runtime


class ProfileWorker(threading.Thread):
    def __init__(
        self,
        *,
        runtime_id: str,
        snapshot: dict[str, Any],
        session_factory: Callable,
        launcher: Any,
        launch_semaphore: threading.BoundedSemaphore,
        profile_lock: Any,
        proxy_preflight: Callable[[dict[str, Any]], str | None],
        on_finished: Callable[[str, "ProfileWorker"], None],
        settings: ManagerSettings,
    ):
        super().__init__(name=f"profile-{snapshot['id']}", daemon=True)
        self.runtime_id = runtime_id
        self.snapshot = snapshot
        self._session_factory = session_factory
        self._launcher = launcher
        self._launch_semaphore = launch_semaphore
        self._profile_lock = profile_lock
        self._proxy_preflight = proxy_preflight
        self._on_finished = on_finished
        self._settings = settings
        self._commands: queue.SimpleQueue[str] = queue.SimpleQueue()

    def request_stop(self) -> None:
        self._commands.put("stop")

    def _transition(self, state: str, message: str | None = None) -> None:
        with self._session_factory() as session:
            runtime = session.get(RuntimeSession, self.runtime_id)
            if runtime is not None:
                transition_runtime(session, runtime, state, message=message)

    def _record_browser_ownership(self, handle: Any) -> None:
        browser_pid = getattr(handle, "browser_pid", None)
        browser_created_at = getattr(handle, "browser_created_at", None)
        if browser_pid is None or browser_created_at is None:
            return
        with self._session_factory() as session:
            runtime = session.get(RuntimeSession, self.runtime_id)
            if runtime is not None:
                runtime.browser_pid = browser_pid
                runtime.browser_created_at = browser_created_at
                session.commit()

    def _append_log(
        self,
        event: str,
        level: str = "info",
        *,
        fields: dict[str, object] | None = None,
    ) -> None:
        with self._session_factory() as session:
            append_profile_log(
                session,
                self.snapshot["id"],
                level,
                event,
                fields=fields,
                settings=self._settings,
            )

    def run(self) -> None:
        handle = None
        try:
            with self._launch_semaphore:
                self._transition("starting")
                self.snapshot["proxy_url"] = self._proxy_preflight(self.snapshot)
                handle = self._launcher.launch(self.snapshot)
                self._record_browser_ownership(handle)
                self._append_log(
                    "runtime.process_started",
                    fields={"profile_path": str(self.snapshot["profile_dir"])},
                )
                self._transition("running")
                self._append_log("runtime.ready")

            while True:
                try:
                    command = self._commands.get(timeout=0.1)
                except queue.Empty:
                    command = None
                if command == "stop" or handle.is_closed():
                    self._transition("stopping")
                    handle.close()
                    self._transition("stopped")
                    self._append_log("runtime.exited")
                    break
        except Exception as error:
            try:
                preflight_failed = (
                    isinstance(error, ManagerError)
                    and error.code == "proxy_preflight_failed"
                )
                if preflight_failed:
                    self._append_log("runtime.preflight_failed", "warning")
                message = (
                    "proxy_preflight_failed"
                    if preflight_failed
                    else ("browser_launch_failed" if handle is None else "browser_crashed")
                )
                self._transition(
                    "crashed",
                    message,
                )
                self._append_log("runtime.crashed", "error")
            except Exception:
                pass
        finally:
            self._profile_lock.release()
            self._on_finished(self.snapshot["id"], self)
