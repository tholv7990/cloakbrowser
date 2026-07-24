from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from ...models import RuntimeSession
from ...config import ManagerSettings
from ...errors import ManagerError
from .logs import append_profile_log
from .service import transition_runtime
from .timing import StartTimer


class ProfileWorker(threading.Thread):
    # Mid-session proxy monitoring (F-013): re-check a running profile's proxy on
    # this cadence; crash the run after this many consecutive failures rather than
    # silently continuing on a dead proxy.
    _PROXY_HEALTH_INTERVAL = 120.0
    _PROXY_HEALTH_FAILURES = 2

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
        proxy_health: Callable[[dict[str, Any]], bool] | None = None,
        timer: StartTimer | None = None,
    ):
        super().__init__(name=f"profile-{snapshot['id']}", daemon=True)
        self.runtime_id = runtime_id
        self.snapshot = snapshot
        self._session_factory = session_factory
        self._launcher = launcher
        self._launch_semaphore = launch_semaphore
        self._profile_lock = profile_lock
        self._proxy_preflight = proxy_preflight
        self._proxy_health = proxy_health
        self._on_finished = on_finished
        self._settings = settings
        self._timer = timer or StartTimer()
        self._commands: queue.SimpleQueue[str] = queue.SimpleQueue()

    def _monitors_proxy(self) -> bool:
        """Only monitor profiles that route through a proxy and opted into testing."""
        return (
            self._proxy_health is not None
            and bool(self.snapshot.get("proxy_url"))
            and bool(self.snapshot.get("test_proxy_before_launch", True))
        )

    def _proxy_alive(self) -> bool:
        try:
            return bool(self._proxy_health(self.snapshot))
        except Exception:
            return False  # a health-check error must never itself crash the run loop

    def request_stop(self) -> None:
        self._commands.put("stop")

    def _transition(self, state: str, message: str | None = None) -> None:
        with self._session_factory() as session:
            runtime = session.get(RuntimeSession, self.runtime_id)
            if runtime is not None:
                transition_runtime(session, runtime, state, message=message)

    def _start_close_watcher(self, handle: Any) -> None:
        """Immediate finalization: a watcher thread blocks until the browser
        process exits, then wakes the run loop through its command queue — instead
        of waiting up to one poll interval. The OS-poll in is_closed() stays as the
        fallback (used when a handle has no waiter). The waiter uses OS process
        primitives only (never Playwright), so calling it off the worker thread is
        safe — no cross-thread driver access. Best-effort; the poll still finalizes
        if the watcher can't run.
        """
        waiter = getattr(handle, "wait_until_closed", None)
        if waiter is None:
            return

        def _watch() -> None:
            try:
                waiter()
            except Exception:
                return
            try:
                self._commands.put("closed")
            except Exception:
                pass

        threading.Thread(
            target=_watch, name=f"close-watch-{self.snapshot['id']}", daemon=True
        ).start()

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
            with self._timer.stage("proxy_preflight"):
                self.snapshot["proxy_url"] = self._proxy_preflight(self.snapshot)
            # Time spent parked on the launch semaphore (other launches ahead) is
            # start latency the user feels but no single stage owns. Acquire/release
            # manually so the wait is timed while the semaphore still wraps ONLY the
            # launch phase (released before the probe loop, unchanged behavior).
            with self._timer.stage("launch_gate_wait"):
                self._launch_semaphore.acquire()
            try:
                self._transition("starting")
                with self._timer.stage("browser_launch"):
                    handle = self._launcher.launch(self.snapshot)
                self._record_browser_ownership(handle)
                self._start_close_watcher(handle)
                self._append_log(
                    "runtime.process_started",
                    fields={"profile_path": str(self.snapshot["profile_dir"])},
                )
                self._transition("running")
                self._append_log("runtime.ready")
                # One structured, non-secret line: where the start wall-clock went.
                self._timer.emit(self.snapshot["id"])
            finally:
                self._launch_semaphore.release()

            proxy_failures = 0
            last_health_check = time.monotonic()
            while True:
                try:
                    command = self._commands.get(timeout=0.1)
                except queue.Empty:
                    command = None
                if command in ("stop", "closed") or handle.is_closed():
                    self._transition("stopping")
                    handle.close()
                    self._transition("stopped")
                    self._append_log("runtime.exited")
                    break
                if self._monitors_proxy():
                    now = time.monotonic()
                    if now - last_health_check >= self._PROXY_HEALTH_INTERVAL:
                        last_health_check = now
                        proxy_failures = 0 if self._proxy_alive() else proxy_failures + 1
                        if proxy_failures >= self._PROXY_HEALTH_FAILURES:
                            self._transition("stopping")
                            handle.close()
                            self._transition("crashed", "proxy_lost")
                            self._append_log("runtime.crashed", "error")
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
