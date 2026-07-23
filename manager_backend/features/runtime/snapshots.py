from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Profile, RuntimeSession
from .service import COUNTED_ACTIVE_STATES


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


def runtime_marker(
    runtimes: list[RuntimeSession], running_count: int
) -> tuple[object, ...]:
    return (
        tuple(
            (runtime.id, runtime.state, runtime.updated_at, runtime.last_message)
            for runtime in runtimes
        ),
        running_count,
    )
