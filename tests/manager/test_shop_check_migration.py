from __future__ import annotations

import sqlite3

from alembic import command
from alembic.config import Config


_TABLES = {
    "shop_check_runs",
    "shop_check_workers",
    "shop_check_emails",
}

# Indexes the feature relies on for run/status/order scans and ownership lookup.
_INDEXES = {
    "ix_shop_check_emails_run_state",
    "ix_shop_check_emails_run_ordinal",
    "ix_shop_check_workers_run_ordinal",
}


def _names(database, kind: str) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type=?", (kind,)
            )
        }


def test_shop_check_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    data_root = tmp_path / "shop-check-migration"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    config = Config("manager_backend/alembic.ini")
    command.upgrade(config, "head")

    database = data_root / "manager.db"
    assert _TABLES <= _names(database, "table")
    assert _INDEXES <= _names(database, "index")

    command.downgrade(config, "0016_retire_dead_behavior_fields")
    assert not (_TABLES & _names(database, "table"))


def test_shop_check_migration_has_no_plaintext_email_column(tmp_path, monkeypatch):
    """Security gate: the emails table must store references + fingerprints, never
    a plaintext `email` column."""
    data_root = tmp_path / "shop-check-columns"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    config = Config("manager_backend/alembic.ini")
    command.upgrade(config, "head")

    database = data_root / "manager.db"
    with sqlite3.connect(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(shop_check_emails)")
        }
    assert "email" not in columns
    assert {"email_fingerprint", "credential_ref"} <= columns
