"""Activation-key redemption and entitlement issuance — the licensing core.

``redeem_key`` is the race-safe transaction that turns a purchased key into a
signed entitlement:

1. HMAC the key and look up its row **FOR UPDATE** (row lock on Postgres; a no-op
   on SQLite, so a Postgres-backed concurrency test is a follow-up).
2. Reject invalid / suspended / revoked / expired keys.
3. If this (key, device) already redeemed → **re-issue** the entitlement without
   consuming another use (idempotent retry).
4. Otherwise **atomically** guard-decrement ``uses_remaining``
   (``UPDATE … WHERE uses_remaining > 0``, checking rowcount) — this, not the
   unique constraint, is the total-use cap across devices — then insert the
   per-device redemption row (the ``unique(key_id, device_id)`` backstop).
5. Record the entitlement and return a signed token.

The caller owns the transaction (commit/rollback); this function only flushes to
surface constraint violations. No secret is logged; the raw key never leaves this
call except as its HMAC verifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from . import models
from .db import ensure_aware_utc, new_id, utc_now
from .entitlements import sign_entitlement
from .keys import key_verifier

DEFAULT_ENTITLEMENT_TTL = timedelta(hours=24)
DEFAULT_OFFLINE_GRACE = timedelta(days=7)
ENTITLEMENT_VERSION = 1

# Redeem outcomes surfaced to the caller (safe, fixed codes — no secrets).
REDEEM_ERRORS = frozenset(
    {
        "invalid_key",
        "key_suspended",
        "key_revoked",
        "key_expired",
        "key_exhausted",
        "plan_missing",
        "redeem_conflict",
    }
)


class RedeemError(Exception):
    def __init__(self, code: str):
        if code not in REDEEM_ERRORS:
            raise ValueError(f"unknown redeem error code: {code}")
        self.code = code
        super().__init__(code)


@dataclass
class RedeemResult:
    token: str
    entitlement: models.Entitlement
    claims: dict
    reused: bool  # True when an existing redemption was re-issued (no use consumed)


def _plan_features(plan: models.Plan) -> list[str]:
    features = plan.features or {}
    return sorted(name for name, enabled in features.items() if enabled)


def _build_claims(
    *,
    entitlement_id: str,
    key_id: str,
    user_id: str,
    device_id: str,
    plan: models.Plan,
    now: datetime,
    expires_at: datetime,
    grace_deadline: datetime,
) -> dict:
    return {
        "jti": entitlement_id,
        "sub": user_id,
        "device_id": device_id,
        "key_id": key_id,
        "plan": plan.id,
        "features": _plan_features(plan),
        "profile_limit": plan.max_profiles,
        "session_limit": plan.max_sessions,
        "device_limit": plan.max_devices,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "offline_grace_deadline": int(grace_deadline.timestamp()),
        "entitlement_version": ENTITLEMENT_VERSION,
    }


def _issue_entitlement(
    session,
    *,
    key: models.ActivationKey,
    user_id: str,
    device_id: str,
    plan: models.Plan,
    private_key: Ed25519PrivateKey,
    now: datetime,
    ttl: timedelta,
    grace: timedelta,
) -> tuple[str, models.Entitlement, dict]:
    entitlement_id = new_id()
    expires_at = now + ttl
    grace_deadline = now + grace
    entitlement = models.Entitlement(
        id=entitlement_id,
        user_id=user_id,
        device_id=device_id,
        key_id=key.id,
        plan_id=plan.id,
        version=ENTITLEMENT_VERSION,
        issued_at=now,
        expires_at=expires_at,
        offline_grace_deadline=grace_deadline,
    )
    session.add(entitlement)
    claims = _build_claims(
        entitlement_id=entitlement_id,
        key_id=key.id,
        user_id=user_id,
        device_id=device_id,
        plan=plan,
        now=now,
        expires_at=expires_at,
        grace_deadline=grace_deadline,
    )
    return sign_entitlement(claims, private_key), entitlement, claims


def redeem_key(
    session,
    *,
    raw_key: str,
    user_id: str,
    device_id: str,
    pepper: bytes,
    private_key: Ed25519PrivateKey,
    now: datetime | None = None,
    ttl: timedelta = DEFAULT_ENTITLEMENT_TTL,
    grace: timedelta = DEFAULT_OFFLINE_GRACE,
) -> RedeemResult:
    now = now or utc_now()
    verifier = key_verifier(raw_key, pepper)

    key = session.execute(
        select(models.ActivationKey)
        .where(models.ActivationKey.verifier == verifier)
        .with_for_update()
    ).scalar_one_or_none()
    if key is None:
        raise RedeemError("invalid_key")
    if key.status == "revoked":
        raise RedeemError("key_revoked")
    if key.status == "suspended":
        raise RedeemError("key_suspended")
    key_expires_at = ensure_aware_utc(key.expires_at)
    if key_expires_at is not None and key_expires_at <= now:
        raise RedeemError("key_expired")

    plan = session.get(models.Plan, key.plan_id)
    if plan is None:
        raise RedeemError("plan_missing")

    existing = session.execute(
        select(models.Redemption).where(
            models.Redemption.key_id == key.id,
            models.Redemption.device_id == device_id,
        )
    ).scalar_one_or_none()

    if existing is not None:
        # Idempotent retry: re-issue a fresh entitlement, consume no further use.
        token, entitlement, claims = _issue_entitlement(
            session,
            key=key,
            user_id=user_id,
            device_id=device_id,
            plan=plan,
            private_key=private_key,
            now=now,
            ttl=ttl,
            grace=grace,
        )
        session.flush()
        return RedeemResult(token=token, entitlement=entitlement, claims=claims, reused=True)

    # First redemption on this device: atomically claim one use. The guard caps the
    # TOTAL across devices; rowcount 0 means the key is spent.
    result = session.execute(
        update(models.ActivationKey)
        .where(
            models.ActivationKey.id == key.id,
            models.ActivationKey.uses_remaining > 0,
        )
        .values(uses_remaining=models.ActivationKey.uses_remaining - 1)
    )
    if result.rowcount != 1:
        raise RedeemError("key_exhausted")

    session.add(
        models.Redemption(key_id=key.id, user_id=user_id, device_id=device_id)
    )
    token, entitlement, claims = _issue_entitlement(
        session,
        key=key,
        user_id=user_id,
        device_id=device_id,
        plan=plan,
        private_key=private_key,
        now=now,
        ttl=ttl,
        grace=grace,
    )
    try:
        session.flush()
    except IntegrityError as error:
        # A truly concurrent redeem for this same (key, device) claimed the slot
        # first. Roll back OUR decrement+insert with the caller's transaction; a
        # retry will find the existing redemption and re-issue idempotently.
        session.rollback()
        raise RedeemError("redeem_conflict") from error

    return RedeemResult(token=token, entitlement=entitlement, claims=claims, reused=False)


# --- entitlement refresh ------------------------------------------------------

REFRESH_ERRORS = frozenset(
    {"device_revoked", "not_entitled", "key_revoked", "key_expired", "plan_missing"}
)


class RefreshError(Exception):
    def __init__(self, code: str):
        if code not in REFRESH_ERRORS:
            raise ValueError(f"unknown refresh error code: {code}")
        self.code = code
        super().__init__(code)


def refresh_entitlement(
    session,
    *,
    device_id: str,
    private_key: Ed25519PrivateKey,
    now: datetime | None = None,
    ttl: timedelta = DEFAULT_ENTITLEMENT_TTL,
    grace: timedelta = DEFAULT_OFFLINE_GRACE,
) -> RedeemResult:
    """Re-issue a fresh signed entitlement for a device that already redeemed a key.
    This is the periodic-refresh path: revocation bites here — a revoked device or a
    revoked/suspended/expired key stops issuing, so a stale cached entitlement can
    only survive until its offline-grace deadline."""
    now = now or utc_now()
    device = session.get(models.Device, device_id)
    if device is None or device.revoked_at is not None:
        raise RefreshError("device_revoked")

    # The device's most recent redemption is its current entitlement source.
    redemption = session.scalars(
        select(models.Redemption)
        .where(models.Redemption.device_id == device_id)
        .order_by(models.Redemption.redeemed_at.desc())
    ).first()
    if redemption is None:
        raise RefreshError("not_entitled")

    key = session.get(models.ActivationKey, redemption.key_id)
    if key is None or key.status in ("revoked", "suspended"):
        raise RefreshError("key_revoked")
    key_expires_at = ensure_aware_utc(key.expires_at)
    if key_expires_at is not None and key_expires_at <= now:
        raise RefreshError("key_expired")

    plan = session.get(models.Plan, key.plan_id)
    if plan is None:
        raise RefreshError("plan_missing")

    token, entitlement, claims = _issue_entitlement(
        session,
        key=key,
        user_id=redemption.user_id,
        device_id=device_id,
        plan=plan,
        private_key=private_key,
        now=now,
        ttl=ttl,
        grace=grace,
    )
    session.flush()
    return RedeemResult(token=token, entitlement=entitlement, claims=claims, reused=True)
