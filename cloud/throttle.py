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


# --- session-based core (caller owns the transaction) -------------------------


def enforce_on(session, *, scope: str, identifier: str, now: datetime | None = None) -> None:
    now = now or utc_now()
    row = _get(session, scope, identifier)
    if (
        row is not None
        and row.locked_until is not None
        and ensure_aware_utc(row.locked_until) > now
    ):
        raise ThrottleError()


def record_failure_on(
    session,
    *,
    scope: str,
    identifier: str,
    max_attempts: int,
    lockout: timedelta,
    now: datetime | None = None,
) -> None:
    now = now or utc_now()
    row = _get(session, scope, identifier)
    if row is None:
        # Single INSERT at the caller's commit — no flush, so no extra write.
        session.add(
            models.AuthThrottle(
                scope=scope,
                identifier=identifier,
                attempts=1,
                window_started_at=now,
                locked_until=now + lockout if 1 >= max_attempts else None,
            )
        )
        return
    # Roll the window once the previous lockout window has elapsed.
    if ensure_aware_utc(row.window_started_at) + lockout < now:
        row.attempts = 0
        row.window_started_at = now
        row.locked_until = None
    row.attempts += 1
    if row.attempts >= max_attempts:
        row.locked_until = now + lockout


def record_success_on(session, *, scope: str, identifier: str) -> None:
    row = _get(session, scope, identifier)
    if row is not None:
        row.attempts = 0
        row.locked_until = None


# --- factory wrappers (own short-lived transaction; persist despite a caller's
#     rollback — used where the failure is recorded on a request that will roll
#     back, e.g. a failed /auth/token). ------------------------------------------


def enforce_not_locked(
    factory: sessionmaker, *, scope: str, identifier: str, now: datetime | None = None
) -> None:
    with factory() as session:
        enforce_on(session, scope=scope, identifier=identifier, now=now)


def record_failure(
    factory: sessionmaker,
    *,
    scope: str,
    identifier: str,
    max_attempts: int,
    lockout: timedelta,
    now: datetime | None = None,
) -> None:
    with factory() as session:
        try:
            record_failure_on(
                session,
                scope=scope,
                identifier=identifier,
                max_attempts=max_attempts,
                lockout=lockout,
                now=now,
            )
            session.commit()
        except IntegrityError:  # concurrent first-failure won the insert — best effort
            session.rollback()


def record_success(factory: sessionmaker, *, scope: str, identifier: str) -> None:
    with factory() as session:
        record_success_on(session, scope=scope, identifier=identifier)
        session.commit()
