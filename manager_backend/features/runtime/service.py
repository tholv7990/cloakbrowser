from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...errors import ManagerError
from ...models import Profile, RuntimeSession, utc_now


ACTIVE_STATES = frozenset({"queued", "starting", "running", "stopping", "detached"})
_TRANSITIONS = {
    "queued": frozenset({"starting", "stopped", "crashed"}),
    "starting": frozenset({"running", "stopping", "crashed"}),
    "running": frozenset({"stopping", "crashed", "detached"}),
    "stopping": frozenset({"stopped", "crashed", "detached"}),
    "detached": frozenset({"stopping", "stopped", "crashed"}),
    "stopped": frozenset(),
    "crashed": frozenset(),
}


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
