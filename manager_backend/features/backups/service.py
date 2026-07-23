"""Verified local snapshots of manager metadata (the SQLite DB).

Each archive is a zip holding a `VACUUM INTO` snapshot of manager.db plus a
manifest with its SHA-256. Metadata is derived by scanning the backups dir and
reading manifests — no backup table, which would otherwise be part of the very
DB a restore overwrites.

Browser profile folders / cookies / sessions are NEVER included. Restore uses
SQLite's online-backup API to copy a snapshot into the live engine in place, so
nothing needs re-wiring and existing sessions keep working.

ponytail: metadata only — extension binaries on disk are not archived (their
rows are, in the DB). Add file-level archival if disk rollback is ever needed.
Reference: Quantum backend/services/backup_service.py.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import Engine, func, select

from ...errors import ManagerError
from ...models import RuntimeSession
from ..runtime.service import ACTIVE_STATES


_DB_ENTRY = "manager.db"
_MANIFEST_ENTRY = "manifest.json"
_CONTENTS = ["profiles", "proxies", "folders", "extensions"]
_RETENTION = 10
_AUTO_INTERVAL = timedelta(hours=24)
_MANIFEST_VERSION = 1


def _backups_dir(data_root: Path) -> Path:
    path = data_root / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _integrity_ok(db_bytes: bytes, scratch_dir: Path) -> bool:
    probe = scratch_dir / f".probe-{secrets.token_hex(4)}.db"
    probe.write_bytes(db_bytes)
    try:
        connection = sqlite3.connect(probe)
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        finally:
            connection.close()
        return bool(row) and row[0] == "ok"
    finally:
        probe.unlink(missing_ok=True)


def _read_manifest(archive: Path) -> dict | None:
    try:
        with zipfile.ZipFile(archive) as zf:
            manifest = json.loads(zf.read(_MANIFEST_ENTRY))
        return manifest if isinstance(manifest, dict) else None
    except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError):
        return None


def _archive_to_dict(archive: Path, manifest: dict) -> dict:
    created = str(manifest.get("created_at", "")).replace("Z", "+00:00")
    return {
        "id": str(manifest.get("id") or archive.stem),
        "created_at": datetime.fromisoformat(created),
        "size_bytes": archive.stat().st_size,
        "automatic": bool(manifest.get("automatic")),
        "verified": bool(manifest.get("verified")),
        "contents": list(manifest.get("contents") or _CONTENTS),
    }


def create_backup(engine: Engine, data_root: Path, *, automatic: bool) -> dict:
    backups = _backups_dir(data_root)
    created = _now()
    backup_id = f"bkp_{created.strftime('%Y%m%dT%H%M%S')}_{secrets.token_hex(3)}"

    snapshot = backups / f".{backup_id}.snapshot.db"
    try:
        # VACUUM INTO writes a consistent, WAL-checkpointed copy of the live DB.
        with engine.connect() as connection:
            connection.exec_driver_sql(f"VACUUM INTO '{snapshot.as_posix()}'")
        db_bytes = snapshot.read_bytes()
    finally:
        snapshot.unlink(missing_ok=True)

    digest = _sha256(db_bytes)
    verified = _integrity_ok(db_bytes, backups)
    manifest = {
        "version": _MANIFEST_VERSION,
        "id": backup_id,
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "automatic": automatic,
        "verified": verified,
        "contents": _CONTENTS,
        "files": {_DB_ENTRY: digest},
    }

    archive = backups / f"{backup_id}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(_DB_ENTRY, db_bytes)
        zf.writestr(_MANIFEST_ENTRY, json.dumps(manifest, indent=2))

    # Confirm the archive read back byte-identical (guards a bad disk write).
    with zipfile.ZipFile(archive) as zf:
        if _sha256(zf.read(_DB_ENTRY)) != digest:
            archive.unlink(missing_ok=True)
            raise ManagerError(
                "backup_write_failed", "The backup could not be written reliably.", 500
            )
    return _archive_to_dict(archive, manifest)


def list_backups(data_root: Path) -> list[dict]:
    archives: list[dict] = []
    for archive in _backups_dir(data_root).glob("*.zip"):
        manifest = _read_manifest(archive)
        if manifest is not None:
            archives.append(_archive_to_dict(archive, manifest))
    archives.sort(key=lambda item: item["created_at"], reverse=True)
    return archives


def _archive_path(data_root: Path, backup_id: str) -> Path:
    archive = _backups_dir(data_root) / f"{backup_id}.zip"
    if not archive.exists():
        raise ManagerError("backup_not_found", "The requested backup was not found.", 404)
    return archive


def _verify_archive(archive: Path, scratch_dir: Path) -> bool:
    manifest = _read_manifest(archive)
    if manifest is None:
        return False
    try:
        with zipfile.ZipFile(archive) as zf:
            db_bytes = zf.read(_DB_ENTRY)
    except (OSError, KeyError, zipfile.BadZipFile):
        return False
    expected = str((manifest.get("files") or {}).get(_DB_ENTRY) or "")
    if _sha256(db_bytes) != expected:
        return False
    return _integrity_ok(db_bytes, scratch_dir)


def delete_backup(data_root: Path, backup_id: str) -> None:
    _archive_path(data_root, backup_id).unlink(missing_ok=True)


def _active_runtime_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count(RuntimeSession.id)).where(
                    RuntimeSession.state.in_(ACTIVE_STATES)
                )
            ).scalar()
            or 0
        )


def _apply_snapshot(engine: Engine, db_bytes: bytes, scratch_dir: Path) -> None:
    """Copy a snapshot into the live engine in place via SQLite's online-backup."""
    scratch = scratch_dir / f".restore-{secrets.token_hex(4)}.db"
    scratch.write_bytes(db_bytes)
    try:
        source = sqlite3.connect(scratch)
        engine.dispose()  # drop pooled connections before overwriting pages
        raw = engine.raw_connection()
        try:
            source.backup(raw.driver_connection)
            raw.driver_connection.commit()
        finally:
            raw.close()
            source.close()
    finally:
        scratch.unlink(missing_ok=True)


