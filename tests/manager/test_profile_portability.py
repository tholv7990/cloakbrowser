from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import Request
from pydantic import ValidationError
from sqlalchemy import func, select

from manager_backend.errors import ManagerError
from manager_backend.features.portability import profiles as portability_profiles
from manager_backend.features.portability.profiles import export_profile, import_profile
from manager_backend.features.portability.schemas import (
    MAX_PROFILE_DOCUMENT_BYTES,
    ProfileExportV1,
)
from manager_backend.models import (
    Folder,
    Profile,
    Proxy,
    RuntimeSession,
    Tag,
    WorkflowStatus,
)


FIXED_EXPORTED_AT = datetime(2026, 7, 22, tzinfo=timezone.utc)


def _document(**profile_changes):
    profile = {
        "name": "Portable profile",
        "folder": None,
        "workflow_status": None,
        "tags": [],
        "notes": "portable notes",
        "pinned": True,
        "startup_urls": ["https://example.com/start"],
        "fingerprint_preset": "consistent",
        "browser_version_mode": "installed",
        "browser_version": None,
        "user_agent_mode": "automatic",
        "custom_user_agent": None,
        "location": {
            "geo_mode": "system",
            "locale": None,
            "timezone": None,
            "webrtc_mode": "direct",
            "geolocation_mode": "ask",
            "latitude": None,
            "longitude": None,
            "accuracy": None,
        },
        "window": {
            "mode": "maximized",
            "width": None,
            "height": None,
            "color_scheme": "system",
        },
        "behavior": {
            "humanize_enabled": False,
            "humanize_preset": "default",
            "clear_cache_before_launch": False,
            "restore_previous_tabs": True,
            "permissions": {},
            "ignore_https_errors": False,
            "hardware_concurrency_mode": "automatic",
            "hardware_concurrency": None,
            "gpu_mode": "automatic",
            "gpu_vendor": None,
        },
        "proxy": None,
        "test_proxy_before_launch": True,
    }
    profile.update(profile_changes)
    return {
        "format": "cloakbrowser-manager-profile",
        "version": 1,
        "exported_at": "2026-07-22T00:00:00Z",
        "profile": profile,
        "extensions": [],
    }


def _persist_rich_profile(session) -> Profile:
    folder = Folder(name="Customers", position=0)
    status = WorkflowStatus(name="Ready", color="#16A34A", position=0)
    tags = [
        Tag(name="Zulu", color="#111111"),
        Tag(name="alpha", color="#222222"),
    ]
    proxy = Proxy(
        label="private-proxy",
        scheme="http",
        host="proxy.example",
        port=8443,
        credential_ref="credential-secret-ref",
    )
    session.add_all([folder, status, *tags, proxy])
    session.flush()
    profile = Profile(
        name="Portable / Profile",
        folder_id=folder.id,
        status_id=status.id,
        notes="safe notes",
        pinned=True,
        startup_urls=["https://example.com/start"],
        fingerprint_seed="123456789",
        fingerprint_preset="consistent",
        fingerprint_revision=9,
        fingerprint_config_hash="a" * 64,
        browser_version_mode="installed",
        user_agent_mode="automatic",
        location={"geo_mode": "system"},
        window={"mode": "maximized"},
        behavior={
            "humanize_enabled": False,
            "download_directory_mode": "custom",
            "custom_download_directory": r"C:\Users\owner\secret-downloads",
            "permissions": {"notifications": "block", "camera": "ask"},
            "additional_args": ["--client-secret=do-not-export"],
        },
        proxy_id=proxy.id,
        tags=tags,
        last_opened_at=FIXED_EXPORTED_AT,
        total_runtime_seconds=900,
    )
    session.add(profile)
    session.flush()
    session.add(RuntimeSession(profile_id=profile.id, state="running", last_message="secret runtime"))
    session.commit()
    return profile


def test_export_profile_is_deterministic_versioned_and_secret_free(db_session_factory):
    with db_session_factory() as session:
        source = _persist_rich_profile(session)
        source_id = source.id
        folder_id = source.folder_id
        status_id = source.status_id
        proxy_id = source.proxy_id

        first = export_profile(session, source_id, exported_at=FIXED_EXPORTED_AT)
        second = export_profile(session, source_id, exported_at=FIXED_EXPORTED_AT)

    assert first.model_dump_json() == second.model_dump_json()
    payload = first.model_dump(mode="json")
    assert list(payload) == ["format", "version", "exported_at", "profile", "extensions"]
    assert payload["format"] == "cloakbrowser-manager-profile"
    assert payload["version"] == 1
    assert payload["extensions"] == []
    assert payload["profile"]["folder"] == {"name": "Customers"}
    assert payload["profile"]["workflow_status"] == {
        "name": "Ready",
        "color": "#16A34A",
    }
    assert payload["profile"]["tags"] == [
        {"name": "alpha", "color": "#222222"},
        {"name": "Zulu", "color": "#111111"},
    ]
    assert payload["profile"]["proxy"] == {
        "scheme": "http",
        "host": "proxy.example",
        "port": 8443,
    }
    assert "custom_download_directory" not in payload["profile"]["behavior"]
    assert "additional_args" not in payload["profile"]["behavior"]
    assert list(payload["profile"]["behavior"]["permissions"]) == [
        "camera",
        "notifications",
    ]

    serialized = first.model_dump_json()
    for forbidden in (
        source_id,
        folder_id,
        status_id,
        proxy_id,
        "123456789",
        "credential-secret-ref",
        r"C:\Users\owner\secret-downloads",
        "do-not-export",
        "secret runtime",
        "fingerprint_config_hash",
        "runtime_state",
        "last_opened_at",
        "total_runtime_seconds",
        "profile_directory",
        "created_at",
        "updated_at",
        "deleted_at",
    ):
        assert forbidden not in serialized


