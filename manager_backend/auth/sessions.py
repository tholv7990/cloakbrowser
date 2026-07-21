from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..errors import ManagerError
from ..models import AuthSession, Owner, utc_now


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class SessionPolicy:
    idle_timeout: timedelta = timedelta(minutes=30)
    absolute_timeout: timedelta = timedelta(hours=12)


@dataclass(frozen=True, slots=True)
class IssuedSession:
    token: str
    csrf_token: str
    record: AuthSession


@dataclass(frozen=True, slots=True)
class ValidatedSession:
    record: AuthSession
    owner: Owner


def issue_session(
    db: Session, owner: Owner, policy: SessionPolicy = SessionPolicy()
) -> IssuedSession:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    now = utc_now()
    record = AuthSession(
        owner_id=owner.id,
        token_hash=_hash_secret(token),
        csrf_hash=_hash_secret(csrf_token),
        created_at=now,
        last_seen_at=now,
        absolute_expires_at=now + policy.absolute_timeout,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return IssuedSession(token, csrf_token, record)


def validate_session(
    db: Session,
    token: str | None,
    *,
    csrf_token: str | None = None,
    require_csrf: bool = False,
    policy: SessionPolicy = SessionPolicy(),
) -> ValidatedSession:
    if not token:
        raise ManagerError("authentication_required", "Please log in to continue.", 401)
    record = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == _hash_secret(token))
    )
    if record is None or record.revoked_at is not None:
        raise ManagerError("authentication_required", "Please log in to continue.", 401)

    now = utc_now()
    if (
        now >= _aware(record.absolute_expires_at)
        or now - _aware(record.last_seen_at) >= policy.idle_timeout
    ):
        record.revoked_at = now
        db.commit()
        raise ManagerError("session_expired", "Your session has expired. Please log in again.", 401)

    if require_csrf and (
        not csrf_token
        or not secrets.compare_digest(_hash_secret(csrf_token), record.csrf_hash)
    ):
        raise ManagerError("csrf_invalid", "The request security token is invalid.", 403)

    record.last_seen_at = now
    db.commit()
    return ValidatedSession(record, record.owner)


def revoke_session(db: Session, record: AuthSession) -> None:
    if record.revoked_at is None:
        record.revoked_at = utc_now()
        db.commit()


def revoke_all_sessions(db: Session, owner_id: str) -> int:
    result = db.execute(
        update(AuthSession)
        .where(AuthSession.owner_id == owner_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utc_now())
    )
    db.commit()
    return int(result.rowcount or 0)
