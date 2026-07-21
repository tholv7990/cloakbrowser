from __future__ import annotations

from sqlalchemy import event

from manager_backend.models import Folder, Profile, RuntimeSession


def _profile_with_runtime(session, *, folder_id, name, state, deleted=False):
    profile = Profile(
        name=name,
        folder_id=folder_id,
        fingerprint_seed=str(abs(hash(name)) % 1_000_000_000 + 1),
        fingerprint_config_hash="a" * 64,
    )
    if deleted:
        from datetime import datetime, timezone

        profile.deleted_at = datetime.now(timezone.utc)
    session.add(profile)
    session.flush()
    session.add(RuntimeSession(profile_id=profile.id, state=state, last_message=state))


def test_folders_report_non_deleted_profiles_and_active_runtime_counts(
    client, auth_headers
):
    with client.app.state.session_factory() as session:
        active_folder = Folder(name="Active", position=0)
        empty_folder = Folder(name="Empty", position=1)
        session.add_all([active_folder, empty_folder])
        session.flush()
        for state in (
            "queued",
            "stopped",
            "starting",
            "running",
            "stopping",
            "crashed",
            "detached",
        ):
            _profile_with_runtime(
                session,
                folder_id=active_folder.id,
                name=f"{state} profile",
                state=state,
            )
        _profile_with_runtime(
            session,
            folder_id=active_folder.id,
            name="deleted running profile",
            state="running",
            deleted=True,
        )
        session.commit()

    response = client.get("/api/v1/folders", headers=auth_headers)

    assert response.status_code == 200
    by_name = {item["name"]: item for item in response.json()}
    assert by_name["Active"]["profile_count"] == 7
    assert by_name["Active"]["running_count"] == 3
    assert by_name["Empty"]["profile_count"] == 0
    assert by_name["Empty"]["running_count"] == 0


def _request_query_count(client, request):
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(client.app.state.engine, "before_cursor_execute", record)
    try:
        response = request()
    finally:
        event.remove(client.app.state.engine, "before_cursor_execute", record)
    assert response.status_code == 200
    return len(statements)


def test_folder_listing_uses_constant_query_count_as_folder_count_grows(
    client, auth_headers
):
    with client.app.state.session_factory() as session:
        session.add(Folder(name="Folder 0", position=0))
        session.commit()

    one_folder_queries = _request_query_count(
        client, lambda: client.get("/api/v1/folders", headers=auth_headers)
    )

    with client.app.state.session_factory() as session:
        session.add_all(
            [Folder(name=f"Folder {index}", position=index) for index in range(1, 10)]
        )
        session.commit()

    ten_folder_queries = _request_query_count(
        client, lambda: client.get("/api/v1/folders", headers=auth_headers)
    )

    assert ten_folder_queries == one_folder_queries


def test_folder_reorder_uses_constant_query_count_as_folder_count_grows(
    client, auth_headers
):
    with client.app.state.session_factory() as session:
        folders = [Folder(name=f"Reorder {index}", position=index) for index in range(2)]
        session.add_all(folders)
        session.commit()
        two_ids = [folder.id for folder in folders]

    two_folder_queries = _request_query_count(
        client,
        lambda: client.post(
            "/api/v1/folders/reorder",
            headers=auth_headers,
            json={"ids": list(reversed(two_ids))},
        ),
    )

    with client.app.state.session_factory() as session:
        session.add_all(
            [Folder(name=f"Reorder {index}", position=index) for index in range(2, 10)]
        )
        session.commit()
        ten_ids = [folder.id for folder in session.query(Folder).all()]

    ten_folder_queries = _request_query_count(
        client,
        lambda: client.post(
            "/api/v1/folders/reorder",
            headers=auth_headers,
            json={"ids": list(reversed(ten_ids))},
        ),
    )

    assert ten_folder_queries == two_folder_queries


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
