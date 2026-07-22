from __future__ import annotations


def _make_profile(client, auth_headers, name):
    return client.post("/api/v1/profiles", headers=auth_headers, json={"name": name}).json()


def _make_asset(client, auth_headers, **changes):
    payload = {"name": "Office webcam", "kind": "camera", "format": "video/mp4"}
    payload.update(changes)
    return client.post("/api/v1/media/assets", headers=auth_headers, json=payload)


def test_settings_default_false_and_patch_round_trips(client, auth_headers):
    assert client.get("/api/v1/media/settings").json() == {"enabled": False}
    patched = client.patch(
        "/api/v1/media/settings", headers=auth_headers, json={"enabled": True}
    )
    assert patched.status_code == 200
    assert patched.json() == {"enabled": True}
    assert client.get("/api/v1/media/settings").json() == {"enabled": True}


def test_create_asset_appears_with_zero_assignments(client, auth_headers):
    created = _make_asset(client, auth_headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "camera"
    assert body["format"] == "video/mp4"
    assert body["assigned_profile_count"] == 0
    assert body["size_bytes"] == 0

    listing = client.get("/api/v1/media/assets").json()
    assert [asset["id"] for asset in listing] == [body["id"]]


def test_invalid_kind_format_is_rejected(client, auth_headers):
    response = _make_asset(client, auth_headers, kind="microphone", format="video/mp4")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "media_format_mismatch"


def test_delete_removes_asset_and_its_assignments(client, auth_headers):
    profile = _make_profile(client, auth_headers, "Assigned")
    asset = _make_asset(client, auth_headers, format="image/jpeg").json()
    assigned = client.put(
        f"/api/v1/media/assets/{asset['id']}/assignments",
        headers=auth_headers,
        json={"profile_ids": [profile["id"]]},
    )
    assert assigned.status_code == 200
    assert assigned.json()["assigned_profile_count"] == 1

    deleted = client.delete(f"/api/v1/media/assets/{asset['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    assert client.get("/api/v1/media/assets").json() == []
    assert (
        client.get(f"/api/v1/media/assets/{asset['id']}/assignments").status_code == 404
    )
    # The profile itself is untouched.
    assert client.get("/api/v1/profiles", headers=auth_headers).json()["total"] == 1


def test_assignments_replace_and_prune_unknown_ids(client, auth_headers):
    one = _make_profile(client, auth_headers, "One")
    two = _make_profile(client, auth_headers, "Two")
    asset = _make_asset(client, auth_headers, format="video/webm").json()

    # Unknown ids are pruned; only the real profile is assigned.
    updated = client.put(
        f"/api/v1/media/assets/{asset['id']}/assignments",
        headers=auth_headers,
        json={"profile_ids": [one["id"], "prof_missing"]},
    ).json()
    assert updated["assigned_profile_count"] == 1
    assert client.get(f"/api/v1/media/assets/{asset['id']}/assignments").json() == [one["id"]]

    # PUT replaces the whole set.
    client.put(
        f"/api/v1/media/assets/{asset['id']}/assignments",
        headers=auth_headers,
        json={"profile_ids": [two["id"]]},
    )
    assert client.get(f"/api/v1/media/assets/{asset['id']}/assignments").json() == [two["id"]]

    cleared = client.put(
        f"/api/v1/media/assets/{asset['id']}/assignments",
        headers=auth_headers,
        json={"profile_ids": []},
    ).json()
    assert cleared["assigned_profile_count"] == 0
