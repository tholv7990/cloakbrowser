from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def _manifest(directory: Path, **changes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "manifest_version": 3,
        "name": "Local Helper",
        "version": "1.2.3",
        "description": "A local extension",
        "permissions": ["storage", "tabs", "storage"],
        "host_permissions": ["https://example.com/*"],
    }
    payload.update(changes)
    path = directory / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def allow_test_paths(monkeypatch):
    from manager_backend.features.extensions import service

    monkeypatch.setattr(service, "_temporary_roots", lambda: ())
    monkeypatch.setattr(service, "_system_roots", lambda: ())


def _register(client, auth_headers, directory: Path):
    return client.post(
        "/api/v1/extensions",
        headers=auth_headers,
        json={"directory": str(directory)},
    )


@pytest.mark.usefixtures("allow_test_paths")
def test_registers_mv2_and_mv3_with_stable_bounded_metadata_only(
    client, auth_headers, tmp_path
):
    mv2 = tmp_path / "mv2"
    _manifest(
        mv2,
        manifest_version=2,
        name="  MV2 Helper  ",
        version="2.0",
        description="x" * 900,
        permissions=[f"permission-{index}" for index in range(200)],
        background={"scripts": ["secret-source.js"]},
    )
    mv3 = tmp_path / "mv3"
    _manifest(mv3, action={"default_popup": "private.html"})

    first = _register(client, auth_headers, mv2)
    second = _register(client, auth_headers, mv3)

    assert first.status_code == second.status_code == 201
    mv2_record = first.json()
    assert mv2_record["name"] == "MV2 Helper"
    assert mv2_record["manifest_version"] == 2
    assert len(mv2_record["description"]) == 500
    assert len(mv2_record["permissions"]) == 100
    assert mv2_record["permissions"] == sorted(set(mv2_record["permissions"]))
    assert len(mv2_record["manifest_hash"]) == 64
    assert set(mv2_record) == {
        "id",
        "directory",
        "name",
        "version",
        "description",
        "manifest_version",
        "permissions",
        "enabled",
        "manifest_hash",
        "created_at",
        "updated_at",
    }
    assert "secret-source.js" not in first.text
    assert "private.html" not in second.text

    # Hash canonical JSON, not formatting or key order.
    raw = json.loads((mv2 / "manifest.json").read_text(encoding="utf-8"))
    (mv2 / "manifest.json").write_text(
        json.dumps(dict(reversed(list(raw.items()))), indent=4), encoding="utf-8"
    )
    duplicate = _register(client, auth_headers, mv2)
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == mv2_record["id"]
    assert duplicate.json()["manifest_hash"] == mv2_record["manifest_hash"]


@pytest.mark.usefixtures("allow_test_paths")
@pytest.mark.parametrize(
    "contents,code",
    [
        ("{not-json", "extension_manifest_invalid"),
        (json.dumps({"manifest_version": 4, "name": "Bad", "version": "1"}), "extension_manifest_invalid"),
        (json.dumps({"manifest_version": True, "name": "Bad", "version": "1"}), "extension_manifest_invalid"),
        (json.dumps({"manifest_version": 3, "name": "", "version": "1"}), "extension_manifest_invalid"),
    ],
)
def test_rejects_malformed_or_invalid_manifest(
    client, auth_headers, tmp_path, contents, code
):
    directory = tmp_path / "invalid"
    directory.mkdir()
    (directory / "manifest.json").write_text(contents, encoding="utf-8")

    response = _register(client, auth_headers, directory)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert contents[:20] not in response.text


@pytest.mark.usefixtures("allow_test_paths")
def test_rejects_oversized_manifest_without_echo(client, auth_headers, tmp_path):
    directory = tmp_path / "oversized"
    path = _manifest(directory)
    path.write_bytes(b"{" + b"x" * (1024 * 1024) + b"}")

    response = _register(client, auth_headers, directory)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "extension_manifest_too_large"
    assert "xxxxx" not in response.text


def test_rejects_profile_temp_system_network_and_reparse_paths(
    client, auth_headers, settings, tmp_path, monkeypatch
):
    from manager_backend.features.extensions import service

    roots = {
        "profile": settings.profile_root,
        "temp": tmp_path / "temp-root",
        "system": tmp_path / "windows-root",
    }
    for root in roots.values():
        _manifest(root / "extension")
    monkeypatch.setattr(service, "_temporary_roots", lambda: (roots["temp"].resolve(),))
    monkeypatch.setattr(service, "_system_roots", lambda: (roots["system"].resolve(),))

    for label, root in roots.items():
        response = _register(client, auth_headers, root / "extension")
        assert response.status_code == 422, label
        assert response.json()["error"]["code"] == "extension_path_forbidden"

    network = client.post(
        "/api/v1/extensions",
        headers=auth_headers,
        json={"directory": r"\\server\share\extension"},
    )
    assert network.status_code == 422
    assert network.json()["error"]["code"] == "extension_path_forbidden"

    allowed = tmp_path / "allowed"
    _manifest(allowed)
    monkeypatch.setattr(service, "_path_has_reparse_component", lambda _path: True)
    escaped = _register(client, auth_headers, allowed)
    assert escaped.status_code == 422
    assert escaped.json()["error"]["code"] == "extension_path_forbidden"


