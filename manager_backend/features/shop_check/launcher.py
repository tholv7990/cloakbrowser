"""Browser-launch abstraction for the Shop-check coordinator.

The coordinator depends on this narrow protocol, not on RuntimeManager directly,
so unit tests inject a fake launcher and never start a real browser.

`RuntimeManager.start()` returns as soon as the background worker is spawned —
Chromium may still be booting and its CDP endpoint not yet written. Shop-check
must not drive the page until it is genuinely ready, so the launcher blocks on
`start_and_wait_ready` and returns the live CDP endpoint. On any failure it stops
whatever it started, so a launch that never becomes ready leaves no orphan
browser.
"""

from __future__ import annotations

import time
from typing import Callable, Protocol

from ...models import RuntimeSession

# Runtime states that mean "still coming up or alive" — anything else is terminal.
_ACTIVE_STATES = frozenset({"queued", "starting", "running", "stopping", "detached"})
_READY_POLL_SECONDS = 0.1


class RuntimeLaunchError(Exception):
    """A runtime could not be brought to a ready, drivable state. `reason` is a
    short, non-secret token (timeout / crashed / cancelled / a runtime message)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class RuntimeLauncher(Protocol):
    def start_and_wait_ready(
        self,
        profile_id: str,
        *,
        timeout_seconds: float,
        is_cancelled: Callable[[], bool],
    ) -> str: ...

    def stop(self, profile_id: str) -> None: ...


class RuntimeManagerLauncher:
    """Delegates to the real RuntimeManager (owned launch/stop, PID tracking) and
    waits for the started runtime to reach `running` with a persisted CDP
    endpoint before returning it."""

    def __init__(self, runtime_manager, session_factory):
        self._runtime_manager = runtime_manager
        self._session_factory = session_factory

    def start_and_wait_ready(
        self,
        profile_id: str,
        *,
        timeout_seconds: float,
        is_cancelled: Callable[[], bool],
    ) -> str:
        runtime = self._runtime_manager.start(profile_id)
        runtime_id = runtime.id
        deadline = time.monotonic() + timeout_seconds
        try:
            while True:
                if is_cancelled():
                    raise RuntimeLaunchError("cancelled")
                state, endpoint, message = self._read(runtime_id)
                if state == "running" and endpoint:
                    return endpoint
                if state is not None and state not in _ACTIVE_STATES:
                    # crashed / stopped / detached before it could be driven.
                    raise RuntimeLaunchError(message or state)
                if time.monotonic() >= deadline:
                    raise RuntimeLaunchError("timeout")
                time.sleep(_READY_POLL_SECONDS)
        except RuntimeLaunchError:
            # We started it; if it never became drivable, stop it so no browser is
            # left running unowned.
            try:
                self._runtime_manager.stop(profile_id)
            except Exception:
                pass
            raise

    def _read(self, runtime_id: str) -> tuple[str | None, str | None, str | None]:
        with self._session_factory() as session:
            runtime = session.get(RuntimeSession, runtime_id)
            if runtime is None:
                return None, None, None
            return runtime.state, runtime.cdp_endpoint, runtime.last_message

    def stop(self, profile_id: str) -> None:
        self._runtime_manager.stop(profile_id)
