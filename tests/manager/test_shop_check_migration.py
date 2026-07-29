from __future__ import annotations

import sqlite3

import pytest
from alembic import command
from alembic.config import Config


_TABLES = {
    "shop_check_runs",
    "shop_check_workers",
    "shop_check_emails",
}

# Indexes/uniqueness the feature relies on for scans, ordering, and integrity.
_INDEXES = {
    "ix_shop_check_emails_run_state",
    "uq_shop_check_emails_run_ordinal",
    "uq_shop_check_emails_run_fingerprint",
    "uq_shop_check_workers_run_ordinal",
    "uq_shop_check_workers_profile_id",
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


def test_worker_profile_id_is_immutable_after_assignment(tmp_path, monkeypatch):
    """A worker's profile ownership must never change once assigned — a DB trigger
    enforces it even if application code is wrong."""
    data_root = tmp_path / "shop-check-immutable"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    config = Config("manager_backend/alembic.ini")
    command.upgrade(config, "head")
    database = data_root / "manager.db"

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO shop_check_runs "
            "(id,status,emails_per_profile,max_parallel,target_url,total_emails,"
            "terminal_count,retryable_count,worker_count,cleanup_state,created_at) "
            "VALUES ('r1','running',5,3,'https://shop.app/',0,0,0,0,'none','2026-07-29T00:00:00Z')"
        )
        connection.execute(
            "INSERT INTO shop_check_workers "
            "(id,run_id,ordinal,state,profile_id,assigned_count,processed_count,created_at) "
            "VALUES ('w1','r1',0,'processing','p1',5,0,'2026-07-29T00:00:00Z')"
        )
        connection.commit()
        # Re-pointing an assigned worker at a different profile must abort.
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE shop_check_workers SET profile_id='p2' WHERE id='w1'")
        # Clearing/keeping the same value is allowed (idempotent writes).
        connection.execute("UPDATE shop_check_workers SET profile_id='p1' WHERE id='w1'")
        connection.commit()
