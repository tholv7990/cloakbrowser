from __future__ import annotations

import base64

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
from cloud.keys import generate_activation_key, key_verifier

EMAIL = "buyer@example.com"
PASSWORD = "correct horse battery staple"


@pytest.fixture
def ctx(tmp_path):
    settings = generate_test_settings()
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    mailer = RecordingEmailSender()
    app = create_app(settings, session_factory=factory, email_sender=mailer)

    display, parts = generate_activation_key()
    with factory() as session:
        session.add(
            models.Plan(
                id="pro",
                name="Pro",
                max_devices=3,
                max_profiles=100,
                max_sessions=10,
                features={"media": True},
            )
        )
        session.flush()  # ensure the plan row exists before the FK-bearing key
        session.add(
            models.ActivationKey(
                verifier=key_verifier(display, settings.activation_pepper),
                lookup_prefix=parts["lookup_prefix"],
                last4=parts["last4"],
                plan_id="pro",
                max_uses=1,
                uses_remaining=1,
            )
        )
        session.commit()

    return {
        "client": TestClient(app),
        "settings": settings,
        "mailer": mailer,
        "activation_key": display,
        "factory": factory,
    }


def _audit_actions(ctx, action):
    with ctx["factory"]() as session:
        return session.scalars(
            select(models.AuditEvent).where(models.AuditEvent.action == action)
        ).all()


def _device():
    private = Ed25519PrivateKey.generate()
    public_b64 = public_key_to_b64(private.public_key())
    challenge = f"plasma-device:{public_b64}"
    signature_b64 = base64.b64encode(private.sign(challenge.encode())).decode("ascii")
    return public_b64, signature_b64


def _register_verify_and_login(ctx) -> dict:
    client, mailer = ctx["client"], ctx["mailer"]
    assert client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD}).status_code == 201
    token = mailer.last_token("verify", EMAIL)
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 200

    public_b64, signature_b64 = _device()
    resp = client.post(
        "/auth/token",
        json={
            "email": EMAIL,
            "password": PASSWORD,
            "device_public_key": public_b64,
            "device_signature": signature_b64,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_full_flow_register_login_redeem_refresh(ctx):
    client, settings = ctx["client"], ctx["settings"]
    tokens = _register_verify_and_login(ctx)
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}

    # Redeem the activation key -> a signed entitlement bound to this device.
    redeem = client.post(
        "/activation/redeem", json={"activation_key": ctx["activation_key"]}, headers=auth
    )
    assert redeem.status_code == 200, redeem.text
    claims = verify_entitlement(redeem.json()["entitlement_token"], settings.signing_public_key)
    assert claims["plan"] == "pro"
    assert claims["features"] == ["media"]

    # Entitlement refresh re-issues.
    again = client.post("/entitlement/refresh", headers=auth)
    assert again.status_code == 200

    # The device is listed for the account.
    devices = client.get("/devices", headers=auth).json()
    assert len(devices) == 1 and devices[0]["revoked"] is False


def test_refresh_rotation_and_reuse_is_blocked(ctx):
    client = ctx["client"]
    tokens = _register_verify_and_login(ctx)

    rotated = client.post("/auth/token/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert rotated.status_code == 200
    current = rotated.json()["refresh_token"]
    # Replaying the old refresh is reuse -> 401.
    replay = client.post("/auth/token/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401
    assert replay.json()["error"] == "refresh_reuse"

    # Containment must PERSIST through the API: the reuse-revoke is committed even
    # though the request raises + rolls back, so the current live token is now dead
    # too. (Regression: it was previously rolled back and stayed valid.)
    contained = client.post("/auth/token/refresh", json={"refresh_token": current})
    assert contained.status_code == 401
    assert contained.json()["error"] == "refresh_reuse"

    # The stolen-token signal is durably audited (persisted alongside the revoke).
    # Both reuse presentations above (the old token, then the now-revoked current one)
    # are each recorded — every presentation of a dead token is a signal.
    events = _audit_actions(ctx, "auth.refresh_reuse")
    assert len(events) == 2
    assert all(e.subject_type == "session_family" for e in events)


def test_redeem_writes_an_audit_event(ctx):
    client = ctx["client"]
    tokens = _register_verify_and_login(ctx)
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.post(
        "/activation/redeem", json={"activation_key": ctx["activation_key"]}, headers=auth
    ).status_code == 200

    events = _audit_actions(ctx, "activation.redeem")
    assert len(events) == 1
    assert events[0].subject_type == "activation_key"
    assert events[0].data["plan"] == "pro"

    # An idempotent re-issue (same device, same key) consumes no use and adds no event.
    assert client.post(
        "/activation/redeem", json={"activation_key": ctx["activation_key"]}, headers=auth
    ).status_code == 200
    assert len(_audit_actions(ctx, "activation.redeem")) == 1


def test_device_revoke_writes_an_audit_event(ctx):
    client = ctx["client"]
    tokens = _register_verify_and_login(ctx)
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}
    device_id = client.get("/devices", headers=auth).json()[0]["id"]

    assert client.post(f"/devices/{device_id}/revoke", headers=auth).status_code == 200
    events = _audit_actions(ctx, "device.revoke")
    assert len(events) == 1
    assert events[0].subject_id == device_id


def test_protected_routes_require_a_valid_bearer(ctx):
    client = ctx["client"]
    assert client.post("/activation/redeem", json={"activation_key": ctx["activation_key"]}).status_code == 401
    assert client.get("/devices", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_wrong_password_is_401_and_generic(ctx):
    client, mailer = ctx["client"], ctx["mailer"]
    client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    client.post("/auth/verify-email", json={"token": mailer.last_token("verify", EMAIL)})
    public_b64, signature_b64 = _device()
    resp = client.post(
        "/auth/token",
        json={
            "email": EMAIL,
            "password": "the wrong password",
            "device_public_key": public_b64,
            "device_signature": signature_b64,
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_credentials"


def test_health(ctx):
    assert ctx["client"].get("/health").json()["status"] == "ok"
