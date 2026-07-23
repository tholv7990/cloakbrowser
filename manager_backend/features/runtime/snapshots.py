from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import Profile, RuntimeSession
from .service import COUNTED_ACTIVE_STATES


@dataclass(frozen=True)
class SnapshotPoll:
    changed: bool
    runtimes: list[RuntimeSession]
    running_count: int


def runtime_change_marker(
    session: Session,
) -> tuple[int, datetime | None, int, datetime | None]:
    runtime_count = int(
        session.scalar(select(func.count()).select_from(RuntimeSession)) or 0
    )
    runtime_updated = session.scalar(select(func.max(RuntimeSession.updated_at)))
    profile_count, profile_updated = session.execute(
        select(func.count(), func.max(Profile.updated_at)).select_from(Profile)
    ).one()
    return runtime_count, runtime_updated, int(profile_count), profile_updated


class RuntimeSnapshotCache:
    def __init__(self) -> None:
        self._marker: tuple[int, datetime | None, int, datetime | None] | None = None
        self._runtimes: list[RuntimeSession] = []
        self._running_count = 0

    def poll(self, session: Session) -> SnapshotPoll:
        marker = runtime_change_marker(session)
        if marker == self._marker:
            return SnapshotPoll(False, self._runtimes, self._running_count)
        runtimes, running_count = load_latest_runtimes(session)
        self._marker = marker
        self._runtimes = runtimes
        self._running_count = running_count
        return SnapshotPoll(True, runtimes, running_count)


def load_latest_runtimes(session: Session) -> tuple[list[RuntimeSession], int]:
    """Return one latest runtime per live profile and its counted-active total."""
    latest_runtime_id = (
        select(RuntimeSession.id)
        .where(RuntimeSession.profile_id == Profile.id)
        .order_by(RuntimeSession.created_at.desc(), RuntimeSession.id.desc())
        .limit(1)
        .correlate(Profile)
        .scalar_subquery()
    )
    latest = (
        select(latest_runtime_id.label("runtime_id"))
        .where(Profile.deleted_at.is_(None))
        .subquery()
    )
    runtimes = list(
        session.scalars(
            select(RuntimeSession)
            .join(latest, latest.c.runtime_id == RuntimeSession.id)
            .order_by(RuntimeSession.created_at.desc(), RuntimeSession.id.desc())
        )
    )
    running_count = sum(
        runtime.state in COUNTED_ACTIVE_STATES for runtime in runtimes
    )
    return runtimes, running_count
