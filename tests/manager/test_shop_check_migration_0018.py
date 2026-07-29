"""0018 hardening must upgrade an existing 0017 database in place, preserving
data. Fresh-DB tests are insufficient — this applies the ORIGINAL 0017 schema,
inserts representative rows the application would have written, upgrades to head,
and proves the rows survive and every new constraint/index/trigger/enum exists.
"""

from __future__ import annotations

import sqlite3

import pytest
from alembic import command
from alembic.config import Config


def _config(monkeypatch, data_root) -> Config:
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    return Config("manager_backend/alembic.ini")


def _seed_0017_rows(db) -> None:
    con = sqlite3.connect(db)
    con.executescript(
        """
        INSERT INTO shop_check_runs
          (id,status,region,emails_per_profile,max_parallel,target_url,
           total_emails,terminal_count,retryable_count,worker_count,cleanup_state,created_at)
        VALUES ('run-1','running',NULL,5,3,'https://shop.app/',2,1,0,1,'none','2026-07-29T00:00:00Z');
        INSERT INTO shop_check_workers
          (id,run_id,ordinal,state,profile_id,proxy_id,assigned_count,processed_count,created_at)
        VALUES ('wk-1','run-1',0,'processing','prof-1','px-1',2,1,'2026-07-29T00:00:00Z');
        -- one still-pending email (no result/checked_at) and one terminal email,
        -- exactly as the application writes them.
        INSERT INTO shop_check_emails
          (id,run_id,worker_id,ordinal,email_fingerprint,credential_ref,email_masked,
           state,result,retry_count,checked_at,created_at)
        VALUES ('em-1','run-1','wk-1',0,'aaaa','ref-1','a***@b***.com',
                'pending',NULL,0,NULL,'2026-07-29T00:00:00Z');
        INSERT INTO shop_check_emails
          (id,run_id,worker_id,ordinal,email_fingerprint,credential_ref,email_masked,
           state,result,retry_count,checked_at,created_at)
        VALUES ('em-2','run-1','wk-1',1,'bbbb','ref-2','c***@d***.com',
                'terminal','login_success',0,'2026-07-29T00:01:00Z','2026-07-29T00:00:00Z');
        """
    )
    con.commit()
    con.close()


def test_0018_upgrades_existing_0017_data_in_place(tmp_path, monkeypatch):
    data_root = tmp_path / "upgrade"
    config = _config(monkeypatch, data_root)
    # Apply ONLY the published 0017 schema, then seed representative rows.
    command.upgrade(config, "0017_shop_check")
    db = data_root / "manager.db"
    _seed_0017_rows(db)

    # Upgrade to head (runs 0018) — data must survive.
    command.upgrade(config, "head")

    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT count(*) FROM shop_check_runs").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM shop_check_workers").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM shop_check_emails").fetchone()[0] == 2
        assert (
            con.execute("SELECT result FROM shop_check_emails WHERE id='em-2'").fetchone()[0]
            == "login_success"
        )
        assert (
            con.execute("SELECT profile_id FROM shop_check_workers WHERE id='wk-1'").fetchone()[0]
            == "prof-1"
        )

        indexes = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
        assert {
            "uq_shop_check_emails_run_ordinal",
            "uq_shop_check_emails_run_fingerprint",
            "uq_shop_check_workers_run_ordinal",
            "uq_shop_check_workers_profile_id",
        } <= indexes

        triggers = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )}
        assert "trg_shop_check_workers_profile_immutable" in triggers

        # New enum value accepted after upgrade.
        con.execute(
            "INSERT INTO shop_check_emails "
            "(id,run_id,worker_id,ordinal,email_fingerprint,credential_ref,email_masked,"
            "state,result,retry_count,checked_at,created_at) "
            "VALUES ('em-3','run-1','wk-1',2,'cccc','ref-3','e***@f***.com',"
            "'terminal','email_rejected',0,'2026-07-29T00:02:00Z','2026-07-29T00:00:00Z')"
        )
        con.commit()

        # Corrected coherence: a pending row with checked_at must be rejected now.
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO shop_check_emails "
                "(id,run_id,worker_id,ordinal,email_fingerprint,credential_ref,email_masked,"
                "state,result,retry_count,checked_at,created_at) "
                "VALUES ('em-bad','run-1',NULL,9,'dddd','ref-4','g***@h***.com',"
                "'pending',NULL,0,'2026-07-29T00:00:00Z','2026-07-29T00:00:00Z')"
            )

        # Immutability trigger active on the migrated table.
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE shop_check_workers SET profile_id='other' WHERE id='wk-1'")
    finally:
        con.close()


def test_0018_downgrade_restores_0017_shape(tmp_path, monkeypatch):
    data_root = tmp_path / "downgrade"
    config = _config(monkeypatch, data_root)
    command.upgrade(config, "head")
    db = data_root / "manager.db"

    command.downgrade(config, "0017_shop_check")
    con = sqlite3.connect(db)
    try:
        triggers = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )}
        assert "trg_shop_check_workers_profile_immutable" not in triggers
        indexes = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
        assert "uq_shop_check_workers_profile_id" not in indexes
        # tables still exist (only the hardening was reverted)
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert {"shop_check_runs", "shop_check_workers", "shop_check_emails"} <= tables
    finally:
        con.close()
