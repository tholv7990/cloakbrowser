from __future__ import annotations

import sqlite3

from alembic import command
from alembic.config import Config


EXPECTED = {
    "ix_profiles_proxy_id",
    "ix_runtime_sessions_profile_created_at",
    "ix_runtime_sessions_profile_state",
    "ix_runtime_sessions_updated_at",
    "ix_runtime_sessions_created_at_id",
    "ix_profile_media_assets_media_profile",
}


def _indexes(database) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {
            name
            for name, in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }


def test_performance_indexes_upgrade_and_downgrade(tmp_path, monkeypatch) -> None:
    data_root = tmp_path / "performance-indexes"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    config = Config("manager_backend/alembic.ini")

    command.upgrade(config, "head")
    database = data_root / "manager.db"
    assert EXPECTED <= _indexes(database)

    command.downgrade(config, "0014_shopify")
    assert EXPECTED.isdisjoint(_indexes(database))


def test_performance_indexes_are_selected_by_sqlite(tmp_path, monkeypatch) -> None:
    data_root = tmp_path / "performance-plans"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    config = Config("manager_backend/alembic.ini")
    command.upgrade(config, "head")

    database = data_root / "manager.db"
    statements = {
        "ix_profiles_proxy_id": "SELECT count(id) FROM profiles WHERE proxy_id = ?",
        "ix_runtime_sessions_profile_created_at": (
            "SELECT id FROM runtime_sessions WHERE profile_id = ? ORDER BY created_at DESC"
        ),
        "ix_runtime_sessions_profile_state": (
            "SELECT id FROM runtime_sessions WHERE profile_id = ? AND state IN "
            "(?,?,?,?,?)"
        ),
        "ix_runtime_sessions_updated_at": (
            "SELECT max(updated_at) FROM runtime_sessions"
        ),
        "ix_runtime_sessions_created_at_id": (
            "SELECT id FROM runtime_sessions ORDER BY created_at DESC, id DESC LIMIT 100"
        ),
        "ix_profile_media_assets_media_profile": (
            "SELECT profile_id FROM profile_media_assets WHERE media_asset_id = ?"
        ),
    }
    with sqlite3.connect(database) as connection:
        for index_name, sql in statements.items():
            parameter = tuple(
                ["missing", "queued", "starting", "running", "stopping", "detached"][
                    : sql.count("?")
                ]
            )
            plan = " ".join(
                str(column)
                for row in connection.execute(f"EXPLAIN QUERY PLAN {sql}", parameter)
                for column in row
            )
            assert index_name in plan, plan
