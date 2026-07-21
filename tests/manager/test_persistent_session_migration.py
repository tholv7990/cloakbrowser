from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from alembic import command
from alembic.config import Config


def test_migration_preserves_existing_unrevoked_session(tmp_path, monkeypatch):
    data_root = tmp_path / "migration-data"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    config = Config("manager_backend/alembic.ini")
    command.upgrade(config, "0003_local_owner_auth")

    database = data_root / "manager.db"
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO owners "
            "(id, email, password_hash, password_changed_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("local-owner", "owner@example.com", "hash", now, now, now),
        )
        connection.execute(
            "INSERT INTO auth_sessions "
            "(id, owner_id, token_hash, csrf_hash, created_at, last_seen_at, "
            "absolute_expires_at, revoked_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
            ("session-id", "local-owner", "t" * 64, "c" * 64, now, now, now),
        )

    command.upgrade(config, "head")
    with sqlite3.connect(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(auth_sessions)")
        }
        session = connection.execute(
            "SELECT id, revoked_at FROM auth_sessions WHERE id = 'session-id'"
        ).fetchone()

    assert "last_seen_at" not in columns
    assert "absolute_expires_at" not in columns
    assert session == ("session-id", None)