def test_profile_document_models_forbid_unknown_or_identity_fields():
    document = _document()
    document["profile"]["fingerprint_seed"] = "1"

    with pytest.raises(ValidationError):
        ProfileExportV1.model_validate_json(json.dumps(document))

    document = _document()
    document["unexpected"] = True
    with pytest.raises(ValidationError):
        ProfileExportV1.model_validate_json(json.dumps(document))


@pytest.mark.parametrize("lookalike", [True, 1.0, "1"])
def test_profile_document_version_does_not_coerce_lookalikes(lookalike):
    document = _document()
    document["version"] = lookalike

    with pytest.raises(ValidationError):
        ProfileExportV1.model_validate_json(json.dumps(document))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pinned", "false"),
        ("test_proxy_before_launch", 0),
        ("window", {"mode": "custom", "width": "1024", "height": 768}),
    ],
)
def test_profile_document_rejects_coercive_field_types(field, value):
    document = _document()
    document["profile"][field] = value

    with pytest.raises(ValidationError):
        ProfileExportV1.model_validate_json(json.dumps(document))


def test_export_route_sets_safe_download_headers(client, auth_headers):
    with client.app.state.session_factory() as session:
        profile = Profile(
            name='Quarterly / Report\r\nX-Injected: yes "',
            fingerprint_seed="700",
            fingerprint_config_hash="a" * 64,
        )
        session.add(profile)
        session.commit()
        profile_id = profile.id

    response = client.get(f"/api/v1/profiles/{profile_id}/export", headers=auth_headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    disposition = response.headers["content-disposition"]
    assert disposition == 'attachment; filename="cloakbrowser-profile-quarterly-report-x-injected-yes.json"'
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "\r" not in disposition and "\n" not in disposition
    assert response.json()["profile"]["name"].startswith("Quarterly / Report")


def test_import_route_rejects_document_larger_than_two_mib(client, auth_headers):
    body = json.dumps(_document()).encode("utf-8")
    oversized = body + (b" " * (MAX_PROFILE_DOCUMENT_BYTES - len(body) + 1))

    response = client.post(
        "/api/v1/profiles/import",
        headers={**auth_headers, "Content-Type": "application/json"},
        content=oversized,
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "profile_document_too_large"
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count(Profile.id))) == 0


