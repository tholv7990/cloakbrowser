from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select

from cloud import models
from cloud.config import generate_test_settings
from cloud.db import Base, create_engine_for, create_session_factory
from cloud.entitlements import public_key_to_b64, verify_entitlement
from cloud.features.auth.service import AuthError, signup_trial

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _device():
    private = Ed25519PrivateKey.generate()
    public_b64 = public_key_to_b64(private.public_key())
    challenge = f"plasma-device:{public_b64}"
    signature_b64 = base64.b64encode(private.sign(challenge.encode())).decode("ascii")
    return public_b64, signature_b64


def test_signup_creates_active_user_trial_key_and_entitlement(session_factory):
    settings = generate_test_settings()
    pub, sig = _device()
    with session_factory() as session:
        result = signup_trial(
            session,
            email="New@Example.com",
            password="correct horse battery staple",
            device_public_key=pub,
            device_signature=sig,
            settings=settings,
            now=NOW,
        )
        session.commit()
        user = session.execute(
            select(models.User).where(models.User.email == "new@example.com")
        ).scalar_one()
        assert user.status == "active"

    claims = verify_entitlement(result.entitlement_token, settings.signing_public_key)
    assert claims["plan"] == "trial"
    assert claims["trial_end"] == int((NOW + timedelta(days=30)).timestamp())
    assert result.tokens.refresh_token  # a session was minted


def test_signup_duplicate_email_rejected(session_factory):
    settings = generate_test_settings()
    pub, sig = _device()
    with session_factory() as session:
        signup_trial(
            session, email="dup@example.com", password="correct horse battery staple",
            device_public_key=pub, device_signature=sig, settings=settings, now=NOW,
        )
        session.commit()
    pub2, sig2 = _device()
    with session_factory() as session:
        with pytest.raises(AuthError) as error:
            signup_trial(
                session, email="dup@example.com", password="another good password here",
                device_public_key=pub2, device_signature=sig2, settings=settings, now=NOW,
            )
    assert error.value.code == "email_taken"
