def test_health_returns_local_service_status(client, auth_headers):
    response = client.get("/api/v1/health", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "cloakbrowser-manager",
        "api_version": "v1",
    }
