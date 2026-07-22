from __future__ import annotations

import json
import zipfile
from pathlib import Path

from manager_backend.models import RuntimeSession


def _backup_dir(client) -> Path:
    return client.app.state.settings.data_root / "backups"


def test_create_backup_is_verified_and_excludes_browser_data(client, auth_headers):
    created = client.post("/api/v1/backups", headers=auth_headers)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["verified"] is True
    assert body["automatic"] is False
    assert body["size_bytes"] > 0
    assert body["contents"] == ["profiles", "proxies", "folders", "extensions"]

    archive = _backup_dir(client) / f"{body['id']}.zip"
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
    # Only the DB snapshot + manifest — never a profile/cookie/session path.
    assert names == {"manager.db", "manifest.json"}


def test_list_returns_created_backups(client, auth_headers):
    assert client.get("/api/v1/backups").json() == []
    first = client.post("/api/v1/backups", headers=auth_headers).json()
    listing = client.get("/api/v1/backups").json()
    assert [item["id"] for item in listing] == [first["id"]]


def test_delete_removes_the_archive(client, auth_headers):
    created = client.post("/api/v1/backups", headers=auth_headers).json()
    archive = _backup_dir(client) / f"{created['id']}.zip"
    assert archive.exists()

    deleted = client.delete(f"/api/v1/backups/{created['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    assert not archive.exists()
    assert client.get("/api/v1/backups").json() == []


def test_restore_is_blocked_while_a_runtime_is_active(client, auth_headers):
    profile = client.post(
        "/api/v1/profiles", headers=auth_headers, json={"name": "Running"}
    ).json()
    created = client.post("/api/v1/backups", headers=auth_headers).json()
    with client.app.state.session_factory() as session:
        session.add(RuntimeSession(profile_id=profile["id"], state="running"))
        session.commit()

    blocked = client.post(f"/api/v1/backups/{created['id']}/restore", headers=auth_headers)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "backup_restore_blocked"


def test_restore_reverts_the_db_and_takes_a_safety_backup(client, auth_headers):
    profile = client.post(
        "/api/v1/profiles", headers=auth_headers, json={"name": "Precious"}
    ).json()
    created = client.post("/api/v1/backups", headers=auth_headers).json()

    # Destroy the profile, then roll back to the snapshot.
    trashed = client.post(
        f"/api/v1/profiles/{profile['id']}/move-to-trash", headers=auth_headers
    )
    assert trashed.status_code == 200
    assert client.get("/api/v1/profiles", headers=auth_headers).json()["total"] == 0

    restored = client.post(f"/api/v1/backups/{created['id']}/restore", headers=auth_headers)
    assert restored.status_code == 204

    listing = client.get("/api/v1/profiles", headers=auth_headers).json()
    assert [item["name"] for item in listing["items"]] == ["Precious"]  # restored in place
    assert listing["total"] == 1

    # A pre-restore safety backup was taken before overwriting.
    archives = client.get("/api/v1/backups").json()
    assert any(item["automatic"] for item in archives)
    assert len(archives) == 2


def test_restore_rejects_a_tampered_archive(client, auth_headers):
    backups = _backup_dir(client)
    backups.mkdir(parents=True, exist_ok=True)
    corrupt_id = "bkp_corrupt"
    manifest = {
        "version": 1,
        "id": corrupt_id,
        "created_at": "2026-07-22T09:00:00Z",
        "automatic": False,
        "verified": True,
        "contents": ["profiles"],
        "files": {"manager.db": "deadbeef"},  # hash will not match the payload
    }
    with zipfile.ZipFile(backups / f"{corrupt_id}.zip", "w") as zf:
        zf.writestr("manager.db", b"this is not a valid sqlite database")
        zf.writestr("manifest.json", json.dumps(manifest))

    response = client.post(f"/api/v1/backups/{corrupt_id}/restore", headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "backup_verification_failed"


def test_restore_of_a_missing_backup_is_not_found(client, auth_headers):
    response = client.post("/api/v1/backups/bkp_missing/restore", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "backup_not_found"


def test_auto_backup_creates_then_skips_within_the_interval(client):
    from manager_backend.features.backups.service import maybe_auto_backup

    engine = client.app.state.engine
    data_root = client.app.state.settings.data_root
    first = maybe_auto_backup(engine, data_root)
    assert first is not None and first["automatic"] is True
    assert maybe_auto_backup(engine, data_root) is None  # newest < 24h old → skip


def test_retention_keeps_the_newest_ten(client):
    from manager_backend.features.backups.service import (
        _enforce_retention,
        create_backup,
        list_backups,
    )

    engine = client.app.state.engine
    data_root = client.app.state.settings.data_root
    for _ in range(12):
        create_backup(engine, data_root, automatic=True)
    _enforce_retention(data_root)
    assert len(list_backups(data_root)) == 10
