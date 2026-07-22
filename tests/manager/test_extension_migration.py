from __future__ import annotations

import sqlite3

from alembic import command
from alembic.config import Config


def test_extension_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    data_root = tmp_path / "extension-migration"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    config = Config("manager_backend/alembic.ini")
    command.upgrade(config, "head")

    database = data_root / "manager.db"
    with sqlite3.connect(database) as connection:
        extension_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(extensions)")
        }
        assignment_pk = {
            row[1]: row[5]
            for row in connection.execute("PRAGMA table_info(profile_extensions)")
        }
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(extensions)")
        }
        foreign_keys = list(connection.execute("PRAGMA foreign_key_list(profile_extensions)"))

    assert {
        "id",
        "directory",
        "name",
        "version",
        "description",
        "manifest_version",
        "permissions_json",
        "enabled",
        "manifest_hash",
        "created_at",
        "updated_at",
    } <= extension_columns
    assert assignment_pk == {"profile_id": 1, "extension_id": 2}
    assert "uq_extensions_directory" in indexes
    assert {row[2] for row in foreign_keys} == {"profiles", "extensions"}

    command.downgrade(config, "0008_runtime_observability")
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "extensions" not in tables
    assert "profile_extensions" not in tables
