from __future__ import annotations

import base64
import hashlib
import secrets

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from cloud.app import create_app
from cloud.config import generate_test_settings
from cloud.db import Base, create_engine_for, create_session_factory
from cloud.email import RecordingEmailSender
from cloud.entitlements import public_key_to_b64
from cloud.tokens import verify_access_token

EMAIL = "buyer@example.com"
PASSWORD = "correct horse battery staple"
REDIRECT = "http://127.0.0.1:53123/callback"


@pytest.fixture
def env(tmp_path):
    settings = generate_test_settings()
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    mailer = RecordingEmailSender()
    client = TestClient(create_app(settings, session_factory=factory, email_sender=mailer))
    client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    client.post("/auth/verify-email", json={"token": mailer.last_token("verify", EMAIL)})
    return client, settings


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def _device() -> tuple[str, str]:
    private = Ed25519PrivateKey.generate()
    public_b64 = public_key_to_b64(private.public_key())
    signature = base64.b64encode(private.sign(f"plasma-device:{public_b64}".encode())).decode()
    return public_b64, signature


def _authorize(client, challenge) -> str:
    resp = client.post(
        "/oauth/authorize",
        json={
            "email": EMAIL,
            "password": PASSWORD,
            "code_challenge": challenge,
            "redirect_uri": REDIRECT,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["code"]


def test_pkce_authorize_then_token(env):
    client, settings = env
    verifier, challenge = _pkce()
    code = _authorize(client, challenge)
    public_b64, signature = _device()

    tok = client.post(
        "/oauth/token",
        json={
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": REDIRECT,
            "device_public_key": public_b64,
            "device_signature": signature,
        },
    )
    assert tok.status_code == 200, tok.text
    claims = verify_access_token(tok.json()["access_token"], settings.signing_public_key)
    assert claims["typ"] == "access"

    # The code is single-use — a replay fails.
    replay = client.post(
        "/oauth/token",
        json={
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": REDIRECT,
            "device_public_key": public_b64,
            "device_signature": signature,
        },
    )
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"


def test_wrong_verifier_is_rejected(env):
    client, _settings = env
    _verifier, challenge = _pkce()
    code = _authorize(client, challenge)
    public_b64, signature = _device()
    wrong_verifier = secrets.token_urlsafe(48)  # does not match the challenge
    resp = client.post(
        "/oauth/token",
        json={
            "code": code,
            "code_verifier": wrong_verifier,
            "redirect_uri": REDIRECT,
            "device_public_key": public_b64,
            "device_signature": signature,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_grant"


def test_wrong_password_at_authorize_is_401(env):
    client, _settings = env
    _verifier, challenge = _pkce()
    resp = client.post(
        "/oauth/authorize",
        json={
            "email": EMAIL,
            "password": "the wrong password",
            "code_challenge": challenge,
            "redirect_uri": REDIRECT,
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_credentials"


def test_login_page_renders_and_reflects_nothing(env):
    client, _settings = env
    # A hostile query string must NOT appear anywhere in the served HTML (no XSS).
    resp = client.get(
        "/oauth/login",
        params={"redirect_uri": "http://127.0.0.1:9/cb", "state": "<script>evil()</script>"},
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Content-Security-Policy" in resp.headers
    body = resp.text
    assert 'id="form"' in body and 'id="password"' in body
    assert "<script>evil()" not in body  # query params are read client-side, never echoed


@pytest.mark.parametrize(
    "uri",
    [
        "http://127.0.0.1:53123/callback",
        "http://localhost:8080/cb",
        "http://[::1]:5000/cb",
    ],
)
def test_loopback_redirect_uris_are_accepted(env, uri):
    client, _settings = env
    _verifier, challenge = _pkce()
    resp = client.post(
        "/oauth/authorize",
        json={
            "email": EMAIL,
            "password": PASSWORD,
            "code_challenge": challenge,
            "redirect_uri": uri,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["redirect_uri"] == uri


@pytest.mark.parametrize(
    "uri",
    [
        "https://evil.example.com/cb",
        "http://evil.example.com/cb",
        "http://127.0.0.1.evil.com/cb",
        "app://callback",
    ],
)
def test_non_loopback_redirect_uri_is_rejected(env, uri):
    client, _settings = env
    _verifier, challenge = _pkce()
    resp = client.post(
        "/oauth/authorize",
        json={
            "email": EMAIL,
            "password": PASSWORD,
            "code_challenge": challenge,
            "redirect_uri": uri,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"
