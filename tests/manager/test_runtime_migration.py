from __future__ import annotations

import sqlite3

from alembic import command
from alembic.config import Config


def test_runtime_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    data_root = tmp_path / "runtime-migration"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    config = Config("manager_backend/alembic.ini")
    command.upgrade(config, "head")

    database = data_root / "manager.db"
    with sqlite3.connect(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(runtime_sessions)")
        }
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(runtime_sessions)")
        }
    assert {"profile_id", "state", "browser_pid", "started_at", "stopped_at"} <= columns
    assert "uq_runtime_sessions_active_profile" in indexes

    command.downgrade(config, "0004_persistent_owner_sessions")
    with sqlite3.connect(database) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='runtime_sessions'"
        ).fetchone()
    assert table is None
