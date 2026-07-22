from __future__ import annotations

import json

import pytest

from manager_backend.errors import ManagerError
from manager_backend.models import Profile, RuntimeSession
from manager_backend.features.portability.cookies import MAX_COOKIE_PAYLOAD_BYTES


COOKIE = {
    "name": "session",
    "value": "cookie-secret",
    "domain": ".example.com",
    "path": "/",
    "expires": -1,
    "secure": True,
    "httpOnly": True,
    "sameSite": "Lax",
}


class FakeCookieAdapter:
    def __init__(self, exported=None):
        self.imported = []
        self.exported = list(exported or [COOKIE])

    def import_cookies(self, profile, cookies):
        self.imported.append((profile.id, cookies))

    def export_cookies(self, profile):
        return list(self.exported)


class FailingCookieAdapter(FakeCookieAdapter):
    def import_cookies(self, profile, cookies):
        raise RuntimeError("private cookie-secret adapter detail")

    def export_cookies(self, profile):
        raise RuntimeError("private cookie-secret adapter detail")


def _profile(client, *, name="Cookie profile"):
    with client.app.state.session_factory() as session:
        profile = Profile(
            name=name,
            fingerprint_seed="8100",
            fingerprint_config_hash="a" * 64,
        )
        session.add(profile)
        session.commit()
        return profile.id


