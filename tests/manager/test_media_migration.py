from __future__ import annotations

import sqlite3

from alembic import command
from alembic.config import Config


def _table_names(database) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }


def test_media_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    data_root = tmp_path / "media-migration"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    config = Config("manager_backend/alembic.ini")
    command.upgrade(config, "head")

    database = data_root / "manager.db"
    tables = _table_names(database)
    assert {"media_assets", "media_settings", "profile_media_assets"} <= tables

    command.downgrade(config, "0011_profile_log_sequence")
    after = _table_names(database)
    assert "media_assets" not in after
    assert "profile_media_assets" not in after
    assert "media_settings" not in after
