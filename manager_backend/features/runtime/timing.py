"""Structured per-stage timing for a profile start (measurement, not enforcement).

A single `StartTimer` travels from `RuntimeManager.start` through the profile
worker and records how long each stage takes. When the runtime reaches
``running`` the worker emits one ``runtime.start_timing`` line on the
``manager.runtime.timing`` logger. Everything logged is non-secret: a canonical
profile UUID, stage names, and millisecond integers — no proxy URLs, no
credentials, no paths.

Kept deliberately out of the profile-log channel (`logs.py`), which is an
allow-listed, safe-message-only surface — timing is diagnostic, not user-facing.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from typing import Iterator

_logger = logging.getLogger("manager.runtime.timing")


class StartTimer:
    """Collects named stage durations for one profile start.

    Use as ``with timer.stage("proxy_preflight"): ...`` around a stage, or
    ``timer.record(name, ms)`` for an externally measured span. ``total_ms`` is
    wall time since the timer was created (i.e. since the start request began).
    """

    __slots__ = ("_t0", "_stages")

    def __init__(self) -> None:
        self._t0 = time.perf_counter()
        self._stages: dict[str, int] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = round((time.perf_counter() - started) * 1000)
            # Sum on repeat so a retried stage accumulates rather than overwrites.
            self._stages[name] = self._stages.get(name, 0) + elapsed

    def record(self, name: str, ms: float) -> None:
        self._stages[name] = self._stages.get(name, 0) + round(ms)

    @property
    def stages_ms(self) -> dict[str, int]:
        return dict(self._stages)

    def total_ms(self) -> int:
        return round((time.perf_counter() - self._t0) * 1000)

    def payload(self, profile_id: str, event: str = "runtime.start_timing") -> dict[str, object]:
        return {
            "event": event,
            "profile_id": profile_id,
            "stages_ms": self.stages_ms,
            "total_ms": self.total_ms(),
        }

    def emit(self, profile_id: str, event: str = "runtime.start_timing") -> dict[str, object]:
        """Log the timing as one structured JSON line and return the payload."""
        data = self.payload(profile_id, event)
        _logger.info(json.dumps(data, separators=(",", ":")))
        return data
