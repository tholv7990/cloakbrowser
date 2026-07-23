from __future__ import annotations

import base64
import dataclasses
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from cloud import throttle
from cloud.app import create_app
from cloud.config import generate_test_settings
from cloud.db import Base, create_engine_for, create_session_factory, utc_now
from cloud.email import RecordingEmailSender
from cloud.entitlements import public_key_to_b64

LOCKOUT = timedelta(minutes=15)
IDENT = "user@example.com"


@pytest.fixture
def factory(tmp_path):
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _fail(factory, n, *, max_attempts=3, now=None):
    for _ in range(n):
        throttle.record_failure(
            factory, scope="login", identifier=IDENT, max_attempts=max_attempts, lockout=LOCKOUT, now=now
        )


def test_lockout_after_max_attempts(factory):
    _fail(factory, 3, max_attempts=3)
    with pytest.raises(throttle.ThrottleError):
        throttle.enforce_not_locked(factory, scope="login", identifier=IDENT)


def test_below_threshold_is_not_locked(factory):
    _fail(factory, 2, max_attempts=3)
    throttle.enforce_not_locked(factory, scope="login", identifier=IDENT)  # no raise


def test_success_resets_the_counter(factory):
    _fail(factory, 2, max_attempts=3)
    throttle.record_success(factory, scope="login", identifier=IDENT)
    _fail(factory, 1, max_attempts=3)  # counter was reset, so this is attempt #1
    throttle.enforce_not_locked(factory, scope="login", identifier=IDENT)  # no raise


def test_window_rolls_after_the_lockout_elapses(factory):
    now = utc_now()
    _fail(factory, 3, max_attempts=3, now=now)
    with pytest.raises(throttle.ThrottleError):
        throttle.enforce_not_locked(factory, scope="login", identifier=IDENT, now=now)
    later = now + timedelta(minutes=20)
    # Lock has expired; window rolls on the next failure (attempts back to 1).
    throttle.enforce_not_locked(factory, scope="login", identifier=IDENT, now=later)
    throttle.record_failure(
        factory, scope="login", identifier=IDENT, max_attempts=3, lockout=LOCKOUT, now=later
    )
    throttle.enforce_not_locked(factory, scope="login", identifier=IDENT, now=later)


def test_api_locks_login_after_repeated_failures(tmp_path):
    settings = dataclasses.replace(generate_test_settings(), max_attempts=3)
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    mailer = RecordingEmailSender()
    client = TestClient(create_app(settings, session_factory=factory, email_sender=mailer))

    email, password = "buyer@example.com", "correct horse battery staple"
    client.post("/auth/register", json={"email": email, "password": password})
    client.post("/auth/verify-email", json={"token": mailer.last_token("verify", email)})

    private = Ed25519PrivateKey.generate()
    public_b64 = public_key_to_b64(private.public_key())
    signature = base64.b64encode(private.sign(f"plasma-device:{public_b64}".encode())).decode()
    good = {
        "email": email,
        "password": password,
        "device_public_key": public_b64,
        "device_signature": signature,
    }
    bad = {**good, "password": "the wrong password"}

    for _ in range(3):
        assert client.post("/auth/token", json=bad).status_code == 401
    # Now locked — even correct credentials are refused with 429.
    locked = client.post("/auth/token", json=good)
    assert locked.status_code == 429
    assert locked.json()["error"] == "throttled"
