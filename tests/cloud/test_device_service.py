from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select

from cloud import models
from cloud.db import Base, create_engine_for, create_session_factory, utc_now
from cloud.entitlements import public_key_to_b64
from cloud.features.devices import service as device_service
from cloud.features.devices.service import (
    DeviceError,
    list_devices,
    register_device,
    revoke_device,
    verify_device_possession,
)

CHALLENGE = "server-issued-nonce-abc123"


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _user(session_factory):
    with session_factory() as session:
        user = models.User(email="u@example.com", password_hash="h", status="active")
        session.add(user)
        session.commit()
        return user.id


def _identity(challenge: str = CHALLENGE):
    private = Ed25519PrivateKey.generate()
    public_b64 = public_key_to_b64(private.public_key())
    signature_b64 = base64.b64encode(private.sign(challenge.encode("utf-8"))).decode("ascii")
    return private, public_b64, signature_b64


def test_possession_check_accepts_a_valid_signature_only():
    private, public_b64, signature_b64 = _identity()
    assert verify_device_possession(public_b64, CHALLENGE, signature_b64) is True
    # Wrong challenge / tampered signature fail closed.
    assert verify_device_possession(public_b64, "different-challenge", signature_b64) is False
    other, _pub, _sig = _identity()
    forged = base64.b64encode(other.sign(CHALLENGE.encode())).decode("ascii")
    assert verify_device_possession(public_b64, CHALLENGE, forged) is False


def test_register_creates_then_is_idempotent(session_factory):
    user_id = _user(session_factory)
    _private, public_b64, signature_b64 = _identity()
    with session_factory() as session:
        user = session.get(models.User, user_id)
        device = register_device(
            session,
            user=user,
            public_key_b64=public_b64,
            challenge=CHALLENGE,
            signature_b64=signature_b64,
        )
        session.commit()
        device_id = device.id
    # Re-register same key → same row (idempotent), last_seen refreshed.
    with session_factory() as session:
        user = session.get(models.User, user_id)
        again = register_device(
            session,
            user=user,
            public_key_b64=public_b64,
            challenge=CHALLENGE,
            signature_b64=signature_b64,
        )
        session.commit()
        assert again.id == device_id
        assert len(list_devices(session, user_id=user_id)) == 1


def test_register_rejects_a_bad_signature(session_factory):
    user_id = _user(session_factory)
    _private, public_b64, _sig = _identity()
    with session_factory() as session:
        user = session.get(models.User, user_id)
        with pytest.raises(DeviceError) as error:
            register_device(
                session,
                user=user,
                public_key_b64=public_b64,
                challenge=CHALLENGE,
                signature_b64=base64.b64encode(b"not a real signature" * 4).decode(),
            )
    assert error.value.code == "bad_signature"


def test_revoke_device_revokes_its_sessions(session_factory):
    user_id = _user(session_factory)
    _private, public_b64, signature_b64 = _identity()
    with session_factory() as session:
        user = session.get(models.User, user_id)
        device = register_device(
            session,
            user=user,
            public_key_b64=public_b64,
            challenge=CHALLENGE,
            signature_b64=signature_b64,
        )
        session.flush()
        session.add(
            models.Session(
                user_id=user_id,
                device_id=device.id,
                family_id="fam-1",
                refresh_token_hash="h" * 64,
                expires_at=utc_now(),
            )
        )
        session.commit()
        device_id = device.id

    with session_factory() as session:
        assert revoke_device(session, device_id=device_id) is True
        session.commit()

    with session_factory() as session:
        device = session.get(models.Device, device_id)
        sess = session.scalars(
            select(models.Session).where(models.Session.device_id == device_id)
        ).first()
        assert device.revoked_at is not None
        assert sess.revoked_at is not None


def test_revoked_device_cannot_reregister(session_factory):
    user_id = _user(session_factory)
    _private, public_b64, signature_b64 = _identity()
    with session_factory() as session:
        user = session.get(models.User, user_id)
        device = register_device(
            session,
            user=user,
            public_key_b64=public_b64,
            challenge=CHALLENGE,
            signature_b64=signature_b64,
        )
        session.commit()
        device_id = device.id
    with session_factory() as session:
        revoke_device(session, device_id=device_id)
        session.commit()
    with session_factory() as session:
        user = session.get(models.User, user_id)
        with pytest.raises(DeviceError) as error:
            register_device(
                session,
                user=user,
                public_key_b64=public_b64,
                challenge=CHALLENGE,
                signature_b64=signature_b64,
            )
    assert error.value.code == "device_revoked"


def test_registration_cap_stops_unbounded_devices(session_factory, monkeypatch):
    monkeypatch.setattr(device_service, "DEVICE_REGISTRATION_CAP", 2)
    user_id = _user(session_factory)
    for _ in range(2):
        _private, public_b64, signature_b64 = _identity()
        with session_factory() as session:
            user = session.get(models.User, user_id)
            register_device(
                session,
                user=user,
                public_key_b64=public_b64,
                challenge=CHALLENGE,
                signature_b64=signature_b64,
            )
            session.commit()
    _private, public_b64, signature_b64 = _identity()
    with session_factory() as session:
        user = session.get(models.User, user_id)
        with pytest.raises(DeviceError) as error:
            register_device(
                session,
                user=user,
                public_key_b64=public_b64,
                challenge=CHALLENGE,
                signature_b64=signature_b64,
            )
    assert error.value.code == "device_cap"
