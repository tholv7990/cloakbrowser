from __future__ import annotations


ORIGIN = "http://127.0.0.1:5173"
OWNER = {"email": "Owner@Example.com", "password": "correct horse battery staple"}


def setup_owner(client):
    response = client.post("/api/v1/auth/setup", json=OWNER, headers={"Origin": ORIGIN})
    assert response.status_code == 201
    return response


def test_auth_status_before_and_after_setup(client):
    assert client.get("/api/v1/auth/status").json() == {"setup_required": True}
    setup_owner(client)
    assert client.get("/api/v1/auth/status").json() == {"setup_required": False}


def test_setup_creates_session_cookie_and_rejects_second_owner(client):
    response = setup_owner(client)
    assert response.json()["email"] == "owner@example.com"
    assert response.json()["csrf_token"]
    assert "cloak_session=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    # Remember-me: the session cookie persists across restarts (Max-Age set) so
    # the owner stays signed in instead of being logged out when the app closes.
    assert "Max-Age=" in response.headers["set-cookie"]
    assert set(response.json()) == {"email", "csrf_token"}

    second = client.post("/api/v1/auth/setup", json=OWNER, headers={"Origin": ORIGIN})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "owner_already_configured"


def test_setup_requires_exact_origin(client):
    response = client.post("/api/v1/auth/setup", json=OWNER)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_origin"


def test_login_uses_generic_failure_and_successful_session(client):
    setup = setup_owner(client)
    csrf = setup.json()["csrf_token"]
    client.post(
        "/api/v1/auth/logout",
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )

    failed = client.post(
        "/api/v1/auth/login",
        json={"email": OWNER["email"], "password": "not the right password"},
        headers={"Origin": ORIGIN},
    )
    assert failed.status_code == 401
    assert failed.json()["error"]["code"] == "invalid_credentials"

    logged_in = client.post(
        "/api/v1/auth/login", json=OWNER, headers={"Origin": ORIGIN}
    )
    assert logged_in.status_code == 200
    assert "password" not in logged_in.text.lower()
    session = client.get("/api/v1/auth/session")
    assert session.status_code == 200
    assert session.json()["email"] == "owner@example.com"
    assert session.json()["csrf_token"]
    assert set(session.json()) == {"email", "csrf_token"}


def test_logout_revokes_current_session(client):
    setup = setup_owner(client)
    response = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": ORIGIN, "X-CSRF-Token": setup.json()["csrf_token"]},
    )
    assert response.status_code == 204
    assert client.get("/api/v1/auth/session").status_code == 401


def test_lock_revokes_all_sessions(client):
    setup = setup_owner(client)
    response = client.post(
        "/api/v1/auth/lock",
        headers={"Origin": ORIGIN, "X-CSRF-Token": setup.json()["csrf_token"]},
    )
    assert response.status_code == 204
    assert client.get("/api/v1/auth/session").status_code == 401


def test_change_password_revokes_sessions_and_accepts_new_password(client):
    setup = setup_owner(client)
    changed = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": OWNER["password"],
            "new_password": "a brand new secure password",
        },
        headers={"Origin": ORIGIN, "X-CSRF-Token": setup.json()["csrf_token"]},
    )
    assert changed.status_code == 204
    assert client.get("/api/v1/auth/session").status_code == 401
    old_login = client.post("/api/v1/auth/login", json=OWNER, headers={"Origin": ORIGIN})
    assert old_login.status_code == 401
    new_login = client.post(
        "/api/v1/auth/login",
        json={"email": OWNER["email"], "password": "a brand new secure password"},
        headers={"Origin": ORIGIN},
    )
    assert new_login.status_code == 200
