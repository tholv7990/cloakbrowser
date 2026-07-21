from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...errors import ManagerError
from ...models import Profile, RuntimeSession, utc_now


ACTIVE_STATES = frozenset({"queued", "starting", "running", "stopping", "detached"})
COUNTED_ACTIVE_STATES = frozenset({"starting", "running", "stopping"})
_TRANSITIONS = {
    "queued": frozenset({"starting", "stopped", "crashed", "detached"}),
    "starting": frozenset({"running", "stopping", "crashed", "detached"}),
    "running": frozenset({"stopping", "crashed", "detached"}),
    "stopping": frozenset({"stopped", "crashed", "detached"}),
    "detached": frozenset({"stopping", "stopped", "crashed"}),
    "stopped": frozenset(),
    "crashed": frozenset(),
}


def _active_runtime_count_filters():
    return (
        RuntimeSession.state.in_(COUNTED_ACTIVE_STATES),
        Profile.deleted_at.is_(None),
    )


def count_active_runtimes(session: Session, folder_id: str | None = None) -> int:
    statement = (
        select(func.count(RuntimeSession.id))
        .join(Profile, RuntimeSession.profile_id == Profile.id)
        .where(*_active_runtime_count_filters())
    )
    if folder_id is not None:
        statement = statement.where(Profile.folder_id == folder_id)
    return int(session.scalar(statement) or 0)


def count_active_runtimes_by_folder(
    session: Session, folder_ids: list[str]
) -> dict[str, int]:
    if not folder_ids:
        return {}
    rows = session.execute(
        select(Profile.folder_id, func.count(RuntimeSession.id))
        .join(Profile, RuntimeSession.profile_id == Profile.id)
        .where(*_active_runtime_count_filters(), Profile.folder_id.in_(folder_ids))
        .group_by(Profile.folder_id)
    )
    return {folder_id: int(count) for folder_id, count in rows}


def active_runtime(session: Session, profile_id: str) -> RuntimeSession | None:
    return session.scalar(
        select(RuntimeSession)
        .where(RuntimeSession.profile_id == profile_id, RuntimeSession.state.in_(ACTIVE_STATES))
        .order_by(RuntimeSession.created_at.desc())
    )


def create_runtime_session(session: Session, profile: Profile) -> RuntimeSession:
    if profile.deleted_at is not None:
        raise ManagerError("profile_trashed", "A trashed profile cannot be started.", 409)
    if active_runtime(session, profile.id) is not None:
        raise ManagerError("profile_already_running", "This profile is already active.", 409)
    runtime = RuntimeSession(profile=profile, state="queued", last_message="queued")
    session.add(runtime)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ManagerError("profile_already_running", "This profile is already active.", 409) from None
    session.refresh(runtime)
    return runtime


def transition_runtime(
    session: Session,
    runtime: RuntimeSession,
    state: str,
    *,
    message: str | None = None,
) -> RuntimeSession:
    if state not in _TRANSITIONS.get(runtime.state, frozenset()):
        raise ManagerError(
            "invalid_runtime_transition",
            "The requested runtime state transition is not allowed.",
            409,
        )
    now = utc_now()
    runtime.state = state
    runtime.last_message = message or state
    if state == "running" and runtime.started_at is None:
        runtime.started_at = now
    if state in {"stopped", "crashed"}:
        runtime.stopped_at = now
    session.commit()
    session.refresh(runtime)
    return runtime
