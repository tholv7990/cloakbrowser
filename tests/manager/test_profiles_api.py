from __future__ import annotations


def create_profile(client, auth_headers, name="Account A", **overrides):
    payload = {"name": name, **overrides}
    response = client.post("/api/v1/profiles", headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_generates_unique_stable_fingerprint_identity(client, auth_headers):
    first = create_profile(client, auth_headers, "Account A")
    second = create_profile(client, auth_headers, "Account B")

    assert first["fingerprint_seed"] != second["fingerprint_seed"]
    assert first["fingerprint_config_hash"] != second["fingerprint_config_hash"]
    assert first["fingerprint_revision"] == second["fingerprint_revision"] == 1
    assert len(first["fingerprint_config_hash"]) == 64
    assert first["fingerprint_preset"] == "consistent"
    assert first["runtime_state"] == "stopped"


def test_create_list_patch_and_trash_profile(client, auth_headers):
    created = create_profile(
        client,
        auth_headers,
        startup_urls=["https://example.com"],
    )
    profile_id = created["id"]

    listed = client.get("/api/v1/profiles?query=Account", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == profile_id

    updated = client.patch(
        f"/api/v1/profiles/{profile_id}",
        headers=auth_headers,
        json={"name": "Updated", "pinned": True},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Updated"
    assert updated.json()["pinned"] is True
    assert updated.json()["fingerprint_seed"] == created["fingerprint_seed"]

    trashed = client.post(
        f"/api/v1/profiles/{profile_id}/move-to-trash", headers=auth_headers
    )
    assert trashed.status_code == 200
    assert trashed.json()["deleted_at"] is not None
    assert client.get("/api/v1/profiles", headers=auth_headers).json()["total"] == 0

    restored = client.post(
        f"/api/v1/profiles/{profile_id}/restore", headers=auth_headers
    )
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None


def test_duplicate_copies_settings_but_gets_new_identity(client, auth_headers):
    original = create_profile(
        client,
        auth_headers,
        startup_urls=["https://example.com", "https://example.org"],
        location={"geo_mode": "manual", "timezone": "Asia/Saigon"},
    )

    response = client.post(
        f"/api/v1/profiles/{original['id']}/duplicate", headers=auth_headers
    )

    assert response.status_code == 201, response.text
    duplicate = response.json()
    assert duplicate["id"] != original["id"]
    assert duplicate["fingerprint_seed"] != original["fingerprint_seed"]
    assert duplicate["fingerprint_config_hash"] != original["fingerprint_config_hash"]
    assert duplicate["startup_urls"] == original["startup_urls"]
    assert duplicate["location"] == original["location"]


def test_regenerate_fingerprint_changes_only_identity(client, auth_headers):
    original = create_profile(client, auth_headers, notes="keep me")

    response = client.post(
        f"/api/v1/profiles/{original['id']}/regenerate-fingerprint",
        headers=auth_headers,
    )

    assert response.status_code == 200
    regenerated = response.json()
    assert regenerated["fingerprint_seed"] != original["fingerprint_seed"]
    assert regenerated["fingerprint_config_hash"] != original["fingerprint_config_hash"]
    assert regenerated["notes"] == "keep me"


def test_folder_tag_status_filters(client, auth_headers):
    folder = client.post(
        "/api/v1/folders", headers=auth_headers, json={"name": "KYC"}
    ).json()
    tag = client.post(
        "/api/v1/tags",
        headers=auth_headers,
        json={"name": "US", "color": "#2563EB"},
    ).json()
    workflow = client.post(
        "/api/v1/workflow-statuses",
        headers=auth_headers,
        json={"name": "Ready", "color": "#16A34A"},
    ).json()
    expected = create_profile(
        client,
        auth_headers,
        folder_id=folder["id"],
        workflow_status_id=workflow["id"],
        tag_ids=[tag["id"]],
    )
    create_profile(client, auth_headers, "Other")

    for query in (
        f"folder_id={folder['id']}",
        f"tag_id={tag['id']}",
        f"workflow_status_id={workflow['id']}",
    ):
        page = client.get(f"/api/v1/profiles?{query}", headers=auth_headers).json()
        assert page["total"] == 1
        assert page["items"][0]["id"] == expected["id"]


def test_invalid_catalog_reference_is_safe(client, auth_headers):
    response = client.post(
        "/api/v1/profiles",
        headers=auth_headers,
        json={
            "name": "Invalid",
            "folder_id": "00000000-0000-0000-0000-000000000000",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_profile_reference"


def test_profile_not_found_is_safe(client, auth_headers):
    response = client.get(
        "/api/v1/profiles/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "profile_not_found"


def test_pagination_and_sort_are_bounded(client, auth_headers):
    create_profile(client, auth_headers, "Bravo")
    create_profile(client, auth_headers, "Alpha")

    page = client.get(
        "/api/v1/profiles?page=1&page_size=1&sort=name", headers=auth_headers
    ).json()

    assert page["total"] == 2
    assert page["pages"] == 2
    assert page["items"][0]["name"] == "Alpha"


def test_explicit_duplicate_seed_is_rejected(client, auth_headers):
    original = create_profile(client, auth_headers)

    response = client.post(
        "/api/v1/profiles",
        headers=auth_headers,
        json={"name": "Duplicate seed", "fingerprint_seed": original["fingerprint_seed"]},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "fingerprint_seed_conflict"


def test_hardware_override_recalculates_hash_not_seed(client, auth_headers):
    original = create_profile(client, auth_headers)

    response = client.patch(
        f"/api/v1/profiles/{original['id']}",
        headers=auth_headers,
        json={
            "behavior": {
                "hardware_concurrency_mode": "custom",
                "hardware_concurrency": 8,
            }
        },
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["fingerprint_seed"] == original["fingerprint_seed"]
    assert updated["fingerprint_config_hash"] != original["fingerprint_config_hash"]


def test_bulk_pin_and_trash(client, auth_headers):
    first = create_profile(client, auth_headers, "First")
    second = create_profile(client, auth_headers, "Second")
    ids = [first["id"], second["id"]]

    pinned = client.post(
        "/api/v1/profiles/bulk",
        headers=auth_headers,
        json={"action": "pin", "ids": ids},
    )
    assert pinned.status_code == 200
    assert pinned.json() == {"updated_ids": ids, "count": 2}
    assert client.get(f"/api/v1/profiles/{first['id']}", headers=auth_headers).json()[
        "pinned"
    ] is True

    trashed = client.post(
        "/api/v1/profiles/bulk",
        headers=auth_headers,
        json={"action": "trash", "ids": ids},
    )
    assert trashed.status_code == 200
    assert client.get("/api/v1/profiles", headers=auth_headers).json()["total"] == 0


def test_runtime_routes_are_typed_until_adapter_is_installed(client, auth_headers):
    profile = create_profile(client, auth_headers)

    for action in ("start", "stop", "focus-window"):
        response = client.post(
            f"/api/v1/profiles/{profile['id']}/{action}", headers=auth_headers
        )
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "runtime_not_available"
