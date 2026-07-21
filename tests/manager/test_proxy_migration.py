from __future__ import annotations

import sqlite3

from alembic import command
from alembic.config import Config


def test_proxy_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    data_root = tmp_path / "proxy-migration"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    config = Config("manager_backend/alembic.ini")
    command.upgrade(config, "head")

    database = data_root / "manager.db"
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(proxies)")}
        foreign_keys = list(connection.execute("PRAGMA foreign_key_list(profiles)"))
        quality_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(proxy_quality_runs)")
        }
    assert {"label", "scheme", "credential_ref", "last_checked_at", "deleted_at"} <= columns
    assert any(row[2] == "proxies" and row[3] == "proxy_id" for row in foreign_keys)
    assert "uq_proxy_quality_runs_active_proxy" in quality_indexes

    command.downgrade(config, "0006_proxy_management")
    with sqlite3.connect(database) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='proxy_quality_runs'"
        ).fetchone()
    assert table is None
    command.downgrade(config, "0005_runtime_sessions")
    with sqlite3.connect(database) as connection:
        proxy_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='proxies'"
        ).fetchone()
    assert proxy_table is None