def _validate_restored(engine: Engine) -> bool:
    """A restored DB must pass integrity_check AND carry the full expected schema."""
    from ...models import Base

    try:
        with engine.connect() as connection:
            row = connection.exec_driver_sql("PRAGMA integrity_check").fetchone()
            if not row or row[0] != "ok":
                return False
            present = {
                name
                for (name,) in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
    except Exception:
        return False
    return set(Base.metadata.tables.keys()).issubset(present)


def restore_backup(engine: Engine, data_root: Path, backup_id: str) -> dict:
    """Restore a verified snapshot in place. Destructive — guarded hard.

    A pre-restore safety backup is taken; if the restored DB fails validation
    (integrity or schema), the safety backup is applied back so the live database
    is never left half-written or structurally broken.
    """
    if _active_runtime_count(engine):
        raise ManagerError(
            "backup_restore_blocked",
            "Stop all running profiles before restoring a backup.",
            409,
        )
    archive = _archive_path(data_root, backup_id)
    backups = _backups_dir(data_root)
    if not _verify_archive(archive, backups):
        raise ManagerError(
            "backup_verification_failed",
            "This backup failed verification and was not restored.",
            422,
        )

    # Safety backup of the current state before overwriting anything.
    safety = create_backup(engine, data_root, automatic=True)
    with zipfile.ZipFile(archive) as zf:
        db_bytes = zf.read(_DB_ENTRY)

    _apply_snapshot(engine, db_bytes, backups)
    if not _validate_restored(engine):
        # Roll back to the safety snapshot so we never leave a broken DB live.
        with zipfile.ZipFile(_archive_path(data_root, safety["id"])) as zf:
            _apply_snapshot(engine, zf.read(_DB_ENTRY), backups)
        raise ManagerError(
            "backup_restore_failed",
            "The backup could not be restored and the previous state was kept.",
            500,
        )
    return safety


def maybe_auto_backup(engine: Engine, data_root: Path) -> dict | None:
    """Create an automatic backup at startup if the newest is >24h old."""
    existing = list_backups(data_root)
    if existing and _now() - existing[0]["created_at"] < _AUTO_INTERVAL:
        return None
    created = create_backup(engine, data_root, automatic=True)
    _enforce_retention(data_root)
    return created


def _enforce_retention(data_root: Path) -> None:
    archives = sorted(
        _backups_dir(data_root).glob("*.zip"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for stale in archives[_RETENTION:]:
        stale.unlink(missing_ok=True)