@pytest.mark.usefixtures("allow_test_paths")
def test_rejects_manifest_symlink_escape(client, auth_headers, tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text(
        json.dumps({"manifest_version": 3, "name": "Outside", "version": "1"}),
        encoding="utf-8",
    )
    directory = tmp_path / "linked"
    directory.mkdir()
    try:
        os.symlink(outside, directory / "manifest.json")
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    response = _register(client, auth_headers, directory)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "extension_path_forbidden"


@pytest.mark.usefixtures("allow_test_paths")
def test_conflict_refresh_enable_list_get_and_unregister_metadata_only(
    client, auth_headers, tmp_path
):
    directory = tmp_path / "refreshable"
    manifest_path = _manifest(directory)
    created = _register(client, auth_headers, directory).json()
    extension_id = created["id"]
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "name": "Refreshed Helper",
                "version": "2.0",
                "permissions": ["cookies"],
            }
        ),
        encoding="utf-8",
    )

    conflict = _register(client, auth_headers, directory)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "extension_manifest_changed"
    assert "Refreshed Helper" not in conflict.text

    refreshed = client.patch(
        f"/api/v1/extensions/{extension_id}",
        headers=auth_headers,
        json={"refresh": True, "enabled": False},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["name"] == "Refreshed Helper"
    assert refreshed.json()["version"] == "2.0"
    assert refreshed.json()["permissions"] == ["cookies"]
    assert refreshed.json()["enabled"] is False
    assert refreshed.json()["manifest_hash"] != created["manifest_hash"]

    assert client.get(f"/api/v1/extensions/{extension_id}", headers=auth_headers).json() == refreshed.json()
    listed = client.get("/api/v1/extensions", headers=auth_headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [extension_id]

    deleted = client.delete(f"/api/v1/extensions/{extension_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert manifest_path.exists()
    assert client.get(f"/api/v1/extensions/{extension_id}", headers=auth_headers).status_code == 404


@pytest.mark.usefixtures("allow_test_paths")
def test_complete_profile_assignment_is_strict_transactional_and_exported(
    client, auth_headers, tmp_path
):
    profile = client.post(
        "/api/v1/profiles", headers=auth_headers, json={"name": "Assigned"}
    ).json()
    first = _register(client, auth_headers, _manifest(tmp_path / "one").parent).json()
    second_dir = tmp_path / "two"
    _manifest(second_dir, name="Second", version="4.0", permissions=[])
    second = _register(client, auth_headers, second_dir).json()

    assigned = client.put(
        f"/api/v1/profiles/{profile['id']}/extensions",
        headers=auth_headers,
        json={"extension_ids": [second["id"], first["id"], second["id"]]},
    )
    assert assigned.status_code == 200
    assert assigned.json() == {"extension_ids": [second["id"], first["id"]]}

    rejected = client.put(
        f"/api/v1/profiles/{profile['id']}/extensions",
        headers=auth_headers,
        json={"extension_ids": [first["id"], "missing"]},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "invalid_extension_reference"

    exported = client.get(
        f"/api/v1/profiles/{profile['id']}/export", headers=auth_headers
    )
    assert exported.status_code == 200
    extensions = exported.json()["extensions"]
    assert extensions == sorted(extensions, key=lambda item: (item["name"].casefold(), item["manifest_hash"]))
    assert {tuple(item) for item in extensions} == {
        ("name", "version", "manifest_version", "manifest_hash")
    }
    assert all("directory" not in item for item in extensions)

    cleared = client.put(
        f"/api/v1/profiles/{profile['id']}/extensions",
        headers=auth_headers,
        json={"extension_ids": []},
    )
    assert cleared.status_code == 200
    assert cleared.json() == {"extension_ids": []}


def test_mutations_require_authentication_origin_csrf_and_strict_payload(
    client, auth_headers, tmp_path
):
    directory = _manifest(tmp_path / "secure").parent
    unauthenticated = client.post("/api/v1/extensions", json={"directory": str(directory)})
    missing_csrf = client.post(
        "/api/v1/extensions",
        headers={"Origin": auth_headers["Origin"]},
        json={"directory": str(directory)},
    )
    invalid_origin = client.post(
        "/api/v1/extensions",
        headers={**auth_headers, "Origin": "https://evil.example"},
        json={"directory": str(directory)},
    )
    extra = client.post(
        "/api/v1/extensions",
        headers=auth_headers,
        json={"directory": str(directory), "manifest": {"source": "echo-me"}},
    )

    assert unauthenticated.status_code == 403
    assert missing_csrf.status_code == 403
    assert invalid_origin.status_code == 403
    assert extra.status_code == 422
    assert "echo-me" not in extra.text


def test_openapi_declares_extension_contract_and_csrf_security(client):
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]

    assert {
        "/api/v1/extensions",
        "/api/v1/extensions/{extension_id}",
        "/api/v1/profiles/{profile_id}/extensions",
    } <= set(paths)
    assert "201" in paths["/api/v1/extensions"]["post"]["responses"]
    assert paths["/api/v1/extensions"]["post"]["security"] == [
        {"SessionCookie": []},
        {"CsrfToken": []},
    ]
