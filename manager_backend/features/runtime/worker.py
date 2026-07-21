from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

from ...models import RuntimeSession
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
        on_finished: Callable[[str, "ProfileWorker"], None],
    ):
        super().__init__(name=f"profile-{snapshot['id']}", daemon=True)
        self.runtime_id = runtime_id
        self.snapshot = snapshot
        self._session_factory = session_factory
        self._launcher = launcher
        self._launch_semaphore = launch_semaphore
        self._profile_lock = profile_lock
        self._on_finished = on_finished
        self._commands: queue.SimpleQueue[str] = queue.SimpleQueue()

    def request_stop(self) -> None:
        self._commands.put("stop")

    def _transition(self, state: str, message: str | None = None) -> None:
        with self._session_factory() as session:
            runtime = session.get(RuntimeSession, self.runtime_id)
            if runtime is not None:
                transition_runtime(session, runtime, state, message=message)

    def run(self) -> None:
        handle = None
        try:
            with self._launch_semaphore:
                self._transition("starting")
                handle = self._launcher.launch(self.snapshot)
                self._transition("running")

            while True:
                try:
                    command = self._commands.get(timeout=0.1)
                except queue.Empty:
                    command = None
                if command == "stop" or handle.is_closed():
                    self._transition("stopping")
                    handle.close()
                    self._transition("stopped")
                    break
        except Exception:
            try:
                self._transition(
                    "crashed",
                    "browser_launch_failed" if handle is None else "browser_crashed",
                )
            except Exception:
                pass
        finally:
            self._profile_lock.release()
            self._on_finished(self.snapshot["id"], self)
