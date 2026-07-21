from __future__ import annotations


def test_proxy_capability_and_frontend_routes_are_published(client, auth_headers):
    bootstrap = client.get("/api/v1/app/bootstrap", headers=auth_headers)
    assert bootstrap.status_code == 200
    assert bootstrap.json()["capabilities"]["proxy_management"] is True
    paths = client.app.openapi()["paths"]
    for path in (
        "/api/v1/proxies",
        "/api/v1/proxies/parse",
        "/api/v1/proxies/{proxy_id}",
        "/api/v1/proxies/{proxy_id}/quick-test",
        "/api/v1/proxies/{proxy_id}/quality-test",
        "/api/v1/proxies/{proxy_id}/reports",
        "/api/v1/proxy-reports/{run_id}",
    ):
        assert path in paths


def test_proxy_write_secrets_are_write_only_and_absent_from_reads(client):
    schemas = client.app.openapi()["components"]["schemas"]
    write = schemas["ProxyWrite"]["properties"]
    assert write["password"]["writeOnly"] is True
    assert write["username"]["writeOnly"] is True
    read = schemas["ProxyRead"]["properties"]
    assert "password" not in read
    assert "credential_ref" not in read
