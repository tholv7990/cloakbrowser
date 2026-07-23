def test_health_returns_local_service_status(client, auth_headers):
    response = client.get("/api/v1/health", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "cloakbrowser-manager",
        "api_version": "v1",
    }


def test_livez_is_public_liveness_probe(client):
    # The desktop shell polls this WITHOUT a session to gate the UI on startup.
    response = client.get("/livez")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
