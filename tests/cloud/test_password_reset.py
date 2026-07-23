from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from cloud.app import create_app
from cloud.config import generate_test_settings
from cloud.db import Base, create_engine_for, create_session_factory
from cloud.email import RecordingEmailSender
from cloud.entitlements import public_key_to_b64

EMAIL = "buyer@example.com"
PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a-brand-new-passphrase-42"


@pytest.fixture
def ctx(tmp_path):
    settings = generate_test_settings()
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    mailer = RecordingEmailSender()
    client = TestClient(create_app(settings, session_factory=factory, email_sender=mailer))
    return {"client": client, "mailer": mailer}


def _device_body(extra: dict) -> dict:
    private = Ed25519PrivateKey.generate()
    public_b64 = public_key_to_b64(private.public_key())
    signature = base64.b64encode(private.sign(f"plasma-device:{public_b64}".encode())).decode()
    return {"device_public_key": public_b64, "device_signature": signature, **extra}


def _register_verify_login(client, mailer, password=PASSWORD) -> dict:
    client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    client.post("/auth/verify-email", json={"token": mailer.last_token("verify", EMAIL)})
    return client.post(
        "/auth/token", json=_device_body({"email": EMAIL, "password": password})
    ).json()


def test_reset_changes_password_and_revokes_sessions(ctx):
    client, mailer = ctx["client"], ctx["mailer"]
    tokens = _register_verify_login(client, mailer)

    assert client.post("/auth/password-reset/request", json={"email": EMAIL}).status_code == 200
    reset_token = mailer.last_token("reset", EMAIL)
    assert reset_token is not None
    confirm = client.post(
        "/auth/password-reset/confirm", json={"token": reset_token, "password": NEW_PASSWORD}
    )
    assert confirm.status_code == 200

    # Old refresh no longer rotates (sessions revoked by the reset).
    assert (
        client.post("/auth/token/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code
        == 401
    )
    # Old password fails; new password logs in.
    assert client.post("/auth/token", json=_device_body({"email": EMAIL, "password": PASSWORD})).status_code == 401
    assert client.post("/auth/token", json=_device_body({"email": EMAIL, "password": NEW_PASSWORD})).status_code == 200


def test_request_for_unknown_email_is_generic_and_sends_nothing(ctx):
    client, mailer = ctx["client"], ctx["mailer"]
    resp = client.post("/auth/password-reset/request", json={"email": "nobody@example.com"})
    assert resp.status_code == 200  # never reveals that the account doesn't exist
    assert mailer.last_token("reset", "nobody@example.com") is None


def test_confirm_with_a_bad_token_is_rejected(ctx):
    client = ctx["client"]
    resp = client.post(
        "/auth/password-reset/confirm", json={"token": "not-a-real-token", "password": NEW_PASSWORD}
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_token"
