from manager_backend.security import redact_text


def test_health_rejects_missing_token(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_local_token"
    assert response.json()["error"]["request_id"]


def test_health_rejects_foreign_origin(client, auth_headers):
    response = client.get(
        "/api/v1/health",
        headers={**auth_headers, "Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_origin"


def test_health_accepts_configured_origin(client, auth_headers):
    response = client.get(
        "/api/v1/health",
        headers={**auth_headers, "Origin": "http://127.0.0.1:5173"},
    )

    assert response.status_code == 200


def test_redaction_removes_proxy_credentials():
    value = "connect socks5://user:secret@proxy.example:1080 failed"

    assert redact_text(value) == "connect socks5://***:***@proxy.example:1080 failed"


def test_redaction_removes_bearer_token():
    assert redact_text("Bearer abc.def-123") == "Bearer ***"
