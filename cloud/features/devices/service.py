"""Device registration + revocation.

A device proves it holds the Ed25519 private key for the public key it registers
by signing a server-issued challenge (challenge freshness/expiry is the endpoint's
job; this layer verifies possession). Registration is idempotent per
(user, public_key). Plan device *limits* are enforced at entitlement issue (a
per-plan property); a generous per-account cap here only stops unbounded abuse
before any plan exists.
"""

from __future__ import annotations

import base64
from datetime import datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import func, select, update

from ... import models
from ...db import utc_now

# Abuse cap before any plan is attached; the plan's max_devices is enforced when
# an entitlement is issued (see licensing/entitlement layer).
DEVICE_REGISTRATION_CAP = 25

DEVICE_ERRORS = frozenset({"bad_signature", "device_revoked", "device_cap"})


class DeviceError(Exception):
    def __init__(self, code: str):
        if code not in DEVICE_ERRORS:
            raise ValueError(f"unknown device error code: {code}")
        self.code = code
        super().__init__(code)


def verify_device_possession(public_key_b64: str, challenge: str, signature_b64: str) -> bool:
    """True iff signature_b64 is a valid Ed25519 signature of `challenge` under the
    given public key — i.e. the caller holds the matching private key."""
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        public_key.verify(base64.b64decode(signature_b64), challenge.encode("utf-8"))
        return True
    except Exception:
        return False


def register_device(
    session,
    *,
    user: models.User,
    public_key_b64: str,
    challenge: str,
    signature_b64: str,
    name: str = "Windows PC",
    platform: str = "windows",
    now: datetime | None = None,
) -> models.Device:
    now = now or utc_now()
    if not verify_device_possession(public_key_b64, challenge, signature_b64):
        raise DeviceError("bad_signature")

    existing = session.execute(
        select(models.Device).where(
            models.Device.user_id == user.id,
            models.Device.public_key == public_key_b64,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.revoked_at is not None:
            # A revoked device must be explicitly replaced, not silently re-armed.
            raise DeviceError("device_revoked")
        existing.last_seen_at = now
        return existing

    active = session.scalar(
        select(func.count())
        .select_from(models.Device)
        .where(models.Device.user_id == user.id, models.Device.revoked_at.is_(None))
    )
    if active >= DEVICE_REGISTRATION_CAP:
        raise DeviceError("device_cap")

    device = models.Device(
        user_id=user.id,
        public_key=public_key_b64,
        name=name,
        platform=platform,
        last_seen_at=now,
    )
    session.add(device)
    session.flush()
    return device


def list_devices(session, *, user_id: str) -> list[models.Device]:
    return list(
        session.scalars(
            select(models.Device)
            .where(models.Device.user_id == user_id)
            .order_by(models.Device.created_at)
        )
    )


def touch_last_seen(session, *, device_id: str, now: datetime | None = None) -> None:
    now = now or utc_now()
    device = session.get(models.Device, device_id)
    if device is not None:
        device.last_seen_at = now


def revoke_device(session, *, device_id: str, now: datetime | None = None) -> bool:
    """Revoke a device and revoke its sessions (device-scoped logout). Its
    entitlement refresh will then fail. Returns False if the device is unknown."""
    now = now or utc_now()
    device = session.get(models.Device, device_id)
    if device is None:
        return False
    if device.revoked_at is None:
        device.revoked_at = now
    session.execute(
        update(models.Session)
        .where(
            models.Session.device_id == device_id,
            models.Session.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    return True
