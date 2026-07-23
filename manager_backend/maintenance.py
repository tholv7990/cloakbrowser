"""Process-wide maintenance gate.

A backup restore rewrites the whole SQLite database, so it must not race any
other writer. The gate lets restore take *exclusive* ownership: while it holds
the gate, every state-changing operation (runtime/diagnostic/automation/factory
starts and other mutations that opt in) is rejected with a safe 409, and restore
waits for already-in-flight operations to drain before it proceeds.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

from fastapi import Request

from .errors import ManagerError


def _maintenance_error() -> ManagerError:
    return ManagerError(
        "maintenance_in_progress",
        "A maintenance operation is in progress. Try again shortly.",
        409,
    )


def _busy_error() -> ManagerError:
    return ManagerError(
        "maintenance_busy",
        "Could not start maintenance because operations are still active. Try again shortly.",
        409,
    )


class MaintenanceGate:
    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._maintenance = False
        self._active = 0

    @contextmanager
    def operation(self):
        """Guard a state-changing operation; 409 while a restore holds the gate."""
        with self._cond:
            if self._maintenance:
                raise _maintenance_error()
            self._active += 1
        try:
            yield
        finally:
            with self._cond:
                self._active -= 1
                self._cond.notify_all()

    @contextmanager
    def exclusive(self, drain_timeout: float = 10.0):
        """Take exclusive ownership for a restore, draining in-flight operations."""
        with self._cond:
            if self._maintenance:
                raise _maintenance_error()
            self._maintenance = True
            deadline = time.monotonic() + drain_timeout
            while self._active > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._maintenance = False
                    self._cond.notify_all()
                    raise _busy_error()
                self._cond.wait(timeout=min(remaining, 0.25))
        try:
            yield
        finally:
            with self._cond:
                self._maintenance = False
                self._cond.notify_all()


def guard_maintenance(request: Request):
    """FastAPI dependency: hold a gate operation for the request's duration, so a
    worker-spawning/state-changing endpoint is rejected (409) while a restore holds
    the gate, and an in-flight request drains before a restore proceeds."""
    with request.app.state.maintenance_gate.operation():
        yield
