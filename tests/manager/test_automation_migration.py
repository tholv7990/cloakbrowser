from __future__ import annotations

import sqlite3

from alembic import command
from alembic.config import Config


_TABLES = {
    "automation_templates",
    "automation_recordings",
    "automation_runs",
    "automation_run_items",
    "automation_credentials",
    "profile_factory_jobs",
    "profile_factory_items",
}


def _table_names(database) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }


def test_automation_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    data_root = tmp_path / "automation-migration"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    config = Config("manager_backend/alembic.ini")
    command.upgrade(config, "head")

    database = data_root / "manager.db"
    assert _TABLES <= _table_names(database)

    command.downgrade(config, "0012_media")
    assert not (_TABLES & _table_names(database))
