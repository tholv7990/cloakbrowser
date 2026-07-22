from __future__ import annotations

import asyncio
from typing import Any, Literal


DiagnosticEventType = Literal["diagnostic.progress", "diagnostic.completed"]


class EventBroker:
    """In-process fan-out with a fixed per-client memory bound."""

    def __init__(self, *, queue_size: int = 64) -> None:
        self._queue_size = max(1, min(256, int(queue_size)))
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=self._queue_size
        )
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: dict[str, Any]) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass


def diagnostic_event(
    event_type: DiagnosticEventType, diagnostic: dict[str, Any]
) -> dict[str, Any]:
    """Return the only diagnostic fields permitted on the realtime channel."""

    progress = max(0, min(100, int(diagnostic.get("progress", 0))))
    status = diagnostic.get("status")
    error_code = diagnostic.get("error_code")
    return {
        "type": event_type,
        "diagnostic": {
            "id": diagnostic.get("id"),
            "profile_id": diagnostic.get("profile_id"),
            "kind": diagnostic.get("kind"),
            "status": status,
            "progress": progress,
            "error_code": error_code if event_type == "diagnostic.completed" else None,
        },
    }
