"""Browser-launch abstraction for the Shop-check coordinator.

The coordinator depends on this narrow protocol, not on RuntimeManager directly,
so unit tests inject a FakeLauncher and never start a real browser. The
production adapter simply delegates to the owned-runtime RuntimeManager.
"""

from __future__ import annotations

from typing import Protocol


class RuntimeLauncher(Protocol):
    def start(self, profile_id: str) -> None: ...

    def stop(self, profile_id: str) -> None: ...


class RuntimeManagerLauncher:
    """Delegates to the real RuntimeManager (owned launch/stop, PID tracking)."""

    def __init__(self, runtime_manager):
        self._runtime_manager = runtime_manager

    def start(self, profile_id: str) -> None:
        self._runtime_manager.start(profile_id)

    def stop(self, profile_id: str) -> None:
        self._runtime_manager.stop(profile_id)
