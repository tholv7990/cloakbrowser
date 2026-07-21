from __future__ import annotations


def test_openapi_declares_cookie_and_csrf_security(client):
    document = client.app.openapi()
    schemes = document["components"]["securitySchemes"]
    assert schemes["SessionCookie"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "cloak_session",
    }
    assert schemes["CsrfToken"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-CSRF-Token",
    }
    security = document["paths"]["/api/v1/profiles"]["post"]["security"]
    assert {"SessionCookie": []} in security
    assert {"CsrfToken": []} in security


def test_auth_contract_never_exposes_password_or_cookie_token(client):
    document = client.app.openapi()
    session_schema = document["components"]["schemas"]["OwnerSessionRead"]
    properties = session_schema["properties"]
    assert "password" not in properties
    assert "password_hash" not in properties
    assert "session_token" not in properties
    assert "csrf_token" in properties
    assert "idle_expires_at" not in properties
    assert "absolute_expires_at" not in properties
