from __future__ import annotations


def test_folder_crud(client, auth_headers):
    created = client.post(
        "/api/v1/folders", headers=auth_headers, json={"name": "KYC"}
    )
    assert created.status_code == 201
    folder_id = created.json()["id"]
    assert created.json()["position"] == 0

    listed = client.get("/api/v1/folders", headers=auth_headers)
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()] == ["KYC"]

    updated = client.patch(
        f"/api/v1/folders/{folder_id}",
        headers=auth_headers,
        json={"name": "Primary"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Primary"

    deleted = client.delete(f"/api/v1/folders/{folder_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert client.get("/api/v1/folders", headers=auth_headers).json() == []


def test_duplicate_folder_uses_safe_error(client, auth_headers):
    assert client.post(
        "/api/v1/folders", headers=auth_headers, json={"name": "KYC"}
    ).status_code == 201

    response = client.post(
        "/api/v1/folders", headers=auth_headers, json={"name": "KYC"}
    )

    assert response.status_code == 409
    payload = response.json()["error"]
    assert payload["code"] == "folder_name_conflict"
    assert payload["request_id"]
    assert "UNIQUE" not in payload["message"]


def test_folder_not_found_uses_standard_error(client, auth_headers):
    response = client.patch(
        "/api/v1/folders/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
        json={"name": "Missing"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "folder_not_found"


def test_folder_reorder_is_deterministic(client, auth_headers):
    first = client.post(
        "/api/v1/folders", headers=auth_headers, json={"name": "First"}
    ).json()
    second = client.post(
        "/api/v1/folders", headers=auth_headers, json={"name": "Second"}
    ).json()

    response = client.post(
        "/api/v1/folders/reorder",
        headers=auth_headers,
        json={"ids": [second["id"], first["id"]]},
    )

    assert response.status_code == 200
    assert [(item["name"], item["position"]) for item in response.json()] == [
        ("Second", 0),
        ("First", 1),
    ]


def test_reorder_requires_every_existing_id_once(client, auth_headers):
    folder = client.post(
        "/api/v1/folders", headers=auth_headers, json={"name": "Only"}
    ).json()

    response = client.post(
        "/api/v1/folders/reorder",
        headers=auth_headers,
        json={"ids": [folder["id"], folder["id"]]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_folder_order"


def test_tag_crud(client, auth_headers):
    created = client.post(
        "/api/v1/tags",
        headers=auth_headers,
        json={"name": "KYC", "color": "#2563EB"},
    )
    assert created.status_code == 201
    assert created.json()["color"] == "#2563EB"

    tag_id = created.json()["id"]
    updated = client.patch(
        f"/api/v1/tags/{tag_id}",
        headers=auth_headers,
        json={"name": "Verified", "color": "#16A34A"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Verified"
    assert client.delete(f"/api/v1/tags/{tag_id}", headers=auth_headers).status_code == 204


def test_invalid_tag_color_uses_standard_error(client, auth_headers):
    response = client.post(
        "/api/v1/tags",
        headers=auth_headers,
        json={"name": "Invalid", "color": "blue"},
    )

    assert response.status_code == 422
    payload = response.json()["error"]
    assert payload["code"] == "validation_error"
    assert payload["field_errors"]["color"]
    assert payload["request_id"]


def test_workflow_status_crud_and_reorder(client, auth_headers):
    ready = client.post(
        "/api/v1/workflow-statuses",
        headers=auth_headers,
        json={"name": "Ready", "color": "#16A34A"},
    ).json()
    review = client.post(
        "/api/v1/workflow-statuses",
        headers=auth_headers,
        json={"name": "Review", "color": "#F59E0B"},
    ).json()

    reordered = client.post(
        "/api/v1/workflow-statuses/reorder",
        headers=auth_headers,
        json={"ids": [review["id"], ready["id"]]},
    )

    assert reordered.status_code == 200
    assert [item["name"] for item in reordered.json()] == ["Review", "Ready"]
