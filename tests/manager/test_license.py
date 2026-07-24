from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

# Sign test entitlements with the CLOUD helper and verify with the MANAGER verifier —
# this cross-checks that the two compact-JWS implementations stay byte-compatible.
from cloud.entitlements import public_key_to_b64, sign_entitlement
from manager_backend.config import ManagerSettings
from manager_backend.errors import ManagerError
from manager_backend.features.license import service
from manager_backend.main import create_app

FAR_FUTURE = 9_999_999_999


def _keypair():
    priv = Ed25519PrivateKey.generate()
    return priv, public_key_to_b64(priv.public_key())


def _settings(tmp_path, *, require=True, pubkey=None):
    return ManagerSettings(
        data_root=tmp_path / "d",
        require_license=require,
        entitlement_pubkey=pubkey,
        auto_backup_enabled=False,
    )


def _entitlement(priv, *, exp, grace, plan="pro", features=("media",)):
    claims = {
        "exp": exp,
        "offline_grace_deadline": grace,
        "plan": plan,
        "features": list(features),
    }
    return sign_entitlement(claims, priv)


# --- service state machine ----------------------------------------------------


def test_disabled_when_enforcement_off(tmp_path):
    st = service.evaluate_license(_settings(tmp_path, require=False))
    assert st.state == "disabled" and st.allowed


def test_unlicensed_when_no_token(tmp_path):
    _priv, pub = _keypair()
    st = service.evaluate_license(_settings(tmp_path, pubkey=pub))
    assert st.state == "unlicensed" and not st.allowed


def test_active_grace_expired_transitions(tmp_path):
    priv, pub = _keypair()
    s = _settings(tmp_path, pubkey=pub)
    now = 1_000_000

    service.save_entitlement(s, _entitlement(priv, exp=now + 100, grace=now + 1000))
    active = service.evaluate_license(s, now=now)
    assert active.state == "active" and active.allowed
    assert active.plan == "pro" and active.features == ["media"]

    service.save_entitlement(s, _entitlement(priv, exp=now - 10, grace=now + 1000))
    grace = service.evaluate_license(s, now=now)
    assert grace.state == "grace" and grace.allowed  # still runs during offline grace

    service.save_entitlement(s, _entitlement(priv, exp=now - 1000, grace=now - 10))
    expired = service.evaluate_license(s, now=now)
    assert expired.state == "expired" and not expired.allowed


def test_wrong_signing_key_is_invalid(tmp_path):
    _priv, pub = _keypair()
    other, _ = _keypair()  # signed by a key we don't trust
    s = _settings(tmp_path, pubkey=pub)
    service.save_entitlement(s, _entitlement(other, exp=FAR_FUTURE, grace=FAR_FUTURE))
    st = service.evaluate_license(s)
    assert st.state == "invalid" and not st.allowed


def test_enforcing_without_pinned_key_fails_closed(tmp_path):
    st = service.evaluate_license(_settings(tmp_path, pubkey=None))
    assert st.state == "invalid" and not st.allowed


def test_install_rejects_unverifiable_token(tmp_path):
    _priv, pub = _keypair()
    with pytest.raises(ManagerError) as err:
        service.install_entitlement(_settings(tmp_path, pubkey=pub), "not.a.token")
    assert err.value.code == "license_invalid" and err.value.status_code == 400


def test_require_entitled_blocks_then_allows(tmp_path):
    priv, pub = _keypair()
    s = _settings(tmp_path, pubkey=pub)
    with pytest.raises(ManagerError) as err:
        service.require_entitled(s)  # unlicensed
    assert err.value.code == "license_required"
    service.save_entitlement(s, _entitlement(priv, exp=FAR_FUTURE, grace=FAR_FUTURE))
    service.require_entitled(s)  # active -> no raise


# --- runtime gate wiring ------------------------------------------------------


def test_runtime_manager_calls_gate_before_work(tmp_path):
    from manager_backend.features.runtime.manager import RuntimeManager

    def gate():
        raise ManagerError("license_expired", "expired", 403)

    rm = RuntimeManager(lambda: None, _settings(tmp_path, require=False), license_gate=gate)
    with pytest.raises(ManagerError) as err:
        rm.start("any-profile-id")
    assert err.value.code == "license_expired"


# --- API ----------------------------------------------------------------------


@pytest.fixture
def enforced(tmp_path):
    priv, pub = _keypair()
    s = ManagerSettings(
        data_root=tmp_path / "md",
        allowed_origin="http://127.0.0.1:5173",
        install_token="t",
        auto_backup_enabled=False,
        require_license=True,
        entitlement_pubkey=pub,
    )
    with TestClient(create_app(s)) as client:
        setup = client.post(
            "/api/v1/auth/setup",
            headers={"Origin": "http://127.0.0.1:5173"},
            json={"email": "owner@example.com", "password": "correct horse battery staple"},
        )
        assert setup.status_code == 201, setup.text
        headers = {
            "Origin": "http://127.0.0.1:5173",
            "X-CSRF-Token": setup.json()["csrf_token"],
        }
        yield client, headers, priv


def test_api_status_install_deactivate(enforced):
    client, headers, priv = enforced
    assert client.get("/api/v1/license", headers=headers).json()["state"] == "unlicensed"

    token = _entitlement(priv, exp=FAR_FUTURE, grace=FAR_FUTURE)
    installed = client.post(
        "/api/v1/license/entitlement", headers=headers, json={"entitlement_token": token}
    )
    assert installed.status_code == 200
    assert installed.json()["state"] == "active" and installed.json()["allowed"] is True

    assert client.get("/api/v1/license", headers=headers).json()["state"] == "active"
    assert client.delete("/api/v1/license", headers=headers).json()["state"] == "unlicensed"


def test_api_install_rejects_garbage(enforced):
    client, headers, _priv = enforced
    resp = client.post(
        "/api/v1/license/entitlement",
        headers=headers,
        json={"entitlement_token": "bad.token.here"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "license_invalid"