def test_json_cookie_import_uses_adapter_and_reports_safe_counts(client, auth_headers):
    profile_id = _profile(client)
    adapter = FakeCookieAdapter()
    client.app.state.cookie_context_adapter = adapter

    response = client.post(
        f"/api/v1/profiles/{profile_id}/cookies/import",
        headers=auth_headers,
        json={
            "format": "json",
            "content": json.dumps(
                {
                    "cookies": [
                        COOKIE,
                        {**COOKIE, "name": "bad;name", "value": "must-not-leak"},
                    ]
                }
            ),
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "format": "json",
        "imported_count": 1,
        "skipped_count": 0,
        "rejected_count": 1,
        "warnings": [{"index": 1, "code": "invalid_name"}],
    }
    assert adapter.imported == [(profile_id, [COOKIE])]
    assert "cookie-secret" not in response.text
    assert "must-not-leak" not in response.text


def test_multipart_netscape_cookie_import_uses_the_accepted_parser(client, auth_headers):
    profile_id = _profile(client)
    adapter = FakeCookieAdapter()
    client.app.state.cookie_context_adapter = adapter
    content = (
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.example.com\tTRUE\t/\tTRUE\t0\tsession\tcookie-secret\n"
    )

    response = client.post(
        f"/api/v1/profiles/{profile_id}/cookies/import",
        headers=auth_headers,
        data={"format": "netscape"},
        files={"file": ("cookies.txt", content, "text/plain")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "format": "netscape",
        "imported_count": 1,
        "skipped_count": 0,
        "rejected_count": 0,
        "warnings": [],
    }
    assert adapter.imported == [
        (
            profile_id,
            [
                {
                    "name": "session",
                    "value": "cookie-secret",
                    "domain": ".example.com",
                    "path": "/",
                    "expires": -1.0,
                    "secure": True,
                    "httpOnly": True,
                }
            ],
        )
    ]


def test_cookie_export_supports_playwright_and_netscape_safe_downloads(
    client, auth_headers
):
    profile_id = _profile(client, name='Quarterly / Cookies\r\nInjected: yes "')
    client.app.state.cookie_context_adapter = FakeCookieAdapter()

    playwright = client.get(
        f"/api/v1/profiles/{profile_id}/cookies/export", headers=auth_headers
    )
    netscape = client.get(
        f"/api/v1/profiles/{profile_id}/cookies/export?format=netscape",
        headers=auth_headers,
    )

    assert playwright.status_code == 200
    assert playwright.json() == [COOKIE]
    assert playwright.headers["content-type"].startswith("application/json")
    assert playwright.headers["content-disposition"] == (
        'attachment; filename="cloakbrowser-cookies-quarterly-cookies-injected-yes.json"'
    )
    assert playwright.headers["cache-control"] == "no-store"
    assert playwright.headers["x-content-type-options"] == "nosniff"
    assert "\r" not in playwright.headers["content-disposition"]
    assert "\n" not in playwright.headers["content-disposition"]

    assert netscape.status_code == 200
    assert netscape.headers["content-type"].startswith("text/plain")
    assert netscape.headers["content-disposition"].endswith('.txt"')
    assert netscape.text == (
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.example.com\tTRUE\t/\tTRUE\t0\tsession\tcookie-secret\n"
    )


@pytest.mark.parametrize("method", ["import", "export"])
def test_cookie_operations_require_a_stopped_profile(client, auth_headers, method):
    profile_id = _profile(client)
    with client.app.state.session_factory() as session:
        session.add(RuntimeSession(profile_id=profile_id, state="running"))
        session.commit()
    adapter = FakeCookieAdapter()
    client.app.state.cookie_context_adapter = adapter

    if method == "import":
        response = client.post(
            f"/api/v1/profiles/{profile_id}/cookies/import",
            headers=auth_headers,
            json={"format": "playwright", "content": "[]"},
        )
    else:
        response = client.get(
            f"/api/v1/profiles/{profile_id}/cookies/export", headers=auth_headers
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "profile_not_stopped"
    assert adapter.imported == []


def test_cookie_mutation_requires_origin_and_csrf(client, auth_headers):
    profile_id = _profile(client)
    client.app.state.cookie_context_adapter = FakeCookieAdapter()

    missing_origin = client.post(
        f"/api/v1/profiles/{profile_id}/cookies/import",
        json={"format": "playwright", "content": "[]"},
    )
    missing_csrf = client.post(
        f"/api/v1/profiles/{profile_id}/cookies/import",
        headers={"Origin": auth_headers["Origin"]},
        json={"format": "playwright", "content": "[]"},
    )

    assert missing_origin.status_code == 403
    assert missing_csrf.status_code == 403


def test_cookie_routes_require_authentication(client):
    response = client.get("/api/v1/profiles/missing/cookies/export")
    assert response.status_code == 401


@pytest.mark.parametrize("kind", ["json", "multipart"])
def test_cookie_import_rejects_ten_mib_requests_before_parsing(
    client, auth_headers, monkeypatch, kind
):
    profile_id = _profile(client)
    client.app.state.cookie_context_adapter = FakeCookieAdapter()

    def parser_must_not_run(*_args, **_kwargs):
        raise AssertionError("oversized input reached the cookie parser")

    monkeypatch.setattr(
        "manager_backend.features.portability.routes.parse_cookie_payload",
        parser_must_not_run,
    )
    if kind == "json":
        response = client.post(
            f"/api/v1/profiles/{profile_id}/cookies/import",
            headers=auth_headers,
            content=b'{"format":"playwright","content":"'
            + (b"x" * MAX_COOKIE_PAYLOAD_BYTES)
            + b'"}',
        )
    else:
        response = client.post(
            f"/api/v1/profiles/{profile_id}/cookies/import",
            headers=auth_headers,
            data={"format": "netscape"},
            files={
                "file": (
                    "cookies.txt",
                    b"x" * MAX_COOKIE_PAYLOAD_BYTES,
                    "text/plain",
                )
            },
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "cookie_payload_too_large"


@pytest.mark.parametrize("method", ["import", "export"])
def test_cookie_adapter_failures_return_value_free_errors(
    client, auth_headers, method
):
    profile_id = _profile(client)
    client.app.state.cookie_context_adapter = FailingCookieAdapter()

    if method == "import":
        response = client.post(
            f"/api/v1/profiles/{profile_id}/cookies/import",
            headers=auth_headers,
            json={"format": "playwright", "content": json.dumps([COOKIE])},
        )
    else:
        response = client.get(
            f"/api/v1/profiles/{profile_id}/cookies/export", headers=auth_headers
        )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "cookie_operation_failed"
    assert "cookie-secret" not in response.text


def test_cookie_context_adapter_uses_headless_normal_profile_config_and_closes(
    settings, db_session_factory
):
    from manager_backend.features.portability.browser_cookies import CookieContextAdapter

    calls = []

    class Context:
        def add_cookies(self, cookies):
            calls.append(("add", cookies))

        def close(self):
            calls.append(("close",))

    def launch(user_data_dir, **kwargs):
        calls.append(("launch", user_data_dir, kwargs))
        return Context()

    with db_session_factory() as session:
        profile = Profile(
            name="Configured",
            fingerprint_seed="8200",
            fingerprint_config_hash="a" * 64,
            fingerprint_preset="consistent",
            browser_version_mode="pinned",
            browser_version="134.0.0",
            user_agent_mode="custom",
            custom_user_agent="Custom User Agent/134.0",
            location={"locale": "vi-VN", "timezone": "Asia/Ho_Chi_Minh"},
        )
        session.add(profile)
        session.commit()
        profile_id = profile.id
        adapter = CookieContextAdapter(
            settings,
            launch_persistent_context=launch,
            proxy_resolver=lambda _profile: "http://user:pass@proxy.example:8080",
        )
        adapter.import_cookies(profile, [COOKIE])

    assert calls == [
        (
            "launch",
            str(settings.profile_root / profile_id / "user-data"),
            {
                "headless": True,
                "fingerprint_preset": "consistent",
                "args": ["--fingerprint=8200"],
                "browser_version": "134.0.0",
                "user_agent": "Custom User Agent/134.0",
                "proxy": "http://user:pass@proxy.example:8080",
                "locale": "vi-VN",
                "timezone": "Asia/Ho_Chi_Minh",
            },
        ),
        ("add", [COOKIE]),
        ("close",),
    ]
    assert not (settings.profile_root / profile_id / ".runtime.lock").exists()


@pytest.mark.parametrize("operation", ["import", "export"])
def test_cookie_context_adapter_closes_after_cookie_api_failure(
    settings, db_session_factory, operation
):
    from manager_backend.features.portability.browser_cookies import CookieContextAdapter

    closed = []

    class Context:
        def add_cookies(self, _cookies):
            raise RuntimeError("private add failure with cookie-secret")

        def cookies(self):
            raise RuntimeError("private read failure with cookie-secret")

        def close(self):
            closed.append(True)

    with db_session_factory() as session:
        profile = Profile(
            name="Failure",
            fingerprint_seed="8300",
            fingerprint_config_hash="a" * 64,
        )
        session.add(profile)
        session.commit()
        profile_id = profile.id
        adapter = CookieContextAdapter(
            settings, launch_persistent_context=lambda *_args, **_kwargs: Context()
        )

        with pytest.raises(ManagerError) as caught:
            if operation == "import":
                adapter.import_cookies(profile, [COOKIE])
            else:
                adapter.export_cookies(profile)

    assert caught.value.code == "cookie_operation_failed"
    assert "cookie-secret" not in caught.value.message
    assert closed == [True]
    assert not (settings.profile_root / profile_id / ".runtime.lock").exists()


def test_cookie_context_adapter_maps_cleanup_failure_to_safe_error(
    settings, db_session_factory
):
    from manager_backend.features.portability.browser_cookies import CookieContextAdapter

    class Context:
        def add_cookies(self, _cookies):
            return None

        def close(self):
            raise RuntimeError("private close failure with cookie-secret")

    with db_session_factory() as session:
        profile = Profile(
            name="Cleanup failure",
            fingerprint_seed="8400",
            fingerprint_config_hash="a" * 64,
        )
        session.add(profile)
        session.commit()
        profile_id = profile.id
        adapter = CookieContextAdapter(
            settings, launch_persistent_context=lambda *_args, **_kwargs: Context()
        )
        with pytest.raises(ManagerError) as caught:
            adapter.import_cookies(profile, [COOKIE])

    assert caught.value.code == "cookie_operation_failed"
    assert "cookie-secret" not in caught.value.message
    assert not (settings.profile_root / profile_id / ".runtime.lock").exists()


def test_cookie_context_adapter_rejects_a_running_profile_before_launch(
    settings, db_session_factory
):
    from manager_backend.features.portability.browser_cookies import CookieContextAdapter

    launched = []
    with db_session_factory() as session:
        profile = Profile(
            name="Running",
            fingerprint_seed="8500",
            fingerprint_config_hash="a" * 64,
        )
        session.add(profile)
        session.flush()
        session.add(RuntimeSession(profile_id=profile.id, state="running"))
        session.commit()
        session.refresh(profile)
        adapter = CookieContextAdapter(
            settings,
            launch_persistent_context=lambda *_args, **_kwargs: launched.append(True),
        )
        with pytest.raises(ManagerError) as caught:
            adapter.import_cookies(profile, [COOKIE])

    assert caught.value.code == "profile_not_stopped"
    assert launched == []
