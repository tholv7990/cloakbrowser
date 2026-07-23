"""Per-(scope, identifier) attempt throttling with lockout — the network-facing
replacement for the desktop's single global in-memory counter.

Throttle writes use their OWN short-lived session (committed immediately) so a
recorded failure PERSISTS even though the failing request's main transaction rolls
back. Enforce before the attempt; record the outcome after.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from . import models
from .db import ensure_aware_utc, utc_now


class ThrottleError(Exception):
    def __init__(self) -> None:
        self.code = "throttled"
        super().__init__("throttled")


def _get(session, scope: str, identifier: str) -> models.AuthThrottle | None:
    return session.execute(
        select(models.AuthThrottle).where(
            models.AuthThrottle.scope == scope,
            models.AuthThrottle.identifier == identifier,
        )
    ).scalar_one_or_none()


def enforce_not_locked(
    factory: sessionmaker, *, scope: str, identifier: str, now: datetime | None = None
) -> None:
    now = now or utc_now()
    with factory() as session:
        row = _get(session, scope, identifier)
        locked = (
            row is not None
            and row.locked_until is not None
            and ensure_aware_utc(row.locked_until) > now
        )
    if locked:
        raise ThrottleError()


def record_failure(
    factory: sessionmaker,
    *,
    scope: str,
    identifier: str,
    max_attempts: int,
    lockout: timedelta,
    now: datetime | None = None,
) -> None:
    now = now or utc_now()
    with factory() as session:
        row = _get(session, scope, identifier)
        if row is None:
            row = models.AuthThrottle(
                scope=scope, identifier=identifier, attempts=0, window_started_at=now
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:  # a concurrent first-failure won the insert
                session.rollback()
                row = _get(session, scope, identifier)
        # Roll the window once the previous lockout window has elapsed.
        if ensure_aware_utc(row.window_started_at) + lockout < now:
            row.attempts = 0
            row.window_started_at = now
            row.locked_until = None
        row.attempts += 1
        if row.attempts >= max_attempts:
            row.locked_until = now + lockout
        session.commit()


def record_success(factory: sessionmaker, *, scope: str, identifier: str) -> None:
    with factory() as session:
        row = _get(session, scope, identifier)
        if row is not None:
            row.attempts = 0
            row.locked_until = None
            session.commit()
