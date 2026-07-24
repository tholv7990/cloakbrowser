"""The packaged desktop serves the UI from http://tauri.localhost while the API
binds http://127.0.0.1 — a *different site*. A SameSite=Strict session cookie is
never sent on those cross-site calls, so login succeeds (the response body seeds
the client) but every later API call 401s. Cross-site needs SameSite=None; Secure
(Chromium treats 127.0.0.1 as a secure context, so Secure rides http loopback).
The browser dev flow is same-origin (Vite proxy) and stays Strict."""

from __future__ import annotations

from fastapi.testclient import TestClient

from manager_backend.auth.routes import _cookie_policy
from manager_backend.config import ManagerSettings
from manager_backend.main import create_app


def test_cookie_policy_desktop_is_cross_site():
    assert _cookie_policy("http://tauri.localhost") == ("none", True)


def test_cookie_policy_dev_loopback_is_strict():
    assert _cookie_policy("http://127.0.0.1:5273") == ("strict", False)
    assert _cookie_policy("http://localhost:5273") == ("strict", False)


def test_cookie_policy_https_loopback_is_secure_strict():
    assert _cookie_policy("https://127.0.0.1:5273") == ("strict", True)


def _desktop_settings(tmp_path):
    return ManagerSettings(
        data_root=tmp_path / "data",
        allowed_origin="http://tauri.localhost",
        install_token="test-token",
        require_local_token=True,
        auto_backup_enabled=False,
    )


def test_desktop_login_issues_cross_site_session_cookie(tmp_path):
    with TestClient(create_app(_desktop_settings(tmp_path))) as client:
        resp = client.post(
            "/api/v1/auth/setup",
            headers={"Origin": "http://tauri.localhost"},
            json={"email": "o@example.com", "password": "correct horse battery staple"},
        )
        assert resp.status_code == 201
        cookies = "; ".join(resp.headers.get_list("set-cookie")).lower()
        assert "cloak_session=" in cookies
        assert "samesite=none" in cookies
        assert "secure" in cookies
