from __future__ import annotations

import sqlite3

from alembic import command
from alembic.config import Config


_OVERRIDE_COLUMNS = {
    "gpu_vendor",
    "gpu_renderer",
    "hardware_concurrency",
    "device_memory",
    "screen_width",
    "screen_height",
    "browser_brand",
}


def test_migration_adds_nullable_overrides_without_changing_existing_seed(
    tmp_path, monkeypatch
) -> None:
    data_root = tmp_path / "fingerprint-overrides"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    config = Config("manager_backend/alembic.ini")
    command.upgrade(config, "0019_shop_check_credential_journal")

    database = data_root / "manager.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO profiles (id, name, notes, pinned, startup_urls_json, "
            "fingerprint_seed, fingerprint_preset, fingerprint_revision, "
            "fingerprint_config_hash, browser_version_mode, user_agent_mode, "
            "location_json, window_json, behavior_json, test_proxy_before_launch, "
            "total_runtime_seconds, created_at, updated_at) VALUES "
            "('existing-profile', 'Existing', '', 0, '[]', '42', 'consistent', 2, "
            "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
            "'installed', 'automatic', '{}', '{}', '{}', 1, 0, "
            "'2026-08-01 00:00:00+00:00', '2026-08-01 00:00:00+00:00')"
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(database) as connection:
        table_info = {
            row[1]: row
            for row in connection.execute("PRAGMA table_info(profiles)")
            if row[1] in _OVERRIDE_COLUMNS
        }
        row = connection.execute(
            "SELECT fingerprint_seed, gpu_vendor, gpu_renderer, "
            "hardware_concurrency, device_memory, screen_width, screen_height, "
            "browser_brand FROM profiles WHERE id = 'existing-profile'"
        ).fetchone()

    assert set(table_info) == _OVERRIDE_COLUMNS
    assert all(column[3] == 0 for column in table_info.values())
    assert row == ("42", None, None, None, None, None, None, None)
