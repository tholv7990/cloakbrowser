from __future__ import annotations


def test_foundation_routes_are_authenticated_and_typed(client, auth_headers):
    bootstrap = client.get("/api/v1/app/bootstrap", headers=auth_headers)
    assert bootstrap.status_code == 200
    assert bootstrap.json() == {
        "api_version": "v1",
        "platform": "windows",
        "owner_email": "owner@example.com",
        "capabilities": {
            "authentication": True,
            "profiles": True,
            "catalogs": True,
            "proxy_management": False,
            "browser_runtime": True,
            "fingerprint_diagnostics": False,
        },
    }

    version = client.get("/api/v1/app/version", headers=auth_headers)
    assert version.status_code == 200
    assert version.json() == {
        "manager_api_version": "1.0.0",
        "cloakbrowser_version": "0.4.12",
        "chromium_version": "146.0.7680.177.5",
    }


def test_foundation_routes_reject_anonymous_requests(client):
    assert client.get("/api/v1/app/bootstrap").status_code == 401
    assert client.get("/api/v1/app/version").status_code == 401


def test_openapi_has_stable_unique_operation_ids_and_error_envelope(client):
    document = client.app.openapi()
    paths = document["paths"]
    assert "/api/v1/profiles" in paths
    assert "/api/v1/folders" in paths
    assert "/api/v1/app/bootstrap" in paths
    assert "ErrorEnvelope" in document["components"]["schemas"]

    operation_ids = [
        operation["operationId"]
        for path in paths.values()
        for method, operation in path.items()
        if method in {"get", "post", "patch", "put", "delete"}
    ]
    assert len(operation_ids) == len(set(operation_ids))
    assert "app_bootstrap" in operation_ids
    assert "app_version" in operation_ids


def test_openapi_errors_reference_canonical_envelope(client):
    document = client.app.openapi()
    responses = document["paths"]["/api/v1/profiles"]["post"]["responses"]
    for status_code in ("401", "403", "422"):
        schema = responses[status_code]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/ErrorEnvelope"}
