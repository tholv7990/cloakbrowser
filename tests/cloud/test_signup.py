from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import select

from cloud import models
from cloud.app import create_app
from cloud.config import generate_test_settings
from cloud.db import Base, create_engine_for, create_session_factory
from cloud.email import RecordingEmailSender
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


def _app(session_factory):
    settings = generate_test_settings()
    app = create_app(settings, session_factory=session_factory, email_sender=RecordingEmailSender())
    return TestClient(app), settings


def test_signup_endpoint_returns_session_and_trial_entitlement(session_factory):
    client, settings = _app(session_factory)
    pub, sig = _device()
    resp = client.post(
        "/auth/signup",
        json={
            "email": "web@example.com",
            "password": "correct horse battery staple",
            "device_public_key": pub,
            "device_signature": sig,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    claims = verify_entitlement(body["entitlement_token"], settings.signing_public_key)
    assert claims["plan"] == "trial" and "trial_end" in claims


def test_signup_endpoint_rejects_short_password(session_factory):
    client, _ = _app(session_factory)
    pub, sig = _device()
    resp = client.post(
        "/auth/signup",
        json={"email": "x@example.com", "password": "short", "device_public_key": pub, "device_signature": sig},
    )
    assert resp.status_code == 422


def test_signup_endpoint_duplicate_email(session_factory):
    client, _ = _app(session_factory)
    pub, sig = _device()
    payload = {"email": "dupe@example.com", "password": "correct horse battery staple",
               "device_public_key": pub, "device_signature": sig}
    assert client.post("/auth/signup", json=payload).status_code == 200
    pub2, sig2 = _device()
    payload2 = {**payload, "device_public_key": pub2, "device_signature": sig2}
    resp = client.post("/auth/signup", json=payload2)
    assert resp.status_code >= 400
    assert resp.json()["error"] == "email_taken"
