from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from sqlalchemy import event

from manager_backend.errors import ManagerError
from manager_backend.features.catalog.service import delete_catalog
from manager_backend.features.profiles import service as profile_service
from manager_backend.features.profiles.schemas import ProfileCreate, ProfilePatch
from manager_backend.features.proxies.credentials import MemoryCredentialStore
from manager_backend.features.proxies.service import delete_proxy
from manager_backend.models import Profile, Proxy, Tag


def patch_profile(client, auth_headers, profile, **changes):
    return client.patch(
        f"/api/v1/profiles/{profile['id']}",
        headers=auth_headers,
        json={"expected_updated_at": profile["updated_at"], **changes},
    )


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
    assert first["profile_directory"] == str(
        (client.app.state.settings.profile_root / first["id"]).resolve()
    )


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

    updated = patch_profile(client, auth_headers, created, name="Updated", pinned=True)
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


def test_duplicate_clears_the_proxy(client, auth_headers):
    from manager_backend.features.proxies.credentials import MemoryCredentialStore

    client.app.state.credential_store = MemoryCredentialStore()
    proxy = client.post(
        "/api/v1/proxies",
        headers=auth_headers,
        json={
            "label": "Src",
            "scheme": "socks5",
            "host": "1.2.3.4",
            "port": 1080,
            "username": "u",
            "password": "p",
            "test_before_launch": True,
        },
    ).json()
    original = create_profile(client, auth_headers, proxy_id=proxy["id"])
    assert original["proxy_id"] == proxy["id"]

    duplicate = client.post(
        f"/api/v1/profiles/{original['id']}/duplicate", headers=auth_headers
    ).json()
    # Per-profile proxies: the clone starts direct so it can't share the source IP.
    assert duplicate["proxy_id"] is None


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

    response = patch_profile(
        client,
        auth_headers,
        original,
        behavior={
            "hardware_concurrency_mode": "custom",
            "hardware_concurrency": 8,
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


def test_bulk_add_and_remove_tag(client, auth_headers):
    tag = client.post(
        "/api/v1/tags", headers=auth_headers, json={"name": "US", "color": "#2563EB"}
    ).json()
    a = create_profile(client, auth_headers, "A")
    b = create_profile(client, auth_headers, "B")
    ids = [a["id"], b["id"]]

    added = client.post(
        "/api/v1/profiles/bulk",
        headers=auth_headers,
        json={"action": "add_tag", "ids": ids, "tag_id": tag["id"]},
    )
    assert added.status_code == 200
    assert client.get(f"/api/v1/profiles/{a['id']}", headers=auth_headers).json()["tag_ids"] == [
        tag["id"]
    ]
    assert client.get(f"/api/v1/profiles/{b['id']}", headers=auth_headers).json()["tag_ids"] == [
        tag["id"]
    ]

    removed = client.post(
        "/api/v1/profiles/bulk",
        headers=auth_headers,
        json={"action": "remove_tag", "ids": ids, "tag_id": tag["id"]},
    )
    assert removed.status_code == 200
    assert (
        client.get(f"/api/v1/profiles/{a['id']}", headers=auth_headers).json()["tag_ids"] == []
    )

    # tag_id is required for tag actions.
    bad = client.post(
        "/api/v1/profiles/bulk",
        headers=auth_headers,
        json={"action": "add_tag", "ids": ids},
    )
    assert bad.status_code == 422


def test_focus_runtime_route_is_typed_until_adapter_is_installed(client, auth_headers):
    profile = create_profile(client, auth_headers)
    response = client.post(
        f"/api/v1/profiles/{profile['id']}/focus-window", headers=auth_headers
    )
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "runtime_command_not_supported"


def test_patch_requires_expected_updated_at(client, auth_headers):
    profile = create_profile(client, auth_headers)

    response = client.patch(
        f"/api/v1/profiles/{profile['id']}",
        headers=auth_headers,
        json={"notes": "missing token"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["field_errors"]["expected_updated_at"] == "Field required"


def test_empty_patch_returns_profile_unchanged(client, auth_headers):
    profile = create_profile(client, auth_headers, notes="keep everything")

    response = patch_profile(client, auth_headers, profile)

    assert response.status_code == 200, response.text
    assert response.json() == profile


def test_metadata_only_patch_preserves_fingerprint_identity(client, auth_headers):
    profile = create_profile(client, auth_headers)

    response = patch_profile(
        client,
        auth_headers,
        profile,
        notes="metadata changed",
        pinned=True,
        startup_urls=["https://example.com"],
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["notes"] == "metadata changed"
    assert updated["pinned"] is True
    assert updated["startup_urls"] == ["https://example.com"]
    assert updated["fingerprint_seed"] == profile["fingerprint_seed"]
    assert updated["fingerprint_revision"] == profile["fingerprint_revision"]
    assert updated["fingerprint_config_hash"] == profile["fingerprint_config_hash"]
    assert updated["updated_at"] != profile["updated_at"]


def test_patch_explicit_null_clears_only_nullable_fields(client, auth_headers):
    folder = client.post(
        "/api/v1/folders", headers=auth_headers, json={"name": "Assigned"}
    ).json()
    profile = create_profile(client, auth_headers, folder_id=folder["id"])

    cleared = patch_profile(client, auth_headers, profile, folder_id=None)

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["folder_id"] is None

    rejected = patch_profile(client, auth_headers, cleared.json(), notes=None)
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "validation_error"
    assert rejected.json()["error"]["field_errors"]["notes"] == (
        "Input should be a valid string"
    )


def test_patch_replaces_nested_objects_atomically(client, auth_headers):
    profile = create_profile(
        client,
        auth_headers,
        location={
            "geo_mode": "manual",
            "locale": "vi-VN",
            "timezone": "Asia/Saigon",
        },
    )

    response = patch_profile(
        client, auth_headers, profile, location={"timezone": "UTC"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["location"] == {
        "geo_mode": "proxy",
        "locale": None,
        "timezone": "UTC",
        "webrtc_mode": "proxy",
        "geolocation_mode": "ask",
        "latitude": None,
        "longitude": None,
        "accuracy": None,
    }


def test_patch_accepts_equivalent_timezone_offset_timestamp(client, auth_headers):
    profile = create_profile(client, auth_headers)
    stored = datetime.fromisoformat(profile["updated_at"])
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=timezone.utc)
    equivalent = stored.astimezone(timezone(timedelta(hours=7))).isoformat()

    response = client.patch(
        f"/api/v1/profiles/{profile['id']}",
        headers=auth_headers,
        json={"expected_updated_at": equivalent, "notes": "canonical UTC"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["notes"] == "canonical UTC"


def test_stale_patch_returns_conflict_with_current_safe_profile(client, auth_headers):
    original = create_profile(client, auth_headers)
    first = patch_profile(client, auth_headers, original, notes="first writer")
    assert first.status_code == 200, first.text
    current = first.json()

    stale = patch_profile(client, auth_headers, original, notes="stale writer")

    assert stale.status_code == 409
    error = stale.json()["error"]
    assert error["code"] == "profile_conflict"
    assert error["field_errors"]["current_profile"] == current
    assert "fingerprint_seed" in error["field_errors"]["current_profile"]
    assert "profile_directory" in error["field_errors"]["current_profile"]
    assert "stale writer" not in stale.text


def test_fingerprint_changes_increment_revision_once_per_semantic_patch(
    client, auth_headers
):
    original = create_profile(client, auth_headers)

    changed = patch_profile(
        client,
        auth_headers,
        original,
        location={"timezone": "UTC"},
        window={"color_scheme": "dark"},
    )
    assert changed.status_code == 200, changed.text
    changed_profile = changed.json()
    assert changed_profile["fingerprint_seed"] == original["fingerprint_seed"]
    assert changed_profile["fingerprint_revision"] == original["fingerprint_revision"] + 1
    assert changed_profile["fingerprint_config_hash"] != original["fingerprint_config_hash"]

    unchanged = patch_profile(
        client,
        auth_headers,
        changed_profile,
        location={"timezone": "UTC"},
        window={"color_scheme": "dark"},
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["fingerprint_revision"] == changed_profile["fingerprint_revision"]
    assert unchanged.json()["fingerprint_config_hash"] == changed_profile["fingerprint_config_hash"]
    assert unchanged.json()["updated_at"] == changed_profile["updated_at"]

    operational = patch_profile(
        client,
        auth_headers,
        unchanged.json(),
        behavior={"clear_cache_before_launch": True},
    )
    assert operational.status_code == 200, operational.text
    assert operational.json()["fingerprint_revision"] == changed_profile["fingerprint_revision"]
    assert operational.json()["fingerprint_config_hash"] == changed_profile[
        "fingerprint_config_hash"
    ]
    assert operational.json()["updated_at"] != changed_profile["updated_at"]


def test_concurrent_patches_allow_exactly_one_writer(
    db_session_factory, settings, monkeypatch
):
    with db_session_factory() as session:
        original = profile_service.create_profile(session, ProfileCreate(name="Race"))
        profile_id = original.id
        expected_updated_at = original.updated_at

    frozen_now = profile_service._canonical_utc(expected_updated_at)
    monkeypatch.setattr(profile_service, "utc_now", lambda: frozen_now)

    barrier = Barrier(2)
    original_validator = profile_service._validate_identity_modes

    def synchronize_after_initial_version_read(profile, changes):
        original_validator(profile, changes)
        barrier.wait(timeout=5)

    monkeypatch.setattr(
        profile_service,
        "_validate_identity_modes",
        synchronize_after_initial_version_read,
    )

    def attempt(notes):
        with db_session_factory() as session:
            try:
                updated = profile_service.update_profile(
                    session,
                    profile_id,
                    ProfilePatch(
                        expected_updated_at=expected_updated_at,
                        notes=notes,
                    ),
                    settings=settings,
                )
                return ("updated", updated.notes)
            except ManagerError as error:
                return (error.code, error.field_errors["current_profile"]["notes"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ("writer one", "writer two")))

    assert sorted(result[0] for result in results) == ["profile_conflict", "updated"]
    winner = next(result[1] for result in results if result[0] == "updated")
    conflict_current = next(
        result[1] for result in results if result[0] == "profile_conflict"
    )
    assert conflict_current == winner

    with db_session_factory() as session:
        persisted = profile_service.get_profile(session, profile_id)
        assert persisted.notes == winner
        assert profile_service._canonical_utc(persisted.updated_at) > frozen_now


def test_proxy_delete_between_request_start_and_cas_returns_reference_error(
    db_session_factory, settings
):
    with db_session_factory() as session:
        proxy = Proxy(label="Race proxy", scheme="direct")
        session.add(proxy)
        session.commit()
        profile = profile_service.create_profile(session, ProfileCreate(name="Proxy race"))
        proxy_id = proxy.id
        profile_id = profile.id
        expected_updated_at = profile.updated_at

    cas_reached = Barrier(2)
    release_cas = Barrier(2)
    engine = db_session_factory.kw["bind"]
    cas_paused = False

    def pause_profile_cas(_conn, _cursor, statement, _parameters, _context, _many):
        nonlocal cas_paused
        normalized = " ".join(statement.lower().split())
        if not cas_paused and normalized.startswith(
            "update profiles set updated_at=profiles.updated_at"
        ):
            cas_paused = True
            cas_reached.wait(timeout=5)
            release_cas.wait(timeout=5)

    event.listen(engine, "before_cursor_execute", pause_profile_cas)

    def patch_proxy():
        with db_session_factory() as session:
            try:
                return profile_service.update_profile(
                    session,
                    profile_id,
                    ProfilePatch(
                        expected_updated_at=expected_updated_at,
                        proxy_id=proxy_id,
                    ),
                    settings=settings,
                )
            except Exception as error:
                return error

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending_patch = executor.submit(patch_proxy)
            cas_reached.wait(timeout=5)
            with db_session_factory() as session:
                delete_proxy(session, MemoryCredentialStore(), proxy_id)
            release_cas.wait(timeout=5)
            result = pending_patch.result(timeout=5)
    finally:
        if event.contains(engine, "before_cursor_execute", pause_profile_cas):
            event.remove(engine, "before_cursor_execute", pause_profile_cas)

    assert isinstance(result, ManagerError)
    assert result.code == "invalid_profile_reference"
    assert result.status_code == 422
    assert result.field_errors == {"proxy_id": "not_found"}
    with db_session_factory() as session:
        assert session.get(Proxy, proxy_id).deleted_at is not None
        assert session.get(Profile, profile_id).proxy_id is None


def test_reserved_proxy_patch_makes_concurrent_delete_fail_as_in_use(
    db_session_factory, settings, monkeypatch
):
    with db_session_factory() as session:
        proxy = Proxy(label="Reserved proxy", scheme="direct")
        session.add(proxy)
        session.commit()
        profile = profile_service.create_profile(
            session, ProfileCreate(name="Reserved proxy race")
        )
        proxy_id = proxy.id
        profile_id = profile.id
        expected_updated_at = profile.updated_at

    patch_validated = Barrier(2)
    release_patch = Barrier(2)
    delete_write_reached = Barrier(2)
    original_validator = profile_service._validate_references
    engine = db_session_factory.kw["bind"]
    delete_write_seen = False

    def pause_after_reference_validation(*args, **kwargs):
        result = original_validator(*args, **kwargs)
        patch_validated.wait(timeout=5)
        release_patch.wait(timeout=5)
        return result

    def observe_proxy_delete(_conn, _cursor, statement, _parameters, _context, _many):
        nonlocal delete_write_seen
        normalized = " ".join(statement.lower().split())
        if not delete_write_seen and normalized.startswith("update proxies set"):
            delete_write_seen = True
            delete_write_reached.wait(timeout=5)

    monkeypatch.setattr(
        profile_service,
        "_validate_references",
        pause_after_reference_validation,
    )
    event.listen(engine, "before_cursor_execute", observe_proxy_delete)

    def patch_proxy():
        with db_session_factory() as session:
            try:
                return profile_service.update_profile(
                    session,
                    profile_id,
                    ProfilePatch(
                        expected_updated_at=expected_updated_at,
                        proxy_id=proxy_id,
                    ),
                    settings=settings,
                )
            except Exception as error:
                return error

    def remove_proxy():
        with db_session_factory() as session:
            try:
                delete_proxy(session, MemoryCredentialStore(), proxy_id)
                return None
            except Exception as error:
                return error

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending_patch = executor.submit(patch_proxy)
            patch_validated.wait(timeout=5)
            pending_delete = executor.submit(remove_proxy)
            delete_write_reached.wait(timeout=5)
            release_patch.wait(timeout=5)
            patch_result = pending_patch.result(timeout=5)
            delete_result = pending_delete.result(timeout=5)
    finally:
        if event.contains(engine, "before_cursor_execute", observe_proxy_delete):
            event.remove(engine, "before_cursor_execute", observe_proxy_delete)

    assert isinstance(patch_result, Profile)
    assert isinstance(delete_result, ManagerError)
    assert delete_result.code == "proxy_in_use"
    assert delete_result.status_code == 409
    with db_session_factory() as session:
        assert session.get(Profile, profile_id).proxy_id == proxy_id
        assert session.get(Proxy, proxy_id).deleted_at is None


def test_tag_delete_between_request_start_and_cas_returns_reference_error(
    db_session_factory, settings
):
    with db_session_factory() as session:
        tag = Tag(name="Race tag", color="#64748B")
        session.add(tag)
        session.commit()
        profile = profile_service.create_profile(session, ProfileCreate(name="Tag race"))
        tag_id = tag.id
        profile_id = profile.id
        expected_updated_at = profile.updated_at

    cas_reached = Barrier(2)
    release_cas = Barrier(2)
    engine = db_session_factory.kw["bind"]
    cas_paused = False

    def pause_profile_cas(_conn, _cursor, statement, _parameters, _context, _many):
        nonlocal cas_paused
        normalized = " ".join(statement.lower().split())
        if not cas_paused and normalized.startswith(
            "update profiles set updated_at=profiles.updated_at"
        ):
            cas_paused = True
            cas_reached.wait(timeout=5)
            release_cas.wait(timeout=5)

    event.listen(engine, "before_cursor_execute", pause_profile_cas)

    def patch_tag():
        with db_session_factory() as session:
            try:
                return profile_service.update_profile(
                    session,
                    profile_id,
                    ProfilePatch(
                        expected_updated_at=expected_updated_at,
                        tag_ids=[tag_id],
                    ),
                    settings=settings,
                )
            except Exception as error:
                return error

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending_patch = executor.submit(patch_tag)
            cas_reached.wait(timeout=5)
            with db_session_factory() as session:
                delete_catalog(session, Tag, tag_id)
            release_cas.wait(timeout=5)
            result = pending_patch.result(timeout=5)
    finally:
        if event.contains(engine, "before_cursor_execute", pause_profile_cas):
            event.remove(engine, "before_cursor_execute", pause_profile_cas)

    assert isinstance(result, ManagerError)
    assert result.code == "invalid_profile_reference"
    assert result.status_code == 422
    assert result.field_errors == {"tag_ids": "contains_unknown_id"}
    with db_session_factory() as session:
        assert session.get(Tag, tag_id) is None
        assert profile_service.get_profile(session, profile_id).tags == []


def test_residual_tag_foreign_key_failure_maps_to_safe_reference_error(
    db_session_factory, settings
):
    with db_session_factory() as session:
        tag = Tag(name="Vanishing tag", color="#64748B")
        session.add(tag)
        session.commit()
        profile = profile_service.create_profile(session, ProfileCreate(name="FK race"))
        tag_id = tag.id
        profile_id = profile.id
        expected_updated_at = profile.updated_at

    engine = db_session_factory.kw["bind"]
    delete_injected = False

    def delete_tag_before_association_insert(
        _conn, cursor, statement, _parameters, _context, _many
    ):
        nonlocal delete_injected
        if not delete_injected and statement.lower().startswith("insert into profile_tags"):
            delete_injected = True
            cursor.execute("DELETE FROM tags WHERE id = ?", (tag_id,))

    event.listen(engine, "before_cursor_execute", delete_tag_before_association_insert)
    try:
        with db_session_factory() as session:
            with pytest.raises(ManagerError) as caught:
                profile_service.update_profile(
                    session,
                    profile_id,
                    ProfilePatch(
                        expected_updated_at=expected_updated_at,
                        tag_ids=[tag_id],
                    ),
                    settings=settings,
                )
    finally:
        if event.contains(
            engine,
            "before_cursor_execute",
            delete_tag_before_association_insert,
        ):
            event.remove(
                engine,
                "before_cursor_execute",
                delete_tag_before_association_insert,
            )

    assert caught.value.code == "invalid_profile_reference"
    assert caught.value.status_code == 422
    assert caught.value.field_errors == {"references": "changed_during_update"}
    assert "foreign key" not in caught.value.message.lower()
    with db_session_factory() as session:
        assert session.get(Tag, tag_id) is not None
        assert profile_service.get_profile(session, profile_id).tags == []
