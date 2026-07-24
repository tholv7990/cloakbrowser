"""End-to-end: the desktop account service driving the REAL cloud service in-process.

Uses Starlette's TestClient as the transport into a live cloud app, so login ->
device registration -> key redemption -> entitlement issue/refresh -> revocation all
run against the actual cloud code path (not a mock), and the manager verifies + caches
the entitlement through the license service.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cloud import models as cloud_models
from cloud.admin import issue_key, set_key_status
from cloud.app import create_app as create_cloud_app
from cloud.config import generate_test_settings as cloud_test_settings
from cloud.db import Base as CloudBase
from cloud.db import create_engine_for as cloud_engine
from cloud.db import create_session_factory as cloud_factory
from cloud.email import RecordingEmailSender
from cloud.entitlements import public_key_to_b64

from manager_backend.config import ManagerSettings
from manager_backend.errors import ManagerError
from manager_backend.features.account.cloud_client import CloudClient
from manager_backend.features.account.secrets import MemorySecretStore
from manager_backend.features.account.service import AccountService
from manager_backend.features.license import service as license_service

CLOUD_BASE = "http://testserver"
EMAIL = "buyer@example.com"
PASSWORD = "correct horse battery staple"


@pytest.fixture
def cloud(tmp_path):
    settings = cloud_test_settings()
    engine = cloud_engine(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    CloudBase.metadata.create_all(engine)
    factory = cloud_factory(engine)
    mailer = RecordingEmailSender()
    http = TestClient(create_cloud_app(settings, session_factory=factory, email_sender=mailer))

    http.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    http.post("/auth/verify-email", json={"token": mailer.last_token("verify", EMAIL)})
    with factory() as session:
        session.add(cloud_models.Plan(id="pro", name="Pro", features={"media": True}))
        session.commit()
    with factory() as session:
        display, key = issue_key(
            session, plan_id="pro", pepper=settings.activation_pepper, max_uses=5
        )
        session.commit()
        key_id = key.id

    return SimpleNamespace(
        http=http,
        factory=factory,
        key=display,
        key_id=key_id,
        pubkey=public_key_to_b64(settings.signing_public_key),
    )


@pytest.fixture
def account(cloud, tmp_path):
    settings = ManagerSettings(
        data_root=tmp_path / "md",
        require_license=True,
        entitlement_pubkey=cloud.pubkey,
        cloud_base_url=CLOUD_BASE,
        auto_backup_enabled=False,
    )
    svc = AccountService(
        settings,
        secret_store=MemorySecretStore(),
        client_factory=lambda base: CloudClient(base, http=cloud.http),
    )
    return svc, settings


def test_login_activate_refresh_then_revoke_locks(cloud, account):
    svc, settings = account
    assert svc.status().signed_in is False

    signed_in = svc.login(email=EMAIL, password=PASSWORD)
    assert signed_in.signed_in and signed_in.email == EMAIL

    activated = svc.activate(activation_key=cloud.key)
    assert activated.state == "active" and activated.allowed
    assert license_service.evaluate_license(settings).state == "active"

    # Re-fetching the entitlement works while the key is valid.
    assert svc.refresh_entitlement().state == "active"

    # Revoke the key in the cloud -> the desktop can no longer re-issue.
    with cloud.factory() as session:
        set_key_status(session, key_id=cloud.key_id, status="revoked")
        session.commit()
    with pytest.raises(ManagerError) as err:
        svc.refresh_entitlement()
    assert err.value.code == "cloud_key_revoked"

    # The cached entitlement then ages past its offline-grace deadline -> blocked.
    assert license_service.evaluate_license(settings, now=10**12).state == "expired"


def test_wrong_password_maps_to_safe_error(account):
    svc, _ = account
    with pytest.raises(ManagerError) as err:
        svc.login(email=EMAIL, password="the wrong password")
    assert err.value.code == "cloud_invalid_credentials" and err.value.status_code == 401


def test_activate_requires_sign_in(account):
    svc, _ = account
    with pytest.raises(ManagerError) as err:
        svc.activate(activation_key="whatever")
    assert err.value.code == "not_signed_in"


def test_logout_clears_session_and_entitlement(cloud, account):
    svc, settings = account
    svc.login(email=EMAIL, password=PASSWORD)
    svc.activate(activation_key=cloud.key)
    assert license_service.evaluate_license(settings).state == "active"

    status = svc.logout()
    assert status.signed_in is False
    assert license_service.evaluate_license(settings).state == "unlicensed"


def test_routes_login_activate_reflect_in_license(cloud, tmp_path):
    from manager_backend.main import create_app

    settings = ManagerSettings(
        data_root=tmp_path / "mr",
        allowed_origin="http://127.0.0.1:5173",
        install_token="t",
        auto_backup_enabled=False,
        require_license=True,
        entitlement_pubkey=cloud.pubkey,
        cloud_base_url=CLOUD_BASE,
    )
    with TestClient(create_app(settings)) as client:
        client.app.state.account_service = AccountService(
            settings,
            secret_store=MemorySecretStore(),
            client_factory=lambda base: CloudClient(base, http=cloud.http),
        )
        setup = client.post(
            "/api/v1/auth/setup",
            headers={"Origin": "http://127.0.0.1:5173"},
            json={"email": "owner@example.com", "password": "correct horse battery staple"},
        )
        headers = {
            "Origin": "http://127.0.0.1:5173",
            "X-CSRF-Token": setup.json()["csrf_token"],
        }
        login = client.post(
            "/api/v1/account/login", headers=headers,
            json={"email": EMAIL, "password": PASSWORD},
        )
        assert login.status_code == 200 and login.json()["signed_in"] is True

        activate = client.post(
            "/api/v1/account/activate", headers=headers,
            json={"activation_key": cloud.key},
        )
        assert activate.status_code == 200 and activate.json()["state"] == "active"
        assert client.get("/api/v1/license", headers=headers).json()["state"] == "active"


def test_routes_register_reflects_in_license(cloud, tmp_path):
    from manager_backend.main import create_app

    settings = ManagerSettings(
        data_root=tmp_path / "mr2",
        allowed_origin="http://127.0.0.1:5173",
        install_token="t",
        auto_backup_enabled=False,
        require_license=True,
        entitlement_pubkey=cloud.pubkey,
        cloud_base_url=CLOUD_BASE,
    )
    with TestClient(create_app(settings)) as client:
        client.app.state.account_service = AccountService(
            settings,
            secret_store=MemorySecretStore(),
            client_factory=lambda base: CloudClient(base, http=cloud.http),
        )
        setup = client.post(
            "/api/v1/auth/setup",
            headers={"Origin": "http://127.0.0.1:5173"},
            json={"email": "owner2@example.com", "password": "correct horse battery staple"},
        )
        headers = {
            "Origin": "http://127.0.0.1:5173",
            "X-CSRF-Token": setup.json()["csrf_token"],
        }
        register = client.post(
            "/api/v1/account/register", headers=headers,
            json={"email": "fresh2@example.com", "password": "correct horse battery staple"},
        )
        assert register.status_code == 200 and register.json()["state"] == "active"
        assert client.get("/api/v1/license", headers=headers).json()["state"] == "active"


def test_register_creates_trial_and_unlocks(cloud, account):
    svc, settings = account
    status = svc.register(email="fresh@example.com", password="correct horse battery staple")
    assert status.state == "active" and status.allowed
    assert status.trial_end is not None
    assert svc.status().signed_in is True
    assert license_service.evaluate_license(settings).state == "active"


def test_register_duplicate_email_is_safe_error(cloud, account):
    svc, _ = account
    svc.register(email="taken@example.com", password="correct horse battery staple")
    with pytest.raises(ManagerError) as err:
        svc.register(email="taken@example.com", password="correct horse battery staple")
    assert err.value.code == "cloud_email_taken"
