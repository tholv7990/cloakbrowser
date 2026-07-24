from __future__ import annotations

import json
import sqlite3

from alembic import command
from alembic.config import Config

from manager_backend.fingerprints import build_fingerprint_identity


_LEGACY_BEHAVIOR = {
    "humanize_enabled": True,
    "humanize_preset": "careful",
    "clear_cache_before_launch": True,
    "restore_previous_tabs": False,
    "download_directory_mode": "custom",
    "custom_download_directory": "C:/secret",
    "ignore_https_errors": True,
    "hardware_concurrency_mode": "custom",
    "hardware_concurrency": 8,
    "gpu_mode": "custom_vendor",
    "gpu_vendor": "ACME",
    "additional_args": ["--foo=bar"],
    "permissions": {"camera": "allow"},
}
_LEGACY_WINDOW = {"mode": "maximized", "color_scheme": "dark"}
_LOCATION = {"geo_mode": "proxy", "webrtc_mode": "proxy", "geolocation_mode": "ask"}


def _insert_legacy_profile(database) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO profiles (id, name, notes, pinned, startup_urls_json, "
            "fingerprint_seed, fingerprint_preset, fingerprint_revision, "
            "fingerprint_config_hash, browser_version_mode, user_agent_mode, "
            "location_json, window_json, behavior_json, test_proxy_before_launch, "
            "total_runtime_seconds, created_at, updated_at) VALUES "
            "(:id, :name, '', 0, '[]', :seed, 'consistent', 1, 'stale-hash', "
            "'installed', 'automatic', :location, :window, :behavior, 1, 0, "
            ":ts, :ts)",
            {
                "id": "prof-legacy",
                "name": "Legacy",
                "seed": "12345678901234567890",
                "location": json.dumps(_LOCATION),
                "window": json.dumps(_LEGACY_WINDOW),
                "behavior": json.dumps(_LEGACY_BEHAVIOR),
                "ts": "2026-07-24 00:00:00+00:00",
            },
        )
        connection.commit()


def test_migration_strips_retired_fields_and_rebaselines_hash(tmp_path, monkeypatch) -> None:
    data_root = tmp_path / "behavior-retire"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    config = Config("manager_backend/alembic.ini")

    command.upgrade(config, "0015_performance_indexes")
    database = data_root / "manager.db"
    _insert_legacy_profile(database)

    command.upgrade(config, "head")

    with sqlite3.connect(database) as connection:
        seed, behavior_json, window_json, config_hash = connection.execute(
            "SELECT fingerprint_seed, behavior_json, window_json, "
            "fingerprint_config_hash FROM profiles WHERE id = 'prof-legacy'"
        ).fetchone()

    behavior = json.loads(behavior_json)
    window = json.loads(window_json)

    # Seed (identity anchor) is never touched.
    assert seed == "12345678901234567890"
    # Every retired behavior key is gone; permissions survives.
    assert behavior == {"permissions": {"camera": "allow"}}
    # color_scheme is stripped; window mode survives.
    assert window == {"mode": "maximized"}
    # The hash is re-baselined to what the current builder produces for the stripped
    # config — so the next identity edit will not spuriously bump the revision.
    expected = build_fingerprint_identity(
        seed=seed,
        fingerprint_preset="consistent",
        browser_version_mode="installed",
        user_agent_mode="automatic",
        location=_LOCATION,
        window=window,
        behavior=behavior,
    )
    assert config_hash == expected.config_hash
    assert config_hash != "stale-hash"
