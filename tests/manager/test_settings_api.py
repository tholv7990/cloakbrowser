from pathlib import Path


def test_settings_requires_authentication(client):
    assert client.get("/api/v1/settings").status_code == 401


def test_settings_returns_persisted_preferences_and_live_binary_facts(
    client, auth_headers, monkeypatch, settings
):
    from manager_backend.features.settings import service

    monkeypatch.setattr(
        service,
        "binary_info",
        lambda: {
            "version": "150.0.7871.114.3",
            "tier": "pro",
            "platform": "windows-x64",
            "binary_path": str(Path("C:/real/chrome.exe")),
            "installed": True,
            "bundled_version": "146.0.7680.177.5",
            "cache_dir": "C:/real",
            "download_url": "redacted",
        },
    )
    monkeypatch.setattr(service, "resolve_license_key", lambda: "super-secret")
    monkeypatch.setattr(
        service,
        "validate_license",
        lambda _key: service.LicenseInfo(True, "solo", "2026-12-31T00:00:00+00:00"),
    )
    monkeypatch.setattr(service, "get_active_session_count", lambda _key: 2)
    monkeypatch.setattr(service, "get_pro_latest_version", lambda: "150.0.7871.114.3")

    response = client.get("/api/v1/settings", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["profile_root"] == str(settings.profile_root)
    assert payload["browser"]["path"] == "C:\\real\\chrome.exe"
    assert payload["browser"]["tier"] == "pro"
    assert payload["browser"]["latest_version"] == "150.0.7871.114.3"
    assert payload["license"] == {
        "configured": True,
        "valid": True,
        "plan": "solo",
        "expires": "2026-12-31T00:00:00+00:00",
        "active_sessions": 2,
        "session_limit": 3,
    }
    assert "super-secret" not in response.text


def test_settings_patch_persists_and_requires_csrf(client, auth_headers):
    rejected = client.patch("/api/v1/settings", json={"theme": "dark"})
    assert rejected.status_code == 403

    updated = client.patch(
        "/api/v1/settings", headers=auth_headers, json={"theme": "dark", "rows_per_page": 50}
    )
    assert updated.status_code == 200
    loaded = client.get("/api/v1/settings", headers=auth_headers)
    assert loaded.json()["theme"] == "dark"
    assert loaded.json()["rows_per_page"] == 50


def test_check_update_uses_free_updater_and_returns_fresh_settings(
    client, auth_headers, monkeypatch
):
    from manager_backend.features.settings import service

    calls = []
    monkeypatch.setattr(service, "resolve_license_key", lambda: None)
    monkeypatch.setattr(service, "check_for_update", lambda: calls.append("free") or None)
    response = client.post(
        "/api/v1/settings/browser/check-update", headers=auth_headers
    )
    assert response.status_code == 200
    assert calls == ["free"]
    assert response.json()["browser"]["version"]