def test_import_route_streams_body_instead_of_buffering_it(
    client, auth_headers, monkeypatch
):
    async def reject_unbounded_body(_request):
        raise AssertionError("request.body() must not buffer an untrusted import")

    monkeypatch.setattr(Request, "body", reject_unbounded_body)

    response = client.post(
        "/api/v1/profiles/import", headers=auth_headers, json=_document()
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("change", "field"),
    [
        (lambda document: document.update(version=2), "version"),
        (lambda document: document.update(format="another-format"), "format"),
        (lambda document: document.update(extra="forbidden"), "extra"),
    ],
)
def test_import_route_rejects_bad_format_version_and_unknown_fields(
    client, auth_headers, change, field
):
    document = _document()
    change(document)

    response = client.post(
        "/api/v1/profiles/import", headers=auth_headers, json=document
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_profile_document"
    assert field in error["field_errors"]
    assert json.dumps(document) not in error["message"]


def test_import_resolves_catalogs_by_normalized_name_and_creates_missing_values(
    db_session_factory, settings
):
    with db_session_factory() as session:
        folder = Folder(name="Customers", position=0)
        status = WorkflowStatus(name="Ready", color="#000000", position=0)
        tag = Tag(name="VIP", color="#111111")
        session.add_all([folder, status, tag])
        session.commit()
        folder_id, status_id, tag_id = folder.id, status.id, tag.id

    document = ProfileExportV1.model_validate_json(
        json.dumps(_document(
            folder={"name": "  customers  "},
            workflow_status={"name": " ready ", "color": "#ABCDEF"},
            tags=[
                {"name": " vip ", "color": "#FFFFFF"},
                {"name": "New   Tag", "color": "#123456"},
            ],
        ))
    )
    with db_session_factory() as session:
        result = import_profile(session, document, settings=settings)

    with db_session_factory() as session:
        imported = session.get(Profile, result.profile_id)
        assert imported is not None
        assert imported.folder_id == folder_id
        assert imported.status_id == status_id
        assert {item.id for item in imported.tags} >= {tag_id}
        assert {item.name for item in imported.tags} == {"VIP", "New Tag"}
        assert session.scalar(select(func.count(Folder.id))) == 1
        assert session.scalar(select(func.count(WorkflowStatus.id))) == 1
        assert session.scalar(select(func.count(Tag.id))) == 2
        assert session.get(Tag, tag_id).color == "#111111"


def test_import_assigns_fresh_identity_and_deterministic_collision_names(
    db_session_factory, settings
):
    with db_session_factory() as session:
        existing = Profile(
            name="Portable profile",
            fingerprint_seed="42",
            fingerprint_revision=99,
            fingerprint_config_hash="f" * 64,
        )
        session.add(existing)
        session.commit()
        existing_id = existing.id

    document = ProfileExportV1.model_validate_json(json.dumps(_document()))
    with db_session_factory() as session:
        first = import_profile(session, document, settings=settings)
    with db_session_factory() as session:
        second = import_profile(session, document, settings=settings)

    with db_session_factory() as session:
        profiles = list(session.scalars(select(Profile).order_by(Profile.name)))
        by_id = {profile.id: profile for profile in profiles}
        assert by_id[first.profile_id].name == "Portable profile (imported 1)"
        assert by_id[second.profile_id].name == "Portable profile (imported 2)"
        assert len({existing_id, first.profile_id, second.profile_id}) == 3
        for imported_id in (first.profile_id, second.profile_id):
            UUID(imported_id)
            imported = by_id[imported_id]
            assert imported.fingerprint_seed != "42"
            assert imported.fingerprint_revision == 1
            assert imported.fingerprint_config_hash != "f" * 64
            assert (settings.profile_root / imported_id).is_dir()


def test_import_warns_without_assigning_proxy_or_missing_extensions(
    db_session_factory, settings
):
    raw = _document(
        proxy={"scheme": "socks5", "host": "proxy.example", "port": 1080}
    )
    raw["extensions"] = [
        {
            "name": "Local Helper",
            "version": "1.2.3",
            "manifest_version": 3,
            "manifest_hash": "a" * 64,
        }
    ]
    document = ProfileExportV1.model_validate_json(json.dumps(raw))

    with db_session_factory() as session:
        result = import_profile(session, document, settings=settings)

    assert [warning.code for warning in result.warnings] == [
        "proxy_assignment_skipped",
        "extension_missing",
    ]
    assert "proxy.example" not in result.model_dump_json()
    assert "Local Helper" not in result.model_dump_json()
    with db_session_factory() as session:
        imported = session.get(Profile, result.profile_id)
        assert imported.proxy_id is None


def test_import_rolls_back_profile_and_new_catalogs_when_directory_creation_fails(
    db_session_factory, settings, monkeypatch
):
    document = ProfileExportV1.model_validate_json(
        json.dumps(_document(
            folder={"name": "Rollback Folder"},
            workflow_status={"name": "Rollback Status", "color": "#123456"},
            tags=[{"name": "Rollback Tag", "color": "#654321"}],
        ))
    )

    def fail_directory(_path: Path) -> None:
        raise OSError("private filesystem detail")

    monkeypatch.setattr(portability_profiles, "_create_profile_directory", fail_directory)
    with db_session_factory() as session:
        with pytest.raises(ManagerError) as caught:
            import_profile(session, document, settings=settings)

    assert caught.value.code == "profile_import_failed"
    assert "private filesystem detail" not in caught.value.message
    with db_session_factory() as session:
        assert session.scalar(select(func.count(Profile.id))) == 0
        assert session.scalar(select(func.count(Folder.id))) == 0
        assert session.scalar(select(func.count(WorkflowStatus.id))) == 0
        assert session.scalar(select(func.count(Tag.id))) == 0


def test_import_never_removes_a_preexisting_profile_directory(
    db_session_factory, settings, monkeypatch
):
    fixed_id = UUID("11111111-1111-4111-8111-111111111111")
    existing_directory = settings.profile_root / str(fixed_id)
    existing_directory.mkdir(parents=True)
    monkeypatch.setattr(portability_profiles, "uuid4", lambda: fixed_id)
    document = ProfileExportV1.model_validate_json(json.dumps(_document()))

    with db_session_factory() as session:
        with pytest.raises(ManagerError) as caught:
            import_profile(session, document, settings=settings)

    assert caught.value.code == "profile_import_failed"
    assert existing_directory.is_dir()
    with db_session_factory() as session:
        assert session.scalar(select(func.count(Profile.id))) == 0
