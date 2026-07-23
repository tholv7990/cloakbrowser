"""Phase 1: the loopback API can require a per-install/per-process Bearer token so
another local process cannot drive Plasma even if it has the session cookie.
Gated by a flag so the browser dev workflow (flag off) is unaffected."""

from __future__ import annotations

from fastapi.testclient import TestClient

from manager_backend.config import ManagerSettings
from manager_backend.main import create_app

ORIGIN = "http://127.0.0.1:5173"
TOKEN = "test-install-token-xyz"


def _app(require_token: bool, tmp_path):
    settings = ManagerSettings(
        data_root=tmp_path / "data",
        allowed_origin=ORIGIN,
        install_token=TOKEN,
        require_local_token=require_token,
        auto_backup_enabled=False,
    )
    return create_app(settings)


def _login(client: TestClient) -> dict:
    # Auth routes are NOT token-gated, so the owner can always log in.
    resp = client.post(
        "/api/v1/auth/setup",
        headers={"Origin": ORIGIN},
        json={"email": "owner@example.com", "password": "correct horse battery staple"},
    )
    assert resp.status_code == 201
    return {"Origin": ORIGIN, "X-CSRF-Token": resp.json()["csrf_token"]}


def test_data_route_requires_local_token_when_enabled(tmp_path):
    with TestClient(_app(True, tmp_path)) as client:
        headers = _login(client)
        # Session is valid, but without the local Bearer token the API refuses.
        blocked = client.get("/api/v1/profiles", headers=headers)
        assert blocked.status_code == 401
        assert blocked.json()["error"]["code"] == "invalid_local_token"
        # With the token it works.
        ok = client.get(
            "/api/v1/profiles", headers={**headers, "Authorization": f"Bearer {TOKEN}"}
        )
        assert ok.status_code == 200


def test_wrong_token_is_rejected(tmp_path):
    with TestClient(_app(True, tmp_path)) as client:
        headers = _login(client)
        resp = client.get(
            "/api/v1/profiles", headers={**headers, "Authorization": "Bearer nope"}
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "invalid_local_token"


def test_flag_off_keeps_the_dev_workflow_tokenless(tmp_path):
    with TestClient(_app(False, tmp_path)) as client:
        headers = _login(client)
        # No Bearer token, flag off → the existing session model still works.
        assert client.get("/api/v1/profiles", headers=headers).status_code == 200
