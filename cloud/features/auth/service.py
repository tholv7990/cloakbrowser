"""Account lifecycle + device-bound refresh sessions.

Sessions use **append-per-rotation**: each rotation marks the presented row
``rotated_at`` and inserts a fresh row in the same ``family_id``. Presenting a
refresh whose row is already rotated/revoked = **reuse** → the whole family is
revoked (stolen-token containment). All tokens are stored only as SHA-256 hashes;
passwords as argon2id. Callers own the transaction (commit/rollback).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ...config import CloudSettings
from ...db import ensure_aware_utc, utc_now
from ... import models
from ...keys import normalize_email
from ...passwords import hash_password, needs_rehash, verify_password
from ...tokens import generate_refresh_token, hash_token, mint_access_token

AUTH_ERRORS = frozenset(
    {
        "email_taken",
        "invalid_token",
        "invalid_credentials",
        "account_unverified",
        "account_suspended",
        "invalid_refresh",
        "refresh_reuse",
        "refresh_expired",
        "device_mismatch",
        "invalid_grant",
    }
)


class AuthError(Exception):
    def __init__(self, code: str):
        if code not in AUTH_ERRORS:
            raise ValueError(f"unknown auth error code: {code}")
        self.code = code
        super().__init__(code)


@dataclass
class IssuedTokens:
    access_token: str
    refresh_token: str  # raw — returned to the client once, stored only as a hash
    session: models.Session


# --- registration + verification ----------------------------------------------


def register_user(
    session, *, email: str, password: str, settings: CloudSettings, now: datetime | None = None
) -> tuple[models.User, str]:
    """Create an unverified account; return (user, raw_verification_token). The
    token is emailed, never stored raw."""
    now = now or utc_now()
    user = models.User(
        email=normalize_email(email),
        password_hash=hash_password(password),
        status="unverified",
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError as error:
        session.rollback()
        raise AuthError("email_taken") from error

    raw_token = secrets.token_urlsafe(32)
    session.add(
        models.EmailVerification(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=now + settings.email_verification_ttl,
        )
    )
    session.flush()
    return user, raw_token


def verify_email(session, *, raw_token: str, now: datetime | None = None) -> models.User:
    now = now or utc_now()
    record = session.execute(
        select(models.EmailVerification).where(
            models.EmailVerification.token_hash == hash_token(raw_token)
        )
    ).scalar_one_or_none()
    if (
        record is None
        or record.consumed_at is not None
        or ensure_aware_utc(record.expires_at) <= now
    ):
        raise AuthError("invalid_token")
    record.consumed_at = now
    user = session.get(models.User, record.user_id)
    if user.status == "unverified":
        user.status = "active"
    session.flush()
    return user


# --- authentication -----------------------------------------------------------


def authenticate(session, *, email: str, password: str) -> models.User:
    user = session.execute(
        select(models.User).where(models.User.email == normalize_email(email))
    ).scalar_one_or_none()
    # Verify even on a missing user path would be ideal for timing; argon2 verify is
    # only reachable with a hash, so we return a generic error either way.
    if user is None or not verify_password(user.password_hash, password):
        raise AuthError("invalid_credentials")
    if user.status == "unverified":
        raise AuthError("account_unverified")
    if user.status == "suspended":
        raise AuthError("account_suspended")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


# --- sessions (refresh rotation + reuse detection) ----------------------------


def _issue(
    session,
    *,
    user: models.User,
    device: models.Device,
    family_id: str,
    settings: CloudSettings,
    now: datetime,
) -> IssuedTokens:
    raw_refresh = generate_refresh_token()
    row = models.Session(
        user_id=user.id,
        device_id=device.id,
        family_id=family_id,
        refresh_token_hash=hash_token(raw_refresh),
        issued_at=now,
        expires_at=now + settings.refresh_ttl,
    )
    session.add(row)
    session.flush()
    access = mint_access_token(
        user_id=user.id,
        session_id=row.id,
        device_id=device.id,
        private_key=settings.signing_private_key,
        now=now,
        ttl=settings.access_ttl,
    )
    return IssuedTokens(access_token=access, refresh_token=raw_refresh, session=row)


def create_session(
    session,
    *,
    user: models.User,
    device: models.Device,
    settings: CloudSettings,
    now: datetime | None = None,
) -> IssuedTokens:
    """Start a new session family for (user, device)."""
    now = now or utc_now()
    from ...db import new_id

    return _issue(
        session, user=user, device=device, family_id=new_id(), settings=settings, now=now
    )


def rotate_refresh(
    session, *, raw_refresh: str, settings: CloudSettings, now: datetime | None = None
) -> IssuedTokens:
    now = now or utc_now()
    row = session.execute(
        select(models.Session).where(
            models.Session.refresh_token_hash == hash_token(raw_refresh)
        )
    ).scalar_one_or_none()
    if row is None:
        raise AuthError("invalid_refresh")

    # Reuse: a rotated or revoked row's token was presented → revoke the whole
    # family (the legitimate holder and the thief both lose access; re-login needed).
    if row.rotated_at is not None or row.revoked_at is not None:
        session.execute(
            update(models.Session)
            .where(models.Session.family_id == row.family_id)
            .values(revoked_at=now, reuse_detected_at=now)
        )
        raise AuthError("refresh_reuse")

    if ensure_aware_utc(row.expires_at) <= now:
        raise AuthError("refresh_expired")

    row.rotated_at = now  # append-per-rotation: mark old, issue new in same family
    user = session.get(models.User, row.user_id)
    device = session.get(models.Device, row.device_id)
    return _issue(
        session,
        user=user,
        device=device,
        family_id=row.family_id,
        settings=settings,
        now=now,
    )


def revoke_session(session, *, raw_refresh: str, now: datetime | None = None) -> bool:
    """Logout: revoke the whole family the refresh belongs to. Returns False if the
    token wasn't found (already gone)."""
    now = now or utc_now()
    row = session.execute(
        select(models.Session).where(
            models.Session.refresh_token_hash == hash_token(raw_refresh)
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    session.execute(
        update(models.Session)
        .where(models.Session.family_id == row.family_id, models.Session.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return True


def revoke_all_sessions(session, *, user_id: str, now: datetime | None = None) -> int:
    """Log out all devices for a user (also used by password change)."""
    now = now or utc_now()
    result = session.execute(
        update(models.Session)
        .where(models.Session.user_id == user_id, models.Session.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    return result.rowcount


def change_password(
    session, *, user: models.User, new_password: str, now: datetime | None = None
) -> int:
    """Set a new password and revoke every session (all refresh families)."""
    now = now or utc_now()
    user.password_hash = hash_password(new_password)
    return revoke_all_sessions(session, user_id=user.id, now=now)


# --- password reset -----------------------------------------------------------


def request_password_reset(
    session, *, email: str, settings: CloudSettings, now: datetime | None = None
) -> tuple[models.User, str] | None:
    """Create a reset token for the account if it exists. Returns (user, raw_token)
    to email, or None when the email is unknown — the caller returns a generic
    response either way so the endpoint never reveals whether an account exists."""
    now = now or utc_now()
    user = session.execute(
        select(models.User).where(models.User.email == normalize_email(email))
    ).scalar_one_or_none()
    if user is None:
        return None
    raw_token = secrets.token_urlsafe(32)
    session.add(
        models.PasswordReset(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=now + settings.password_reset_ttl,
        )
    )
    session.flush()
    return user, raw_token


def confirm_password_reset(
    session, *, raw_token: str, new_password: str, now: datetime | None = None
) -> models.User:
    now = now or utc_now()
    record = session.execute(
        select(models.PasswordReset).where(
            models.PasswordReset.token_hash == hash_token(raw_token)
        )
    ).scalar_one_or_none()
    if (
        record is None
        or record.consumed_at is not None
        or ensure_aware_utc(record.expires_at) <= now
    ):
        raise AuthError("invalid_token")
    record.consumed_at = now
    user = session.get(models.User, record.user_id)
    user.password_hash = hash_password(new_password)
    # A reset invalidates every existing session (stolen-account containment).
    revoke_all_sessions(session, user_id=user.id, now=now)
    session.flush()
    return user
